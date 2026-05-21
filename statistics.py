"""
statistics.py — KPI, confronti storici, statistiche.
"""
from __future__ import annotations
from collections import defaultdict
import pandas as pd
from database import Client, FeeReport, get_session
from utils import pct_change


def get_annual_summary(year):
    with get_session() as s:
        reports = s.query(FeeReport).filter_by(year=year).all()
        rows = []
        for r in reports:
            c = s.query(Client).filter_by(id=r.client_id).first()
            rows.append({"client_id": r.client_id,
                         "client_code": c.client_code if c else "",
                         "name": c.name if c else "",
                         "total": sum(l.total for l in r.lines)})
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["client_id","client_code","name","total"])


def get_client_history(client_id):
    with get_session() as s:
        reports = s.query(FeeReport).filter_by(client_id=client_id).order_by(FeeReport.year).all()
        rows = []
        for r in reports:
            rows.append({"year": r.year,
                         "q1": sum(l.effective_q1 for l in r.lines),
                         "q2": sum(l.effective_q2 for l in r.lines),
                         "q3": sum(l.effective_q3 for l in r.lines),
                         "q4": sum(l.effective_q4 for l in r.lines),
                         "total": sum(l.total for l in r.lines),
                         "report_id": r.id})
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["year","q1","q2","q3","q4","total","report_id"])


def get_yoy_comparison(year_curr, year_prev):
    df_c = get_annual_summary(year_curr).rename(columns={"total":"total_curr"})
    df_p = get_annual_summary(year_prev).rename(columns={"total":"total_prev"})
    merged = pd.merge(df_c[["client_id","name","total_curr"]],
                      df_p[["client_id","total_prev"]], on="client_id", how="outer").fillna(0)
    merged["delta_abs"] = merged["total_curr"] - merged["total_prev"]
    merged["delta_pct"] = merged.apply(lambda r: pct_change(r["total_prev"], r["total_curr"]), axis=1)
    return merged.sort_values("delta_abs", ascending=False)


def get_service_frequency(year):
    with get_session() as s:
        reports = s.query(FeeReport).filter_by(year=year).all()
        counter = defaultdict(lambda: {"count":0,"total":0.0,"description":"","category":""})
        for r in reports:
            for l in r.lines:
                if l.total > 0:
                    counter[l.service_code_snap]["description"] = l.description_snap
                    counter[l.service_code_snap]["category"] = l.category_snap or ""
                    counter[l.service_code_snap]["count"] += 1
                    counter[l.service_code_snap]["total"] += l.total
    rows = [{"service_code":k,**v} for k,v in counter.items()]
    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["service_code","description","category","count","total"])
    return df.sort_values("total", ascending=False) if not df.empty else df


def get_category_totals(year):
    with get_session() as s:
        reports = s.query(FeeReport).filter_by(year=year).all()
        totals = defaultdict(float)
        for r in reports:
            for l in r.lines: totals[l.category_snap or "Altro"] += l.total
    rows = [{"category":k,"total":v} for k,v in totals.items()]
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["category","total"])
    return df.sort_values("total", ascending=False) if not df.empty else df


def get_dashboard_kpis(year):
    df = get_annual_summary(year)
    if df.empty:
        return {"total_revenue":0.0,"client_count":0,"avg_per_client":0.0,
                "top_client":None,"top_client_total":0.0}
    return {"total_revenue": df["total"].sum(), "client_count": len(df),
            "avg_per_client": df["total"].mean(),
            "top_client": df.loc[df["total"].idxmax(),"name"],
            "top_client_total": df["total"].max()}


def get_quarterly_trend(year):
    with get_session() as s:
        reports = s.query(FeeReport).filter_by(year=year).all()
        t = {"T1":0.0,"T2":0.0,"T3":0.0,"T4":0.0}
        for r in reports:
            for l in r.lines:
                t["T1"] += l.effective_q1; t["T2"] += l.effective_q2
                t["T3"] += l.effective_q3; t["T4"] += l.effective_q4
    return t


def get_client_report_lines_df(report):
    rows = [{"Codice": l.service_code_snap, "Prestazione": l.description_snap,
             "Categoria": l.category_snap or "",
             "T1": l.effective_q1, "T2": l.effective_q2,
             "T3": l.effective_q3, "T4": l.effective_q4,
             "Totale": l.total} for l in report.lines]
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["Codice","Prestazione","Categoria","T1","T2","T3","T4","Totale"])
