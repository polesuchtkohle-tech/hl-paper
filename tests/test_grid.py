"""Tests fuer Parameter-Grid-Generierung und Validierung."""

import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from grid import generate_grid, validate_combination, konto_id_from_params, N_WERTE, TP_WERTE, SL_WERTE, HEBEL_WERTE


def test_volles_grid_maximal_kombinationen():
    """Nach Filterung ungültiger Kombinationen weniger als Rohdaten, aber nie 0.

    Rohdaten-Maximum ergibt sich aus dem aktuellen Grid (dynamisch).
    """
    max_roh = len(N_WERTE) * len(TP_WERTE) * len(SL_WERTE) * len(HEBEL_WERTE)
    grid = generate_grid(testmodus=False)
    breakout_konten = [k for k in grid if k["strategie"] == "breakout"]
    assert len(breakout_konten) <= max_roh
    assert len(breakout_konten) > 0


def test_testmodus_hat_genau_6_konten():
    """Im Testmodus: N=20, TP 1.0/2.0, SL 0.5, Hebel 1/5/25 = 6 Konten."""
    grid = generate_grid(testmodus=True)
    breakout_konten = [k for k in grid if k["strategie"] == "breakout"]
    assert len(breakout_konten) == 6
    for konto in breakout_konten:
        assert konto["n"] == 20
        assert konto["tp"] in (1.0, 2.0)
        assert konto["sl"] == 0.5
        assert konto["hebel"] in (1, 5, 25)


def test_mechanisch_unmoeglich_wird_ausgeschlossen():
    """Hebel 25 mit SL 5.0% ist mechanisch unmöglich (Liq bei ~3.6%)."""
    # Liquidationsdistanz = 1/25 * 0.9 * 100 = 3.6%
    # SL 5.0% > 3.6% -> mechanisch unmoeglich -> wird nicht simuliert
    gueltig, grund = validate_combination(n=20, tp=1.0, sl=5.0, hebel=25)
    assert gueltig is False
    assert "mechanisch unmoeglich" in grund


def test_gueltige_kombination_wird_akzeptiert():
    """Hebel 1 mit SL 3.0% ist immer gültig (Liq bei 90%)."""
    gueltig, grund = validate_combination(n=20, tp=1.0, sl=3.0, hebel=1)
    assert gueltig is True


def test_kostendominiert_wird_markiert_aber_simuliert():
    """TP < 3x Rundenkosten wird simuliert, aber als kostendominiert markiert.

    Rundenkosten = 2 * (0.045% + 0.01%) = 0.11%
    3x Rundenkosten = 0.33%
    TP 0.3% < 0.33% -> kostendominiert
    """
    gueltig, grund = validate_combination(n=20, tp=0.3, sl=0.5, hebel=1)
    assert gueltig is True  # Wird trotzdem simuliert
    assert "kostendominiert" in grund


def test_normales_tp_hat_keine_warnung():
    """TP 1.0% bei 0.11% Rundenkosten ist klar ueber der Schwelle."""
    gueltig, grund = validate_combination(n=20, tp=1.0, sl=0.5, hebel=1)
    assert gueltig is True
    assert grund == ""


def test_konto_id_format_breakout():
    """Breakout-Konto-ID hat das Format brk_N_tp_sl_hebel."""
    kid = konto_id_from_params(20, 1.0, 0.5, 5)
    assert kid == "brk_20_1.0_0.5_5"


def test_vergleichsstrategien_im_grid():
    """Buy-and-Hold und Zufall muessen im vollen Grid enthalten sein."""
    grid = generate_grid(testmodus=False)
    strategien = {k["strategie"] for k in grid}
    assert "buy_and_hold" in strategien
    assert "zufall" in strategien


def test_startkapital_ist_100():
    """Jedes Konto startet mit 100 USDC."""
    grid = generate_grid(testmodus=True)
    for konto in grid:
        assert konto["startkapital"] == 100.0


def test_kein_konto_mit_negativem_kontostand():
    """Alle Konten starten mit positivem Kapital."""
    grid = generate_grid(testmodus=False)
    for konto in grid:
        assert konto["startkapital"] > 0
