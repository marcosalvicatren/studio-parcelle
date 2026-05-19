"""
utils.py — Motore di calcolo parcelle, validazioni, utility.
"""

from __future__ import annotations

from typing import Optional

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
    "scaglioni": "A scaglioni con conguaglio",
    "unitario":  "A quantità (tariffa × numero)",
}

QUARTERS = ["T1", "T2", "T3", "T4"]


# ---------------------------------------------------------------------------
# Motore di calcolo
# ---------------------------------------------------------------------------

def calc_fee_scaglioni(service, driver_quarterly: float) -> float:
    """
    Calcola il compenso trimestrale per una prestazione a scaglioni.
    Logica: driver_trimestrale × 4 = driver_annuale → trova scaglione → compenso_annuo / 4
    Oltre l'ultimo scaglione: compenso_max + eccedenza × marginal_rate (se definito)
    """
    if not driver_quarterly or driver_quarterly <= 0:
        return 0.0

    brackets = sorted(service.brackets, key=lambda b: b.threshold_from)
    if not brackets:
        return 0.0

    driver_annual = driver_quarterly * 4
    matched_fee = None

    for bracket in brackets:
        upper = bracket.threshold_to
        if upper is None:
            if driver_annual >= bracket.threshold_from:
                if service.marginal_rate:
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
        matched_fee = brackets[0].annual_fee

    return round(matched_fee / 4, 4)


def calc_fee_unitario(service, quantity: float) -> float:
    """Compenso = quantità × tariffa unitaria."""
    if not quantity or quantity <= 0:
        return 0.0
    return round((service.unit_price or 0.0) * quantity, 4)


def calc_quarterly_fee(service, driver_value: Optional[float]) -> float:
    """Dispatcher principale calcolo compenso trimestrale."""
    if driver_value is None:
        return 0.0
    if service.calc_type == "scaglioni":
        return calc_fee_scaglioni(service, driver_value)
    elif service.calc_type == "unitario":
        return calc_fee_unitario(service, driver_value)
    return 0.0


def calc_conguaglio(fee_q1: float, fee_q2: float, fee_q3: float,
                    driver_q4: float, service) -> float:
    """
    Calcola il conguaglio di T4 per prestazioni a scaglioni.
    Logica Excel: 
      - Calcola il compenso annuo effettivo usando il driver annuale reale (somma dei 4 driver)
      - Conguaglio = compenso_annuo_effettivo - (fee_q1 + fee_q2 + fee_q3)
    Se il driver Q4 non è disponibile, usa solo fee_q4 calcolato normalmente.
    """
    if service.calc_type != "scaglioni":
        return calc_quarterly_fee(service, driver_q4)

    # Non possiamo calcolare il conguaglio senza i driver precedenti
    # Il conguaglio viene calcolato in recalc_line dove abbiamo tutti i driver
    return calc_quarterly_fee(service, driver_q4)


def recalc_line(line, service) -> None:
    """
    Ricalcola tutti i compensi di una riga in base ai driver attuali.
    Per scaglioni: T1/T2/T3 normali, T4 = conguaglio annuale.
    Non sovrascrive gli override manuali.
    """
    line.fee_q1 = calc_quarterly_fee(service, line.driver_q1)
    line.fee_q2 = calc_quarterly_fee(service, line.driver_q2)
    line.fee_q3 = calc_quarterly_fee(service, line.driver_q3)

    if service.calc_type == "scaglioni":
        # Conguaglio T4: compenso annuo reale - somma T1+T2+T3
        # Il driver annuale reale è la somma dei 4 driver trimestrali
        d1 = line.driver_q1 or 0.0
        d2 = line.driver_q2 or 0.0
        d3 = line.driver_q3 or 0.0
        d4 = line.driver_q4 or 0.0
        driver_annual_real = d1 + d2 + d3 + d4

        if driver_annual_real > 0:
            brackets = sorted(service.brackets, key=lambda b: b.threshold_from)
            annual_fee_real = _find_annual_fee(brackets, driver_annual_real, service.marginal_rate)
            conguaglio = annual_fee_real - (line.fee_q1 + line.fee_q2 + line.fee_q3)
            line.fee_q4 = round(conguaglio, 4)
        else:
            line.fee_q4 = 0.0
    else:
        line.fee_q4 = calc_quarterly_fee(service, line.driver_q4)


def _find_annual_fee(brackets, driver_annual: float, marginal_rate: Optional[float]) -> float:
    """Trova il compenso annuo per un dato driver annuale."""
    for bracket in brackets:
        upper = bracket.threshold_to
        if upper is None:
            if driver_annual >= bracket.threshold_from:
                if marginal_rate:
                    excess = driver_annual - bracket.threshold_from
                    return bracket.annual_fee + excess * marginal_rate
                return bracket.annual_fee
        else:
            if bracket.threshold_from <= driver_annual <= upper:
                return bracket.annual_fee
    return brackets[0].annual_fee if brackets else 0.0


# ---------------------------------------------------------------------------
# Validazioni
# ---------------------------------------------------------------------------

def validate_client(data: dict) -> list[str]:
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
    if old == 0:
        return None
    return round((new - old) / abs(old) * 100, 2)


# ---------------------------------------------------------------------------
# Clonazione listino
# ---------------------------------------------------------------------------

def clone_price_list_for_year(source_year: int, target_year: int, percent_increase: float = 0.0):
    """Crea un nuovo listino per target_year copiando da source_year con aumento %."""
    from database import get_session, PriceList, ServiceItem, ServiceBracket

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
            new_svc = ServiceItem(
                price_list_id=new_pl.id,
                service_code=svc.service_code,
                description=svc.description,
                category=svc.category,
                calc_type=svc.calc_type,
                driver_label=svc.driver_label,
                driver_unit=svc.driver_unit,
                unit_price=round(svc.unit_price * factor, 2) if svc.unit_price else None,
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
