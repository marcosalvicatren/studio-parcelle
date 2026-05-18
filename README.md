# Studio Parcelle

Gestionale per il calcolo e la gestione delle parcelle di uno studio di commercialisti.
Replica fedelmente la logica dell'Excel esistente dello studio, con database centralizzato,
storicità completa e generazione PDF professionale.

---

## Struttura progetto

```
studio_parcelle/
├── app.py               # Entry point Streamlit – routing e tutte le pagine
├── database.py          # Schema SQLite, modelli ORM, operazioni CRUD
├── utils.py             # Motore di calcolo scaglioni, validazioni, utility
├── pdf_generator.py     # Generazione PDF rendiconti con ReportLab
├── excel_parser.py      # Import anagrafiche CSV/XLSX, lettura storico Excel
├── statistics.py        # Statistiche, confronti storici, KPI dashboard
├── requirements.txt     # Dipendenze Python
├── tests/
│   ├── test_utils.py    # Test calcoli, validazioni, coerenza Excel
│   └── test_statistics.py  # Test statistiche, snapshot, YoY
└── README.md
```

---

## Installazione

```bash
# 1. Clona il repository
git clone https://github.com/tuo-studio/studio-parcelle.git
cd studio-parcelle

# 2. Crea un ambiente virtuale (consigliato)
python -m venv .venv
source .venv/bin/activate        # Linux/Mac
.venv\Scripts\activate           # Windows

# 3. Installa le dipendenze
pip install -r requirements.txt
```

---

## Avvio locale

```bash
streamlit run app.py
```

L'app si apre automaticamente nel browser su `http://localhost:8501`.

**Credenziali default:** `admin` / `admin123`
Cambia la password dopo il primo accesso dalle Impostazioni → Utenti.

---

## Deploy su Streamlit Community Cloud

