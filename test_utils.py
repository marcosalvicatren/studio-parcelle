"""
tests/test_utils.py — Test unitari per motore di calcolo e validazioni.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock

from utils import (
    calc_fee_scaglioni,
    calc_fee_unitario,
    calc_fee_minimo_percentuale,
    calc_quarterly_fee,
    fmt_currency,
    pct_change,
    validate_client,
)


# ---------------------------------------------------------------------------
# Fixture: ServiceItem mock
# ---------------------------------------------------------------------------

def make_service(calc_type="scaglioni", unit_price=None, min_fee=None,
                 percent_fee=None, marginal_rate=None, brackets=None):
    svc = MagicMock()
    svc.calc_type = calc_type
    svc.unit_price = unit_price
    svc.min_fee = min_fee
    svc.percent_fee = percent_fee
    svc.marginal_rate = marginal_rate
    svc.brackets = brackets or []
    return svc


def make_bracket(from_val, to_val, annual_fee):
    b = MagicMock()
    b.threshold_from = from_val
    b.threshold_to = to_val
    b.annual_fee = annual_fee
    return b


# ---------------------------------------------------------------------------
# Test: calcolo scaglioni (replica logica Excel)
# ---------------------------------------------------------------------------

class TestCalcScaglioni:
    """
    Replica i calcoli dell'Excel per Contabilità Ordinaria:
    Scaglioni annui: 1-600 → 2700€, 601-2000 → 3827.25€, 2001-6000 → 5472.97€
    Driver trimestrale × 4 = driver annuale per ricerca scaglione.
    """

    def setup_method(self):
        self.svc = make_service(
            calc_type="scaglioni",
            marginal_rate=1.5,
            brackets=[
                make_bracket(1, 600, 2700),
                make_bracket(601, 2000, 3827.25),
                make_bracket(2001, 6000, 5472.97),
                make_bracket(6001, None, 5472.97),  # Ultimo scaglione
            ],
        )

    def test_driver_zero_returns_zero(self):
        assert calc_fee_scaglioni(self.svc, 0) == 0.0

    def test_driver_none_returns_zero(self):
        assert calc_fee_scaglioni(self.svc, None) == 0.0

    def test_scaglione_1_primo(self):
        # 100 × 4 = 400 → primo scaglione → 2700/4 = 675
        result = calc_fee_scaglioni(self.svc, 100)
        assert result == pytest.approx(675.0, rel=1e-3)

    def test_scaglione_2(self):
        # 400 × 4 = 1600 → secondo scaglione → 3827.25/4 = 956.8125
        result = calc_fee_scaglioni(self.svc, 400)
        assert result == pytest.approx(956.8125, rel=1e-3)

    def test_scaglione_3(self):
        # 1000 × 4 = 4000 → terzo scaglione → 5472.97/4
        result = calc_fee_scaglioni(self.svc, 1000)
        assert result == pytest.approx(5472.97 / 4, rel=1e-3)

    def test_oltre_ultimo_scaglione_con_marginal_rate(self):
        # 2000 × 4 = 8000 → oltre 6001 → 5472.97 + (8000-6001)*1.5
        # Compenso annuo = 5472.97 + 1999 * 1.5 = 8470.97
        # Trimestrale = 8470.97 / 4 ≈ 2117.74
        result = calc_fee_scaglioni(self.svc, 2000)
        expected = (5472.97 + (8000 - 6001) * 1.5) / 4
        assert result == pytest.approx(expected, rel=1e-2)

    def test_valore_esatto_confine_scaglione(self):
        # 150 × 4 = 600 → primo scaglione esatto → 2700/4
        result = calc_fee_scaglioni(self.svc, 150)
        assert result == pytest.approx(675.0, rel=1e-3)

    def test_no_brackets_returns_zero(self):
        svc = make_service(brackets=[])
        assert calc_fee_scaglioni(svc, 100) == 0.0


# ---------------------------------------------------------------------------
# Test: calcolo unitario
# ---------------------------------------------------------------------------

class TestCalcUnitario:
    def test_basic(self):
        svc = make_service(calc_type="unitario", unit_price=16.0)
        assert calc_fee_unitario(svc, 5) == pytest.approx(80.0)

    def test_zero_quantity(self):
        svc = make_service(calc_type="unitario", unit_price=16.0)
        assert calc_fee_unitario(svc, 0) == 0.0

    def test_none_quantity(self):
        svc = make_service(calc_type="unitario", unit_price=16.0)
        assert calc_fee_unitario(svc, None) == 0.0

    def test_fractional(self):
        # F24: 7 invii × 16€ = 112€
        svc = make_service(calc_type="unitario", unit_price=16.0)
        assert calc_fee_unitario(svc, 7) == pytest.approx(112.0)

    def test_autofatture(self):
        # 4 autofatture × 11€ = 44€ (da Excel T2)
        svc = make_service(calc_type="unitario", unit_price=11.0)
        assert calc_fee_unitario(svc, 4) == pytest.approx(44.0)


# ---------------------------------------------------------------------------
# Test: calcolo minimo percentuale (Visto di conformità IVA)
# ---------------------------------------------------------------------------

class TestCalcMinimoPercentuale:
    def setup_method(self):
        self.svc = make_service(
            calc_type="minimo_percentuale",
            percent_fee=0.02,   # 2%
            min_fee=155.0,
        )

    def test_percent_maggiore_del_minimo(self):
        # 2% di 10000 = 200 > 155 → 200
        result = calc_fee_minimo_percentuale(self.svc, 10000)
        assert result == pytest.approx(200.0)

    def test_minimo_garantito_applicato(self):
        # 2% di 5000 = 100 < 155 → 155
        result = calc_fee_minimo_percentuale(self.svc, 5000)
        assert result == pytest.approx(155.0)

    def test_base_zero_returns_zero(self):
        assert calc_fee_minimo_percentuale(self.svc, 0) == 0.0

    def test_base_none_returns_zero(self):
        assert calc_fee_minimo_percentuale(self.svc, None) == 0.0


# ---------------------------------------------------------------------------
# Test: dispatcher principale calc_quarterly_fee
# ---------------------------------------------------------------------------

class TestCalcQuarterlyFee:
    def test_dispatches_scaglioni(self):
        svc = make_service(calc_type="scaglioni", brackets=[
            make_bracket(1, 600, 2700),
        ])
        result = calc_quarterly_fee(svc, 100)
        assert result == pytest.approx(675.0, rel=1e-3)

    def test_dispatches_unitario(self):
        svc = make_service(calc_type="unitario", unit_price=16.0)
        assert calc_quarterly_fee(svc, 5) == pytest.approx(80.0)

    def test_dispatches_forfait(self):
        svc = make_service(calc_type="forfait", unit_price=115.0)
        assert calc_quarterly_fee(svc, 1) == pytest.approx(115.0)

    def test_none_driver_returns_zero(self):
        svc = make_service(calc_type="unitario", unit_price=100.0)
        assert calc_quarterly_fee(svc, None) == 0.0

    def test_unknown_calc_type_returns_zero(self):
        svc = make_service(calc_type="unknown")
        assert calc_quarterly_fee(svc, 10) == 0.0


# ---------------------------------------------------------------------------
# Test: validazione cliente
# ---------------------------------------------------------------------------

class TestValidateClient:
    def _valid(self):
        return {
            "client_code": "CLI001",
            "name": "Carpenteria Mada SRL",
            "client_type": "società di capitali",
        }

    def test_valid_client_no_errors(self):
        assert validate_client(self._valid()) == []

    def test_missing_name(self):
        data = self._valid()
        data["name"] = ""
        errors = validate_client(data)
        assert any("denominazione" in e.lower() for e in errors)

    def test_missing_code(self):
        data = self._valid()
        data["client_code"] = ""
        errors = validate_client(data)
        assert any("codice" in e.lower() for e in errors)

    def test_missing_type(self):
        data = self._valid()
        data["client_type"] = ""
        errors = validate_client(data)
        assert any("tipologia" in e.lower() for e in errors)

    def test_invalid_cf_length(self):
        data = self._valid()
        data["tax_code"] = "ABC123"  # né 11 né 16
        errors = validate_client(data)
        assert any("fiscale" in e.lower() for e in errors)

    def test_valid_cf_16(self):
        data = self._valid()
        data["tax_code"] = "RSSMRA80A01H501Z"
        assert validate_client(data) == []

    def test_valid_piva_11(self):
        data = self._valid()
        data["vat_number"] = "12345678901"
        assert validate_client(data) == []

    def test_invalid_piva_length(self):
        data = self._valid()
        data["vat_number"] = "1234"
        errors = validate_client(data)
        assert any("iva" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# Test: utilità
# ---------------------------------------------------------------------------

class TestUtils:
    def test_fmt_currency_positive(self):
        assert fmt_currency(3827.25) == "€ 3.827,25"

    def test_fmt_currency_zero(self):
        assert "0" in fmt_currency(0)

    def test_fmt_currency_none(self):
        assert fmt_currency(None) == "—"

    def test_pct_change_positive(self):
        assert pct_change(1000, 1100) == pytest.approx(10.0)

    def test_pct_change_negative(self):
        assert pct_change(1000, 900) == pytest.approx(-10.0)

    def test_pct_change_zero_old(self):
        assert pct_change(0, 100) is None

    def test_pct_change_unchanged(self):
        assert pct_change(1000, 1000) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Test: coerenza Excel per caso reale
# ---------------------------------------------------------------------------

class TestExcelCoherence:
    """Verifica che i calcoli replicano esattamente i valori del file Excel."""

    def test_contabilita_ordinaria_t1(self):
        """
        Excel: T1 = 404 registrazioni → scaglione 601-2000 → 3827.25/4 = 956.8125
        """
        svc = make_service(
            calc_type="scaglioni",
            marginal_rate=1.5,
            brackets=[
                make_bracket(1, 600, 2700),
                make_bracket(601, 2000, 3827.25),
                make_bracket(2001, 6000, 5472.97),
                make_bracket(6001, None, 5472.97),
            ],
        )
        result = calc_fee_scaglioni(svc, 404)
        assert result == pytest.approx(956.8125, rel=1e-3)

    def test_f24_telematico_t3(self):
        """Excel: T3 = 7 invii × 16€ = 112€"""
        svc = make_service(calc_type="unitario", unit_price=16.0)
        assert calc_fee_unitario(svc, 7) == pytest.approx(112.0)

    def test_situazioni_contabili_t2(self):
        """Excel: T2 = 1 situazione × 115€ = 115€"""
        svc = make_service(calc_type="unitario", unit_price=115.0)
        assert calc_fee_unitario(svc, 1) == pytest.approx(115.0)

    def test_redditi_sc_t4(self):
        """
        Excel: T4 volume d'affari = 526271.53 → scaglione 300001-600000 → 1112/4 = 278
        (inserito direttamente in T4, non annualizzato perché driver annuale)
        """
        svc = make_service(
            calc_type="scaglioni",
            marginal_rate=0.15,
            brackets=[
                make_bracket(0, 150000, 522),
                make_bracket(150001, 300000, 743),
                make_bracket(300001, 600000, 1112),
                make_bracket(600001, 900000, 1480),
                make_bracket(900001, None, 1480),
            ],
        )
        # Nel foglio Excel il volume d'affari è annuale inserito in T4
        # Il driver trimestrale = 526271.53 / 4 per coerenza con logica ×4
        result = calc_fee_scaglioni(svc, 526271.53 / 4)
        assert result == pytest.approx(1112 / 4, rel=1e-2)
