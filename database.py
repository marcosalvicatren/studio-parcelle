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
    calc_type:
      'scaglioni'  → driver trimestrale × 4 → scaglione annuo → compenso/4, conguaglio T4
      'unitario'   → quantità × tariffa unitaria
    """
    __tablename__ = "service_items"
    __table_args__ = (UniqueConstraint("price_list_id", "service_code"),)

    id            = Column(Integer, primary_key=True, autoincrement=True)
    price_list_id = Column(Integer, ForeignKey("price_lists.id", ondelete="CASCADE"), nullable=False)
    service_code  = Column(String(50), nullable=False)
    description   = Column(String(500), nullable=False)
    category      = Column(String(100), nullable=True)
    calc_type     = Column(String(20), nullable=False, default="unitario")  # scaglioni | unitario
    driver_label  = Column(String(100), nullable=True)   # es. "Numero registrazioni"
    driver_unit   = Column(String(30), nullable=True)    # es. "registrazioni"
    unit_price    = Column(Float, nullable=True)         # per calc_type=unitario
    marginal_rate = Column(Float, nullable=True)         # tariffa marginale oltre ultimo scaglione
    is_active     = Column(Boolean, default=True)
    sort_order    = Column(Integer, default=0)

    price_list = relationship("PriceList", back_populates="services")
    brackets   = relationship("ServiceBracket", back_populates="service",
                              cascade="all, delete-orphan",
                              order_by="ServiceBracket.threshold_from")


class ServiceBracket(Base):
    """Scaglioni annui per una voce di listino."""
    __tablename__ = "service_brackets"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    service_item_id = Column(Integer, ForeignKey("service_items.id", ondelete="CASCADE"), nullable=False)
    threshold_from  = Column(Float, nullable=False)
    threshold_to    = Column(Float, nullable=True)   # NULL = illimitato
    annual_fee      = Column(Float, nullable=False)
    service = relationship("ServiceItem", back_populates="brackets")


class FeeReport(Base):
    """Testata rendiconto: cliente + anno."""
    __tablename__ = "fee_reports"
    __table_args__ = (UniqueConstraint("client_id", "year"),)

    id           = Column(Integer, primary_key=True, autoincrement=True)
    client_id    = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    year         = Column(Integer, nullable=False)
    notes        = Column(Text, nullable=True)
    hours_q1     = Column(Float, nullable=True)
    hours_q2     = Column(Float, nullable=True)
    hours_q3     = Column(Float, nullable=True)
    hours_q4     = Column(Float, nullable=True)
    hourly_rate  = Column(Float, nullable=True)
    billed_prev  = Column(Float, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client", back_populates="fee_reports")
    lines  = relationship("FeeReportLine", back_populates="report",
                          cascade="all, delete-orphan",
                          order_by="FeeReportLine.sort_order")


class FeeReportLine(Base):
    """
    Riga rendiconto con snapshot dati listino + valori trimestrali.
    
    Per calc_type='scaglioni':
      driver_q1..q4 = driver trimestrale inserito dall'utente
      fee_q1..q3    = compenso calcolato (annualizzato / 4)
      fee_q4        = conguaglio: totale_annuo_effettivo - (fee_q1 + fee_q2 + fee_q3)
    
    Per calc_type='unitario':
      driver_q1..q4 = quantità inserita dall'utente
      fee_q1..q4    = quantità × tariffa unitaria
    
    override_q* sovrascrive il calcolato se non NULL.
    """
    __tablename__ = "fee_report_lines"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    report_id         = Column(Integer, ForeignKey("fee_reports.id", ondelete="CASCADE"), nullable=False)
    sort_order        = Column(Integer, default=0)

    # Snapshot listino
    service_code_snap = Column(String(50), nullable=False)
    description_snap  = Column(String(500), nullable=False)
    category_snap     = Column(String(100), nullable=True)
    calc_type_snap    = Column(String(20), nullable=False)

    # Driver trimestrali (input utente)
    driver_q1 = Column(Float, nullable=True)
    driver_q2 = Column(Float, nullable=True)
    driver_q3 = Column(Float, nullable=True)
    driver_q4 = Column(Float, nullable=True)

    # Compensi calcolati
    fee_q1 = Column(Float, nullable=True, default=0.0)
    fee_q2 = Column(Float, nullable=True, default=0.0)
    fee_q3 = Column(Float, nullable=True, default=0.0)
    fee_q4 = Column(Float, nullable=True, default=0.0)  # per scaglioni = conguaglio

    # Override manuali
    override_q1 = Column(Float, nullable=True)
    override_q2 = Column(Float, nullable=True)
    override_q3 = Column(Float, nullable=True)
    override_q4 = Column(Float, nullable=True)

    notes = Column(Text, nullable=True)

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
    __tablename__ = "studio_settings"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    key        = Column(String(100), unique=True, nullable=False)
    value      = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------------------------------------------------------------------
# Init DB
# ---------------------------------------------------------------------------

def init_db():
    Base.metadata.create_all(engine)
    _seed_defaults()


def _hash_password(password: str) -> str:
    import hashlib
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    import hashlib
    return hashlib.sha256(password.encode()).hexdigest() == hashed


def _seed_defaults():
    with get_session() as session:
        if not session.query(User).filter_by(username="admin").first():
            session.add(User(
                username="admin",
                password_hash=_hash_password("admin123"),
                full_name="Amministratore",
                role="admin",
            ))
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


# ---------------------------------------------------------------------------
# Settings
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


# ---------------------------------------------------------------------------
# CRUD Clienti
# ---------------------------------------------------------------------------

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
            c = Client(**{k: v for k, v in data.items() if hasattr(Client, k) and k != "id"})
            session.add(c)
        session.flush()
        session.expunge(c)
        return c


# ---------------------------------------------------------------------------
# CRUD Listini
# ---------------------------------------------------------------------------

def get_price_lists():
    with get_session() as session:
        pls = session.query(PriceList).order_by(PriceList.year.desc()).all()
        session.expunge_all()
        return pls


def get_price_list(pl_id: int) -> Optional[PriceList]:
    with get_session() as session:
        pl = session.query(PriceList).filter_by(id=pl_id).first()
        if pl:
            for s in pl.services:
                _ = s.brackets
            session.expunge_all()
        return pl


def get_price_list_by_year(year: int) -> Optional[PriceList]:
    with get_session() as session:
        pl = session.query(PriceList).filter_by(year=year).first()
        if pl:
            for s in pl.services:
                _ = s.brackets
            session.expunge_all()
        return pl


# ---------------------------------------------------------------------------
# CRUD Rendiconti
# ---------------------------------------------------------------------------

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
            _ = r.lines
            session.expunge_all()
        return r


def get_fee_report_by_client_year(client_id: int, year: int) -> Optional[FeeReport]:
    with get_session() as session:
        r = (session.query(FeeReport)
             .filter_by(client_id=client_id, year=year)
             .first())
        if r:
            _ = r.lines
            session.expunge_all()
        return r


# ---------------------------------------------------------------------------
# CRUD Utenti
# ---------------------------------------------------------------------------

def get_users():
    with get_session() as session:
        users = session.query(User).all()
        session.expunge_all()
        return users


def save_user(data: dict) -> User:
    with get_session() as session:
        existing = session.query(User).filter_by(username=data["username"]).first()
        if existing:
            # Aggiorna utente esistente
            if data.get("full_name"):
                existing.full_name = data["full_name"]
            if data.get("role"):
                existing.role = data["role"]
            if data.get("password"):
                existing.password_hash = _hash_password(data["password"])
            session.flush()
            session.expunge(existing)
            return existing
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
