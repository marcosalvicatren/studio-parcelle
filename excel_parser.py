"""
excel_parser.py — Import clienti da CSV/XLSX.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pandas as pd


COLUMN_MAP = {
    "client_code": ["codice", "cod", "client_code", "codice cliente", "id cliente"],
    "name":        ["denominazione", "nome", "ragione sociale", "name", "cliente"],
    "tax_code":    ["c.f.", "cf", "codice fiscale", "tax_code", "codicefiscale"],
    "vat_number":  ["p.iva", "piva", "partita iva", "vat", "vat_number", "partitaiva"],
    "client_type": ["tipologia", "tipo", "client_type", "tipo cliente"],
    "status":      ["stato", "status"],
    "notes":       ["note", "notes", "annotazioni"],
}

VALID_TYPES = [
    "persona fisica",
    "ditta individuale",
    "società di persone",
    "società di capitali",
    "ente",
    "altro",
]

COLUMN_LABELS = {
    "client_code": "Codice",
    "name":        "Denominazione",
    "tax_code":    "C.F.",
    "vat_number":  "P.IVA",
    "client_type": "Tipologia",
    "status":      "Stato",
    "notes":       "Note",
}


def _normalize_col(col: str) -> str:
    return col.strip().lower()


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

    mapping = {}
    for field, candidates in COLUMN_MAP.items():
        col = _detect_column(list(df.columns), candidates)
        if col:
            mapping[field] = col

    if "name" not in mapping:
        return [], ["Colonna 'denominazione/nome' non trovata nel file."]

    for i, row in df.iterrows():
        name = str(row.get(mapping.get("name", ""), "")).strip()
        if not name or name.lower() == "nan":
            continue

        client_code = str(row.get(mapping.get("client_code", ""), "")).strip()
        if not client_code or client_code.lower() == "nan":
            client_code = _slugify(name)[:20]
            warnings.append(f"Riga {i+2}: codice generato automaticamente per '{name}'.")

        client_type = str(row.get(mapping.get("client_type", ""), "")).strip().lower()
        if client_type not in VALID_TYPES:
            if client_type and client_type != "nan":
                warnings.append(f"Riga {i+2}: tipologia '{client_type}' non riconosciuta, impostata 'altro'.")
            client_type = "altro"

        tax_code   = str(row.get(mapping.get("tax_code", ""), "")).strip().upper()
        vat_number = str(row.get(mapping.get("vat_number", ""), "")).strip()

        if tax_code in ("NAN", ""):
            tax_code = ""
        if vat_number in ("NAN", ""):
            vat_number = ""

        # Gestisci notazione scientifica residua per P.IVA
        if vat_number and ("E+" in vat_number.upper() or ("." in vat_number and "E" not in vat_number.upper())):
            try:
                vat_number = str(int(float(vat_number))).zfill(11)
            except ValueError:
                vat_number = ""

        notes = str(row.get(mapping.get("notes", ""), "")).strip()
        if notes.lower() == "nan":
            notes = ""

        clients.append({
            "client_code": client_code,
            "name":        name,
            "tax_code":    tax_code,
            "vat_number":  vat_number,
            "client_type": client_type,
            "status":      "attivo",
            "notes":       notes,
        })

    return clients, warnings


def _slugify(text: str) -> str:
    text = text.upper()
    text = re.sub(r"[^A-Z0-9 ]", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text
