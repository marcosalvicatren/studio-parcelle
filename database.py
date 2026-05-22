"""
database.py — Schema SQLite, modelli ORM, CRUD, seed listino reale da Excel.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint, create_engine, event,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

DB_PATH = Path("studio_parcelle.db")
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False,
)

@event.listens_for(engine, "connect")
def _set_pragmas(dbapi_conn, _rec):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute("PRAGMA journal_mode = WAL")
    cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    username      = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    full_name     = Column(String(100), nullable=True)
    role          = Column(String(20), nullable=False, default="user")
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)


class Client(Base):
    __tablename__ = "clients"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    client_code  = Column(String(50), unique=True, nullable=False, index=True)
    name         = Column(String(255), nullable=False)
    tax_code     = Column(String(20), nullable=True)
    vat_number   = Column(String(20), nullable=True)
    client_type  = Column(String(50), nullable=False, default="altro")
    status       = Column(String(20), nullable=False, default="attivo")
    notes        = Column(Text, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    fee_reports  = relationship("FeeReport", back_populates="client", cascade="all, delete-orphan")


class PriceList(Base):
    __tablename__ = "price_lists"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    year       = Column(Integer, nullable=False, unique=True)
    name       = Column(String(100), nullable=False)
    notes      = Column(Text, nullable=True)
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    services   = relationship("ServiceItem", back_populates="price_list",
                              cascade="all, delete-orphan",
                              order_by="ServiceItem.sort_order")


class ServiceItem(Base):
    """
    Voce di listino.
    calc_type: 'scaglioni' | 'unitario'
    has_marginal_rate: True solo per driver quantitativi (registrazioni, fatture)
    """
    __tablename__ = "service_items"
    __table_args__ = (UniqueConstraint("price_list_id", "service_code"),)

    id               = Column(Integer, primary_key=True, autoincrement=True)
    price_list_id    = Column(Integer, ForeignKey("price_lists.id", ondelete="CASCADE"), nullable=False)
    service_code     = Column(String(50), nullable=False)
    description      = Column(String(500), nullable=False)
    category         = Column(String(100), nullable=True)
    calc_type        = Column(String(20), nullable=False, default="unitario")
    driver_label     = Column(String(100), nullable=True)
    driver_unit      = Column(String(30), nullable=True)
    unit_price       = Column(Float, nullable=True)
    has_marginal_rate= Column(Boolean, default=False)
    marginal_rate    = Column(Float, nullable=True)
    is_active        = Column(Boolean, default=True)
    sort_order       = Column(Integer, default=0)

    price_list = relationship("PriceList", back_populates="services")
    brackets   = relationship("ServiceBracket", back_populates="service",
                              cascade="all, delete-orphan",
                              order_by="ServiceBracket.threshold_from")


class ServiceBracket(Base):
    __tablename__ = "service_brackets"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    service_item_id = Column(Integer, ForeignKey("service_items.id", ondelete="CASCADE"), nullable=False)
    threshold_from  = Column(Float, nullable=False)
    threshold_to    = Column(Float, nullable=True)
    annual_fee      = Column(Float, nullable=False)
    service = relationship("ServiceItem", back_populates="brackets")


class FeeReport(Base):
    __tablename__ = "fee_reports"
    __table_args__ = (UniqueConstraint("client_id", "year"),)

    id          = Column(Integer, primary_key=True, autoincrement=True)
    client_id   = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    year        = Column(Integer, nullable=False)
    notes       = Column(Text, nullable=True)

    # Ore lavorate per trimestre (IM)
    ore_q1 = Column(Float, nullable=True)
    ore_q2 = Column(Float, nullable=True)
    ore_q3 = Column(Float, nullable=True)
    ore_q4 = Column(Float, nullable=True)

    # Compenso a ore per trimestre (IM)
    comp_ore_q1 = Column(Float, nullable=True)
    comp_ore_q2 = Column(Float, nullable=True)
    comp_ore_q3 = Column(Float, nullable=True)
    comp_ore_q4 = Column(Float, nullable=True)

    # Anno precedente (IM)
    fatturato_prec   = Column(Float, nullable=True)
    ore_prec         = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client", back_populates="fee_reports")
    lines  = relationship("FeeReportLine", back_populates="report",
                          cascade="all, delete-orphan",
                          order_by="FeeReportLine.sort_order")

    # --- Proprietà calcolate ---
    @property
    def ore_tot(self): return (self.ore_q1 or 0) + (self.ore_q2 or 0) + (self.ore_q3 or 0) + (self.ore_q4 or 0)

    @property
    def comp_ore_tot(self): return (self.comp_ore_q1 or 0) + (self.comp_ore_q2 or 0) + (self.comp_ore_q3 or 0) + (self.comp_ore_q4 or 0)

    @property
    def comp_orario_teorico_q1(self): return round(self.comp_ore_q1 / self.ore_q1, 2) if (self.ore_q1 or 0) > 0 else None
    @property
    def comp_orario_teorico_q2(self): return round(self.comp_ore_q2 / self.ore_q2, 2) if (self.ore_q2 or 0) > 0 else None
    @property
    def comp_orario_teorico_q3(self): return round(self.comp_ore_q3 / self.ore_q3, 2) if (self.ore_q3 or 0) > 0 else None
    @property
    def comp_orario_teorico_q4(self): return round(self.comp_ore_q4 / self.ore_q4, 2) if (self.ore_q4 or 0) > 0 else None

    @property
    def comp_orario_teorico_tot(self):
        return round(self.comp_ore_tot / self.ore_tot, 2) if self.ore_tot > 0 else None

    @property
    def comp_orario_reale_prec(self):
        return round(self.fatturato_prec / self.ore_prec, 2) if (self.ore_prec or 0) > 0 else None


class FeeReportLine(Base):
    """
    Riga rendiconto con snapshot + driver trimestrali + compensi calcolati.
    Per scaglioni: fee_q4 = conguaglio annuale.
    override_q* sovrascrive il calcolato.
    """
    __tablename__ = "fee_report_lines"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    report_id         = Column(Integer, ForeignKey("fee_reports.id", ondelete="CASCADE"), nullable=False)
    sort_order        = Column(Integer, default=0)

    service_item_id   = Column(Integer, ForeignKey("service_items.id"), nullable=True)

    # Snapshot
    service_code_snap = Column(String(50), nullable=False)
    description_snap  = Column(String(500), nullable=False)
    category_snap     = Column(String(100), nullable=True)
    calc_type_snap    = Column(String(20), nullable=False)
    driver_label_snap = Column(String(100), nullable=True)
    driver_unit_snap  = Column(String(30), nullable=True)

    # Driver (input utente)
    driver_q1 = Column(Float, nullable=True)
    driver_q2 = Column(Float, nullable=True)
    driver_q3 = Column(Float, nullable=True)
    driver_q4 = Column(Float, nullable=True)

    # Compensi calcolati
    fee_q1 = Column(Float, default=0.0)
    fee_q2 = Column(Float, default=0.0)
    fee_q3 = Column(Float, default=0.0)
    fee_q4 = Column(Float, default=0.0)

    # Override manuali
    override_q1 = Column(Float, nullable=True)
    override_q2 = Column(Float, nullable=True)
    override_q3 = Column(Float, nullable=True)
    override_q4 = Column(Float, nullable=True)

    notes = Column(Text, nullable=True)

    report = relationship("FeeReport", back_populates="lines")

    @property
    def effective_q1(self): return self.override_q1 if self.override_q1 is not None else (self.fee_q1 or 0.0)
    @property
    def effective_q2(self): return self.override_q2 if self.override_q2 is not None else (self.fee_q2 or 0.0)
    @property
    def effective_q3(self): return self.override_q3 if self.override_q3 is not None else (self.fee_q3 or 0.0)
    @property
    def effective_q4(self): return self.override_q4 if self.override_q4 is not None else (self.fee_q4 or 0.0)

    @property
    def total(self): return self.effective_q1 + self.effective_q2 + self.effective_q3 + self.effective_q4


class StudioSettings(Base):
    __tablename__ = "studio_settings"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    key        = Column(String(100), unique=True, nullable=False)
    value      = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def init_db():
    _migrate_db()
    Base.metadata.create_all(engine)
    _seed_defaults()


def _migrate_db():
    """Aggiunge colonne mancanti senza perdere dati esistenti."""
    import sqlite3
    if not DB_PATH.exists():
        return
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Colonne da aggiungere se mancanti: tabella, colonna, tipo, default
    migrations = [
        ("fee_reports", "ore_q1",        "FLOAT",   "NULL"),
        ("fee_reports", "ore_q2",        "FLOAT",   "NULL"),
        ("fee_reports", "ore_q3",        "FLOAT",   "NULL"),
        ("fee_reports", "ore_q4",        "FLOAT",   "NULL"),
        ("fee_reports", "comp_ore_q1",   "FLOAT",   "NULL"),
        ("fee_reports", "comp_ore_q2",   "FLOAT",   "NULL"),
        ("fee_reports", "comp_ore_q3",   "FLOAT",   "NULL"),
        ("fee_reports", "comp_ore_q4",   "FLOAT",   "NULL"),
        ("fee_reports", "fatturato_prec","FLOAT",   "NULL"),
        ("fee_reports", "ore_prec",      "FLOAT",   "NULL"),
        ("fee_report_lines", "service_item_id",   "INTEGER", "NULL"),
        ("fee_report_lines", "driver_label_snap", "VARCHAR(100)", "NULL"),
        ("fee_report_lines", "driver_unit_snap",  "VARCHAR(30)",  "NULL"),
        ("service_items", "has_marginal_rate", "BOOLEAN", "0"),
    ]

    for table, column, col_type, default in migrations:
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT {default}")
        except sqlite3.OperationalError:
            pass  # colonna già esistente

    conn.commit()
    conn.close()


def _hash_password(p): 
    import hashlib
    return hashlib.sha256(p.encode()).hexdigest()

def verify_password(p, h):
    import hashlib
    return hashlib.sha256(p.encode()).hexdigest() == h

def _seed_defaults():
    with get_session() as s:
        if not s.query(User).filter_by(username="Marco").first():
            s.add(User(username="Marco", password_hash=_hash_password("Newyork2016?!"),
                       full_name="Marco", role="admin"))
        defaults = {
            "studio_name": "Studio Commercialisti", "studio_address": "",
            "studio_city": "", "studio_phone": "", "studio_email": "",
            "studio_piva": "", "studio_cf": "", "pdf_footer": "",
        }
        for k, v in defaults.items():
            if not s.query(StudioSettings).filter_by(key=k).first():
                s.add(StudioSettings(key=k, value=v))
        # Seed listino reale se non esiste
        if not s.query(PriceList).filter_by(year=2024).first():
            _seed_listino_2024(s)


def _seed_listino_2024(s):
    """Precarica il listino 2024 con tutte le prestazioni reali dall'Excel."""
    pl = PriceList(year=2024, name="Listino 2024", is_active=True)
    s.add(pl)
    s.flush()

    def add_svc(code, desc, cat, calc_type, driver_label, driver_unit,
                unit_price=None, has_mr=False, mr=None, sort=0):
        svc = ServiceItem(
            price_list_id=pl.id, service_code=code, description=desc,
            category=cat, calc_type=calc_type, driver_label=driver_label,
            driver_unit=driver_unit, unit_price=unit_price,
            has_marginal_rate=has_mr, marginal_rate=mr,
            is_active=True, sort_order=sort,
        )
        s.add(svc)
        s.flush()
        return svc

    def add_br(svc, f, t, fee):
        s.add(ServiceBracket(service_item_id=svc.id,
                             threshold_from=f, threshold_to=t, annual_fee=fee))

    # --- Contabilità semplificata (driver: numero registrazioni) ---
    svc = add_svc("CONT-SEMPL", "Contabilità semplificata", "Contabilità",
                  "scaglioni", "Numero registrazioni", "registrazioni",
                  has_mr=True, mr=1.65, sort=10)
    add_br(svc, 1, 90, 1178)
    add_br(svc, 91, 180, 1580)
    add_br(svc, 181, 360, 2267)
    add_br(svc, 361, None, 2267)

    # --- Contabilità ordinaria (driver: numero articoli in PD) ---
    svc = add_svc("CONT-ORD", "Contabilità ordinaria", "Contabilità",
                  "scaglioni", "Numero articoli in PD", "articoli",
                  has_mr=True, mr=1.5, sort=20)
    add_br(svc, 1, 600, 2700)
    add_br(svc, 601, 2000, round(3645 * 1.05, 2))
    add_br(svc, 2001, 6000, round(3645 * 1.05 * 1.43, 2))
    add_br(svc, 6001, None, round(3645 * 1.05 * 1.43, 2))

    # --- Dichiarazioni IVA (driver: volume d'affari) ---
    svc = add_svc("DICH-IVA", "Dichiarazioni IVA", "Dichiarazioni",
                  "scaglioni", "Volume d'affari", "€",
                  has_mr=False, sort=30)
    add_br(svc, 0, 75000, 189)
    add_br(svc, 75001, 150000, 237)
    add_br(svc, 105001, 500000, 371)
    add_br(svc, 600001, None, 594)

    # --- Redditi PF p.IVA e SP (driver: volume d'affari) ---
    svc = add_svc("REDD-PF-IVA", "Redditi PF p.IVA e Società di Persone", "Dichiarazioni",
                  "scaglioni", "Volume d'affari", "€",
                  has_mr=False, sort=40)
    add_br(svc, 0, 75000, 296)
    add_br(svc, 75001, 150000, 533)
    add_br(svc, 150001, 300000, 711)
    add_br(svc, 300001, None, 886)

    # --- Redditi SC (driver: volume d'affari) ---
    svc = add_svc("REDD-SC", "Redditi SC", "Dichiarazioni",
                  "scaglioni", "Volume d'affari", "€",
                  has_mr=False, sort=50)
    add_br(svc, 0, 150000, 522)
    add_br(svc, 150001, 300000, 743)
    add_br(svc, 300001, 600000, 1112)
    add_br(svc, 600001, 900000, 1480)
    add_br(svc, 900001, None, 1480)

    # --- Bilancio CEE-01 (driver: attivo) ---
    svc = add_svc("BIL-CEE-01", "Bilancio CEE - Attivo", "Bilancio",
                  "scaglioni", "Attivo di bilancio", "€",
                  has_mr=False, sort=60)
    add_br(svc, 0, 150000, 357)
    add_br(svc, 150001, 500000, 562)
    add_br(svc, 500001, 1300000, 989)
    add_br(svc, 1300001, 2600000, 1410)
    add_br(svc, 2600001, None, 1410)

    # --- Bilancio CEE-02 (driver: ricavi) ---
    svc = add_svc("BIL-CEE-02", "Bilancio CEE - Ricavi", "Bilancio",
                  "scaglioni", "Ricavi", "€",
                  has_mr=False, sort=70)
    add_br(svc, 0, 300000, 333)
    add_br(svc, 300001, 600000, 450)
    add_br(svc, 601000, 1300000, 705)
    add_br(svc, 1300001, 3500000, 1000)
    add_br(svc, 3500001, None, 1000)

    # --- LIPE Interne (driver: volume d'affari dichiarazione IVA) ---
    svc = add_svc("LIPE-INT", "LIPE Interne", "Dichiarazioni",
                  "scaglioni", "Volume d'affari Dich. IVA", "€",
                  has_mr=False, sort=80)
    add_br(svc, 0, 37500, 150)
    add_br(svc, 37501, 75000, 190)
    add_br(svc, 75001, 150000, 265)
    add_br(svc, 150001, None, 380)

    # --- LIPE Esterne ---
    svc = add_svc("LIPE-EST", "LIPE Esterne", "Dichiarazioni",
                  "scaglioni", "Volume d'affari Dich. IVA", "€",
                  has_mr=False, sort=90)
    add_br(svc, 0, 37500, 210)
    add_br(svc, 37501, 75000, 270)
    add_br(svc, 75001, 150000, 380)
    add_br(svc, 150001, None, 490)

    # --- Modello 770 (driver: numero percipienti) ---
    svc = add_svc("MOD-770", "Modello 770", "Dichiarazioni",
                  "scaglioni", "Numero percipienti", "percipienti",
                  has_mr=True, mr=0.0, sort=100)
    add_br(svc, 1, 5, round(110 * 1.055, 2))
    add_br(svc, 6, 15, round(150 * 1.05, 2))
    add_br(svc, 16, 25, round(200 * 1.05, 2))
    add_br(svc, 26, 50, round(250 * 1.05, 2))
    add_br(svc, 51, None, round(250 * 1.05, 2))

    # --- Redditi PF senza p.IVA (driver: reddito) ---
    svc = add_svc("REDD-PF", "Redditi PF senza partita IVA", "Dichiarazioni",
                  "scaglioni", "Reddito", "€",
                  has_mr=False, sort=110)
    add_br(svc, 1, 20000, round(150 * 1.05, 2))
    add_br(svc, 20001, 50000, round(200 * 1.05, 2))
    add_br(svc, 50001, 100000, round(250 * 1.05, 2))
    add_br(svc, 100001, None, round(350 * 1.05, 2))

    # --- F24 Telematico (unitario) ---
    add_svc("F24", "F24 Telematico", "Adempimenti",
            "unitario", "Numero invii", "invii",
            unit_price=16.0, sort=120)

    # --- Situazioni contabili (unitario) ---
    add_svc("SIT-CONT", "Situazioni contabili", "Contabilità",
            "unitario", "Numero situazioni", "situazioni",
            unit_price=115.0, sort=130)

    # --- Modello CU (unitario con fisso) ---
    add_svc("MOD-CU", "Modello CU", "Dichiarazioni",
            "unitario", "Numero percipienti", "percipienti",
            unit_price=19.0, sort=140)

    # --- Redditi forfettari (unitario) ---
    add_svc("REDD-FORF", "Redditi forfettari", "Dichiarazioni",
            "unitario", "Numero dichiarazioni", "dichiarazioni",
            unit_price=round(350 * 1.1, 2), sort=150)

    # --- Ravvedimento F24 (unitario) ---
    add_svc("RAVV-F24", "Ravvedimento F24", "Adempimenti",
            "unitario", "Numero pratiche", "pratiche",
            unit_price=0.0, sort=160)

    # --- Visto di conformità (unitario) ---
    add_svc("VISTO-CONF", "Visto di conformità", "Adempimenti",
            "unitario", "Numero visti", "visti",
            unit_price=350.0, sort=170)

    # --- INTRASTAT (unitario) ---
    add_svc("INTRASTAT", "INTRASTAT", "Adempimenti",
            "unitario", "Numero dichiarazioni", "dichiarazioni",
            unit_price=75.0, sort=180)

    # --- Fatture Elettroniche (unitario) ---
    add_svc("FATT-ELETT", "Fatture Elettroniche", "Adempimenti",
            "unitario", "Numero fatture", "fatture",
            unit_price=12.0, sort=190)

    # --- Prestazioni a ore (unitario) ---
    add_svc("PREST-ORE", "Prestazioni a ore / vacazione", "Varie",
            "unitario", "Numero ore", "ore",
            unit_price=102.0, sort=200)

    # --- Pratica invio bilancio CCIAA (unitario) ---
    add_svc("CCIAA", "Pratica invio bilancio CCIAA", "Adempimenti",
            "unitario", "Numero pratiche", "pratiche",
            unit_price=55.0, sort=210)

    # --- Visto di conformità IVA (unitario) ---
    add_svc("VISTO-IVA", "Visto di conformità IVA", "Adempimenti",
            "unitario", "Credito IVA", "€",
            unit_price=0.02, sort=220)

    # --- Tariffa/bolli/diritti CCIAA (unitario) ---
    add_svc("BOLLI-CCIAA", "Tariffa, bolli, diritti CCIAA", "Adempimenti",
            "unitario", "Importo", "€",
            unit_price=1.0, sort=230)

    # --- Gestione libri sociali SC (unitario) ---
    add_svc("LIBRI-SOC", "Gestione Libri Sociali SC", "Adempimenti",
            "unitario", "Numero libri", "libri",
            unit_price=55.0, sort=240)

    # --- CIVIS (unitario) ---
    add_svc("CIVIS", "CIVIS - Procedura", "Adempimenti",
            "unitario", "Numero procedure", "procedure",
            unit_price=55.0, sort=250)

    # --- Rateazione avvisi bonari (unitario) ---
    add_svc("RATEAZ-BON", "Rateazione avvisi bonari", "Adempimenti",
            "unitario", "Numero pratiche", "pratiche",
            unit_price=37.0, sort=260)

    # --- Rateazioni cartelle esattoriali (unitario) ---
    add_svc("RATEAZ-CART", "Rateazioni cartelle esattoriali", "Adempimenti",
            "unitario", "Numero pratiche", "pratiche",
            unit_price=95.0, sort=270)

    # --- Esame cartelle/avvisi bonari (unitario) ---
    add_svc("ESAME-CART", "Esame cartelle / Avvisi bonari", "Adempimenti",
            "unitario", "Numero pratiche", "pratiche",
            unit_price=70.0, sort=280)

    # --- Dichiarazione imposta di bollo (unitario) ---
    add_svc("DICH-BOLLO", "Dichiarazione imposta di bollo", "Adempimenti",
            "unitario", "Numero dichiarazioni", "dichiarazioni",
            unit_price=160.0, sort=290)

    # --- Autofatture (unitario) ---
    add_svc("AUTOFATT", "Autofatture", "Contabilità",
            "unitario", "Numero autofatture", "autofatture",
            unit_price=11.0, sort=300)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_setting(key):
    with get_session() as s:
        row = s.query(StudioSettings).filter_by(key=key).first()
        return row.value if row else ""

