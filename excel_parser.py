"""
excel_parser.py — Import clienti da CSV/XLSX e lettura storico da Excel multi-foglio.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Import anagrafica clienti da CSV/XLSX
# ---------------------------------------------------------------------------

# Mapping flessibile: nomi colonne accettati → campo interno
COLUMN_MAP = {
    "client_code":  ["codice", "cod", "client_code", "codice cliente", "id cliente"],
    "name":         ["denominazione", "nome", "ragione sociale", "name", "cliente"],
    "tax_code":     ["codice fiscale", "cf", "tax_code", "codicefiscale"],
    "vat_number":   ["partita iva", "piva", "p.iva", "vat", "vat_number", "partitaiva"],
    "client_type":  ["tipologia", "tipo", "client_type", "tipo cliente"],
    "status":       ["stato", "status"],
    "notes":        ["note", "notes", "annotazioni"],
}


def _normalize_col(col: str) -> str:
    return col.strip().lower().replace("  ", " ")


def _detect_column(df_cols: list[str], candidates: list[str]) -> Optional[str]:
    norm = {_normalize_col(c): c for c in df_cols}
    for candidate in candidates:
        if candidate in norm:
            return norm[candidate]
    return None


def parse_clients_file(file_path: str | Path) -> tuple[list[dict], list[str]]:
    """
    Legge un file CSV o XLSX con l'anagrafica clienti.
    Ritorna (lista_clienti, lista_warnings).
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    try:
        if suffix == ".csv":
            df = pd.read_csv(path, dtype=str).fillna("")
        elif suffix in (".xlsx", ".xls"):
            df = pd.read_excel(path, dtype=str).fillna("")
        else:
            return [], [f"Formato file non supportato: {suffix}"]
    except Exception as e:
        return [], [f"Errore lettura file: {e}"]

    df.columns = [str(c) for c in df.columns]
    warnings = []
    clients = []

    # Mappa colonne
    mapping = {}
    for field, candidates in COLUMN_MAP.items():
        col = _detect_column(list(df.columns), candidates)
        if col:
            mapping[field] = col

    if "name" not in mapping:
        return [], ["Colonna 'denominazione/nome' non trovata nel file."]

    for i, row in df.iterrows():
        name = str(row.get(mapping.get("name", ""), "")).strip()
        if not name:
            continue

        client_code = str(row.get(mapping.get("client_code", ""), "")).strip()
        if not client_code:
            # Genera codice automatico se mancante
            client_code = _slugify(name)[:20]
            warnings.append(f"Riga {i+2}: codice cliente generato automaticamente per '{name}'.")

        client_type = str(row.get(mapping.get("client_type", ""), "")).strip().lower()
        valid_types = [
            "persona fisica", "ditta individuale", "società di persone",
            "società di capitali", "ente", "altro",
        ]
        if client_type not in valid_types:
            client_type = "altro"

        clients.append({
            "client_code": client_code,
            "name":        name,
            "tax_code":    str(row.get(mapping.get("tax_code", ""), "")).strip().upper(),
            "vat_number":  str(row.get(mapping.get("vat_number", ""), "")).strip(),
            "client_type": client_type,
            "status":      "attivo",
            "notes":       str(row.get(mapping.get("notes", ""), "")).strip(),
        })

    return clients, warnings


# ---------------------------------------------------------------------------
# Lettura storico da Excel multi-foglio (formato studio)
# ---------------------------------------------------------------------------

def parse_studio_excel(file_path: str | Path) -> dict[str, dict]:
    """
    Legge il file Excel multi-foglio dello studio.
    Ogni foglio = un cliente.
    Ritorna dict: {sheet_name: {"client_name": ..., "year": ..., "lines": [...]}}

    Le righe estratte sono quelle del RESOCONTO FINALE (tabella riepilogativa).
    """
    path = Path(file_path)
    try:
        xl = pd.ExcelFile(path)
    except Exception as e:
        return {"_error": str(e)}

    results = {}
    for sheet in xl.sheet_names:
        try:
            data = _parse_single_sheet(xl, sheet)
            if data:
                results[sheet] = data
        except Exception as e:
            results[sheet] = {"_error": str(e)}

    return results


def _parse_single_sheet(xl: pd.ExcelFile, sheet_name: str) -> Optional[dict]:
    """
    Estrae dal foglio del singolo cliente:
    - nome cliente
    - anno
    - righe del resoconto (prestazione + T1/T2/T3/T4/Totale)
    """
    df = xl.parse(sheet_name, header=None, dtype=object)

    client_name = None
    year = None
    resoconto_start = None

    # Scansione righe per trovare nome cliente, anno e inizio resoconto
    for i, row in df.iterrows():
        row_vals = [str(v).strip() if pd.notna(v) else "" for v in row]
        row_str = " ".join(row_vals).lower()

        # Nome cliente: cella che contiene "CLIENTE" seguita dal nome
        if "cliente" in row_vals and client_name is None:
            idx = next((j for j, v in enumerate(row_vals) if v == "CLIENTE"), None)
            if idx is not None and idx + 1 < len(row_vals):
                client_name = row_vals[idx + 1].strip()

        # Anno: cella numerica tra 2000 e 2099
        for v in row_vals:
            try:
                y = int(float(v))
                if 2000 <= y <= 2099:
                    year = y
                    break
            except (ValueError, TypeError):
                pass

        # Inizio sezione RESOCONTO
        if "resoconto" in row_str or "conto" in row_str:
            # Verifica presenza colonne trimestrali
            has_quarters = sum(1 for v in row_vals if v in ("T1", "T2", "T3", "T4")) >= 3
            if has_quarters:
                resoconto_start = i
                break

    if resoconto_start is None:
        return None

    # Leggi righe resoconto fino alla riga totale
    lines = []
    for i in range(resoconto_start + 1, min(resoconto_start + 60, len(df))):
        row = df.iloc[i]
        row_vals = [str(v).strip() if pd.notna(v) else "" for v in row]

        # Riga vuota o riga totale → fine sezione
        non_empty = [v for v in row_vals if v]
        if len(non_empty) < 2:
            continue

        # Prima cella non vuota = descrizione prestazione
        desc = next((v for v in row_vals if v and v not in ("0", "")), None)
        if not desc:
            continue

        # Cerca valori numerici nelle celle successive
        numeric_vals = []
        for v in row_vals:
            try:
                num = float(v.replace(",", "."))
                numeric_vals.append(num)
            except ValueError:
                pass

        if len(numeric_vals) >= 4:
            lines.append({
                "description": desc,
                "q1": numeric_vals[0] if len(numeric_vals) > 0 else 0.0,
                "q2": numeric_vals[1] if len(numeric_vals) > 1 else 0.0,
                "q3": numeric_vals[2] if len(numeric_vals) > 2 else 0.0,
                "q4": numeric_vals[3] if len(numeric_vals) > 3 else 0.0,
            })

    if not lines:
        return None

    return {
        "client_name": client_name or sheet_name,
        "year": year,
        "lines": lines,
        "sheet": sheet_name,
    }


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    text = text.upper()
    text = re.sub(r"[^A-Z0-9 ]", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text
