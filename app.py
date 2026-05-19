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
from excel_parser import parse_clients_file, VALID_TYPES
from pdf_generator import generate_fee_report_pdf
from statistics import (
    get_annual_summary, get_category_totals, get_client_history,
    get_client_report_lines_df, get_dashboard_kpis, get_quarterly_trend,
    get_service_frequency, get_yoy_comparison,
)
from utils import (
    CALC_TYPES, CLIENT_STATUSES, CLIENT_TYPES, QUARTERS,
    calc_quarterly_fee, clone_price_list_for_year, fmt_currency,
    recalc_line, validate_client,
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

st.markdown("""
<style>
    [data-testid="stSidebar"] {
        background-color: #f8f9fa;
        border-right: 1px solid #e0e0e0;
    }
    [data-testid="stSidebar"] * { color: #212121 !important; }
    [data-testid="stSidebar"] hr { border-color: #e0e0e0; }
    .section-title {
        font-size: 1.3rem; font-weight: 600; color: #212121;
        border-bottom: 2px solid #1976d2; padding-bottom: 6px; margin-bottom: 16px;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Auth
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
            username  = st.text_input("Username")
            password  = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Accedi", use_container_width=True)
            if submitted:
                user = authenticate(username, password)
                if user:
                    st.session_state["user"] = user
                    st.rerun()
                else:
                    st.error("Credenziali non valide.")


# ---------------------------------------------------------------------------
# Sidebar
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
        st.markdown(f"### {settings.get('studio_name', 'Studio Parcelle')}")
        user = st.session_state.get("user")
        if user:
            st.caption(f"👤 {user.full_name or user.username}  •  {user.role}")
        st.markdown("---")
        selection = st.radio("Menu", list(MENU_ITEMS.keys()), label_visibility="collapsed")
        st.markdown("---")
        if st.button("Esci", use_container_width=True):
            st.session_state.clear()
            st.rerun()
    return MENU_ITEMS[selection]


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def page_dashboard():
    st.markdown('<div class="section-title">📊 Dashboard</div>', unsafe_allow_html=True)
    current_year = datetime.date.today().year
    year = st.selectbox("Anno", range(current_year, current_year - 6, -1), key="dash_year")

    kpis    = get_dashboard_kpis(year)
    q_trend = get_quarterly_trend(year)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Fatturato totale",    fmt_currency(kpis["total_revenue"]))
    col2.metric("Clienti rendicontati", kpis["client_count"])
    col3.metric("Media per cliente",   fmt_currency(kpis["avg_per_client"]))
    col4.metric("Cliente principale",  kpis.get("top_client") or "—")

    st.markdown("---")
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("**Andamento trimestrale**")
        trend_df = pd.DataFrame({"Trimestre": list(q_trend.keys()),
                                  "Importo":   list(q_trend.values())})
        st.bar_chart(trend_df.set_index("Trimestre"), color="#2e6da4")

    with col_b:
        st.markdown("**Totali per categoria**")
        cat_df = get_category_totals(year)
        if not cat_df.empty:
            st.bar_chart(cat_df.set_index("category")["total"], color="#1a3a5c")
        else:
            st.info("Nessun dato.")

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
# Clienti
# ---------------------------------------------------------------------------

def page_clients():
    st.markdown('<div class="section-title">👥 Gestione clienti</div>', unsafe_allow_html=True)
    tab_list, tab_new, tab_edit = st.tabs(["📋 Elenco", "➕ Nuovo cliente", "✏️ Modifica"])

    with tab_list:
        show_archived = st.checkbox("Mostra archiviati")
        clients = get_clients(include_archived=show_archived)
        if clients:
            df = pd.DataFrame([{
                "Codice":      c.client_code,
                "Denominazione": c.name,
                "Tipo":        c.client_type,
                "P.IVA":       c.vat_number or "",
                "C.F.":        c.tax_code or "",
                "Stato":       c.status,
            } for c in clients])
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption(f"{len(clients)} clienti")
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
            code  = st.text_input("Codice cliente *", value=existing.client_code if existing else "")
            name  = st.text_input("Denominazione *",  value=existing.name if existing else "")
            cf    = st.text_input("Codice fiscale",   value=existing.tax_code or "" if existing else "")
            piva  = st.text_input("Partita IVA",      value=existing.vat_number or "" if existing else "")
        with col2:
            ctype = st.selectbox(
                "Tipologia *", CLIENT_TYPES,
                index=CLIENT_TYPES.index(existing.client_type)
                      if existing and existing.client_type in CLIENT_TYPES else 0,
            )
            status = st.selectbox(
                "Stato", CLIENT_STATUSES,
                index=CLIENT_STATUSES.index(existing.status)
                      if existing and existing.status in CLIENT_STATUSES else 0,
            )
            notes = st.text_area("Note", value=existing.notes or "" if existing else "", height=100)

        submitted = st.form_submit_button(
            "💾 Aggiorna" if existing else "💾 Salva cliente",
            use_container_width=True,
        )
        if submitted:
            data = {
                "client_code": code.strip(),
                "name":        name.strip(),
                "tax_code":    cf.strip().upper(),
                "vat_number":  piva.strip(),
                "client_type": ctype,
                "status":      status,
                "notes":       notes.strip(),
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
                    st.success("Cliente salvato.")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Errore: {ex}")


# ---------------------------------------------------------------------------
# Import anagrafiche
# ---------------------------------------------------------------------------

def page_import():
    st.markdown('<div class="section-title">📥 Import anagrafiche</div>', unsafe_allow_html=True)

    st.markdown("""
    Carica un file **CSV o XLSX** con le seguenti colonne (i nomi devono essere esatti):

    | Colonna | Obbligatoria | Note |
    |---------|:---:|------|
    | `denominazione` | ✅ | Nome o ragione sociale |
    | `codice` | ✅ | Codice cliente (es. 000001) |
    | `C.F.` | — | Codice fiscale (11 o 16 caratteri) |
    | `P.IVA` | — | Partita IVA (11 cifre) |
    | `tipologia` | — | Vedi valori accettati sotto |
    | `note` | — | Note libere |

    **Valori accettati per tipologia:**
    """)
    st.code("\n".join(VALID_TYPES))

    st.markdown("---")
    uploaded = st.file_uploader("Scegli file", type=["csv", "xlsx", "xls"])
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
                st.success(f"Trovati **{len(clients)}** clienti nel file.")
                # Anteprima con colonne in italiano
                df_preview = pd.DataFrame([{
                    "Codice":      c["client_code"],
                    "Denominazione": c["name"],
                    "C.F.":        c["tax_code"],
                    "P.IVA":       c["vat_number"],
                    "Tipologia":   c["client_type"],
                    "Stato":       c["status"],
                } for c in clients])
                st.dataframe(df_preview, use_container_width=True, hide_index=True)

                if st.button("📥 Importa tutti", type="primary"):
                    imported, skipped = 0, 0
                    for c in clients:
                        try:
                            save_client(c)
                            imported += 1
                        except Exception:
                            skipped += 1
                    st.success(f"✅ Importati: {imported}   |   ⏭️ Saltati (già presenti): {skipped}")
            elif not warnings:
                st.warning("Nessun cliente trovato nel file.")
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Listino prestazioni
# ---------------------------------------------------------------------------

def page_pricelist():
    st.markdown('<div class="section-title">📋 Listino prestazioni</div>', unsafe_allow_html=True)

    price_lists = get_price_lists()
    tab_view, tab_new_list, tab_clone = st.tabs(
        ["📋 Visualizza / Modifica", "➕ Nuovo listino", "📋 Clona listino"])

    # ---- TAB: Visualizza / Modifica ----
    with tab_view:
        if not price_lists:
            st.info("Nessun listino. Crea il primo dalla scheda 'Nuovo listino'.")
        else:
            pl_options = {f"{pl.year} — {pl.name}": pl.id for pl in price_lists}
            selected_pl = st.selectbox("Seleziona listino", list(pl_options.keys()))
            pl = get_price_list(pl_options[selected_pl])

            if pl:
                col1, col2, col3 = st.columns(3)
                col1.metric("Anno", pl.year)
                col2.metric("Prestazioni", len(pl.services))
                col3.metric("Stato", "✅ Attivo" if pl.is_active else "⛔ Non attivo")

                st.markdown("---")
                services = pl.services
                if services:
                    for svc in services:
                        label = f"**{svc.service_code}** — {svc.description}"
                        if svc.calc_type == "scaglioni":
                            label += "  🔢 *Scaglioni*"
                        else:
                            label += f"  📐 *Unitario (€ {svc.unit_price or 0:.2f})*"
                        with st.expander(label):
                            _service_form(svc, pl.id, readonly=not is_admin())
                else:
                    st.info("Nessuna prestazione. Aggiungila qui sotto.")

                if is_admin():
                    st.markdown("---")
                    st.markdown("**➕ Aggiungi nuova prestazione**")
                    _service_form(None, pl.id)

    # ---- TAB: Nuovo listino ----
    with tab_new_list:
        if not is_admin():
            st.warning("Solo gli amministratori possono creare listini.")
        else:
            with st.form("new_pricelist_form"):
                col1, col2 = st.columns(2)
                with col1:
                    new_year  = st.number_input("Anno *", min_value=2000, max_value=2099,
                                                value=datetime.date.today().year)
                    new_name  = st.text_input("Nome listino *",
                                              value=f"Listino {datetime.date.today().year}")
                with col2:
                    new_notes  = st.text_area("Note", height=80)
                    new_active = st.checkbox("Attivo", value=True)

                submitted = st.form_submit_button("💾 Crea listino", use_container_width=True)

            if submitted:
                if not new_name.strip():
                    st.error("Il nome del listino è obbligatorio.")
                else:
                    try:
                        with get_session() as session:
                            if session.query(PriceList).filter_by(year=int(new_year)).first():
                                st.error(f"Esiste già un listino per l'anno {new_year}.")
                            else:
                                session.add(PriceList(
                                    year=int(new_year), name=new_name.strip(),
                                    notes=new_notes, is_active=new_active,
                                ))
                        st.success(f"✅ Listino {new_year} creato.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Errore: {e}")

    # ---- TAB: Clona listino ----
    with tab_clone:
        if not is_admin():
            st.warning("Solo gli amministratori possono clonare listini.")
        elif not price_lists:
            st.info("Nessun listino da clonare.")
        else:
            st.markdown("Copia un listino esistente in un nuovo anno, con eventuale aumento percentuale su tutti i prezzi.")
            col1, col2, col3 = st.columns(3)
            with col1:
                source_year = st.selectbox("Anno sorgente", [pl.year for pl in price_lists])
            with col2:
                target_year = st.number_input("Anno destinazione", min_value=2000, max_value=2099,
                                              value=max(pl.year for pl in price_lists) + 1)
            with col3:
                pct = st.number_input("Aumento % (0 = nessuno)", value=0.0, step=0.1,
                                      help="Es. 5 per aumentare tutti i prezzi del 5%")

            if st.button("📋 Clona listino", type="primary"):
                try:
                    clone_price_list_for_year(int(source_year), int(target_year), float(pct))
                    st.success(f"✅ Listino {target_year} creato da {source_year}" +
                               (f" con aumento {pct}%." if pct else "."))
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore: {e}")


def _service_form(svc: Optional[ServiceItem], price_list_id: int, readonly: bool = False):
    """Form per creare/modificare una voce di listino."""
    form_key = f"svc_form_{svc.id if svc else 'new'}_{price_list_id}"

    with st.form(form_key):
        col1, col2, col3 = st.columns(3)
        with col1:
            code     = st.text_input("Codice *", value=svc.service_code if svc else "",
                                     disabled=readonly)
            category = st.text_input("Categoria", value=svc.category or "" if svc else "",
                                     disabled=readonly)
        with col2:
            desc = st.text_input("Descrizione *", value=svc.description if svc else "",
                                 disabled=readonly)
            calc_type = st.selectbox(
                "Tipo calcolo *",
                list(CALC_TYPES.keys()),
                index=list(CALC_TYPES.keys()).index(svc.calc_type)
                      if svc and svc.calc_type in CALC_TYPES else 0,
                format_func=lambda x: CALC_TYPES[x],
                disabled=readonly,
                help="Scaglioni = driver trimestrale × 4 → scaglione annuo → compenso/4 + conguaglio T4\nUnitario = quantità × tariffa",
            )
        with col3:
            sort_order = st.number_input("Ordinamento", value=svc.sort_order if svc else 0,
                                         step=1, disabled=readonly)
            active = st.checkbox("Attiva", value=svc.is_active if svc else True,
                                 disabled=readonly)

        # Campi specifici per tipo calcolo
        if calc_type == "unitario":
            col_a, col_b = st.columns(2)
            with col_a:
                unit_price = st.number_input(
                    "Tariffa unitaria (€) *",
                    value=float(svc.unit_price or 0) if svc else 0.0,
                    step=0.01, disabled=readonly,
                    help="Compenso per singola unità (es. per F24: prezzo per invio)")
            with col_b:
                driver_unit = st.text_input(
                    "Unità di misura", value=svc.driver_unit or "" if svc else "",
                    disabled=readonly, help="Es. 'invii', 'pratiche', 'situazioni'")
            driver_label   = st.text_input(
                "Etichetta quantità", value=svc.driver_label or "" if svc else "",
                disabled=readonly, help="Es. 'Numero invii F24'")
            marginal_rate  = None

        else:  # scaglioni
            col_a, col_b = st.columns(2)
            with col_a:
                driver_label = st.text_input(
                    "Etichetta driver", value=svc.driver_label or "" if svc else "",
                    disabled=readonly,
                    help="Es. 'Numero registrazioni', 'Volume d\\'affari (€)'")
            with col_b:
                driver_unit = st.text_input(
                    "Unità driver", value=svc.driver_unit or "" if svc else "",
                    disabled=readonly, help="Es. 'registrazioni', '€'")
            marginal_rate = st.number_input(
                "Tariffa marginale oltre ultimo scaglione (€ per unità)",
                value=float(svc.marginal_rate or 0) if svc else 0.0,
                step=0.01, disabled=readonly,
                help="Applicata sull'eccedenza oltre l'ultimo scaglione. Lascia 0 se non prevista.")
            unit_price = None

            # Scaglioni esistenti
            if svc and svc.brackets:
                st.markdown("**Scaglioni (compensi annui):**")
                bracket_rows = []
                for b in sorted(svc.brackets, key=lambda x: x.threshold_from):
                    bracket_rows.append({
                        "Da":               b.threshold_from,
                        "A (vuoto=∞)":      b.threshold_to if b.threshold_to else "∞",
                        "Compenso annuo €": b.annual_fee,
                    })
                st.dataframe(pd.DataFrame(bracket_rows), hide_index=True, use_container_width=True)

        if not readonly:
            submitted = st.form_submit_button(
                "💾 Aggiorna prestazione" if svc else "💾 Aggiungi prestazione",
                use_container_width=True,
            )
            if submitted:
                if not code.strip() or not desc.strip():
                    st.error("Codice e descrizione sono obbligatori.")
                else:
                    with get_session() as session:
                        if svc:
                            item = session.query(ServiceItem).filter_by(id=svc.id).first()
                        else:
                            item = ServiceItem(price_list_id=price_list_id)
                            session.add(item)

                        item.service_code  = code.strip()
                        item.description   = desc.strip()
                        item.category      = category.strip()
                        item.calc_type     = calc_type
                        item.driver_label  = driver_label.strip() if calc_type == "scaglioni" else (driver_label.strip() if 'driver_label' in dir() else "")
                        item.driver_unit   = driver_unit.strip()
                        item.unit_price    = unit_price
                        item.marginal_rate = marginal_rate if marginal_rate else None
                        item.is_active     = active
                        item.sort_order    = int(sort_order)
                    st.success("✅ Prestazione salvata.")
                    st.rerun()
        else:
            st.form_submit_button("(sola lettura)", disabled=True)

    # Gestione scaglioni separata (fuori dal form principale)
    if svc and svc.calc_type == "scaglioni" and not readonly and is_admin():
        with st.expander("➕ Aggiungi / modifica scaglioni"):
            _bracket_editor(svc.id)


def _bracket_editor(service_id: int):
    with st.form(f"bracket_add_{service_id}"):
        st.markdown("**Nuovo scaglione** (valori annui del driver):")
        c1, c2, c3 = st.columns(3)
        with c1:
            t_from = st.number_input("Da (incluso)", value=0.0, step=1.0)
        with c2:
            t_to_str = st.text_input("A (lascia vuoto per illimitato)")
        with c3:
            ann_fee = st.number_input("Compenso annuo (€)", value=0.0, step=1.0)

        if st.form_submit_button("➕ Aggiungi scaglione"):
            t_to = float(t_to_str.strip()) if t_to_str.strip() else None
            with get_session() as session:
                session.add(ServiceBracket(
                    service_item_id=service_id,
                    threshold_from=t_from,
                    threshold_to=t_to,
                    annual_fee=ann_fee,
                ))
            st.success("Scaglione aggiunto.")
            st.rerun()


# ---------------------------------------------------------------------------
# Nuovo rendiconto
# ---------------------------------------------------------------------------

def page_new_report():
    st.markdown('<div class="section-title">📝 Gestione rendiconto</div>', unsafe_allow_html=True)

    clients = get_clients()
    if not clients:
        st.warning("Nessun cliente. Crea prima un cliente.")
        return

    price_lists   = get_price_lists()
    active_lists  = [pl for pl in price_lists if pl.is_active]
    if not active_lists:
        st.warning("Nessun listino attivo. Crea prima un listino.")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        client_options = {f"{c.client_code} — {c.name}": c.id for c in clients}
        sel_client_key = st.selectbox("Cliente *", list(client_options.keys()))
        client_id = client_options[sel_client_key]
    with col2:
        current_year = datetime.date.today().year
        year = st.selectbox("Anno *", range(current_year + 1, current_year - 6, -1))
    with col3:
        pl_options = {f"{pl.year} — {pl.name}": pl.id for pl in active_lists}
        sel_pl_key = st.selectbox("Listino *", list(pl_options.keys()))
        pl_id = pl_options[sel_pl_key]

    client          = get_client(client_id)
    pl              = get_price_list(pl_id)
    existing_report = get_fee_report_by_client_year(client_id, year)

    if existing_report:
        st.info(f"Rendiconto {year} per **{client.name}** già presente. Puoi modificarlo.")

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("📂 Apri rendiconto", type="primary", use_container_width=True):
            if not existing_report:
                with get_session() as session:
                    new_r = FeeReport(client_id=client_id, year=year)
                    session.add(new_r)
                    session.flush()
                    for i, svc in enumerate(pl.services):
                        if svc.is_active:
                            session.add(FeeReportLine(
                                report_id=new_r.id,
                                sort_order=i,
                                service_code_snap=svc.service_code,
                                description_snap=svc.description,
                                category_snap=svc.category or "",
                                calc_type_snap=svc.calc_type,
                            ))
                    report_id = new_r.id
                st.session_state["open_report_id"] = report_id
                st.success("Rendiconto creato.")
                st.rerun()
            else:
                st.session_state["open_report_id"] = existing_report.id
                st.rerun()

    # Editor rendiconto
    report_id = st.session_state.get("open_report_id")
    if report_id:
        report = get_fee_report(report_id)
        if report and report.client_id == client_id:
            _report_editor(report, pl)


def _report_editor(report: FeeReport, pl: PriceList):
    client = get_client(report.client_id)
    st.markdown(f"### {client.name} — Rendiconto {report.year}")

    # Meta
    with st.expander("📝 Note e dati interni"):
        with st.form("report_meta"):
            col1, col2 = st.columns(2)
            with col1:
                notes       = st.text_area("Note rendiconto", value=report.notes or "")
                billed_prev = st.number_input("Fatturato anno precedente (€)",
                                              value=float(report.billed_prev or 0), step=0.01)
                hourly_rate = st.number_input("Compenso orario teorico (€/h)",
                                              value=float(report.hourly_rate or 0), step=0.01)
            with col2:
                h1 = st.number_input("Ore T1", value=float(report.hours_q1 or 0), step=0.25)
                h2 = st.number_input("Ore T2", value=float(report.hours_q2 or 0), step=0.25)
                h3 = st.number_input("Ore T3", value=float(report.hours_q3 or 0), step=0.25)
                h4 = st.number_input("Ore T4", value=float(report.hours_q4 or 0), step=0.25)
            if st.form_submit_button("💾 Salva"):
                with get_session() as session:
                    r = session.query(FeeReport).filter_by(id=report.id).first()
                    r.notes = notes; r.billed_prev = billed_prev; r.hourly_rate = hourly_rate
                    r.hours_q1 = h1; r.hours_q2 = h2; r.hours_q3 = h3; r.hours_q4 = h4
                st.success("Salvato."); st.rerun()

    # Righe
    st.markdown("---")
    st.markdown("**Inserimento dati per prestazione**")
    st.caption("Per le prestazioni **a scaglioni**: inserisci il driver per T1, T2, T3. Il T4 viene calcolato come conguaglio annuale (totale annuo effettivo meno la somma T1+T2+T3).")
    st.caption("Per le prestazioni **a quantità**: inserisci il numero di unità per ogni trimestre.")

    pl_services = {svc.service_code: svc for svc in pl.services}

    for line in report.lines:
        svc          = pl_services.get(line.service_code_snap)
        calc_type    = line.calc_type_snap
        driver_label = (svc.driver_label if svc and svc.driver_label else "Quantità")
        driver_unit  = (svc.driver_unit  if svc and svc.driver_unit  else "")

        # Etichetta expander con totale attuale
        badge = "🔢" if calc_type == "scaglioni" else "📐"
        total_label = fmt_currency(line.total) if line.total else "non compilato"
        with st.expander(f"{badge} **{line.service_code_snap}** — {line.description_snap}  |  {total_label}"):

            with st.form(f"line_{line.id}"):
                col1, col2, col3, col4 = st.columns(4)
                driver_vals   = {}
                override_vals = {}

                for q_idx, col in enumerate([col1, col2, col3, col4], 1):
                    with col:
                        is_conguaglio = (calc_type == "scaglioni" and q_idx == 4)
                        st.markdown(f"**T{q_idx}**" + (" *(conguaglio)*" if is_conguaglio else ""))

                        current_driver = getattr(line, f"driver_q{q_idx}") or 0.0

                        if is_conguaglio:
                            # T4 scaglioni: mostra solo il conguaglio calcolato, non il driver
                            st.caption("Calcolato automaticamente")
                            driver_vals[q_idx] = current_driver
                            calc_val = getattr(line, f"fee_q{q_idx}") or 0.0
                        else:
                            input_label = f"{driver_label}"
                            if driver_unit:
                                input_label += f" ({driver_unit})"
                            driver_val = st.number_input(
                                input_label, value=float(current_driver),
                                step=1.0, key=f"d_{line.id}_{q_idx}", min_value=0.0,
                            )
                            driver_vals[q_idx] = driver_val
                            calc_val = calc_quarterly_fee(svc, driver_val) if svc else 0.0

                        st.caption(f"Calcolato: {fmt_currency(calc_val)}")

                        # Override
                        current_override = getattr(line, f"override_q{q_idx}")
                        override_str = st.text_input(
                            "Override (opzionale)",
                            value=str(current_override) if current_override is not None else "",
                            key=f"ov_{line.id}_{q_idx}",
                            help="Inserisci un valore manuale per sovrascrivere il calcolato",
                            disabled=is_conguaglio,
                        )
                        try:
                            override_vals[q_idx] = float(override_str) if override_str.strip() else None
                        except ValueError:
                            override_vals[q_idx] = None

                line_notes = st.text_input("Note", value=line.notes or "", key=f"ln_{line.id}")

                if st.form_submit_button("💾 Salva riga", use_container_width=True):
                    with get_session() as session:
                        db_line = session.query(FeeReportLine).filter_by(id=line.id).first()
                        for q_idx in range(1, 5):
                            setattr(db_line, f"driver_q{q_idx}", driver_vals[q_idx])
                            setattr(db_line, f"override_q{q_idx}", override_vals[q_idx])
                        if svc:
                            recalc_line(db_line, svc)
                        db_line.notes = line_notes
                    st.success("✅ Riga salvata.")
                    st.rerun()

    # Riepilogo e PDF
    st.markdown("---")
    report = get_fee_report(report.id)
    df_summary = get_client_report_lines_df(report)

    if not df_summary.empty:
        df_show = df_summary.copy()
        for col in ["T1", "T2", "T3", "T4", "Totale"]:
            df_show[col] = df_show[col].apply(fmt_currency)
        st.markdown("**Riepilogo**")
        st.dataframe(df_show, use_container_width=True, hide_index=True)
        total_annual = df_summary["Totale"].sum()
        st.metric("Totale annuale", fmt_currency(total_annual))

        st.markdown("---")
        st.markdown("**Genera PDF**")
        col_a, col_b, col_c, col_d, col_e = st.columns(5)
        for col, (q, label) in zip(
            [col_a, col_b, col_c, col_d, col_e],
            [(None, "Annuale"), (1, "T1"), (2, "T2"), (3, "T3"), (4, "T4")]
        ):
            with col:
                if st.button(f"📄 {label}", key=f"genpdf_{report.id}_{q}", use_container_width=True):
                    pdf_bytes = generate_fee_report_pdf(report, client, quarter=q)
                    fname = f"rendiconto_{client.client_code}_{report.year}"
                    fname += f"_T{q}.pdf" if q else "_annuale.pdf"
                    st.download_button(
                        f"⬇️ Scarica {label}", data=pdf_bytes,
                        file_name=fname, mime="application/pdf",
                        key=f"dlpdf_{report.id}_{q}", use_container_width=True,
                    )


# ---------------------------------------------------------------------------
# Storico rendiconti
# ---------------------------------------------------------------------------

def page_history():
    st.markdown('<div class="section-title">📁 Storico rendiconti</div>', unsafe_allow_html=True)

    clients = get_clients(include_archived=True)
    if not clients:
        st.info("Nessun cliente.")
        return

    options = {f"{c.client_code} — {c.name}": c.id for c in clients}
    selected = st.selectbox("Cliente", list(options.keys()))
    client_id = options[selected]
    client    = get_client(client_id)

    reports = get_fee_reports(client_id)
    if not reports:
        st.info("Nessun rendiconto per questo cliente.")
        return

    history_df = get_client_history(client_id)
    if not history_df.empty and len(history_df) > 1:
        st.markdown("**Andamento storico**")
        st.line_chart(history_df.set_index("year")["total"], color="#2e6da4")

    st.markdown("---")
    for report in reports:
        lines_df    = get_client_report_lines_df(report)
        total       = lines_df["Totale"].sum() if not lines_df.empty else 0
        total_hours = sum([report.hours_q1 or 0, report.hours_q2 or 0,
                           report.hours_q3 or 0, report.hours_q4 or 0])

        with st.expander(f"**Anno {report.year}** — {fmt_currency(total)}"):
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

            col_a, col_b, col_c = st.columns(3)
            with col_a:
                if st.button(f"📄 PDF Annuale", key=f"h_ann_{report.id}"):
                    pdf = generate_fee_report_pdf(report, client, quarter=None)
                    st.download_button("⬇️ Scarica", data=pdf,
                        file_name=f"rendiconto_{client.client_code}_{report.year}_annuale.pdf",
                        mime="application/pdf", key=f"h_dl_ann_{report.id}")
            with col_b:
                q_sel = st.selectbox("Trimestre", [1,2,3,4],
                                     format_func=lambda x: f"T{x}",
                                     key=f"h_qsel_{report.id}")
            with col_c:
                if st.button(f"📄 PDF T{q_sel}", key=f"h_q_{report.id}"):
                    pdf = generate_fee_report_pdf(report, client, quarter=q_sel)
                    st.download_button("⬇️ Scarica", data=pdf,
                        file_name=f"rendiconto_{client.client_code}_{report.year}_T{q_sel}.pdf",
                        mime="application/pdf", key=f"h_dl_q_{report.id}")


# ---------------------------------------------------------------------------
# Statistiche
# ---------------------------------------------------------------------------

def page_stats():
    st.markdown('<div class="section-title">📈 Statistiche e confronti</div>', unsafe_allow_html=True)

    current_year = datetime.date.today().year
    col1, col2 = st.columns(2)
    with col1:
        year_curr = st.selectbox("Anno corrente", range(current_year, current_year - 6, -1))
    with col2:
        year_prev = st.selectbox("Anno confronto", range(current_year - 1, current_year - 7, -1))

    tab1, tab2, tab3, tab4 = st.tabs(
        ["📊 Per cliente", "🔄 Confronto YoY", "🏆 Prestazioni", "📂 Categorie"])

    with tab1:
        df = get_annual_summary(year_curr)
        if df.empty:
            st.info(f"Nessun dato per {year_curr}.")
        else:
            df_s = df.sort_values("total", ascending=False)
            st.bar_chart(df_s.set_index("name")["total"], color="#1a3a5c")
            df_s = df_s.copy()
            df_s["total"] = df_s["total"].apply(fmt_currency)
            st.dataframe(df_s[["client_code", "name", "total"]].rename(
                columns={"client_code": "Codice", "name": "Cliente", "total": "Totale"}),
                use_container_width=True, hide_index=True)

    with tab2:
        df_yoy = get_yoy_comparison(year_curr, year_prev)
        if df_yoy.empty:
            st.info("Nessun dato.")
        else:
            df_show = df_yoy.copy()
            df_show["total_prev"] = df_show["total_prev"].apply(fmt_currency)
            df_show["total_curr"] = df_show["total_curr"].apply(fmt_currency)
            df_show["delta_abs"]  = df_show["delta_abs"].apply(fmt_currency)
            df_show["delta_pct"]  = df_show["delta_pct"].apply(
                lambda x: f"+{x:.1f}%" if x and x > 0 else (f"{x:.1f}%" if x else "—"))
            st.dataframe(df_show[["name", "total_prev", "total_curr", "delta_abs", "delta_pct"]].rename(
                columns={"name": "Cliente", "total_prev": f"{year_prev}",
                         "total_curr": f"{year_curr}", "delta_abs": "Δ €", "delta_pct": "Δ %"}),
                use_container_width=True, hide_index=True)

    with tab3:
        df_svc = get_service_frequency(year_curr)
        if df_svc.empty:
            st.info(f"Nessun dato per {year_curr}.")
        else:
            st.bar_chart(df_svc.set_index("description")["count"], color="#2e6da4")
            df_svc["total"] = df_svc["total"].apply(fmt_currency)
            st.dataframe(df_svc.rename(columns={
                "service_code": "Codice", "description": "Prestazione",
                "category": "Categoria", "count": "Freq.", "total": "Totale"}),
                use_container_width=True, hide_index=True)

    with tab4:
        df_cat = get_category_totals(year_curr)
        if df_cat.empty:
            st.info(f"Nessun dato per {year_curr}.")
        else:
            st.bar_chart(df_cat.set_index("category")["total"], color="#1a3a5c")
            df_cat["total"] = df_cat["total"].apply(fmt_currency)
            st.dataframe(df_cat.rename(columns={"category": "Categoria", "total": "Totale"}),
                         use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Impostazioni
# ---------------------------------------------------------------------------

def page_settings():
    st.markdown('<div class="section-title">⚙️ Impostazioni</div>', unsafe_allow_html=True)

    tab_studio, tab_users = st.tabs(["🏢 Dati studio", "👤 Utenti"])

    with tab_studio:
        settings = get_all_settings()
        with st.form("settings_form"):
            col1, col2 = st.columns(2)
            with col1:
                studio_name    = st.text_input("Nome studio",   value=settings.get("studio_name", ""))
                studio_address = st.text_input("Indirizzo",     value=settings.get("studio_address", ""))
                studio_city    = st.text_input("Città / CAP",   value=settings.get("studio_city", ""))
            with col2:
                studio_phone = st.text_input("Telefono", value=settings.get("studio_phone", ""))
                studio_email = st.text_input("Email",    value=settings.get("studio_email", ""))
                studio_piva  = st.text_input("P.IVA",    value=settings.get("studio_piva", ""))
                studio_cf    = st.text_input("C.F.",     value=settings.get("studio_cf", ""))
            pdf_footer = st.text_area("Testo footer PDF", value=settings.get("pdf_footer", ""), height=60)

            if st.form_submit_button("💾 Salva impostazioni", use_container_width=True):
                for key, val in [
                    ("studio_name", studio_name), ("studio_address", studio_address),
                    ("studio_city", studio_city),  ("studio_phone", studio_phone),
                    ("studio_email", studio_email), ("studio_piva", studio_piva),
                    ("studio_cf", studio_cf),       ("pdf_footer", pdf_footer),
                ]:
                    set_setting(key, val)
                st.success("✅ Impostazioni salvate.")

    with tab_users:
        if not is_admin():
            st.warning("Solo gli amministratori possono gestire gli utenti.")
            return

        users = get_users()
        st.dataframe(pd.DataFrame([{
            "Username": u.username, "Nome": u.full_name or "",
            "Ruolo": u.role, "Attivo": "✅" if u.is_active else "❌",
        } for u in users]), use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("**Aggiungi utente o modifica password**")
        st.caption("Se l'username esiste già, aggiorna nome, ruolo e password.")
        with st.form("user_form"):
            col1, col2 = st.columns(2)
            with col1:
                u_username = st.text_input("Username *")
                u_fullname = st.text_input("Nome completo")
            with col2:
                u_password = st.text_input("Password *", type="password")
                u_role     = st.selectbox("Ruolo", ["user", "admin"])

            if st.form_submit_button("💾 Salva utente", use_container_width=True):
                if not u_username or not u_password:
                    st.error("Username e password sono obbligatori.")
                else:
                    try:
                        save_user({"username": u_username, "password": u_password,
                                   "full_name": u_fullname, "role": u_role})
                        st.success(f"✅ Utente '{u_username}' salvato.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Errore: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not is_logged_in():
        login_page()
        return

    page = sidebar()

    pages = {
        "dashboard":  page_dashboard,
        "clients":    page_clients,
        "import":     page_import,
        "pricelist":  page_pricelist,
        "new_report": page_new_report,
        "history":    page_history,
        "stats":      page_stats,
        "settings":   page_settings,
    }
    pages[page]()


if __name__ == "__main__":
    main()
