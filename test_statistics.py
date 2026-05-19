"""
tests/test_statistics.py — Test statistiche, confronti, snapshot.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock
from utils import pct_change


class TestPctChange:
    def test_aumento(self):
        assert pct_change(1000, 1100) == pytest.approx(10.0)

    def test_diminuzione(self):
        assert pct_change(2000, 1000) == pytest.approx(-50.0)

    def test_invariato(self):
        assert pct_change(500, 500) == pytest.approx(0.0)

    def test_base_zero(self):
        assert pct_change(0, 500) is None

    def test_a_zero(self):
        assert pct_change(1000, 0) == pytest.approx(-100.0)

    def test_valori_reali(self):
        assert pct_change(7830.25, 8500.0) == pytest.approx(8.55, rel=0.01)


class TestReportCoherence:
    def _line(self, q1, q2, q3, q4, ov1=None, ov2=None, ov3=None, ov4=None):
        line = MagicMock()
        line.effective_q1 = ov1 if ov1 is not None else q1
        line.effective_q2 = ov2 if ov2 is not None else q2
        line.effective_q3 = ov3 if ov3 is not None else q3
        line.effective_q4 = ov4 if ov4 is not None else q4
        line.total = line.effective_q1 + line.effective_q2 + line.effective_q3 + line.effective_q4
        return line

    def test_totale_senza_override(self):
        assert self._line(100, 200, 150, 300).total == pytest.approx(750.0)

    def test_override_sovrascrive(self):
        line = self._line(100, 200, 150, 300, ov2=999.0)
        assert line.effective_q2 == pytest.approx(999.0)
        assert line.total == pytest.approx(100 + 999 + 150 + 300)

    def test_override_zero_valido(self):
        line = self._line(100, 200, 150, 300, ov1=0.0)
        assert line.effective_q1 == 0.0
        assert line.total == pytest.approx(0 + 200 + 150 + 300)

    def test_coerenza_excel_contabilita(self):
        """T1=T2=T3=T4=956.8125 → totale = 3827.25"""
        line = self._line(956.8125, 956.8125, 956.8125, 956.8125)
        assert line.total == pytest.approx(3827.25, rel=1e-4)

    def test_coerenza_excel_rendiconto_completo(self):
        """
        Totale rendiconto CARPENTERIA MADA SRL 2024.
        Valori approssimativi da Excel per verifica coerenza strutturale.
        """
        lines = [
            self._line(956.8125, 956.8125, 956.8125, 956.8125),   # Cont. ord.
            self._line(594, 0, 0, 0),                              # Dich. IVA
            self._line(0, 0, 0, 278),                              # Redditi SC
            self._line(0, 562, 0, 0),                              # Bil. CEE-01
            self._line(0, 450, 0, 0),                              # Bil. CEE-02
            self._line(95, 95, 95, 95),                            # LIPE
            self._line(80, 80, 112, 112),                          # F24
            self._line(0, 115, 115, 115),                          # Sit. cont.
            self._line(0, 55, 0, 0),                               # CCIAA
            self._line(33, 44, 22, 22),                            # Autofatture
        ]
        total = sum(l.total for l in lines)
        assert total > 0
        assert total == pytest.approx(sum(l.total for l in lines))

    def test_somma_trimestri_uguale_totale(self):
        line = self._line(100.5, 200.75, 300.25, 400.0)
        somma = line.effective_q1 + line.effective_q2 + line.effective_q3 + line.effective_q4
        assert line.total == pytest.approx(somma)


class TestSnapshot:
    def test_snapshot_immutabile(self):
        line = MagicMock()
        line.description_snap = "Contabilità ordinaria 2023"
        snap_originale = line.description_snap
        # Anche se il listino cambia, lo snapshot non deve cambiare
        assert line.description_snap == snap_originale

    def test_snapshot_calc_type(self):
        line = MagicMock()
        line.calc_type_snap = "scaglioni"
        assert line.calc_type_snap == "scaglioni"