1. Crea un repository GitHub con tutti i file del progetto.
2. Vai su [share.streamlit.io](https://share.streamlit.io) e connetti il repository.
3. Imposta `app.py` come file principale.
4. Clicca **Deploy**.

> **Nota sul database:** Su Streamlit Community Cloud il filesystem è effimero.
> Il database SQLite viene ricreato ad ogni restart. Per persistenza dei dati in produzione,
> considera di montare un volume esterno o usare [Streamlit Secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)
> per configurare un database esterno (es. PostgreSQL su Supabase gratuito).
> Per uso interno su server fisso o NAS, la versione SQLite è pienamente adeguata.

---

## Struttura database

### `users` — Utenti del sistema
| Campo | Tipo | Note |
|-------|------|-------|
| username | string | univoco |
| password_hash | string | SHA-256 |
| role | string | `admin` o `user` |

### `clients` — Anagrafica clienti
| Campo | Tipo | Note |
|-------|------|-------|
| client_code | string | codice univoco |
| name | string | denominazione |
| tax_code | string | codice fiscale |
| vat_number | string | partita IVA |
| client_type | string | tipologia |
| status | string | `attivo` o `archiviato` |

### `price_lists` — Listini (uno per anno)
| Campo | Tipo | Note |
|-------|------|-------|
| year | integer | univoco |
| name | string | es. "Listino 2024" |
| is_active | boolean | solo listini attivi usati nei rendiconti |

### `service_items` — Voci di listino
| Campo | Tipo | Note |
|-------|------|-------|
| price_list_id | FK | listino di appartenenza |
| service_code | string | codice univoco nel listino |
| calc_type | string | `scaglioni`, `unitario`, `minimo_percentuale`, `forfait` |
| driver_label | string | etichetta del dato da inserire (es. "Numero registrazioni") |
| marginal_rate | float | tariffa marginale oltre ultimo scaglione |

### `service_brackets` — Scaglioni
| Campo | Tipo | Note |
|-------|------|-------|
| service_item_id | FK | prestazione di riferimento |
| threshold_from/to | float | limiti scaglione (annui) |
| annual_fee | float | compenso annuo per questo scaglione |

### `fee_reports` — Rendiconti (testata)
| Campo | Tipo | Note |
|-------|------|-------|
| client_id | FK | cliente |
| year | integer | anno rendiconto |
| hours_q1..q4 | float | ore lavorate per trimestre (KPI interni) |
| hourly_rate | float | compenso orario teorico |
| billed_prev | float | fatturato anno precedente (per confronto) |

### `fee_report_lines` — Righe rendiconto (con snapshot)
| Campo | Tipo | Note |
|-------|------|-------|
| service_code_snap | string | **snapshot** del codice al momento della creazione |
| description_snap | string | **snapshot** della descrizione |
| driver_q1..q4 | float | valori driver inseriti dall'utente |
| fee_q1..q4 | float | compensi calcolati automaticamente |
| override_q1..q4 | float | override manuali (NULL = usa calcolato) |

---

## Logica di calcolo

Il motore replica esattamente la logica Excel dello studio:

### Prestazioni a scaglioni
Il driver trimestrale viene **moltiplicato × 4** per ottenere il driver annuale, che viene confrontato con gli scaglioni. Il compenso annuo dello scaglione trovato viene diviso per 4.

```
driver_annuale = driver_trimestrale × 4
→ trova scaglione in cui cade driver_annuale
→ compenso_trimestrale = compenso_annuo_scaglione / 4
→ se supera ultimo scaglione: compenso_max + (eccedenza × tariffa_marginale) / 4
```

### Prestazioni unitarie
```
compenso_trimestrale = quantità × tariffa_unitaria
```

### Prestazioni con minimo garantito (es. Visto conformità IVA)
```
compenso_trimestrale = MAX(base × percentuale, minimo_fisso)
```

### Override manuale
Ogni trimestre può avere un override manuale che sovrascrive il valore calcolato. Il valore calcolato viene sempre preservato per riferimento.

---

## Gestione listini

- Ogni anno ha il proprio listino indipendente. I vecchi listini non vengono mai modificati.
- Per creare il listino di un nuovo anno: **Listino → Clona listino**, seleziona l'anno sorgente e inserisci l'eventuale aumento percentuale globale.
- Le singole voci possono essere modificate manualmente dopo la clonazione.
- Solo gli utenti con ruolo **admin** possono modificare i listini.

---

## Import Excel

### Import anagrafiche (CSV/XLSX)
Il file deve contenere le colonne (nomi flessibili, riconoscimento automatico):
- `denominazione` o `nome` — obbligatorio
- `codice` — codice cliente (generato automaticamente se assente)
- `codice fiscale` — CF
- `partita iva` — P.IVA
- `tipologia` — tipo cliente

### Import storico Excel studio
Il file multi-foglio dello studio (un foglio per cliente) viene analizzato per estrarre il riepilogo storico. L'import è in sola lettura/anteprima — i dati vengono poi inseriti manualmente nel gestionale.

---

## Generazione PDF

Il PDF viene generato con ReportLab e include:
- Intestazione studio (configurabile in Impostazioni)
- Dati cliente (denominazione, codice, P.IVA, CF)
- Tabella prestazioni con colonne T1/T2/T3/T4/Totale (annuale) o singolo trimestre
- Totale finale
- Footer personalizzabile

Il PDF è disponibile sia **annuale** che per **singolo trimestre** dalla pagina Storico e dalla pagina Nuovo rendiconto.

---

## Test

```bash
# Esegui tutti i test
pytest tests/ -v

# Test specifici
pytest tests/test_utils.py -v
pytest tests/test_statistics.py -v
```

I test verificano:
- Calcolo scaglioni con i valori reali dell'Excel dello studio
- Calcolo unitario (F24, autofatture, situazioni contabili)
- Calcolo minimo percentuale (Visto conformità IVA)
- Validazione anagrafica clienti
- Coerenza totale rendiconto con i valori Excel originali
- Integrità snapshot storici
- Confronti percentuali anno su anno

---

## Limiti attuali (MVP)

- **Database su file locale**: adeguato per uso su un singolo server/PC; per uso multi-sede con accesso simultaneo considerare PostgreSQL.
- **Nessuna gestione allegati**: i PDF vengono generati ma non archiviati nel sistema.
- **Import Excel storico**: produce solo un'anteprima, l'inserimento dati storici rimane manuale.
- **Autenticazione semplice**: password hashate SHA-256, adeguato per uso interno; per accesso internet valutare 2FA.

---

## Sviluppi futuri suggeriti

- Archiviazione PDF generati per cliente/anno
- Notifiche scadenze e promemoria
- Export dati in Excel
- Integrazione firma digitale
- Gestione note spese e rimborsi
- API REST per integrazione con software contabilità esterno
