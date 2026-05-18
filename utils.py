"""
utils.py — Motore di calcolo parcelle, validazioni, utility.
"""

from __future__ import annotations

from typing import Optional
from database import ServiceItem, FeeReportLine


# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

CLIENT_TYPES = [
    "persona fisica",
    "ditta individuale",
    "società di persone",
    "società di capitali",
    "ente",
    "altro",
]

CLIENT_STATUSES = ["attivo", "archiviato"]

CALC_TYPES = {
    "scaglioni":           "A scaglioni (driver quantitativo)",
    "unitario":            "Tariffa fissa × quantità",
    "minimo_percentuale":  "Percentuale con minimo garantito",
    "forfait":             "Forfait fisso per trimestre",
}

QUARTERS = ["T1", "T2", "T3", "T4"]


# ---------------------------------------------------------------------------
# Motore di calcolo scaglioni
# Replica la logica Excel: il driver trimestrale viene moltiplicato ×4
# per trovare lo scaglione annuo, poi il compenso annuo viene diviso /4.
# Oltre l'ultimo scaglione: compenso_max + eccedenza * marginal_rate (se definito)
# ---------------------------------------------------------------------------

def calc_fee_scaglioni(service: ServiceItem, driver_quarterly: float) -> float:
    """
    Calcola il compenso trimestrale per una prestazione a scaglioni.
    driver_quarterly: valore del driver nel trimestre (es. numero registrazioni T1).
    Logica Excel: annualizza il driver (×4), trova lo scaglione, ritorna compenso/4.
    """
    if not driver_quarterly or driver_quarterly <= 0:
        return 0.0

    brackets = sorted(service.brackets, key=lambda b: b.threshold_from)
    if not brackets:
        return 0.0

    driver_annual = driver_quarterly * 4

    # Trova scaglione
    matched_fee = None
    for bracket in brackets:
        upper = bracket.threshold_to
        if upper is None:
            # Ultimo scaglione (illimitato)
            if driver_annual >= bracket.threshold_from:
                if service.marginal_rate:
                    # Compenso max + eccedenza * tariffa marginale
                    excess = driver_annual - bracket.threshold_from
                    matched_fee = bracket.annual_fee + excess * service.marginal_rate
                else:
                    matched_fee = bracket.annual_fee
                break
        else:
            if bracket.threshold_from <= driver_annual <= upper:
                matched_fee = bracket.annual_fee
                break

    if matched_fee is None:
        # Sotto il primo scaglione: usa il compenso minimo
        matched_fee = brackets[0].annual_fee

    return round(matched_fee / 4, 4)


def calc_fee_unitario(service: ServiceItem, quantity_quarterly: float) -> float:
    """Compenso = quantità × tariffa unitaria."""
    if not quantity_quarterly or quantity_quarterly <= 0:
        return 0.0
    return round((service.unit_price or 0.0) * quantity_quarterly, 4)


def calc_fee_minimo_percentuale(service: ServiceItem, base_amount: float) -> float:
    """Compenso = MAX(base × percentuale, minimo fisso)."""
    if not base_amount or base_amount <= 0:
        return 0.0
    percent_fee = (service.percent_fee or 0.0) * base_amount
    min_fee = service.min_fee or 0.0
    return round(max(percent_fee, min_fee), 4)


def calc_fee_forfait(service: ServiceItem) -> float:
    """Compenso fisso per trimestre."""
    return round(service.unit_price or 0.0, 4)


def calc_quarterly_fee(service: ServiceItem, driver_value: Optional[float]) -> float:
    """
    Dispatcher principale: calcola il compenso trimestrale
    in base al calc_type della prestazione.
    """
    if driver_value is None:
        return 0.0

    calc_type = service.calc_type

    if calc_type == "scaglioni":
        return calc_fee_scaglioni(service, driver_value)
    elif calc_type == "unitario":
        return calc_fee_unitario(service, driver_value)
    elif calc_type == "minimo_percentuale":
        return calc_fee_minimo_percentuale(service, driver_value)
    elif calc_type == "forfait":
        return calc_fee_forfait(service)
    else:
        return 0.0


def recalc_line(line: FeeReportLine, service: ServiceItem) -> FeeReportLine:
    """
    Ricalcola i compensi di una riga in base ai driver attuali.
    Non sovrascrive gli override manuali.
    """
    line.fee_q1 = calc_quarterly_fee(service, line.driver_q1)
    line.fee_q2 = calc_quarterly_fee(service, line.driver_q2)
    line.fee_q3 = calc_quarterly_fee(service, line.driver_q3)
    line.fee_q4 = calc_quarterly_fee(service, line.driver_q4)
    return line


# ---------------------------------------------------------------------------
# Validazioni
# ---------------------------------------------------------------------------

