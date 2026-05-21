"""
app.py — Entry point Streamlit.
"""
from __future__ import annotations
import datetime
from typing import Optional
import pandas as pd
import streamlit as st

from database import (
    Client, FeeReport, FeeReportLine, PriceList, ServiceBracket, ServiceItem,
    authenticate, get_all_settings, get_client, get_clients, get_fee_report,
    get_fee_report_by_client_year, get_fee_reports, get_price_list,
    get_price_lists, get_session, get_users, init_db, save_client, save_user, set_setting,
)
from excel_parser import parse_clients_file, VALID_TYPES
from pdf_generator import generate_fee_report_pdf
from statistics import (
    get_annual_summary, get_category_totals, get_client_history,
    get_client_report_lines_df, get_dashboard_kpis, get_quarterly_trend,
    get_service_frequency, get_yoy_comparison,
)
from utils import (
    CALC_TYPES, CLIENT_STATUSES, CLIENT_TYPES, QUARTERS,
    calc_quarterly_fee, clone_price_list_for_year, fmt_currency, fmt_num,
    recalc_line, validate_client,
)

init_db()

st.set_page_config(page_title="Studio Parcelle", page_icon="⚖️",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    [data-testid="stSidebar"] { background-color: #f8f9fa; border-right: 1px solid #e0e0e0; }
    [data-testid="stSidebar"] * { color: #212121 !important; }
    [data-testid="stSidebar"] hr { border-color: #e0e0e0; }
    .section-title {
        font-size: 1.3rem; font-weight: 600; color: #212121;
        border-bottom: 2px solid #1976d2; padding-bottom: 6px; margin-bottom: 16px;
    }
    .kpi-box { background:#f0f4f8; border-radius:8px; padding:12px; text-align:center; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def is_logged_in(): return st.session_state.get("user") is not None
def is_admin():
    u = st.session_state.get("user")
    return u is not None and u.role == "admin"

def login_page():
    col1,col2,col3 = st.columns([1,2,1])
    with col2:
        st.markdown("## ⚖️ Studio Parcelle")
        with st.form("login"):
            un = st.text_input("Username")
            pw = st.text_input("Password", type="password")
            if st.form_submit_button("Accedi", use_container_width=True):
                u = authenticate(un, pw)
                if u: st.session_state["user"] = u; st.rerun()
                else: st.error("Credenziali non valide.")

MENU = {
    "📊 Dashboard":           "dashboard",
    "👥 Clienti":             "clients",
    "📥 Import anagrafiche":  "import",
    "📋 Listino prestazioni": "pricelist",
    "📝 Rendiconto":          "new_report",
    "📁 Storico":             "history",
    "📈 Statistiche":         "stats",
    "⚙️ Impostazioni":        "settings",
}

def sidebar():
    with st.sidebar:
        s = get_all_settings()
        st.markdown(f"### {s.get('studio_name','Studio Parcelle')}")
        u = st.session_state.get("user")
        if u: st.caption(f"👤 {u.full_name or u.username} · {u.role}")
        st.markdown("---")
        sel = st.radio("Menu", list(MENU.keys()), label_visibility="collapsed")
        st.markdown("---")
        if st.button("Esci", use_container_width=True):
            st.session_state.clear(); st.rerun()
    return MENU[sel]


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def page_dashboard():
    st.markdown('<div class="section-title">📊 Dashboard</div>', unsafe_allow_html=True)
    year = st.selectbox("Anno", range(datetime.date.today().year, datetime.date.today().year-6,-1))
    kpis = get_dashboard_kpis(year)
    q    = get_quarterly_trend(year)

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Fatturato totale",    fmt_currency(kpis["total_revenue"]))
    c2.metric("Clienti rendicontati", kpis["client_count"])
    c3.metric("Media per cliente",   fmt_currency(kpis["avg_per_client"]))
    c4.metric("Cliente principale",  kpis.get("top_client") or "—")

    st.markdown("---")
    ca,cb = st.columns(2)
    with ca:
        st.markdown("**Andamento trimestrale**")
        st.bar_chart(pd.DataFrame({"T":list(q.keys()),"€":list(q.values())}).set_index("T"))
    with cb:
        st.markdown("**Per categoria**")
        df = get_category_totals(year)
        if not df.empty: st.bar_chart(df.set_index("category")["total"])
        else: st.info("Nessun dato.")

    st.markdown("---")
    df = get_annual_summary(year)
    if not df.empty:
        df2 = df[["client_code","name","total"]].copy()
        df2.columns = ["Codice","Cliente","Totale"]
        df2["Totale"] = df2["Totale"].apply(fmt_currency)
        st.dataframe(df2, use_container_width=True, hide_index=True)
    else:
        st.info(f"Nessun rendiconto per {year}.")


# ---------------------------------------------------------------------------
# Clienti
# ---------------------------------------------------------------------------

def page_clients():
    st.markdown('<div class="section-title">👥 Gestione clienti</div>', unsafe_allow_html=True)
    t1,t2,t3 = st.tabs(["📋 Elenco","➕ Nuovo","✏️ Modifica"])
    with t1:
        arch = st.checkbox("Mostra archiviati")
        cl = get_clients(include_archived=arch)
        if cl:
            df = pd.DataFrame([{"Codice":c.client_code,"Denominazione":c.name,
                                 "Tipo":c.client_type,"P.IVA":c.vat_number or "",
                                 "C.F.":c.tax_code or "","Stato":c.status} for c in cl])
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption(f"{len(cl)} clienti")
        else: st.info("Nessun cliente.")
    with t2: _client_form(None)
    with t3:
        cl_all = get_clients(include_archived=True)
        if not cl_all: st.info("Nessun cliente.")
        else:
            opts = {f"{c.client_code} — {c.name}": c.id for c in cl_all}
            sel = st.selectbox("Seleziona", list(opts.keys()))
            if sel: _client_form(opts[sel])


def _client_form(client_id):
    ex = get_client(client_id) if client_id else None
    with st.form(f"cf_{client_id or 'new'}"):
        c1,c2 = st.columns(2)
        with c1:
            code  = st.text_input("Codice *", value=ex.client_code if ex else "")
            name  = st.text_input("Denominazione *", value=ex.name if ex else "")
            cf    = st.text_input("Codice fiscale", value=ex.tax_code or "" if ex else "")
            piva  = st.text_input("Partita IVA", value=ex.vat_number or "" if ex else "")
        with c2:
            ctype = st.selectbox("Tipologia *", CLIENT_TYPES,
                                 index=CLIENT_TYPES.index(ex.client_type) if ex and ex.client_type in CLIENT_TYPES else 0)
            status= st.selectbox("Stato", CLIENT_STATUSES,
                                 index=CLIENT_STATUSES.index(ex.status) if ex and ex.status in CLIENT_STATUSES else 0)
            notes = st.text_area("Note", value=ex.notes or "" if ex else "", height=100)
        if st.form_submit_button("💾 Salva", use_container_width=True):
            data = {"client_code":code.strip(),"name":name.strip(),
                    "tax_code":cf.strip().upper(),"vat_number":piva.strip(),
                    "client_type":ctype,"status":status,"notes":notes.strip()}
            if ex: data["id"] = ex.id
            errs = validate_client(data)
            if errs:
                for e in errs: st.error(e)
            else:
                try: save_client(data); st.success("Salvato."); st.rerun()
                except Exception as e: st.error(f"Errore: {e}")


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def page_import():
    st.markdown('<div class="section-title">📥 Import anagrafiche</div>', unsafe_allow_html=True)
    st.markdown("""
Carica un file **CSV o XLSX** con le colonne:

| Colonna | Obbligatoria | Note |
|---------|:---:|------|
| `denominazione` | ✅ | Nome o ragione sociale |
| `codice` | ✅ | Codice cliente |
| `C.F.` | — | Codice fiscale |
| `P.IVA` | — | Partita IVA (11 cifre) |
| `tipologia` | — | persona fisica / ditta individuale / società di persone / società di capitali / ente / altro |
| `note` | — | Note libere |
""")
    up = st.file_uploader("Scegli file", type=["csv","xlsx","xls"])
    if up:
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False, suffix=up.name) as tmp:
            tmp.write(up.read()); tmp_path = tmp.name
        try:
            clients, warnings = parse_clients_file(tmp_path)
            for w in warnings: st.warning(w)
            if clients:
                st.success(f"Trovati **{len(clients)}** clienti.")
                df = pd.DataFrame([{"Codice":c["client_code"],"Denominazione":c["name"],
                                     "C.F.":c["tax_code"],"P.IVA":c["vat_number"],
                                     "Tipologia":c["client_type"]} for c in clients])
                st.dataframe(df, use_container_width=True, hide_index=True)
                if st.button("📥 Importa tutti", type="primary"):
                    ok=ko=0
                    for c in clients:
                        try: save_client(c); ok+=1
                        except: ko+=1
                    st.success(f"✅ Importati: {ok}  |  ⏭️ Saltati: {ko}")
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Listino
# ---------------------------------------------------------------------------

def page_pricelist():
    st.markdown('<div class="section-title">📋 Listino prestazioni</div>', unsafe_allow_html=True)
    pls = get_price_lists()
    t1,t2,t3 = st.tabs(["📋 Visualizza / Modifica","➕ Nuovo listino","📋 Clona listino"])

    with t1:
        if not pls: st.info("Nessun listino. Crea dalla scheda 'Nuovo listino'."); return
        opts = {f"{pl.year} — {pl.name}": pl.id for pl in pls}
        sel  = st.selectbox("Listino", list(opts.keys()))
        pl   = get_price_list(opts[sel])
        if not pl: return

        c1,c2,c3 = st.columns(3)
        c1.metric("Anno", pl.year)
        c2.metric("Prestazioni", len(pl.services))
        c3.metric("Stato", "✅ Attivo" if pl.is_active else "⛔ Non attivo")
        st.markdown("---")

        if pl.services:
            for svc in pl.services:
                badge = "🔢" if svc.calc_type=="scaglioni" else "📐"
                with st.expander(f"{badge} **{svc.service_code}** — {svc.description}"):
                    _service_form(svc, pl.id, readonly=not is_admin())
        else:
            st.info("Nessuna prestazione.")

        if is_admin():
            st.markdown("---")
            st.markdown("**➕ Aggiungi prestazione**")
            _service_form(None, pl.id)

    with t2:
        if not is_admin(): st.warning("Solo admin."); return
        with st.form("new_pl"):
            c1,c2 = st.columns(2)
            with c1:
                ny = st.number_input("Anno *", min_value=2000, max_value=2099,
                                     value=datetime.date.today().year)
                nn = st.text_input("Nome *", value=f"Listino {datetime.date.today().year}")
            with c2:
                nt = st.text_area("Note", height=80)
                na = st.checkbox("Attivo", value=True)
            sub = st.form_submit_button("💾 Crea listino", use_container_width=True)
        if sub:
            if not nn.strip(): st.error("Nome obbligatorio.")
            else:
                try:
                    with get_session() as s:
                        if s.query(PriceList).filter_by(year=int(ny)).first():
                            st.error(f"Anno {ny} già presente.")
                        else:
                            s.add(PriceList(year=int(ny),name=nn.strip(),notes=nt,is_active=na))
                    st.success(f"✅ Listino {ny} creato."); st.rerun()
                except Exception as e: st.error(f"Errore: {e}")

    with t3:
        if not is_admin(): st.warning("Solo admin."); return
        if not pls: st.info("Nessun listino."); return
        st.markdown("Copia un listino in un nuovo anno con eventuale aumento % su tutti i prezzi.")
        c1,c2,c3 = st.columns(3)
        with c1: sy = st.selectbox("Anno sorgente", [pl.year for pl in pls])
        with c2: ty = st.number_input("Anno destinazione", min_value=2000, max_value=2099,
                                       value=max(pl.year for pl in pls)+1)
        with c3: pct= st.number_input("Aumento %", value=0.0, step=0.1)
        if st.button("📋 Clona", type="primary"):
            try:
                clone_price_list_for_year(int(sy),int(ty),float(pct))
                st.success(f"✅ Listino {ty} creato."); st.rerun()
            except Exception as e: st.error(f"Errore: {e}")


def _service_form(svc, price_list_id, readonly=False):
    fk = f"svcf_{svc.id if svc else 'new'}_{price_list_id}"
    with st.form(fk):
        c1,c2,c3 = st.columns(3)
        with c1:
            code     = st.text_input("Codice *", value=svc.service_code if svc else "", disabled=readonly)
            category = st.text_input("Categoria", value=svc.category or "" if svc else "", disabled=readonly)
        with c2:
            desc = st.text_input("Descrizione *", value=svc.description if svc else "", disabled=readonly)
            calc_type = st.selectbox("Tipo calcolo *", list(CALC_TYPES.keys()),
                index=list(CALC_TYPES.keys()).index(svc.calc_type) if svc and svc.calc_type in CALC_TYPES else 0,
                format_func=lambda x: CALC_TYPES[x], disabled=readonly)
        with c3:
            sort_order = st.number_input("Ordine", value=svc.sort_order if svc else 0, step=1, disabled=readonly)
            active = st.checkbox("Attiva", value=svc.is_active if svc else True, disabled=readonly)

        unit_price = driver_label = driver_unit = marginal_rate = None
        has_mr = False

        if calc_type == "unitario":
            ca,cb = st.columns(2)
            with ca: unit_price = st.number_input("Tariffa unitaria (€) *",
                value=float(svc.unit_price or 0) if svc else 0.0, step=0.01, disabled=readonly)
            with cb: driver_unit= st.text_input("Unità",
                value=svc.driver_unit or "" if svc else "", disabled=readonly)
            driver_label = st.text_input("Etichetta quantità",
                value=svc.driver_label or "" if svc else "", disabled=readonly)
        else:
            ca,cb = st.columns(2)
            with ca: driver_label = st.text_input("Etichetta driver",
                value=svc.driver_label or "" if svc else "", disabled=readonly,
                help="Es. 'Numero registrazioni', 'Volume d\\'affari'")
            with cb: driver_unit = st.text_input("Unità driver",
                value=svc.driver_unit or "" if svc else "", disabled=readonly,
                help="Es. 'registrazioni', '€'")
            has_mr = st.checkbox("Tariffa marginale oltre ultimo scaglione",
                value=svc.has_marginal_rate if svc else False, disabled=readonly,
                help="Attiva solo per driver quantitativi (registrazioni, fatture). NON per driver monetari (fatturato, attivo).")
            if has_mr:
                marginal_rate = st.number_input("€ per unità oltre ultimo scaglione",
                    value=float(svc.marginal_rate or 0) if svc else 0.0, step=0.01, disabled=readonly)

            # Tabella scaglioni esistenti
            if svc and svc.brackets:
                st.markdown("**Scaglioni (valori annui del driver → compenso annuo):**")
                br_data = [{"Da": b.threshold_from,
                            "A": b.threshold_to if b.threshold_to else "∞",
                            "Compenso annuo €": b.annual_fee}
                           for b in sorted(svc.brackets, key=lambda x: x.threshold_from)]
                st.dataframe(pd.DataFrame(br_data), hide_index=True, use_container_width=True)

        if not readonly:
            sub = st.form_submit_button("💾 Salva prestazione", use_container_width=True)
            if sub:
                if not code.strip() or not desc.strip():
                    st.error("Codice e descrizione obbligatori.")
                else:
                    with get_session() as session:
                        if svc:
                            item = session.query(ServiceItem).filter_by(id=svc.id).first()
                        else:
                            item = ServiceItem(price_list_id=price_list_id)
                            session.add(item)
                        item.service_code = code.strip()
                        item.description  = desc.strip()
                        item.category     = category.strip() if category else ""
                        item.calc_type    = calc_type
                        item.driver_label = driver_label.strip() if driver_label else ""
                        item.driver_unit  = driver_unit.strip() if driver_unit else ""
                        item.unit_price   = unit_price
                        item.has_marginal_rate = has_mr
                        item.marginal_rate= marginal_rate if has_mr else None
                        item.is_active    = active
                        item.sort_order   = int(sort_order)
                    st.success("✅ Salvato."); st.rerun()
        else:
            st.form_submit_button("(sola lettura)", disabled=True)

    # Gestione scaglioni fuori dal form
    if svc and svc.calc_type == "scaglioni" and not readonly and is_admin():
        with st.expander("➕ Aggiungi / elimina scaglioni"):
            _bracket_editor(svc.id)


def _bracket_editor(service_id):
    with st.form(f"br_{service_id}"):
        st.markdown("**Aggiungi scaglione** (inserisci valori annui del driver):")
        c1,c2,c3 = st.columns(3)
        with c1: tf = st.number_input("Da (incluso)", value=0.0, step=1.0)
        with c2: ts = st.text_input("A (vuoto = illimitato)")
        with c3: af = st.number_input("Compenso annuo €", value=0.0, step=1.0)
        if st.form_submit_button("➕ Aggiungi"):
            t_to = float(ts.strip()) if ts.strip() else None
            with get_session() as s:
                s.add(ServiceBracket(service_item_id=service_id,
                                     threshold_from=tf, threshold_to=t_to, annual_fee=af))
            st.success("Scaglione aggiunto."); st.rerun()


# ---------------------------------------------------------------------------
# Rendiconto — pagina principale
# ---------------------------------------------------------------------------

def page_new_report():
    st.markdown('<div class="section-title">📝 Rendiconto cliente</div>', unsafe_allow_html=True)

    clients = get_clients()
    pls     = [pl for pl in get_price_lists() if pl.is_active]
    if not clients: st.warning("Nessun cliente."); return
    if not pls:     st.warning("Nessun listino attivo."); return

    c1,c2,c3 = st.columns(3)
    with c1:
        copts = {f"{c.client_code} — {c.name}": c.id for c in clients}
        ck    = st.selectbox("Cliente *", list(copts.keys()))
        client_id = copts[ck]
    with c2:
        cy = datetime.date.today().year
        year = st.selectbox("Anno *", range(cy+1, cy-6, -1))
    with c3:
        plopts = {f"{pl.year} — {pl.name}": pl.id for pl in pls}
        pk     = st.selectbox("Listino *", list(plopts.keys()))
        pl_id  = plopts[pk]

    pl     = get_price_list(pl_id)
    client = get_client(client_id)
    ex     = get_fee_report_by_client_year(client_id, year)
    if ex: st.info(f"Rendiconto {year} per **{client.name}** già presente.")

    if st.button("📂 Apri rendiconto", type="primary"):
        if not ex:
            with get_session() as s:
                r = FeeReport(client_id=client_id, year=year)
                s.add(r); s.flush()
                rid = r.id
            st.session_state["open_report_id"] = rid
            st.success("Rendiconto creato.")
        else:
            st.session_state["open_report_id"] = ex.id
        st.rerun()

    rid = st.session_state.get("open_report_id")
    if rid:
        report = get_fee_report(rid)
        if report and report.client_id == client_id:
            _report_editor(report, pl)


def _report_editor(report: FeeReport, pl: PriceList):
    client = get_client(report.client_id)
    st.markdown(f"### {client.name} — Anno {report.year}")

    # ---- TAB principali ----
    tab_prest, tab_kpi, tab_vista, tab_pdf = st.tabs(
        ["📋 Prestazioni", "📊 KPI studio", "📄 Riepilogo", "🖨️ PDF"])

    # ================================================================
    # TAB 1: Selezione e inserimento prestazioni
    # ================================================================
    with tab_prest:
        pl_services = {svc.service_code: svc for svc in pl.services if svc.is_active}
        existing_codes = {l.service_code_snap for l in report.lines}

        # Aggiungi prestazione dal listino
        st.markdown("**Aggiungi prestazione dal listino:**")
        available = [svc for svc in pl.services if svc.is_active and svc.service_code not in existing_codes]
        if available:
            c1, c2 = st.columns([4,1])
            with c1:
                add_opts = {f"{s.service_code} — {s.description}": s.id for s in available}
                add_sel  = st.selectbox("Seleziona prestazione", list(add_opts.keys()), label_visibility="collapsed")
            with c2:
                if st.button("➕ Aggiungi", use_container_width=True):
                    svc_id = add_opts[add_sel]
                    with get_session() as sess:
                        svc = sess.query(ServiceItem).filter_by(id=svc_id).first()
                        max_order = max((l.sort_order for l in report.lines), default=0)
                        sess.add(FeeReportLine(
                            report_id=report.id,
                            sort_order=max_order + 10,
                            service_item_id=svc.id,
                            service_code_snap=svc.service_code,
                            description_snap=svc.description,
                            category_snap=svc.category or "",
                            calc_type_snap=svc.calc_type,
                            driver_label_snap=svc.driver_label or "",
                            driver_unit_snap=svc.driver_unit or "",
                        ))
                    st.rerun()
        else:
            st.caption("Tutte le prestazioni del listino sono già presenti.")

        st.markdown("---")

        if not report.lines:
            st.info("Nessuna prestazione aggiunta. Usa il selettore sopra.")
            return

        st.markdown("**Inserimento dati trimestrali:**")
        st.caption("Per **scaglioni**: inserisci il driver per T1, T2, T3. Il T4 è il conguaglio calcolato automaticamente. Per **quantità**: inserisci il numero di unità per ogni trimestre.")

        for line in report.lines:
            svc = pl_services.get(line.service_code_snap)
            badge = "🔢" if line.calc_type_snap == "scaglioni" else "📐"
            total_lbl = fmt_currency(line.total) if line.total else "non compilato"

            with st.expander(f"{badge} **{line.service_code_snap}** — {line.description_snap}  |  {total_lbl}"):
                col_rm, _ = st.columns([1,5])
                with col_rm:
                    if st.button("🗑️ Rimuovi", key=f"rm_{line.id}"):
                        with get_session() as sess:
                            sess.query(FeeReportLine).filter_by(id=line.id).delete()
                        st.rerun()

                with st.form(f"line_{line.id}"):
                    driver_lbl  = line.driver_label_snap or "Quantità"
                    driver_unit = line.driver_unit_snap or ""
                    is_scaglioni = line.calc_type_snap == "scaglioni"

                    c1,c2,c3,c4 = st.columns(4)
                    dvs = {}; ovs = {}

                    for q, col in enumerate([c1,c2,c3,c4], 1):
                        is_cong = is_scaglioni and q == 4
                        with col:
                            st.markdown(f"**T{q}**" + (" *(conguaglio)*" if is_cong else ""))
                            cur_d = getattr(line, f"driver_q{q}") or 0.0

                            if is_cong:
                                dvs[q] = cur_d
                                fee_val = getattr(line, f"fee_q{q}") or 0.0
                                st.metric("Conguaglio", fmt_currency(fee_val))
                            else:
                                lbl = f"{driver_lbl}"
                                if driver_unit: lbl += f" ({driver_unit})"
                                dvs[q] = st.number_input(lbl, value=float(cur_d),
                                    step=1.0, key=f"d_{line.id}_{q}", min_value=0.0)
                                calc = calc_quarterly_fee(svc, dvs[q]) if svc else 0.0
                                st.caption(f"Calcolato: {fmt_currency(calc)}")

                            cur_ov = getattr(line, f"override_q{q}")
                            ov_str = st.text_input("Override",
                                value=str(cur_ov) if cur_ov is not None else "",
                                key=f"ov_{line.id}_{q}",
                                help="Lascia vuoto per usare il calcolato",
                                disabled=is_cong)
                            try: ovs[q] = float(ov_str) if ov_str.strip() else None
                            except: ovs[q] = None

                    ln = st.text_input("Note", value=line.notes or "", key=f"ln_{line.id}")

                    if st.form_submit_button("💾 Salva riga", use_container_width=True):
                        with get_session() as sess:
                            db_l = sess.query(FeeReportLine).filter_by(id=line.id).first()
                            for q in range(1,5):
                                setattr(db_l, f"driver_q{q}", dvs[q])
                                setattr(db_l, f"override_q{q}", ovs[q])
                            if svc: recalc_line(db_l, svc)
                            db_l.notes = ln
                        st.success("✅ Salvato."); st.rerun()

    # ================================================================
    # TAB 2: KPI studio
    # ================================================================
    with tab_kpi:
        st.markdown("**Dati anno in corso — per trimestre**")

        with st.form("kpi_form"):
            # Tabella inserimento ore e compenso a ore
            st.markdown("*Ore lavorate e compenso a ore (inserimento manuale):*")
            kpi_cols = st.columns(5)
            kpi_cols[0].markdown("**Campo**")
            for i,q in enumerate(["T1","T2","T3","T4","Annuale"],1):
                kpi_cols[i].markdown(f"**{q}**")

            # Ore lavorate
            ore_row = [st.columns(5)]
            r = st.columns(5)
            r[0].markdown("Ore lavorate")
            ore_q1 = r[1].number_input("", value=float(report.ore_q1 or 0), step=0.25, key="ore1", label_visibility="collapsed")
            ore_q2 = r[2].number_input("", value=float(report.ore_q2 or 0), step=0.25, key="ore2", label_visibility="collapsed")
            ore_q3 = r[3].number_input("", value=float(report.ore_q3 or 0), step=0.25, key="ore3", label_visibility="collapsed")
            ore_q4 = r[4].number_input("", value=float(report.ore_q4 or 0), step=0.25, key="ore4", label_visibility="collapsed")

            # Compenso a ore
            r2 = st.columns(5)
            r2[0].markdown("Compenso a ore (€)")
            co_q1 = r2[1].number_input("", value=float(report.comp_ore_q1 or 0), step=1.0, key="co1", label_visibility="collapsed")
            co_q2 = r2[2].number_input("", value=float(report.comp_ore_q2 or 0), step=1.0, key="co2", label_visibility="collapsed")
            co_q3 = r2[3].number_input("", value=float(report.comp_ore_q3 or 0), step=1.0, key="co3", label_visibility="collapsed")
            co_q4 = r2[4].number_input("", value=float(report.comp_ore_q4 or 0), step=1.0, key="co4", label_visibility="collapsed")

            st.markdown("---")
            st.markdown("**Anno precedente** *(inserimento manuale)*")
            cp1,cp2 = st.columns(2)
            with cp1: fat_prec = st.number_input("Fatturato anno precedente (€)",
                                                   value=float(report.fatturato_prec or 0), step=1.0)
            with cp2: ore_prec = st.number_input("Ore lavorate anno precedente",
                                                   value=float(report.ore_prec or 0), step=0.25)

            notes_kpi = st.text_area("Note rendiconto", value=report.notes or "")

            if st.form_submit_button("💾 Salva KPI", use_container_width=True):
                with get_session() as sess:
                    r_db = sess.query(FeeReport).filter_by(id=report.id).first()
                    r_db.ore_q1=ore_q1; r_db.ore_q2=ore_q2; r_db.ore_q3=ore_q3; r_db.ore_q4=ore_q4
                    r_db.comp_ore_q1=co_q1; r_db.comp_ore_q2=co_q2
                    r_db.comp_ore_q3=co_q3; r_db.comp_ore_q4=co_q4
                    r_db.fatturato_prec=fat_prec; r_db.ore_prec=ore_prec
                    r_db.notes=notes_kpi
                st.success("✅ Salvato."); st.rerun()

        # Valori calcolati
        st.markdown("---")
        st.markdown("**Valori calcolati — anno in corso**")

        report = get_fee_report(report.id)  # ricarica
        fat_q = [sum(getattr(l, f"effective_q{q}") for l in report.lines) for q in range(1,5)]
        fat_tot = sum(fat_q)
        ore_vals = [report.ore_q1 or 0, report.ore_q2 or 0, report.ore_q3 or 0, report.ore_q4 or 0]
        co_vals  = [report.comp_ore_q1 or 0, report.comp_ore_q2 or 0,
                    report.comp_ore_q3 or 0, report.comp_ore_q4 or 0]

        def _resa(fat, ore): return round(fat/ore, 2) if ore > 0 else None
        def _cor_teo(co, ore): return round(co/ore, 2) if ore > 0 else None

        df_calc = pd.DataFrame({
            "Campo": ["Compenso orario teorico (€/h)", "Fatturato parcella (€)", "Compenso orario reale (€/h)"],
            "T1":  [fmt_currency(_cor_teo(co_vals[0],ore_vals[0])), fmt_currency(fat_q[0]), fmt_currency(_resa(fat_q[0],ore_vals[0]))],
            "T2":  [fmt_currency(_cor_teo(co_vals[1],ore_vals[1])), fmt_currency(fat_q[1]), fmt_currency(_resa(fat_q[1],ore_vals[1]))],
            "T3":  [fmt_currency(_cor_teo(co_vals[2],ore_vals[2])), fmt_currency(fat_q[2]), fmt_currency(_resa(fat_q[2],ore_vals[2]))],
            "T4":  [fmt_currency(_cor_teo(co_vals[3],ore_vals[3])), fmt_currency(fat_q[3]), fmt_currency(_resa(fat_q[3],ore_vals[3]))],
            "Annuale": [fmt_currency(_cor_teo(sum(co_vals),sum(ore_vals))),
                        fmt_currency(fat_tot),
                        fmt_currency(_resa(fat_tot, sum(ore_vals)))],
        })
        st.dataframe(df_calc, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("**Anno precedente — valori calcolati**")
        fat_p = report.fatturato_prec or 0
        ore_p = report.ore_prec or 0
        cp1,cp2,cp3 = st.columns(3)
        cp1.metric("Fatturato", fmt_currency(fat_p))
        cp2.metric("Ore", fmt_num(ore_p, 2))
        cp3.metric("Compenso orario reale", fmt_currency(_resa(fat_p, ore_p)))

    # ================================================================
    # TAB 3: Vista tabellare (come Excel)
    # ================================================================
    with tab_vista:
        report = get_fee_report(report.id)
        if not report.lines:
            st.info("Nessuna prestazione nel rendiconto."); return

        df = get_client_report_lines_df(report)
        if df.empty: st.info("Nessun dato."); return

        # Formatta per display
        df_show = df.copy()
        for col in ["T1","T2","T3","T4","Totale"]:
            df_show[col] = df_show[col].apply(fmt_currency)

        st.markdown(f"**{client.name} — Anno {report.year}**")
        st.dataframe(df_show, use_container_width=True, hide_index=True)

        # Riga totali
        totali = {q: df[f"T{q}"].sum() for q in range(1,5)}
        totali["Ann."] = df["Totale"].sum()
        st.markdown("---")
        tc = st.columns(6)
        tc[0].markdown("**TOTALE**")
        for i,(k,v) in enumerate(totali.items(),1):
            tc[i].metric(k, fmt_currency(v))

    # ================================================================
    # TAB 4: PDF
    # ================================================================
    with tab_pdf:
        st.markdown("**Scegli il periodo da stampare:**")
        pdf_opts = {
            "Solo T1":          [1],
            "T1 + T2 (cumul.)": [1,2],
            "T1+T2+T3 (cumul.)":[1,2,3],
            "Annuale completo": [1,2,3,4],
        }
        sel_pdf = st.radio("Periodo", list(pdf_opts.keys()), horizontal=True)
        quarters = pdf_opts[sel_pdf]

        if st.button("📄 Genera PDF", type="primary"):
            report = get_fee_report(report.id)
            pdf = generate_fee_report_pdf(report, client, quarters=quarters)
            fname = f"rendiconto_{client.client_code}_{report.year}_{sel_pdf.replace(' ','_').replace('+','')}.pdf"
            st.download_button("⬇️ Scarica PDF", data=pdf, file_name=fname,
                               mime="application/pdf", use_container_width=True)


# ---------------------------------------------------------------------------
# Storico
# ---------------------------------------------------------------------------

def page_history():
    st.markdown('<div class="section-title">📁 Storico rendiconti</div>', unsafe_allow_html=True)
    clients = get_clients(include_archived=True)
    if not clients: st.info("Nessun cliente."); return

    opts = {f"{c.client_code} — {c.name}": c.id for c in clients}
    sel  = st.selectbox("Cliente", list(opts.keys()))
    client = get_client(opts[sel])
    reports = get_fee_reports(opts[sel])
    if not reports: st.info("Nessun rendiconto."); return

    hist = get_client_history(opts[sel])
    if len(hist) > 1:
        st.line_chart(hist.set_index("year")["total"])

    for r in reports:
        df   = get_client_report_lines_df(r)
        tot  = df["Totale"].sum() if not df.empty else 0
        ore  = (r.ore_q1 or 0)+(r.ore_q2 or 0)+(r.ore_q3 or 0)+(r.ore_q4 or 0)

        with st.expander(f"**Anno {r.year}** — {fmt_currency(tot)}"):
            c1,c2,c3 = st.columns(3)
            c1.metric("Totale", fmt_currency(tot))
            c2.metric("Ore totali", fmt_num(ore,2))
            c3.metric("€/h reale", fmt_currency(tot/ore) if ore>0 else "—")

            if not df.empty:
                df_s = df.copy()
                for col in ["T1","T2","T3","T4","Totale"]:
                    df_s[col] = df_s[col].apply(fmt_currency)
                st.dataframe(df_s, use_container_width=True, hide_index=True)

            pdf_opts = {"Solo T1":[1],"T1+T2":[1,2],"T1+T2+T3":[1,2,3],"Annuale":[1,2,3,4]}
            ca,cb = st.columns(2)
            with ca: ps = st.selectbox("Periodo PDF", list(pdf_opts.keys()), key=f"ps_{r.id}")
            with cb:
                if st.button("📄 Genera PDF", key=f"pdf_{r.id}"):
                    pdf = generate_fee_report_pdf(r, client, quarters=pdf_opts[ps])
                    fname = f"rendiconto_{client.client_code}_{r.year}_{ps}.pdf"
                    st.download_button("⬇️ Scarica", data=pdf, file_name=fname,
                                       mime="application/pdf", key=f"dl_{r.id}")


# ---------------------------------------------------------------------------
# Statistiche
# ---------------------------------------------------------------------------

def page_stats():
    st.markdown('<div class="section-title">📈 Statistiche</div>', unsafe_allow_html=True)
    cy = datetime.date.today().year
    c1,c2 = st.columns(2)
    with c1: yc = st.selectbox("Anno corrente", range(cy,cy-6,-1))
    with c2: yp = st.selectbox("Anno confronto", range(cy-1,cy-7,-1))

    t1,t2,t3,t4 = st.tabs(["Per cliente","YoY","Prestazioni","Categorie"])

    with t1:
        df = get_annual_summary(yc)
        if df.empty: st.info(f"Nessun dato per {yc}.")
        else:
            st.bar_chart(df.sort_values("total",ascending=False).set_index("name")["total"])
            df2 = df.copy(); df2["total"] = df2["total"].apply(fmt_currency)
            st.dataframe(df2[["client_code","name","total"]].rename(
                columns={"client_code":"Codice","name":"Cliente","total":"Totale"}),
                use_container_width=True, hide_index=True)

    with t2:
        df = get_yoy_comparison(yc,yp)
        if df.empty: st.info("Nessun dato.")
        else:
            df2 = df.copy()
            df2["total_prev"] = df2["total_prev"].apply(fmt_currency)
            df2["total_curr"] = df2["total_curr"].apply(fmt_currency)
            df2["delta_abs"]  = df2["delta_abs"].apply(fmt_currency)
            df2["delta_pct"]  = df2["delta_pct"].apply(
                lambda x: f"+{x:.1f}%" if x and x>0 else (f"{x:.1f}%" if x else "—"))
            st.dataframe(df2[["name","total_prev","total_curr","delta_abs","delta_pct"]].rename(
                columns={"name":"Cliente","total_prev":str(yp),"total_curr":str(yc),
                         "delta_abs":"Δ €","delta_pct":"Δ %"}),
                use_container_width=True, hide_index=True)

    with t3:
        df = get_service_frequency(yc)
        if df.empty: st.info(f"Nessun dato per {yc}.")
        else:
            st.bar_chart(df.set_index("description")["count"])
            df2 = df.copy(); df2["total"] = df2["total"].apply(fmt_currency)
            st.dataframe(df2.rename(columns={"service_code":"Codice","description":"Prestazione",
                                              "category":"Cat.","count":"Freq.","total":"Totale"}),
                         use_container_width=True, hide_index=True)

    with t4:
        df = get_category_totals(yc)
        if df.empty: st.info(f"Nessun dato per {yc}.")
        else:
            st.bar_chart(df.set_index("category")["total"])
            df2 = df.copy(); df2["total"] = df2["total"].apply(fmt_currency)
            st.dataframe(df2.rename(columns={"category":"Categoria","total":"Totale"}),
                         use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Impostazioni
# ---------------------------------------------------------------------------

def page_settings():
    st.markdown('<div class="section-title">⚙️ Impostazioni</div>', unsafe_allow_html=True)
    t1,t2 = st.tabs(["🏢 Dati studio","👤 Utenti"])

    with t1:
        s = get_all_settings()
        with st.form("sf"):
            c1,c2 = st.columns(2)
            with c1:
                sn = st.text_input("Nome studio",  value=s.get("studio_name",""))
                sa = st.text_input("Indirizzo",     value=s.get("studio_address",""))
                sc = st.text_input("Città / CAP",   value=s.get("studio_city",""))
            with c2:
                sp = st.text_input("Telefono", value=s.get("studio_phone",""))
                se = st.text_input("Email",    value=s.get("studio_email",""))
                sv = st.text_input("P.IVA",    value=s.get("studio_piva",""))
                sf = st.text_input("C.F.",     value=s.get("studio_cf",""))
            pf = st.text_area("Footer PDF", value=s.get("pdf_footer",""), height=60)
            if st.form_submit_button("💾 Salva", use_container_width=True):
                for k,v in [("studio_name",sn),("studio_address",sa),("studio_city",sc),
                             ("studio_phone",sp),("studio_email",se),("studio_piva",sv),
                             ("studio_cf",sf),("pdf_footer",pf)]:
                    set_setting(k,v)
                st.success("✅ Salvato.")

    with t2:
        if not is_admin(): st.warning("Solo admin."); return
        users = get_users()
        st.dataframe(pd.DataFrame([{"Username":u.username,"Nome":u.full_name or "",
                                     "Ruolo":u.role,"Attivo":"✅" if u.is_active else "❌"}
                                    for u in users]),
                     use_container_width=True, hide_index=True)
        st.markdown("---")
        st.caption("Se l'username esiste, aggiorna password e ruolo.")
        with st.form("uf"):
            c1,c2 = st.columns(2)
            with c1: uu=st.text_input("Username *"); ufn=st.text_input("Nome completo")
            with c2: up=st.text_input("Password *",type="password"); ur=st.selectbox("Ruolo",["user","admin"])
            if st.form_submit_button("💾 Salva", use_container_width=True):
                if not uu or not up: st.error("Username e password obbligatori.")
                else:
                    try: save_user({"username":uu,"password":up,"full_name":ufn,"role":ur}); st.success("✅ Salvato."); st.rerun()
                    except Exception as e: st.error(f"Errore: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not is_logged_in(): login_page(); return
    page = sidebar()
    {"dashboard":page_dashboard,"clients":page_clients,"import":page_import,
     "pricelist":page_pricelist,"new_report":page_new_report,"history":page_history,
     "stats":page_stats,"settings":page_settings}[page]()

if __name__ == "__main__":
    main()
