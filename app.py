"""
app.py — Entry point Streamlit. Login, routing menu, tutte le pagine.
Avvio: streamlit run app.py
"""

from __future__ import annotations

import datetime
import io
from typing import Optional

import pandas as pd
import streamlit as st

from database import (
    Client, FeeReport, FeeReportLine, PriceList, ServiceBracket, ServiceItem,
    authenticate, get_all_settings, get_client, get_clients, get_fee_report,
    get_fee_report_by_client_year, get_fee_reports, get_price_list,
    get_price_list_by_year, get_price_lists, get_session, get_users,
    init_db, save_client, save_user, set_setting,
)
from excel_parser import parse_clients_file, parse_studio_excel
from pdf_generator import generate_fee_report_pdf
from statistics import (
    get_annual_summary, get_category_totals, get_client_history,
    get_client_report_lines_df, get_dashboard_kpis, get_quarterly_trend,
    get_service_frequency, get_yoy_comparison,
)
from utils import (
    CALC_TYPES, CLIENT_STATUSES, CLIENT_TYPES, QUARTERS,
    calc_quarterly_fee, clone_price_list_for_year, fmt_currency,
    recalc_line, validate_client, validate_service_item,
)

# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

init_db()

st.set_page_config(
    page_title="Studio Parcelle",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CSS personalizzato
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    [data-testid="stSidebar"] {background-color: #1a3a5c;}
    [data-testid="stSidebar"] * {color: #e8f0f7 !important;}
    [data-testid="stSidebar"] .stRadio label {
        padding: 6px 12px; border-radius: 6px; cursor: pointer;
    }
    [data-testid="stSidebar"] .stRadio label:hover {background: rgba(255,255,255,0.1);}
    .metric-card {
        background: white; border: 1px solid #e0e7ef; border-radius: 10px;
        padding: 20px; text-align: center;
    }
    .metric-value {font-size: 2rem; font-weight: 700; color: #1a3a5c;}
    .metric-label {font-size: 0.85rem; color: #6b7a8d; margin-top: 4px;}
    .stDataFrame {border-radius: 8px; overflow: hidden;}
    div[data-testid="stForm"] {border: 1px solid #e0e7ef; border-radius: 8px; padding: 20px;}
    .section-title {
        font-size: 1.3rem; font-weight: 600; color: #1a3a5c;
        border-bottom: 2px solid #2e6da4; padding-bottom: 6px; margin-bottom: 16px;
    }
    .warning-box {
        background: #fff3cd; border: 1px solid #ffc107;
        border-radius: 6px; padding: 10px; margin: 8px 0;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Sessione e autenticazione
# ---------------------------------------------------------------------------

def is_logged_in() -> bool:
    return st.session_state.get("user") is not None


def is_admin() -> bool:
    user = st.session_state.get("user")
    return user is not None and user.role == "admin"


def login_page():
    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("## ⚖️ Studio Parcelle")
        st.markdown("### Accesso")
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Accedi", use_container_width=True)
            if submitted:
                user = authenticate(username, password)
                if user:
                    st.session_state["user"] = user
                    st.rerun()
                else:
                    st.error("Credenziali non valide.")
        st.caption("Credenziali default: admin / admin123")


# ---------------------------------------------------------------------------
# Sidebar menu
# ---------------------------------------------------------------------------

MENU_ITEMS = {
    "📊 Dashboard":           "dashboard",
    "👥 Clienti":             "clients",
    "📥 Import anagrafiche":  "import",
    "📋 Listino prestazioni": "pricelist",
    "📝 Nuovo rendiconto":    "new_report",
    "📁 Storico rendiconti":  "history",
    "📈 Statistiche":         "stats",
    "⚙️ Impostazioni":        "settings",
}


def sidebar():
    with st.sidebar:
        settings = get_all_settings()
        st.markdown(f"### {settings.get('studio_name', 'Studio')}")
        user = st.session_state.get("user")
        if user:
            st.caption(f"👤 {user.full_name or user.username} ({user.role})")
        st.markdown("---")

        selection = st.radio(
            "Menu",
            list(MENU_ITEMS.keys()),
            label_visibility="collapsed",
        )
        st.markdown("---")
        if st.button("🚪 Esci", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    return MENU_ITEMS[selection]


# ---------------------------------------------------------------------------
# PAGINA: Dashboard
# ---------------------------------------------------------------------------

def page_dashboard():
    st.markdown('<div class="section-title">📊 Dashboard</div>', unsafe_allow_html=True)

    current_year = datetime.date.today().year
    year = st.selectbox("Anno di riferimento", range(current_year, current_year - 6, -1), key="dash_year")

    kpis = get_dashboard_kpis(year)
    q_trend = get_quarterly_trend(year)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Fatturato totale", fmt_currency(kpis["total_revenue"]))
    with col2:
        st.metric("Clienti con rendiconto", kpis["client_count"])
    with col3:
        st.metric("Media per cliente", fmt_currency(kpis["avg_per_client"]))
    with col4:
        st.metric("Cliente principale", kpis.get("top_client") or "—",
                  help=fmt_currency(kpis["top_client_total"]) if kpis.get("top_client") else None)

    st.markdown("---")
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("**Andamento trimestrale**")
        trend_df = pd.DataFrame({
            "Trimestre": list(q_trend.keys()),
            "Importo": list(q_trend.values()),
        })
        st.bar_chart(trend_df.set_index("Trimestre"), color="#2e6da4")

    with col_b:
        st.markdown("**Totali per categoria**")
        cat_df = get_category_totals(year)
        if not cat_df.empty:
            st.bar_chart(cat_df.set_index("category")["total"], color="#1a3a5c")
        else:
            st.info("Nessun dato disponibile.")

    st.markdown("---")
    st.markdown("**Riepilogo clienti**")
    df = get_annual_summary(year)
    if not df.empty:
        df_show = df[["client_code", "name", "total"]].copy()
        df_show.columns = ["Codice", "Cliente", "Totale"]
        df_show["Totale"] = df_show["Totale"].apply(fmt_currency)
        st.dataframe(df_show, use_container_width=True, hide_index=True)
    else:
        st.info(f"Nessun rendiconto per l'anno {year}.")


# ---------------------------------------------------------------------------
# PAGINA: Clienti
# ---------------------------------------------------------------------------

def page_clients():
    st.markdown('<div class="section-title">👥 Gestione clienti</div>', unsafe_allow_html=True)

    tab_list, tab_new, tab_edit = st.tabs(["📋 Elenco", "➕ Nuovo cliente", "✏️ Modifica"])

    with tab_list:
        show_archived = st.checkbox("Mostra archiviati")
        clients = get_clients(include_archived=show_archived)
        if clients:
            df = pd.DataFrame([{
                "ID": c.id,
                "Codice": c.client_code,
                "Denominazione": c.name,
                "Tipo": c.client_type,
                "P.IVA": c.vat_number or "",
                "C.F.": c.tax_code or "",
                "Stato": c.status,
            } for c in clients])
            st.dataframe(df.drop(columns=["ID"]), use_container_width=True, hide_index=True)
            st.caption(f"{len(clients)} clienti trovati")
        else:
            st.info("Nessun cliente presente.")

    with tab_new:
        _client_form(None)

    with tab_edit:
        clients_all = get_clients(include_archived=True)
        if not clients_all:
            st.info("Nessun cliente da modificare.")
        else:
            options = {f"{c.client_code} — {c.name}": c.id for c in clients_all}
            selected = st.selectbox("Seleziona cliente", list(options.keys()), key="edit_client_sel")
            if selected:
                _client_form(options[selected])


def _client_form(client_id: Optional[int]):
    existing = get_client(client_id) if client_id else None

    with st.form(f"client_form_{client_id or 'new'}"):
        col1, col2 = st.columns(2)
        with col1:
            code = st.text_input("Codice cliente *", value=existing.client_code if existing else "")
            name = st.text_input("Denominazione / Nome *", value=existing.name if existing else "")
            cf   = st.text_input("Codice fiscale", value=existing.tax_code or "" if existing else "")
            piva = st.text_input("Partita IVA", value=existing.vat_number or "" if existing else "")
        with col2:
            ctype = st.selectbox(
                "Tipologia *", CLIENT_TYPES,
                index=CLIENT_TYPES.index(existing.client_type) if existing and existing.client_type in CLIENT_TYPES else 0,
            )
            status = st.selectbox(
                "Stato", CLIENT_STATUSES,
                index=CLIENT_STATUSES.index(existing.status) if existing and existing.status in CLIENT_STATUSES else 0,
            )
            notes = st.text_area("Note", value=existing.notes or "" if existing else "", height=100)

        submitted = st.form_submit_button(
            "💾 Aggiorna cliente" if existing else "💾 Salva cliente",
            use_container_width=True,
        )
        if submitted:
            data = {
                "client_code": code.strip(),
                "name": name.strip(),
                "tax_code": cf.strip().upper(),
                "vat_number": piva.strip(),
                "client_type": ctype,
                "status": status,
                "notes": notes.strip(),
            }
            if existing:
                data["id"] = existing.id

            errors = validate_client(data)
            if errors:
                for e in errors:
                    st.error(e)
            else:
                try:
                    save_client(data)
                    st.success("Cliente salvato correttamente.")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Errore: {ex}")


# ---------------------------------------------------------------------------
# PAGINA: Import anagrafiche
# ---------------------------------------------------------------------------

def page_import():
    st.markdown('<div class="section-title">📥 Import anagrafiche</div>', unsafe_allow_html=True)

    tab_csv, tab_excel = st.tabs(["📄 CSV / XLSX anagrafica", "📊 Excel storico studio"])

    with tab_csv:
        st.markdown("Carica un file CSV o XLSX con le colonne: denominazione, codice, CF, P.IVA, tipologia.")
        uploaded = st.file_uploader("Scegli file", type=["csv", "xlsx", "xls"], key="import_csv")
        if uploaded:
            import tempfile, os
            with tempfile.NamedTemporaryFile(delete=False, suffix=uploaded.name) as tmp:
                tmp.write(uploaded.read())
                tmp_path = tmp.name
            try:
                clients, warnings = parse_clients_file(tmp_path)
                for w in warnings:
                    st.warning(w)
                if clients:
                    st.success(f"Trovati {len(clients)} clienti nel file.")
                    df_preview = pd.DataFrame(clients)
                    st.dataframe(df_preview, use_container_width=True, hide_index=True)

                    if st.button("📥 Importa tutti", type="primary"):
                        imported, skipped = 0, 0
                        for c in clients:
                            try:
                                save_client(c)
                                imported += 1
                            except Exception:
                                skipped += 1
                        st.success(f"Importati: {imported}, saltati (duplicati): {skipped}")
            finally:
                os.unlink(tmp_path)

    with tab_excel:
        st.markdown("Carica il file Excel multi-foglio dello studio per importare lo storico.")
        uploaded_xl = st.file_uploader("Scegli file Excel studio", type=["xlsx", "xls"], key="import_xl")
        if uploaded_xl:
            import tempfile, os
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                tmp.write(uploaded_xl.read())
                tmp_path = tmp.name
            try:
                results = parse_studio_excel(tmp_path)
                if "_error" in results:
                    st.error(f"Errore: {results['_error']}")
                else:
                    st.success(f"Trovati {len(results)} fogli.")
                    for sheet, data in results.items():
                        if "_error" in data:
                            st.warning(f"Foglio '{sheet}': {data['_error']}")
                            continue
                        with st.expander(f"📄 {sheet} — {data.get('client_name', '')} ({data.get('year', '?')})"):
                            lines_df = pd.DataFrame(data.get("lines", []))
                            if not lines_df.empty:
                                st.dataframe(lines_df, use_container_width=True, hide_index=True)
            finally:
                os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# PAGINA: Listino prestazioni
# ---------------------------------------------------------------------------

def page_pricelist():
    st.markdown('<div class="section-title">📋 Listino prestazioni</div>', unsafe_allow_html=True)

    price_lists = get_price_lists()

    tab_view, tab_new_list, tab_clone = st.tabs([
        "📋 Visualizza / Modifica", "➕ Nuovo listino", "📋 Clona listino"
    ])

    with tab_view:
        if not price_lists:
            st.info("Nessun listino presente. Crea il primo listino.")
        else:
            pl_options = {f"{pl.year} — {pl.name}": pl.id for pl in price_lists}
            selected_pl = st.selectbox("Seleziona listino", list(pl_options.keys()))
            pl = get_price_list(pl_options[selected_pl])

            if pl:
                col1, col2, col3 = st.columns(3)
                col1.metric("Anno", pl.year)
                col2.metric("Prestazioni", len(pl.services))
                col3.metric("Stato", "Attivo" if pl.is_active else "Non attivo")

                st.markdown("---")

                # Tabella servizi
                services = sorted(pl.services, key=lambda s: s.sort_order)
                if services:
                    for svc in services:
                        with st.expander(f"**{svc.service_code}** — {svc.description}"):
                            _service_form(svc, pl.id, readonly=not is_admin())
                else:
                    st.info("Nessuna prestazione nel listino.")

                if is_admin():
                    st.markdown("---")
                    st.markdown("**Aggiungi prestazione**")
                    _service_form(None, pl.id)

    with tab_new_list:
        if not is_admin():
            st.warning("Solo gli amministratori possono creare listini.")
        else:
            with st.form("new_pricelist"):
                col1, col2 = st.columns(2)
                with col1:
                    new_year = st.number_input("Anno *", min_value=2000, max_value=2099,
                                               value=datetime.date.today().year)
                    new_name = st.text_input("Nome listino *", value=f"Listino {datetime.date.today().year}")
                with col2:
                    new_notes = st.text_area("Note", height=80)
                    new_active = st.checkbox("Attivo", value=True)

                if st.form_submit_button("💾 Crea listino", use_container_width=True):
                    try:
                        with get_session() as session:
                            existing = session.query(PriceList).filter_by(year=new_year).first()
                            if existing:
                                st.error(f"Esiste già un listino per l'anno {new_year}.")
                            else:
                                session.add(PriceList(
                                    year=int(new_year), name=new_name,
                                    notes=new_notes, is_active=new_active,
                                ))
                        st.success(f"Listino {new_year} creato.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Errore: {e}")

    with tab_clone:
        if not is_admin():
            st.warning("Solo gli amministratori possono clonare listini.")
        elif not price_lists:
            st.info("Nessun listino da clonare.")
        else:
            st.markdown("Copia un listino esistente verso un nuovo anno, con eventuale aumento percentuale.")
            col1, col2, col3 = st.columns(3)
            with col1:
                source_year = st.selectbox("Anno sorgente", [pl.year for pl in price_lists])
            with col2:
                target_year = st.number_input("Anno destinazione", min_value=2000, max_value=2099,
                                              value=max(pl.year for pl in price_lists) + 1)
            with col3:
                pct = st.number_input("Aumento % (es. 5 per +5%)", value=0.0, step=0.1)

            if st.button("📋 Clona listino", type="primary"):
                try:
                    clone_price_list_for_year(int(source_year), int(target_year), float(pct))
                    st.success(f"Listino {target_year} creato da {source_year} con aumento {pct}%.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore: {e}")


def _service_form(svc: Optional[ServiceItem], price_list_id: int, readonly: bool = False):
    """Form per creare/modificare una voce di listino."""
    form_key = f"svc_{svc.id if svc else 'new'}_{price_list_id}"

    with st.form(form_key):
        col1, col2, col3 = st.columns(3)
        with col1:
            code = st.text_input("Codice *", value=svc.service_code if svc else "",
                                 disabled=readonly)
            category = st.text_input("Categoria", value=svc.category or "" if svc else "",
                                     disabled=readonly)
        with col2:
            desc = st.text_input("Descrizione *", value=svc.description if svc else "",
                                 disabled=readonly)
            calc_type = st.selectbox(
                "Tipo calcolo *", list(CALC_TYPES.keys()),
                index=list(CALC_TYPES.keys()).index(svc.calc_type) if svc and svc.calc_type in CALC_TYPES else 0,
                format_func=lambda x: CALC_TYPES[x],
                disabled=readonly,
            )
        with col3:
            sort_order = st.number_input("Ordinamento", value=svc.sort_order if svc else 0,
                                         step=1, disabled=readonly)
            active = st.checkbox("Attiva", value=svc.is_active if svc else True, disabled=readonly)

        # Campi specifici per tipo
        unit_price, min_fee, percent_fee, marginal_rate = None, None, None, None
        driver_label, driver_unit = "", ""

        if calc_type in ("unitario", "forfait"):
            col_a, col_b = st.columns(2)
            with col_a:
                unit_price = st.number_input("Tariffa unitaria (€)",
                                             value=float(svc.unit_price or 0) if svc else 0.0,
                                             step=0.01, disabled=readonly)
            with col_b:
                driver_unit = st.text_input("Unità driver",
                                            value=svc.driver_unit or "" if svc else "",
                                            disabled=readonly)

        elif calc_type == "minimo_percentuale":
            col_a, col_b = st.columns(2)
            with col_a:
                percent_fee = st.number_input("Percentuale (es. 0.02 per 2%)",
                                              value=float(svc.percent_fee or 0) if svc else 0.0,
                                              step=0.001, format="%.3f", disabled=readonly)
            with col_b:
                min_fee = st.number_input("Minimo garantito (€)",
                                         value=float(svc.min_fee or 0) if svc else 0.0,
                                         step=0.01, disabled=readonly)

        elif calc_type == "scaglioni":
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                driver_label = st.text_input("Etichetta driver",
                                             value=svc.driver_label or "" if svc else "",
                                             disabled=readonly,
                                             help="Es. 'Numero articoli in PD'")
            with col_b:
                driver_unit = st.text_input("Unità driver",
                                            value=svc.driver_unit or "" if svc else "",
                                            disabled=readonly,
                                            help="Es. 'registrazioni'")
            with col_c:
                marginal_rate = st.number_input("Tariffa marginale (oltre ultimo scaglione)",
                                                value=float(svc.marginal_rate or 0) if svc else 0.0,
                                                step=0.01, disabled=readonly)

            # Scaglioni esistenti
            if svc and svc.brackets:
                st.markdown("**Scaglioni:**")
                bracket_data = []
                for b in sorted(svc.brackets, key=lambda x: x.threshold_from):
                    bracket_data.append({
                        "Da": b.threshold_from,
                        "A": b.threshold_to if b.threshold_to else "∞",
                        "Compenso annuo (€)": b.annual_fee,
                        "_id": b.id,
                    })
                df_b = pd.DataFrame(bracket_data)
                st.dataframe(df_b[["Da", "A", "Compenso annuo (€)"]], hide_index=True)

        if not readonly:
            submitted = st.form_submit_button(
                "💾 Aggiorna" if svc else "💾 Aggiungi prestazione",
                use_container_width=True,
            )
            if submitted:
                with get_session() as session:
                    if svc:
                        item = session.query(ServiceItem).filter_by(id=svc.id).first()
                    else:
                        item = ServiceItem(price_list_id=price_list_id)
                        session.add(item)

                    item.service_code = code.strip()
                    item.description = desc.strip()
                    item.category = category.strip()
                    item.calc_type = calc_type
                    item.unit_price = unit_price
                    item.min_fee = min_fee
                    item.percent_fee = percent_fee
                    item.marginal_rate = marginal_rate if marginal_rate else None
                    item.driver_label = driver_label.strip()
                    item.driver_unit = driver_unit.strip()
                    item.is_active = active
                    item.sort_order = int(sort_order)
                st.success("Prestazione salvata.")
                st.rerun()
        else:
            st.form_submit_button("(sola lettura)", disabled=True)


def _bracket_editor(service_id: int):
    """Gestione scaglioni per una prestazione."""
    with get_session() as session:
        svc = session.query(ServiceItem).filter_by(id=service_id).first()
        if not svc:
            return

        st.markdown("**Aggiungi scaglione:**")
        with st.form(f"bracket_add_{service_id}"):
            c1, c2, c3 = st.columns(3)
            with c1:
                t_from = st.number_input("Da (incluso)", value=0.0, step=1.0)
            with c2:
                t_to_str = st.text_input("A (lascia vuoto per ∞)", value="")
            with c3:
                ann_fee = st.number_input("Compenso annuo (€)", value=0.0, step=1.0)

            if st.form_submit_button("➕ Aggiungi scaglione"):
                t_to = float(t_to_str) if t_to_str.strip() else None
                session.add(ServiceBracket(
                    service_item_id=service_id,
                    threshold_from=t_from,
                    threshold_to=t_to,
                    annual_fee=ann_fee,
                ))
                st.success("Scaglione aggiunto.")
                st.rerun()


# ---------------------------------------------------------------------------
# PAGINA: Nuovo rendiconto
# ---------------------------------------------------------------------------

def page_new_report():
    st.markdown('<div class="section-title">📝 Gestione rendiconto</div>', unsafe_allow_html=True)

    clients = get_clients()
    if not clients:
        st.warning("Nessun cliente presente. Crea prima un cliente.")
        return

    price_lists = get_price_lists()
    active_lists = [pl for pl in price_lists if pl.is_active]
    if not active_lists:
        st.warning("Nessun listino attivo. Crea prima un listino.")
        return

    # Selezione cliente e anno
    col1, col2, col3 = st.columns(3)
    with col1:
        client_options = {f"{c.client_code} — {c.name}": c.id for c in clients}
        selected_client_key = st.selectbox("Cliente *", list(client_options.keys()))
        client_id = client_options[selected_client_key]
    with col2:
        current_year = datetime.date.today().year
        year = st.selectbox("Anno *", range(current_year + 1, current_year - 6, -1))
    with col3:
        pl_options = {f"{pl.year} — {pl.name}": pl.id for pl in active_lists}
        selected_pl_key = st.selectbox("Listino di riferimento *", list(pl_options.keys()))
        pl_id = pl_options[selected_pl_key]

    client = get_client(client_id)
    pl = get_price_list(pl_id)
    existing_report = get_fee_report_by_client_year(client_id, year)

    if existing_report:
        st.info(f"Esiste già un rendiconto per {client.name} — anno {year}. Stai modificando quello esistente.")
        report = existing_report
    else:
        report = None

    if st.button("📂 Apri / Crea rendiconto", type="primary"):
        if not report:
            with get_session() as session:
                new_report = FeeReport(client_id=client_id, year=year)
                session.add(new_report)
                session.flush()

                # Crea righe per tutte le prestazioni attive del listino
                for i, svc in enumerate(sorted(pl.services, key=lambda s: s.sort_order)):
                    if svc.is_active:
                        line = FeeReportLine(
                            report_id=new_report.id,
                            sort_order=i,
                            service_code_snap=svc.service_code,
                            description_snap=svc.description,
                            category_snap=svc.category or "",
                            calc_type_snap=svc.calc_type,
                        )
                        session.add(line)
            st.success("Rendiconto creato. Ora inserisci i dati.")
            st.rerun()
        else:
            st.session_state["open_report_id"] = report.id
            st.rerun()

    # Editor rendiconto
    report_id = st.session_state.get("open_report_id")
    if report_id:
        report = get_fee_report(report_id)
        if report and report.client_id == client_id:
            _report_editor(report, pl)


def _report_editor(report: FeeReport, pl: PriceList):
    """Editor interattivo del rendiconto."""
    client = get_client(report.client_id)
    st.markdown(f"### Rendiconto {report.year} — {client.name}")

    # Note e KPI
    with st.expander("📝 Note e dati interni studio"):
        with st.form("report_meta"):
            col1, col2 = st.columns(2)
            with col1:
                notes = st.text_area("Note rendiconto", value=report.notes or "")
                billed_prev = st.number_input("Fatturato anno precedente (€)",
                                              value=float(report.billed_prev or 0), step=0.01)
                hourly_rate = st.number_input("Compenso orario teorico (€/h)",
                                              value=float(report.hourly_rate or 0), step=0.01)
            with col2:
                h1 = st.number_input("Ore T1", value=float(report.hours_q1 or 0), step=0.25)
                h2 = st.number_input("Ore T2", value=float(report.hours_q2 or 0), step=0.25)
                h3 = st.number_input("Ore T3", value=float(report.hours_q3 or 0), step=0.25)
                h4 = st.number_input("Ore T4", value=float(report.hours_q4 or 0), step=0.25)

            if st.form_submit_button("💾 Salva meta"):
                with get_session() as session:
                    r = session.query(FeeReport).filter_by(id=report.id).first()
                    r.notes = notes
                    r.billed_prev = billed_prev
                    r.hourly_rate = hourly_rate
                    r.hours_q1 = h1; r.hours_q2 = h2
                    r.hours_q3 = h3; r.hours_q4 = h4
                st.success("Salvato.")
                st.rerun()

    # Righe prestazioni
    st.markdown("**Inserimento dati per prestazione:**")
    st.caption("Inserisci il driver (es. numero registrazioni, volume d'affari) per ogni trimestre. Il compenso viene calcolato automaticamente. Puoi sovrascrivere manualmente.")

    # Recupera servizi dal listino per il calcolo
    pl_services = {svc.service_code: svc for svc in pl.services}

    changed = False
    lines_data = {}

    for line in report.lines:
        svc = pl_services.get(line.service_code_snap)
        calc_type = line.calc_type_snap
        driver_label = svc.driver_label if svc and svc.driver_label else "Quantità"
        driver_unit = svc.driver_unit if svc and svc.driver_unit else ""

        with st.expander(f"**{line.service_code_snap}** — {line.description_snap}  |  Totale: {fmt_currency(line.total)}"):
            with st.form(f"line_{line.id}"):
                if calc_type == "forfait":
                    st.info("Prestazione a forfait. Inserisci 1 se attiva nel trimestre, 0 altrimenti.")

                col1, col2, col3, col4 = st.columns(4)
                driver_vals = {}
                override_vals = {}

                for q_idx, (col, qname) in enumerate(zip([col1, col2, col3, col4], QUARTERS), 1):
                    with col:
                        st.markdown(f"**{qname}**")
                        driver_attr = f"driver_q{q_idx}"
                        current_driver = getattr(line, driver_attr) or 0.0

                        if calc_type != "forfait":
                            driver_val = st.number_input(
                                f"{driver_label} ({driver_unit})" if driver_unit else driver_label,
                                value=float(current_driver), step=1.0,
                                key=f"d_{line.id}_{q_idx}", min_value=0.0,
                            )
                        else:
                            driver_val = st.number_input(
                                "Attiva (1=sì, 0=no)", value=float(current_driver),
                                step=1.0, min_value=0.0, max_value=1.0,
                                key=f"d_{line.id}_{q_idx}",
                            )
                        driver_vals[q_idx] = driver_val

                        # Mostra compenso calcolato
                        if svc:
                            calc_val = calc_quarterly_fee(svc, driver_val)
                        else:
                            calc_val = 0.0
                        st.caption(f"Calcolato: {fmt_currency(calc_val)}")

                        # Override
                        override_attr = f"override_q{q_idx}"
                        current_override = getattr(line, override_attr)
                        override_str = st.text_input(
                            "Override manuale",
                            value=str(current_override) if current_override is not None else "",
                            key=f"ov_{line.id}_{q_idx}",
                            help="Lascia vuoto per usare il calcolato",
                        )
                        try:
                            override_vals[q_idx] = float(override_str) if override_str.strip() else None
                        except ValueError:
                            override_vals[q_idx] = None

                line_notes = st.text_input("Note riga", value=line.notes or "", key=f"ln_{line.id}")

                if st.form_submit_button("💾 Salva riga"):
                    with get_session() as session:
                        db_line = session.query(FeeReportLine).filter_by(id=line.id).first()
                        for q_idx in range(1, 5):
                            setattr(db_line, f"driver_q{q_idx}", driver_vals[q_idx])
                            setattr(db_line, f"override_q{q_idx}", override_vals[q_idx])
                        # Ricalcola
                        if svc:
                            recalc_line(db_line, svc)
                        db_line.notes = line_notes
                    st.success("Riga salvata.")
                    st.rerun()

    # Riepilogo e PDF
    st.markdown("---")
    report = get_fee_report(report.id)  # Ricarica
    df_summary = get_client_report_lines_df(report)

    if not df_summary.empty:
        # Formatta
        df_show = df_summary.copy()
        for col in ["T1", "T2", "T3", "T4", "Totale"]:
            df_show[col] = df_show[col].apply(fmt_currency)
        st.markdown("**Riepilogo rendiconto**")
        st.dataframe(df_show, use_container_width=True, hide_index=True)

        total_annual = df_summary["Totale"].sum()
        col_t, col_q = st.columns(2)
        col_t.metric("Totale annuale", fmt_currency(total_annual))

        st.markdown("---")
        st.markdown("**Genera PDF**")
        col_pdf1, col_pdf2, col_pdf3, col_pdf4, col_pdf5 = st.columns(5)
        pdf_quarters = {
            col_pdf1: (None, "📄 Annuale"),
            col_pdf2: (1, "T1"),
            col_pdf3: (2, "T2"),
            col_pdf4: (3, "T3"),
            col_pdf5: (4, "T4"),
        }
        client = get_client(report.client_id)
        for col, (q, label) in pdf_quarters.items():
            with col:
                if st.button(f"⬇️ {label}", use_container_width=True):
                    pdf_bytes = generate_fee_report_pdf(report, client, quarter=q)
                    fname = f"rendiconto_{client.client_code}_{report.year}"
                    fname += f"_T{q}.pdf" if q else "_annuale.pdf"
                    st.download_button(
                        f"📥 Scarica {label}", data=pdf_bytes,
                        file_name=fname, mime="application/pdf",
                        use_container_width=True,
                    )


# ---------------------------------------------------------------------------
# PAGINA: Storico rendiconti
# ---------------------------------------------------------------------------

def page_history():
    st.markdown('<div class="section-title">📁 Storico rendiconti</div>', unsafe_allow_html=True)

    clients = get_clients(include_archived=True)
    if not clients:
        st.info("Nessun cliente presente.")
        return

    client_options = {f"{c.client_code} — {c.name}": c.id for c in clients}
    selected = st.selectbox("Seleziona cliente", list(client_options.keys()))
    client_id = client_options[selected]
    client = get_client(client_id)

    reports = get_fee_reports(client_id)
    if not reports:
        st.info("Nessun rendiconto per questo cliente.")
        return

    history_df = get_client_history(client_id)
    if not history_df.empty:
        st.markdown("**Andamento storico**")
        st.line_chart(history_df.set_index("year")["total"], color="#2e6da4")

    st.markdown("---")
    st.markdown(f"**{len(reports)} rendiconti trovati**")

    for report in reports:
        lines_df = get_client_report_lines_df(report)
        total = lines_df["Totale"].sum() if not lines_df.empty else 0
        total_hours = (report.hours_q1 or 0) + (report.hours_q2 or 0) + \
                      (report.hours_q3 or 0) + (report.hours_q4 or 0)

        with st.expander(f"**Anno {report.year}** — Totale: {fmt_currency(total)}"):
            col1, col2, col3 = st.columns(3)
            col1.metric("Totale", fmt_currency(total))
            col2.metric("Ore totali", f"{total_hours:.1f} h")
            col3.metric("Resa oraria",
                        fmt_currency(total / total_hours) if total_hours > 0 else "—")

            if not lines_df.empty:
                df_show = lines_df.copy()
                for col in ["T1", "T2", "T3", "T4", "Totale"]:
                    df_show[col] = df_show[col].apply(fmt_currency)
                st.dataframe(df_show, use_container_width=True, hide_index=True)

            # PDF
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button(f"📄 PDF Annuale {report.year}", key=f"pdf_ann_{report.id}"):
                    pdf = generate_fee_report_pdf(report, client, quarter=None)
                    st.download_button(
                        "⬇️ Scarica", data=pdf,
                        file_name=f"rendiconto_{client.client_code}_{report.year}_annuale.pdf",
                        mime="application/pdf", key=f"dl_ann_{report.id}",
                    )
            with col_b:
                q_sel = st.selectbox("Trimestre", [1, 2, 3, 4],
                                     format_func=lambda x: f"T{x}", key=f"qsel_{report.id}")
                if st.button(f"📄 PDF T{q_sel}", key=f"pdf_q_{report.id}"):
                    pdf = generate_fee_report_pdf(report, client, quarter=q_sel)
                    st.download_button(
                        "⬇️ Scarica", data=pdf,
                        file_name=f"rendiconto_{client.client_code}_{report.year}_T{q_sel}.pdf",
                        mime="application/pdf", key=f"dl_q_{report.id}",
                    )


# ---------------------------------------------------------------------------
# PAGINA: Statistiche
# ---------------------------------------------------------------------------

def page_stats():
    st.markdown('<div class="section-title">📈 Statistiche e confronti</div>', unsafe_allow_html=True)

    current_year = datetime.date.today().year
    col1, col2 = st.columns(2)
    with col1:
        year_curr = st.selectbox("Anno corrente", range(current_year, current_year - 6, -1))
    with col2:
        year_prev = st.selectbox("Anno precedente (confronto)",
                                 range(current_year - 1, current_year - 7, -1))

    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Totali per cliente", "🔄 Confronto YoY",
        "🏆 Prestazioni", "📂 Categorie"
    ])

    with tab1:
        df = get_annual_summary(year_curr)
        if df.empty:
            st.info(f"Nessun dato per {year_curr}.")
        else:
            df_sorted = df.sort_values("total", ascending=False)
            st.bar_chart(df_sorted.set_index("name")["total"], color="#1a3a5c")
            df_show = df_sorted.copy()
            df_show["total"] = df_show["total"].apply(fmt_currency)
            df_show.columns = ["ID", "Codice", "Cliente", "Totale"]
            st.dataframe(df_show[["Codice", "Cliente", "Totale"]], use_container_width=True, hide_index=True)

    with tab2:
        df_yoy = get_yoy_comparison(year_curr, year_prev)
        if df_yoy.empty:
            st.info("Nessun dato disponibile per il confronto.")
        else:
            # Evidenzia aumenti/diminuzioni
            df_show = df_yoy.copy()
            df_show["total_prev"] = df_show["total_prev"].apply(fmt_currency)
            df_show["total_curr"] = df_show["total_curr"].apply(fmt_currency)
            df_show["delta_abs"] = df_show["delta_abs"].apply(fmt_currency)
            df_show["delta_pct"] = df_show["delta_pct"].apply(
                lambda x: f"+{x:.1f}%" if x and x > 0 else (f"{x:.1f}%" if x else "—")
            )
            df_show.columns = ["ID", "Cliente", f"Totale {year_curr}",
                               f"Totale {year_prev}", "Δ Assoluto", "Δ %"]
            st.dataframe(df_show[["Cliente", f"Totale {year_prev}",
                                  f"Totale {year_curr}", "Δ Assoluto", "Δ %"]],
                         use_container_width=True, hide_index=True)

            col_inc, col_dec = st.columns(2)
            with col_inc:
                st.markdown("**🟢 Maggiori aumenti**")
                top_inc = df_yoy.nlargest(5, "delta_abs")[["name", "delta_abs"]]
                top_inc["delta_abs"] = top_inc["delta_abs"].apply(fmt_currency)
                st.dataframe(top_inc, hide_index=True)
            with col_dec:
                st.markdown("**🔴 Maggiori diminuzioni**")
                top_dec = df_yoy.nsmallest(5, "delta_abs")[["name", "delta_abs"]]
                top_dec["delta_abs"] = top_dec["delta_abs"].apply(fmt_currency)
                st.dataframe(top_dec, hide_index=True)

    with tab3:
        df_svc = get_service_frequency(year_curr)
        if df_svc.empty:
            st.info(f"Nessun dato per {year_curr}.")
        else:
            st.bar_chart(df_svc.set_index("description")["count"], color="#2e6da4")
            df_show = df_svc.copy()
            df_show["total"] = df_show["total"].apply(fmt_currency)
            df_show.columns = ["Codice", "Descrizione", "Categoria", "Freq.", "Totale"]
            st.dataframe(df_show, use_container_width=True, hide_index=True)

    with tab4:
        df_cat = get_category_totals(year_curr)
        if df_cat.empty:
            st.info(f"Nessun dato per {year_curr}.")
        else:
            st.bar_chart(df_cat.set_index("category")["total"], color="#1a3a5c")
            df_show = df_cat.copy()
            df_show["total"] = df_show["total"].apply(fmt_currency)
            st.dataframe(df_show, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# PAGINA: Impostazioni
# ---------------------------------------------------------------------------

def page_settings():
    st.markdown('<div class="section-title">⚙️ Impostazioni</div>', unsafe_allow_html=True)

    tab_studio, tab_users = st.tabs(["🏢 Dati studio", "👤 Utenti"])

    with tab_studio:
        settings = get_all_settings()
        with st.form("settings_form"):
            st.markdown("**Intestazione PDF e dati studio**")
            col1, col2 = st.columns(2)
            with col1:
                studio_name = st.text_input("Nome studio", value=settings.get("studio_name", ""))
                studio_address = st.text_input("Indirizzo", value=settings.get("studio_address", ""))
                studio_city = st.text_input("Città / CAP", value=settings.get("studio_city", ""))
            with col2:
                studio_phone = st.text_input("Telefono", value=settings.get("studio_phone", ""))
                studio_email = st.text_input("Email", value=settings.get("studio_email", ""))
                studio_piva = st.text_input("Partita IVA", value=settings.get("studio_piva", ""))
                studio_cf = st.text_input("Codice fiscale", value=settings.get("studio_cf", ""))
            pdf_footer = st.text_area("Testo footer PDF", value=settings.get("pdf_footer", ""), height=60)

            if st.form_submit_button("💾 Salva impostazioni", use_container_width=True):
                for key, val in [
                    ("studio_name", studio_name),
                    ("studio_address", studio_address),
                    ("studio_city", studio_city),
                    ("studio_phone", studio_phone),
                    ("studio_email", studio_email),
                    ("studio_piva", studio_piva),
                    ("studio_cf", studio_cf),
                    ("pdf_footer", pdf_footer),
                ]:
                    set_setting(key, val)
                st.success("Impostazioni salvate.")

    with tab_users:
        if not is_admin():
            st.warning("Solo gli amministratori possono gestire gli utenti.")
            return

        users = get_users()
        df_users = pd.DataFrame([{
            "Username": u.username,
            "Nome": u.full_name or "",
            "Ruolo": u.role,
            "Attivo": "✅" if u.is_active else "❌",
        } for u in users])
        st.dataframe(df_users, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("**Nuovo utente / Modifica password**")
        with st.form("user_form"):
            col1, col2 = st.columns(2)
            with col1:
                u_username = st.text_input("Username *")
                u_fullname = st.text_input("Nome completo")
            with col2:
                u_password = st.text_input("Password *", type="password")
                u_role = st.selectbox("Ruolo", ["user", "admin"])

            if st.form_submit_button("💾 Salva utente"):
                if not u_username or not u_password:
                    st.error("Username e password sono obbligatori.")
                else:
                    try:
                        save_user({
                            "username": u_username,
                            "password": u_password,
                            "full_name": u_fullname,
                            "role": u_role,
                        })
                        st.success(f"Utente '{u_username}' salvato.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Errore: {e}")


# ---------------------------------------------------------------------------
# Main router
# ---------------------------------------------------------------------------

def main():
    if not is_logged_in():
        login_page()
        return

    page = sidebar()

    if page == "dashboard":
        page_dashboard()
    elif page == "clients":
        page_clients()
    elif page == "import":
        page_import()
    elif page == "pricelist":
        page_pricelist()
    elif page == "new_report":
        page_new_report()
    elif page == "history":
        page_history()
    elif page == "stats":
        page_stats()
    elif page == "settings":
        page_settings()


if __name__ == "__main__":
    main()