def set_setting(key, value):
    with get_session() as s:
        row = s.query(StudioSettings).filter_by(key=key).first()
        if row: row.value = value
        else: s.add(StudioSettings(key=key, value=value))

def get_all_settings():
    with get_session() as s:
        return {r.key: r.value for r in s.query(StudioSettings).all()}


# ---------------------------------------------------------------------------
# CRUD Clienti
# ---------------------------------------------------------------------------

def get_clients(include_archived=False):
    with get_session() as s:
        q = s.query(Client)
        if not include_archived:
            q = q.filter(Client.status != "archiviato")
        clients = q.order_by(Client.name).all()
        s.expunge_all()
        return clients

def get_client(client_id):
    with get_session() as s:
        c = s.query(Client).filter_by(id=client_id).first()
        if c: s.expunge(c)
        return c

def save_client(data):
    with get_session() as s:
        if data.get("id"):
            c = s.query(Client).filter_by(id=data["id"]).first()
            for k, v in data.items():
                if k != "id" and hasattr(c, k): setattr(c, k, v)
            c.updated_at = datetime.utcnow()
        else:
            c = Client(**{k: v for k, v in data.items() if hasattr(Client, k) and k != "id"})
            s.add(c)
        s.flush(); s.expunge(c)
        return c


# ---------------------------------------------------------------------------
# CRUD Listini
# ---------------------------------------------------------------------------

