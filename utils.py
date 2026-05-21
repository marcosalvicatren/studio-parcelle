"""
utils.py — Motore di calcolo, validazioni, utility.
"""

from __future__ import annotations
from typing import Optional

CLIENT_TYPES = ["persona fisica","ditta individuale","società di persone",
                "società di capitali","ente","altro"]
CLIENT_STATUSES = ["attivo", "archiviato"]
CALC_TYPES = {
    "scaglioni": "A scaglioni con conguaglio",
    "unitario":  "A quantità (tariffa × numero)",
}
QUARTERS = ["T1","T2","T3","T4"]


def _find_annual_fee(brackets, driver_annual, has_mr, marginal_rate):
    brackets = sorted(brackets, key=lambda b: b.threshold_from)
    for b in brackets:
        upper = b.threshold_to
        if upper is None:
            if driver_annual >= b.threshold_from:
                if has_mr and marginal_rate:
                    excess = driver_annual - b.threshold_from
                    return b.annual_fee + excess * marginal_rate
                return b.annual_fee
        else:
            if b.threshold_from <= driver_annual <= upper:
                return b.annual_fee
    return brackets[0].annual_fee if brackets else 0.0


def calc_quarterly_fee(service, driver_value):
    if not driver_value or driver_value <= 0:
        return 0.0
    if service.calc_type == "scaglioni":
        if not service.brackets:
            return 0.0
        annual = _find_annual_fee(
            service.brackets, driver_value * 4,
            service.has_marginal_rate, service.marginal_rate
        )
        return round(annual / 4, 4)
    elif service.calc_type == "unitario":
        return round((service.unit_price or 0.0) * driver_value, 4)
    return 0.0


def recalc_line(line, service):
    """
    Ricalcola T1/T2/T3 normalmente.
    T4 per scaglioni = conguaglio: compenso annuo reale (su driver annuale totale) - (T1+T2+T3)
    """
    line.fee_q1 = calc_quarterly_fee(service, line.driver_q1)
    line.fee_q2 = calc_quarterly_fee(service, line.driver_q2)
    line.fee_q3 = calc_quarterly_fee(service, line.driver_q3)

    if service.calc_type == "scaglioni":
        d_tot = (line.driver_q1 or 0) + (line.driver_q2 or 0) + \
                (line.driver_q3 or 0) + (line.driver_q4 or 0)
        if d_tot > 0 and service.brackets:
            annual_real = _find_annual_fee(
                service.brackets, d_tot,
                service.has_marginal_rate, service.marginal_rate
            )
            line.fee_q4 = round(annual_real - (line.fee_q1 + line.fee_q2 + line.fee_q3), 4)
        else:
            line.fee_q4 = 0.0
    else:
        line.fee_q4 = calc_quarterly_fee(service, line.driver_q4)


def validate_client(data):
    errors = []
    if not data.get("name","").strip(): errors.append("La denominazione è obbligatoria.")
    if not data.get("client_code","").strip(): errors.append("Il codice cliente è obbligatorio.")
    if not data.get("client_type"): errors.append("La tipologia cliente è obbligatoria.")
    cf = data.get("tax_code","")
    if cf and len(cf) not in (0,11,16): errors.append("Il codice fiscale deve avere 11 o 16 caratteri.")
    piva = data.get("vat_number","")
    if piva and len(piva) not in (0,11): errors.append("La partita IVA deve avere 11 caratteri.")
    return errors


def fmt_currency(value):
    if value is None: return "—"
    return f"€ {value:,.2f}".replace(",","X").replace(".",",").replace("X",".")

def fmt_num(value, decimals=2):
    if value is None: return "—"
    return f"{value:,.{decimals}f}".replace(",","X").replace(".",",").replace("X",".")

def pct_change(old, new):
    if not old: return None
    return round((new - old) / abs(old) * 100, 2)


def clone_price_list_for_year(source_year, target_year, percent_increase=0.0):
    from database import get_session, PriceList, ServiceItem, ServiceBracket
    factor = 1 + percent_increase / 100
    with get_session() as s:
        src = s.query(PriceList).filter_by(year=source_year).first()
        if not src: raise ValueError(f"Listino {source_year} non trovato.")
        if s.query(PriceList).filter_by(year=target_year).first():
            raise ValueError(f"Listino {target_year} già esistente.")
        new_pl = PriceList(year=target_year, name=f"Listino {target_year}", is_active=True)
        s.add(new_pl); s.flush()
        for svc in src.services:
            new_svc = ServiceItem(
                price_list_id=new_pl.id, service_code=svc.service_code,
                description=svc.description, category=svc.category,
                calc_type=svc.calc_type, driver_label=svc.driver_label,
                driver_unit=svc.driver_unit,
                unit_price=round(svc.unit_price * factor, 2) if svc.unit_price else None,
                has_marginal_rate=svc.has_marginal_rate,
                marginal_rate=round(svc.marginal_rate * factor, 4) if svc.marginal_rate else None,
                is_active=svc.is_active, sort_order=svc.sort_order,
            )
            s.add(new_svc); s.flush()
            for b in svc.brackets:
                s.add(ServiceBracket(
                    service_item_id=new_svc.id,
                    threshold_from=b.threshold_from, threshold_to=b.threshold_to,
                    annual_fee=round(b.annual_fee * factor, 2),
                ))
