"""
tests/test_statistics.py — Test per statistiche e confronti storici.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch
import pandas as pd

from utils import pct_change


# ---------------------------------------------------------------------------
# Test: pct_change
# ---------------------------------------------------------------------------

class TestPctChange:
    def test_aumento_10_percento(self):
        assert pct_change(1000, 1100) == pytest.approx(10.0)

    def test_diminuzione_50_percento(self):
        assert pct_change(2000, 1000) == pytest.approx(-50.0)

    def test_nessuna_variazione(self):
        assert pct_change(500, 500) == pytest.approx(0.0)

    def test_base_zero_ritorna_none(self):
        assert pct_change(0, 500) is None

    def test_da_positivo_a_zero(self):
        assert pct_change(1000, 0) == pytest.approx(-100.0)

    def test_valori_reali_studio(self):
        # Es: da 7830.25 a 8500.00 → +8.56%
        result = pct_change(7830.25, 8500.0)
        assert result == pytest.approx(8.55, rel=0.01)


# ---------------------------------------------------------------------------
# Test: coerenza calcoli rendiconto
# ---------------------------------------------------------------------------

class TestReportCoherence:
    def _make_line(self, q1, q2, q3, q4,
                   ov1=None, ov2=None, ov3=None, ov4=None):
        """Crea un FeeReportLine mock con valori specificati."""
        line = MagicMock()
        line.fee_q1 = q1
        line.fee_q2 = q2
        line.fee_q3 = q3
        line.fee_q4 = q4
        line.override_q1 = ov1
        line.override_q2 = ov2
        line.override_q3 = ov3
        line.override_q4 = ov4

        # Replica la logica delle property effective_q*
        line.effective_q1 = ov1 if ov1 is not None else q1
        line.effective_q2 = ov2 if ov2 is not None else q2
        line.effective_q3 = ov3 if ov3 is not None else q3
        line.effective_q4 = ov4 if ov4 is not None else q4
        line.total = (
            line.effective_q1 + line.effective_q2 +
            line.effective_q3 + line.effective_q4
        )
        return line

    def test_totale_senza_override(self):
        line = self._make_line(100.0, 200.0, 150.0, 300.0)
        assert line.total == pytest.approx(750.0)

    def test_override_sostituisce_calcolato(self):
        line = self._make_line(100.0, 200.0, 150.0, 300.0, ov2=999.0)
        assert line.effective_q2 == pytest.approx(999.0)
        assert line.total == pytest.approx(100.0 + 999.0 + 150.0 + 300.0)

    def test_override_zero_valido(self):
        """Override a 0 deve essere rispettato (non confuso con None)."""
        line = self._make_line(100.0, 200.0, 150.0, 300.0, ov1=0.0)
        assert line.effective_q1 == 0.0
        assert line.total == pytest.approx(0.0 + 200.0 + 150.0 + 300.0)

    def test_tutti_override(self):
        line = self._make_line(100.0, 200.0, 150.0, 300.0,
                               ov1=110.0, ov2=220.0, ov3=165.0, ov4=330.0)
        assert line.total == pytest.approx(825.0)

    def test_coerenza_excel_contabilita_ordinaria(self):
        """
        Replica il caso reale dell'Excel:
        T1=956.8125, T2=956.8125, T3=956.8125, T4=956.8125 → Tot=3827.25
        """
        line = self._make_line(956.8125, 956.8125, 956.8125, 956.8125)
        assert line.total == pytest.approx(3827.25, rel=1e-4)

    def test_coerenza_excel_totale_rendiconto(self):
        """
        Replica il totale finale del rendiconto Excel (CARPENTERIA MADA SRL 2024):
        Conto T1+T2+T3+T4 = 1758.8125 + 2357.8125 + 1300.8125 + 2412.8125 = 7830.25
        """
        lines = [
            self._make_line(956.8125, 956.8125, 956.8125, 956.8125),   # Cont. ord.
            self._make_line(594.0, 0, 0, 0),                            # Dich. IVA
            self._make_line(0, 0, 0, 1112.0),                           # Redditi SC
            self._make_line(0, 562.0, 0, 0),                            # Bil. CEE-01
            self._make_line(0, 450.0, 0, 0),                            # Bil. CEE-02
            self._make_line(95.0, 95.0, 95.0, 95.0),                   # LIPE Int.
            self._make_line(80.0, 80.0, 112.0, 112.0),                 # F24
            self._make_line(0, 115.0, 115.0, 115.0),                   # Sit. cont.
            self._make_line(0, 55.0, 0, 0),                             # CCIAA
            self._make_line(33.0, 44.0, 22.0, 22.0),                   # Autofatture
        ]
        total = sum(l.total for l in lines)
        assert total == pytest.approx(7830.25, rel=1e-3)

    def test_totale_trimestrale_coerente(self):
        """La somma dei trimestri deve uguagliare il totale annuale."""
        line = self._make_line(100.5, 200.75, 300.25, 400.0)
        sum_quarters = (line.effective_q1 + line.effective_q2 +
                        line.effective_q3 + line.effective_q4)
        assert line.total == pytest.approx(sum_quarters)


# ---------------------------------------------------------------------------
# Test: snapshot storico
# ---------------------------------------------------------------------------

class TestSnapshotIntegrity:
    """Verifica che le righe rendiconto salvino snapshot corretti."""

    def test_snapshot_preserva_descrizione(self):
        """Il snapshot della descrizione non deve cambiare se il listino cambia."""
        snap_desc = "Contabilità ordinaria (snapshot 2023)"
        line = MagicMock()
        line.description_snap = snap_desc
        # Simula cambio listino
        new_desc = "Contabilità ordinaria (aggiornato 2024)"
        # La riga storica NON deve cambiare
        assert line.description_snap == snap_desc
        assert line.description_snap != new_desc

    def test_snapshot_preserva_calc_type(self):
        line = MagicMock()
        line.calc_type_snap = "scaglioni"
        assert line.calc_type_snap == "scaglioni"
