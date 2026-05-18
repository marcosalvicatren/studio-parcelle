"""
database.py — Schema SQLite, modelli ORM, operazioni CRUD.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint, create_engine, event,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass

# ---------------------------------------------------------------------------
# Modelli
# ---------------------------------------------------------------------------

class User(Base):
    """Utenti del sistema con ruolo admin/utente."""
    __tablename__ = "users"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    username     = Column(String(50), unique=True, nullable=False)
    password_hash= Column(String(256), nullable=False)
    full_name    = Column(String(100), nullable=True)
    role         = Column(String(20), nullable=False, default="user")  # admin | user
    is_active    = Column(Boolean, default=True)
    created_at   = Column(DateTime, default=datetime.utcnow)


class Client(Base):
    """Anagrafica clienti."""
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
    """Testata listino (un listino per anno)."""
    __tablename__ = "price_lists"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    year       = Column(Integer, nullable=False, unique=True)
    name       = Column(String(100), nullable=False)
    notes      = Column(Text, nullable=True)
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    services   = relationship("ServiceItem", back_populates="price_list", cascade="all, delete-orphan")


class ServiceItem(Base):
    """
    Singola voce di listino.
    calc_type: 'scaglioni' | 'unitario' | 'minimo_percentuale'
    driver_label: etichetta del driver (es. 'Numero articoli in PD')
    driver_unit: unità del driver (es. 'registrazioni', 'euro')
    Per calc_type='unitario': unit_price è il prezzo per unità, niente scaglioni.
    Per calc_type='scaglioni': gli scaglioni sono in ServiceBracket.
    Per calc_type='minimo_percentuale': percent + min_fee.
    """
    __tablename__ = "service_items"
    __table_args__ = (UniqueConstraint("price_list_id", "service_code"),)

    id             = Column(Integer, primary_key=True, autoincrement=True)
    price_list_id  = Column(Integer, ForeignKey("price_lists.id", ondelete="CASCADE"), nullable=False)
    service_code   = Column(String(50), nullable=False)
    description    = Column(String(500), nullable=False)
    category       = Column(String(100), nullable=True)
    calc_type      = Column(String(30), nullable=False, default="unitario")
    driver_label   = Column(String(100), nullable=True)   # es. "Numero articoli in PD"
    driver_unit    = Column(String(30), nullable=True)    # es. "registrazioni"
    unit_price     = Column(Float, nullable=True)         # per calc_type=unitario
    percent_fee    = Column(Float, nullable=True)         # per calc_type=minimo_percentuale
    min_fee        = Column(Float, nullable=True)         # minimo garantito
    marginal_rate  = Column(Float, nullable=True)         # tariffa marginale oltre ultimo scaglione
    is_active      = Column(Boolean, default=True)
    sort_order     = Column(Integer, default=0)

    price_list = relationship("PriceList", back_populates="services")
    brackets   = relationship("ServiceBracket", back_populates="service",
                              cascade="all, delete-orphan", order_by="ServiceBracket.threshold_from")


class ServiceBracket(Base):
    """
    Scaglioni per una voce di listino.
    threshold_from/to: limiti annui del driver.
    annual_fee: compenso annuo per questo scaglione.
    """
    __tablename__ = "service_brackets"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    service_item_id= Column(Integer, ForeignKey("service_items.id", ondelete="CASCADE"), nullable=False)
    threshold_from = Column(Float, nullable=False)
    threshold_to   = Column(Float, nullable=True)   # NULL = infinito
    annual_fee     = Column(Float, nullable=False)

    service = relationship("ServiceItem", back_populates="brackets")


class FeeReport(Base):
    """Testata rendiconto: cliente + anno."""
    __tablename__ = "fee_reports"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    client_id    = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    year         = Column(Integer, nullable=False)
    notes        = Column(Text, nullable=True)
    # KPI interni studio
    hours_q1     = Column(Float, nullable=True)
    hours_q2     = Column(Float, nullable=True)
    hours_q3     = Column(Float, nullable=True)
    hours_q4     = Column(Float, nullable=True)
    hourly_rate  = Column(Float, nullable=True)   # compenso orario teorico
    billed_prev  = Column(Float, nullable=True)   # fatturato anno precedente (per confronto)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client", back_populates="fee_reports")
    lines  = relationship("FeeReportLine", back_populates="report",
                          cascade="all, delete-orphan", order_by="FeeReportLine.sort_order")

    __table_args__ = (UniqueConstraint("client_id", "year"),)


class FeeReportLine(Base):
    """
    Riga rendiconto con snapshot dati listino + valori trimestrali.
    I driver trimestrali (d_q1..d_q4) sono i valori inseriti dall'utente.
    I compensi trimestrali (fee_q1..fee_q4) sono calcolati e poi salvati (snapshot).
    override_q* = compenso manuale che sovrascrive il calcolato.
    """
    __tablename__ = "fee_report_lines"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    report_id            = Column(Integer, ForeignKey("fee_reports.id", ondelete="CASCADE"), nullable=False)
    sort_order           = Column(Integer, default=0)

    # Snapshot listino al momento della creazione
    service_code_snap    = Column(String(50), nullable=False)
    description_snap     = Column(String(500), nullable=False)
    category_snap        = Column(String(100), nullable=True)
    calc_type_snap       = Column(String(30), nullable=False)

    # Driver trimestrali (input utente)
    driver_q1            = Column(Float, nullable=True)
    driver_q2            = Column(Float, nullable=True)
    driver_q3            = Column(Float, nullable=True)
    driver_q4            = Column(Float, nullable=True)

    # Compensi calcolati
    fee_q1               = Column(Float, nullable=True, default=0.0)
    fee_q2               = Column(Float, nullable=True, default=0.0)
    fee_q3               = Column(Float, nullable=True, default=0.0)
    fee_q4               = Column(Float, nullable=True, default=0.0)

    # Override manuali (sovrascrivono il calcolato se non NULL)
    override_q1          = Column(Float, nullable=True)
    override_q2          = Column(Float, nullable=True)
    override_q3          = Column(Float, nullable=True)
    override_q4          = Column(Float, nullable=True)

    notes                = Column(Text, nullable=True)

    report = relationship("FeeReport", back_populates="lines")

    @property
    def effective_q1(self) -> float:
        return self.override_q1 if self.override_q1 is not None else (self.fee_q1 or 0.0)

    @property
    def effective_q2(self) -> float:
        return self.override_q2 if self.override_q2 is not None else (self.fee_q2 or 0.0)

    @property
    def effective_q3(self) -> float:
        return self.override_q3 if self.override_q3 is not None else (self.fee_q3 or 0.0)

    @property
    def effective_q4(self) -> float:
        return self.override_q4 if self.override_q4 is not None else (self.fee_q4 or 0.0)

    @property
    def total(self) -> float:
        return self.effective_q1 + self.effective_q2 + self.effective_q3 + self.effective_q4


class StudioSettings(Base):
    """Impostazioni studio (intestazione PDF, dati fiscali, ecc.)."""
    __tablename__ = "studio_settings"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    key        = Column(String(100), unique=True, nullable=False)
    value      = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------------------------------------------------------------------
# Init DB
# ---------------------------------------------------------------------------

def init_db():
    """Crea tutte le tabelle e inserisce dati di default."""
    Base.metadata.create_all(engine)
    _seed_defaults()


def _seed_defaults():
    """Inserisce utente admin e impostazioni studio se non esistono."""
    import hashlib
    with get_session() as session:
        # Admin di default
        if not session.query(User).filter_by(username="admin").first():
            session.add(User(
                username="admin",
                password_hash=_hash_password("admin123"),
                full_name="Amministratore",
                role="admin",
            ))
        # Impostazioni studio di default
        defaults = {
            "studio_name": "Studio Commercialisti",
            "studio_address": "",
            "studio_city": "",
            "studio_phone": "",
            "studio_email": "",
            "studio_piva": "",
            "studio_cf": "",
            "pdf_footer": "",
        }
        for key, value in defaults.items():
            if not session.query(StudioSettings).filter_by(key=key).first():
                session.add(StudioSettings(key=key, value=value))


def _hash_password(password: str) -> str:
    import hashlib
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    import hashlib
    return hashlib.sha256(password.encode()).hexdigest() == hashed


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def get_setting(key: str) -> str:
    with get_session() as session:
        row = session.query(StudioSettings).filter_by(key=key).first()
        return row.value if row else ""


def set_setting(key: str, value: str):
    with get_session() as session:
        row = session.query(StudioSettings).filter_by(key=key).first()
        if row:
            row.value = value
        else:
            session.add(StudioSettings(key=key, value=value))


def get_all_settings() -> dict:
    with get_session() as session:
        rows = session.query(StudioSettings).all()
        return {r.key: r.value for r in rows}


def get_clients(include_archived=False):
    with get_session() as session:
        q = session.query(Client)
        if not include_archived:
            q = q.filter(Client.status != "archiviato")
        clients = q.order_by(Client.name).all()
        session.expunge_all()
        return clients


def get_client(client_id: int) -> Optional[Client]:
    with get_session() as session:
        c = session.query(Client).filter_by(id=client_id).first()
        if c:
            session.expunge(c)
        return c


def save_client(data: dict) -> Client:
    with get_session() as session:
        if data.get("id"):
            c = session.query(Client).filter_by(id=data["id"]).first()
            for k, v in data.items():
                if k != "id" and hasattr(c, k):
                    setattr(c, k, v)
            c.updated_at = datetime.utcnow()
        else:
            c = Client(**{k: v for k, v in data.items() if hasattr(Client, k)})
            session.add(c)
        session.flush()
        session.expunge(c)
        return c


def get_price_lists():
    with get_session() as session:
        pls = session.query(PriceList).order_by(PriceList.year.desc()).all()
        session.expunge_all()
        return pls


def get_price_list(pl_id: int) -> Optional[PriceList]:
    with get_session() as session:
        pl = session.query(PriceList).filter_by(id=pl_id).first()
        if pl:
            # Eager load
            _ = [(s.brackets) for s in pl.services]
            session.expunge_all()
        return pl


def get_price_list_by_year(year: int) -> Optional[PriceList]:
    with get_session() as session:
        pl = session.query(PriceList).filter_by(year=year).first()
        if pl:
            _ = [(s.brackets) for s in pl.services]
            session.expunge_all()
        return pl


def get_fee_reports(client_id: int):
    with get_session() as session:
        reports = (session.query(FeeReport)
                   .filter_by(client_id=client_id)
                   .order_by(FeeReport.year.desc())
                   .all())
        for r in reports:
            _ = r.lines
        session.expunge_all()
        return reports


def get_fee_report(report_id: int) -> Optional[FeeReport]:
    with get_session() as session:
        r = session.query(FeeReport).filter_by(id=report_id).first()
        if r:
            _ = [(l.report_id) for l in r.lines]
            session.expunge_all()
        return r


def get_fee_report_by_client_year(client_id: int, year: int) -> Optional[FeeReport]:
    with get_session() as session:
        r = (session.query(FeeReport)
             .filter_by(client_id=client_id, year=year)
             .first())
        if r:
            _ = [(l.report_id) for l in r.lines]
            session.expunge_all()
        return r


def get_users():
    with get_session() as session:
        users = session.query(User).all()
        session.expunge_all()
        return users


def save_user(data: dict) -> User:
    with get_session() as session:
        if data.get("id"):
            u = session.query(User).filter_by(id=data["id"]).first()
            for k, v in data.items():
                if k not in ("id", "password_hash") and hasattr(u, k):
                    setattr(u, k, v)
            if data.get("new_password"):
                u.password_hash = _hash_password(data["new_password"])
        else:
            u = User(
                username=data["username"],
                password_hash=_hash_password(data["password"]),
                full_name=data.get("full_name", ""),
                role=data.get("role", "user"),
            )
            session.add(u)
        session.flush()
        session.expunge(u)
        return u


def authenticate(username: str, password: str) -> Optional[User]:
    with get_session() as session:
        u = session.query(User).filter_by(username=username, is_active=True).first()
        if u and verify_password(password, u.password_hash):
            session.expunge(u)
            return u
        return None