def get_price_lists():
    with get_session() as s:
        pls = s.query(PriceList).order_by(PriceList.year.desc()).all()
        s.expunge_all()
        return pls

def get_price_list(pl_id):
    with get_session() as s:
        pl = s.query(PriceList).filter_by(id=pl_id).first()
        if pl:
            for svc in pl.services: _ = svc.brackets
            s.expunge_all()
        return pl

def get_price_list_by_year(year):
    with get_session() as s:
        pl = s.query(PriceList).filter_by(year=year).first()
        if pl:
            for svc in pl.services: _ = svc.brackets
            s.expunge_all()
        return pl


# ---------------------------------------------------------------------------
# CRUD Rendiconti
# ---------------------------------------------------------------------------

def get_fee_reports(client_id):
    with get_session() as s:
        reports = s.query(FeeReport).filter_by(client_id=client_id).order_by(FeeReport.year.desc()).all()
        for r in reports: _ = r.lines
        s.expunge_all()
        return reports

def get_fee_report(report_id):
    with get_session() as s:
        r = s.query(FeeReport).filter_by(id=report_id).first()
        if r: _ = r.lines; s.expunge_all()
        return r

def get_fee_report_by_client_year(client_id, year):
    with get_session() as s:
        r = s.query(FeeReport).filter_by(client_id=client_id, year=year).first()
        if r: _ = r.lines; s.expunge_all()
        return r


# ---------------------------------------------------------------------------
# CRUD Utenti
# ---------------------------------------------------------------------------

def get_users():
    with get_session() as s:
        users = s.query(User).all(); s.expunge_all(); return users

def save_user(data):
    with get_session() as s:
        existing = s.query(User).filter_by(username=data["username"]).first()
        if existing:
            if data.get("full_name"): existing.full_name = data["full_name"]
            if data.get("role"):     existing.role = data["role"]
            if data.get("password"): existing.password_hash = _hash_password(data["password"])
            s.flush(); s.expunge(existing); return existing
        else:
            u = User(username=data["username"], password_hash=_hash_password(data["password"]),
                     full_name=data.get("full_name",""), role=data.get("role","user"))
            s.add(u); s.flush(); s.expunge(u); return u

def authenticate(username, password):
    with get_session() as s:
        u = s.query(User).filter_by(username=username, is_active=True).first()
        if u and verify_password(password, u.password_hash):
            s.expunge(u); return u
        return None
