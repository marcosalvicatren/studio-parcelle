"""
tests/test_utils.py — Test unitari per motore di calcolo e validazioni.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock
from utils import (
    calc_fee_scaglioni, calc_fee_unitario, calc_quarterly_fee,
    fmt_currency, pct_change, validate_client, recalc_line,
)


def make_service(calc_type="scaglioni", unit_price=None, marginal_rate=None, brackets=None):
    svc = MagicMock()
    svc.calc_type     = calc_type
    svc.unit_price    = unit_price
    svc.marginal_rate = marginal_rate
    svc.brackets      = brackets or []
    return svc


def make_bracket(from_val, to_val, annual_fee):
    b = MagicMock()
    b.threshold_from = from_val
    b.threshold_to   = to_val
    b.annual_fee     = annual_fee
    return b


# ---------------------------------------------------------------------------
# Scaglioni
# ---------------------------------------------------------------------------

class TestCalcScaglioni:
    def setup_method(self):
        self.svc = make_service(
            calc_type="scaglioni", marginal_rate=1.5,
            brackets=[
                make_bracket(1,    600,  2700.00),
                make_bracket(601,  2000, 3827.25),
                make_bracket(2001, 6000, 5472.97),
                make_bracket(6001, None, 5472.97),
            ])

    def test_driver_zero(self):
        assert calc_fee_scaglioni(self.svc, 0) == 0.0

    def test_driver_none(self):
        assert calc_fee_scaglioni(self.svc, None) == 0.0

    def test_primo_scaglione(self):
        # 100 × 4 = 400 → scaglione 1-600 → 2700/4 = 675
        assert calc_fee_scaglioni(self.svc, 100) == pytest.approx(675.0, rel=1e-3)

    def test_secondo_scaglione(self):
        # 400 × 4 = 1600 → scaglione 601-2000 → 3827.25/4
        assert calc_fee_scaglioni(self.svc, 400) == pytest.approx(956.8125, rel=1e-3)

    def test_terzo_scaglione(self):
        # 1000 × 4 = 4000 → scaglione 2001-6000 → 5472.97/4
        assert calc_fee_scaglioni(self.svc, 1000) == pytest.approx(5472.97/4, rel=1e-3)

    def test_oltre_ultimo_scaglione(self):
        # 2000 × 4 = 8000 → oltre 6001 → 5472.97 + (8000-6001)*1.5 = 8470.97 → /4
        expected = (5472.97 + (8000 - 6001) * 1.5) / 4
        assert calc_fee_scaglioni(self.svc, 2000) == pytest.approx(expected, rel=1e-2)

    def test_confine_scaglione(self):
        # 150 × 4 = 600 → primo scaglione esatto → 675
        assert calc_fee_scaglioni(self.svc, 150) == pytest.approx(675.0, rel=1e-3)

    def test_no_brackets(self):
        svc = make_service(brackets=[])
        assert calc_fee_scaglioni(svc, 100) == 0.0


# ---------------------------------------------------------------------------
# Unitario
# ---------------------------------------------------------------------------

class TestCalcUnitario:
    def test_base(self):
        svc = make_service(calc_type="unitario", unit_price=16.0)
        assert calc_fee_unitario(svc, 7) == pytest.approx(112.0)

    def test_zero_quantity(self):
        svc = make_service(calc_type="unitario", unit_price=16.0)
        assert calc_fee_unitario(svc, 0) == 0.0

    def test_none_quantity(self):
        svc = make_service(calc_type="unitario", unit_price=16.0)
        assert calc_fee_unitario(svc, None) == 0.0

    def test_situazioni_contabili(self):
        svc = make_service(calc_type="unitario", unit_price=115.0)
        assert calc_fee_unitario(svc, 1) == pytest.approx(115.0)

    def test_autofatture(self):
        svc = make_service(calc_type="unitario", unit_price=11.0)
        assert calc_fee_unitario(svc, 4) == pytest.approx(44.0)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

class TestCalcQuarterlyFee:
    def test_scaglioni(self):
        svc = make_service(calc_type="scaglioni", brackets=[make_bracket(1, 600, 2700)])
        assert calc_quarterly_fee(svc, 100) == pytest.approx(675.0, rel=1e-3)

    def test_unitario(self):
        svc = make_service(calc_type="unitario", unit_price=16.0)
        assert calc_quarterly_fee(svc, 5) == pytest.approx(80.0)

    def test_none_driver(self):
        svc = make_service(calc_type="unitario", unit_price=100.0)
        assert calc_quarterly_fee(svc, None) == 0.0

    def test_unknown_type(self):
        svc = make_service(calc_type="unknown")
        assert calc_quarterly_fee(svc, 10) == 0.0


# ---------------------------------------------------------------------------
# Conguaglio T4
# ---------------------------------------------------------------------------

class TestConguaglio:
    def test_conguaglio_stesso_scaglione(self):
        """
        T1=T2=T3=T4=100 registrazioni → driver annuale = 400 → primo scaglione (1-600) → 2700
        fee_q1=fee_q2=fee_q3 = 675, conguaglio = 2700 - 2025 = 675
        """
        svc = make_service(
            calc_type="scaglioni",
            brackets=[
                make_bracket(1, 600, 2700),
                make_bracket(601, 2000, 3827.25),
            ])
        line = MagicMock()
        line.driver_q1 = 100.0
        line.driver_q2 = 100.0
        line.driver_q3 = 100.0
        line.driver_q4 = 100.0
        line.fee_q1 = line.fee_q2 = line.fee_q3 = line.fee_q4 = 0.0
        recalc_line(line, svc)
        assert line.fee_q1 == pytest.approx(675.0, rel=1e-3)
        assert line.fee_q2 == pytest.approx(675.0, rel=1e-3)
        assert line.fee_q3 == pytest.approx(675.0, rel=1e-3)
        # Conguaglio: annuo reale = 2700, somma T1+T2+T3 = 2025 → 675
        assert line.fee_q4 == pytest.approx(675.0, rel=1e-3)

    def test_conguaglio_scaglione_superiore(self):
        """
        T1=T2=T3=100, T4=200 → driver annuale = 500 → ancora primo scaglione → 2700
        fee_q1=fee_q2=fee_q3 = 675, conguaglio = 2700 - 2025 = 675
        Ma T1=T2=T3=200, T4=200 → driver annuale = 800 → secondo scaglione → 3827.25
        conguaglio = 3827.25 - (956.8125*3) = 3827.25 - 2870.4375 = 956.8125
        """
        svc = make_service(
            calc_type="scaglioni",
            brackets=[
                make_bracket(1, 600, 2700),
                make_bracket(601, 2000, 3827.25),
            ])
        line = MagicMock()
        line.driver_q1 = 200.0
        line.driver_q2 = 200.0
        line.driver_q3 = 200.0
        line.driver_q4 = 200.0
        line.fee_q1 = line.fee_q2 = line.fee_q3 = line.fee_q4 = 0.0
        recalc_line(line, svc)
        # 800 driver annuale → secondo scaglione → 3827.25
        assert line.fee_q1 == pytest.approx(956.8125, rel=1e-3)
        assert line.fee_q4 == pytest.approx(956.8125, rel=1e-3)
        # Somma totale = 3827.25
        total = line.fee_q1 + line.fee_q2 + line.fee_q3 + line.fee_q4
        assert total == pytest.approx(3827.25, rel=1e-3)


# ---------------------------------------------------------------------------
# Validazione cliente
# ---------------------------------------------------------------------------

class TestValidateClient:
    def _valid(self):
        return {"client_code": "CLI001", "name": "Test SRL", "client_type": "società di capitali"}

    def test_valido(self):
        assert validate_client(self._valid()) == []

    def test_nome_mancante(self):
        d = self._valid(); d["name"] = ""
        assert any("denominazione" in e.lower() for e in validate_client(d))

    def test_codice_mancante(self):
        d = self._valid(); d["client_code"] = ""
        assert any("codice" in e.lower() for e in validate_client(d))

    def test_tipologia_mancante(self):
        d = self._valid(); d["client_type"] = ""
        assert any("tipologia" in e.lower() for e in validate_client(d))

    def test_cf_lunghezza_errata(self):
        d = self._valid(); d["tax_code"] = "ABC123"
        assert any("fiscale" in e.lower() for e in validate_client(d))

    def test_cf_16_valido(self):
        d = self._valid(); d["tax_code"] = "RSSMRA80A01H501Z"
        assert validate_client(d) == []

    def test_piva_errata(self):
        d = self._valid(); d["vat_number"] = "1234"
        assert any("iva" in e.lower() for e in validate_client(d))

    def test_piva_11_valida(self):
        d = self._valid(); d["vat_number"] = "02873210989"
        assert validate_client(d) == []


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

class TestUtils:
    def test_fmt_currency(self):
        assert fmt_currency(3827.25) == "€ 3.827,25"

    def test_fmt_currency_none(self):
        assert fmt_currency(None) == "—"

    def test_pct_change_positivo(self):
        assert pct_change(1000, 1100) == pytest.approx(10.0)

    def test_pct_change_negativo(self):
        assert pct_change(1000, 900) == pytest.approx(-10.0)

    def test_pct_change_zero_base(self):
        assert pct_change(0, 100) is None

    def test_pct_change_invariato(self):
        assert pct_change(1000, 1000) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Coerenza con Excel reale (CARPENTERIA MADA SRL)
# ---------------------------------------------------------------------------

class TestExcelCoherence:
    def test_contabilita_ordinaria(self):
        """404 registrazioni T1 → scaglione 601-2000 → 3827.25/4 = 956.8125"""
        svc = make_service(calc_type="scaglioni", brackets=[
            make_bracket(1, 600, 2700),
            make_bracket(601, 2000, 3827.25),
            make_bracket(2001, 6000, 5472.97),
            make_bracket(6001, None, 5472.97),
        ])
        assert calc_fee_scaglioni(svc, 404) == pytest.approx(956.8125, rel=1e-3)

    def test_f24_telematico(self):
        """7 invii × 16€ = 112€"""
        svc = make_service(calc_type="unitario", unit_price=16.0)
        assert calc_fee_unitario(svc, 7) == pytest.approx(112.0)

    def test_situazioni_contabili(self):
        """1 × 115€ = 115€"""
        svc = make_service(calc_type="unitario", unit_price=115.0)
        assert calc_fee_unitario(svc, 1) == pytest.approx(115.0)