def validate_client(data: dict) -> list[str]:
    """Ritorna lista di errori di validazione per un cliente."""
    errors = []
    if not data.get("name", "").strip():
        errors.append("La denominazione è obbligatoria.")
    if not data.get("client_code", "").strip():
        errors.append("Il codice cliente è obbligatorio.")
    if not data.get("client_type"):
        errors.append("La tipologia cliente è obbligatoria.")
    cf = data.get("tax_code", "")
    piva = data.get("vat_number", "")
    if cf and len(cf) not in (0, 11, 16):
        errors.append("Il codice fiscale deve avere 11 o 16 caratteri.")
    if piva and len(piva) not in (0, 11):
        errors.append("La partita IVA deve avere 11 caratteri.")
    return errors


def validate_price_list(data: dict) -> list[str]:
    errors = []
    if not data.get("year"):
        errors.append("L'anno del listino è obbligatorio.")
    if not data.get("name", "").strip():
        errors.append("Il nome del listino è obbligatorio.")
    return errors


def validate_service_item(data: dict) -> list[str]:
    errors = []
    if not data.get("service_code", "").strip():
        errors.append("Il codice prestazione è obbligatorio.")
    if not data.get("description", "").strip():
        errors.append("La descrizione è obbligatoria.")
    if data.get("calc_type") not in CALC_TYPES:
        errors.append("Tipo di calcolo non valido.")
    if data.get("calc_type") == "unitario" and not data.get("unit_price"):
        errors.append("La tariffa unitaria è obbligatoria per questo tipo di calcolo.")
    return errors


# ---------------------------------------------------------------------------
# Formattazione
# ---------------------------------------------------------------------------

def fmt_currency(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"€ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_driver(value: Optional[float], unit: Optional[str] = None) -> str:
    if value is None or value == 0:
        return "—"
    s = f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    if unit:
        s += f" {unit}"
    return s


def pct_change(old: float, new: float) -> Optional[float]:
    """Variazione percentuale tra due valori."""
    if old == 0:
        return None
    return round((new - old) / abs(old) * 100, 2)


# ---------------------------------------------------------------------------
# Aggiornamento listino in blocco
# ---------------------------------------------------------------------------

def apply_global_increase(services: list[ServiceItem], percent: float) -> list[dict]:
    """
    Applica un aumento percentuale globale a tutte le tariffe del listino.
    Ritorna lista di dict con i nuovi valori (non salva nel DB).
    percent: es. 5.0 per +5%
    """
    factor = 1 + percent / 100
    result = []
    for svc in services:
        updated = {
            "id": svc.id,
            "unit_price": round(svc.unit_price * factor, 2) if svc.unit_price else None,
            "min_fee": round(svc.min_fee * factor, 2) if svc.min_fee else None,
            "brackets": [
                {
                    "id": b.id,
                    "annual_fee": round(b.annual_fee * factor, 2),
                }
                for b in svc.brackets
            ],
        }
        result.append(updated)
    return result


def clone_price_list_for_year(source_year: int, target_year: int, percent_increase: float = 0.0):
    """
    Crea un nuovo listino per target_year copiando tutti i servizi e scaglioni
    da source_year, con eventuale aumento percentuale applicato.
    """
    from database import get_session, PriceList, ServiceItem as SI, ServiceBracket
    from sqlalchemy.orm import Session

    with get_session() as session:
        source = session.query(PriceList).filter_by(year=source_year).first()
        if not source:
            raise ValueError(f"Listino {source_year} non trovato.")
        if session.query(PriceList).filter_by(year=target_year).first():
            raise ValueError(f"Listino {target_year} già esistente.")

        factor = 1 + percent_increase / 100

        new_pl = PriceList(
            year=target_year,
            name=f"Listino {target_year}",
            is_active=True,
        )
        session.add(new_pl)
        session.flush()

        for svc in source.services:
            new_svc = SI(
                price_list_id=new_pl.id,
                service_code=svc.service_code,
                description=svc.description,
                category=svc.category,
                calc_type=svc.calc_type,
                driver_label=svc.driver_label,
                driver_unit=svc.driver_unit,
                unit_price=round(svc.unit_price * factor, 2) if svc.unit_price else None,
                percent_fee=svc.percent_fee,
                min_fee=round(svc.min_fee * factor, 2) if svc.min_fee else None,
                marginal_rate=round(svc.marginal_rate * factor, 4) if svc.marginal_rate else None,
                is_active=svc.is_active,
                sort_order=svc.sort_order,
            )
            session.add(new_svc)
            session.flush()

            for b in svc.brackets:
                session.add(ServiceBracket(
                    service_item_id=new_svc.id,
                    threshold_from=b.threshold_from,
                    threshold_to=b.threshold_to,
                    annual_fee=round(b.annual_fee * factor, 2),
                ))
