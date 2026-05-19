"""
statistics.py — Calcolo statistiche, confronti storici, KPI per dashboard.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

import pandas as pd

from database import Client, FeeReport, get_session
from utils import pct_change


def get_annual_summary(year: int) -> pd.DataFrame:
    with get_session() as session:
        reports = (session.query(FeeReport)
                   .filter_by(year=year).all())
        results = []
        for r in reports:
            client = session.query(Client).filter_by(id=r.client_id).first()
            total = sum(l.total for l in r.lines)
            results.append({
                "client_id":   r.client_id,
                "client_code": client.client_code if client else "",
                "name":        client.name if client else "",
                "total":       total,
            })
    return pd.DataFrame(results) if results else pd.DataFrame(
        columns=["client_id", "client_code", "name", "total"])


def get_client_history(client_id: int) -> pd.DataFrame:
    with get_session() as session:
        reports = (session.query(FeeReport)
                   .filter_by(client_id=client_id)
                   .order_by(FeeReport.year).all())
        rows = []
        for r in reports:
            total = sum(l.total for l in r.lines)
            rows.append({
                "year":       r.year,
                "q1":         sum(l.effective_q1 for l in r.lines),
                "q2":         sum(l.effective_q2 for l in r.lines),
                "q3":         sum(l.effective_q3 for l in r.lines),
                "q4":         sum(l.effective_q4 for l in r.lines),
                "total":      total,
                "hours":      (r.hours_q1 or 0) + (r.hours_q2 or 0) + (r.hours_q3 or 0) + (r.hours_q4 or 0),
                "report_id":  r.id,
            })
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["year", "q1", "q2", "q3", "q4", "total", "hours", "report_id"])


def get_yoy_comparison(year_curr: int, year_prev: int) -> pd.DataFrame:
    df_curr = get_annual_summary(year_curr).rename(columns={"total": "total_curr"})
    df_prev = get_annual_summary(year_prev).rename(columns={"total": "total_prev"})
    merged = pd.merge(
        df_curr[["client_id", "name", "total_curr"]],
        df_prev[["client_id", "total_prev"]],
        on="client_id", how="outer"
    ).fillna(0)
    merged["delta_abs"] = merged["total_curr"] - merged["total_prev"]
    merged["delta_pct"] = merged.apply(
        lambda r: pct_change(r["total_prev"], r["total_curr"]), axis=1)
    return merged.sort_values("delta_abs", ascending=False)


def get_service_frequency(year: int) -> pd.DataFrame:
    with get_session() as session:
        reports = session.query(FeeReport).filter_by(year=year).all()
        counter: dict = defaultdict(lambda: {"count": 0, "total": 0.0,
                                             "description": "", "category": ""})
        for r in reports:
            for line in r.lines:
                if line.total > 0:
                    k = line.service_code_snap
                    counter[k]["description"] = line.description_snap
                    counter[k]["category"]    = line.category_snap or ""
                    counter[k]["count"]       += 1
                    counter[k]["total"]       += line.total

    rows = [{"service_code": k, **v} for k, v in counter.items()]
    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["service_code", "description", "category", "count", "total"])
    return df.sort_values("total", ascending=False) if not df.empty else df


def get_category_totals(year: int) -> pd.DataFrame:
    with get_session() as session:
        reports = session.query(FeeReport).filter_by(year=year).all()
        totals: dict = defaultdict(float)
        for r in reports:
            for line in r.lines:
                cat = line.category_snap or "Altro"
                totals[cat] += line.total
    rows = [{"category": k, "total": v} for k, v in totals.items()]
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["category", "total"])
    return df.sort_values("total", ascending=False) if not df.empty else df


def get_dashboard_kpis(year: int) -> dict:
    df = get_annual_summary(year)
    if df.empty:
        return {"total_revenue": 0.0, "client_count": 0,
                "avg_per_client": 0.0, "top_client": None, "top_client_total": 0.0}
    return {
        "total_revenue":    df["total"].sum(),
        "client_count":     len(df),
        "avg_per_client":   df["total"].mean(),
        "top_client":       df.loc[df["total"].idxmax(), "name"],
        "top_client_total": df["total"].max(),
    }


def get_quarterly_trend(year: int) -> dict:
    with get_session() as session:
        reports = session.query(FeeReport).filter_by(year=year).all()
        totals = {"T1": 0.0, "T2": 0.0, "T3": 0.0, "T4": 0.0}
        for r in reports:
            for line in r.lines:
                totals["T1"] += line.effective_q1
                totals["T2"] += line.effective_q2
                totals["T3"] += line.effective_q3
                totals["T4"] += line.effective_q4
    return totals


def get_client_report_lines_df(report) -> pd.DataFrame:
    rows = []
    for line in report.lines:
        rows.append({
            "Codice":      line.service_code_snap,
            "Prestazione": line.description_snap,
            "Categoria":   line.category_snap or "",
            "T1":          line.effective_q1,
            "T2":          line.effective_q2,
            "T3":          line.effective_q3,
            "T4":          line.effective_q4,
            "Totale":      line.total,
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["Codice", "Prestazione", "Categoria", "T1", "T2", "T3", "T4", "Totale"])
