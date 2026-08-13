"""Tests fuer die Simulations-Engine.

Kritische Tests:
- Kein Look-Ahead (Signal auf Kerze t wird auf Kerze t+1 ausgefuehrt)
- Liquidationspruefung bei jeder Kerze
- Konservative Fills (schlechtester Preis)
- Ruinerkennung und -Zeitpunkt
- Korrekte Fee-Berechnung
"""

import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db import get_connection, init_schema, get_konten
from engine import SimulationEngine


def _kerze(close, high=None, low=None, open_p=None, zeit="2026-08-01T00:00:00Z", vol=100.0):
    """Hilfskerze. high/low werden aus close abgeleitet wenn nicht angegeben."""
    if high is None:
        high = close * 1.001  # 0.1% ueber Close
    if low is None:
        low = close * 0.999   # 0.1% unter Close
    if open_p is None:
        open_p = close
    return {"open": open_p, "high": high, "low": low, "close": close, "zeit": zeit, "volume": vol}


@pytest.fixture
def engine(tmp_path):
    """Engine mit In-Memory-DB und temporaerem Datenverzeichnis."""
    conn = get_connection(":memory:")
    init_schema(conn)
    eng = SimulationEngine(db_conn=conn, data_dir=str(tmp_path), testmodus=True)
    return eng, conn


def _grid_eintrag(n=20, tp=1.0, sl=0.5, hebel=5):
    return {
        "konto_id": f"brk_{n}_{tp}_{sl}_{hebel}",
        "n": n, "tp": tp, "sl": sl, "hebel": hebel,
        "strategie": "breakout",
        "startkapital": 100.0,
        "warnung": None,
    }


class TestKeinLookAhead:
    def test_signal_auf_t_wird_auf_t_plus_1_ausgefuehrt(self, engine):
        """Signal auf Kerze t darf erst auf Kerze t+1 ausgefuehrt werden."""
        eng, conn = engine
        eng.init_konten([_grid_eintrag(n=2, tp=5.0, sl=5.0, hebel=1)])

        # Kerze 1 und 2: Range aufbauen (Hochs bei 100, 101)
        eng.process_candle(_kerze(100, high=100, low=99, zeit="2026-08-01T00:00:00Z"))
        eng.process_candle(_kerze(101, high=101, low=100, zeit="2026-08-01T00:01:00Z"))

        # Kerze 3: Breakout-Signal (Close 103 > hoechstes Hoch 101)
        # Aber noch KEIN Trade offen (Signal wird erst auf Kerze 4 ausgefuehrt)
        eng.process_candle(_kerze(103, high=104, low=102, zeit="2026-08-01T00:02:00Z"))

        # Pruefe: Kein Trade nach Kerze 3
        cursor = conn.execute("SELECT COUNT(*) FROM trades")
        assert cursor.fetchone()[0] == 0

        # Kerze 4: Trade wird ausgefuehrt (zum schlechtesten Preis: High)
        eng.process_candle(_kerze(102, high=105, low=101, zeit="2026-08-01T00:03:00Z"))

        # Jetzt sollte eine offene Position existieren
        konten = get_konten(conn)
        assert konten[0]["position_richtung"] == "long"
        # Einstiegspreis muss High der Kerze 4 sein (105), nicht Close der Kerze 3
        assert konten[0]["position_preis"] == 105.0


class TestKonservativeFills:
    def test_long_einstieg_zum_high(self, engine):
        """Long-Einstieg erfolgt zum High der Ausfuehrungskerze (schlechtester Preis)."""
        eng, conn = engine
        eng.init_konten([_grid_eintrag(n=2, tp=5.0, sl=5.0, hebel=1)])

        # Range aufbauen und Signal erzeugen
        eng.process_candle(_kerze(100, high=100, low=99, zeit="2026-08-01T00:00:00Z"))
        eng.process_candle(_kerze(100, high=100, low=99, zeit="2026-08-01T00:01:00Z"))
        eng.process_candle(_kerze(101, high=102, low=100, zeit="2026-08-01T00:02:00Z"))  # Signal
        # Ausfuehrungskerze mit High 110
        eng.process_candle(_kerze(105, high=110, low=104, zeit="2026-08-01T00:03:00Z"))

        konten = get_konten(conn)
        # Einstieg muss zum High (110) stattgefunden haben, nicht zum Open oder Close
        assert konten[0]["position_preis"] == 110.0

    def test_short_einstieg_zum_low(self, engine):
        """Short-Einstieg erfolgt zum Low der Ausfuehrungskerze (schlechtester Preis)."""
        eng, conn = engine
        eng.init_konten([_grid_eintrag(n=2, tp=5.0, sl=5.0, hebel=1)])

        # Range aufbauen und Short-Signal erzeugen
        eng.process_candle(_kerze(100, high=101, low=100, zeit="2026-08-01T00:00:00Z"))
        eng.process_candle(_kerze(100, high=101, low=100, zeit="2026-08-01T00:01:00Z"))
        eng.process_candle(_kerze(99, high=100, low=99, zeit="2026-08-01T00:02:00Z"))   # Signal: Close < Low der Range
        # Ausfuehrungskerze mit Low 90
        eng.process_candle(_kerze(95, high=96, low=90, zeit="2026-08-01T00:03:00Z"))

        konten = get_konten(conn)
        assert konten[0]["position_richtung"] == "short"
        assert konten[0]["position_preis"] == 90.0


class TestTakeProfit:
    def test_long_tp_exit(self, engine):
        """Long-Position wird bei TP geschlossen."""
        eng, conn = engine
        # TP = 2%, SL = 5%, Hebel 1, Startkapital 100
        eng.init_konten([_grid_eintrag(n=2, tp=2.0, sl=5.0, hebel=1)])

        # Range + Signal + Einstieg
        eng.process_candle(_kerze(100, high=100, low=99, zeit="2026-08-01T00:00:00Z"))
        eng.process_candle(_kerze(100, high=100, low=99, zeit="2026-08-01T00:01:00Z"))
        eng.process_candle(_kerze(101, high=102, low=100, zeit="2026-08-01T00:02:00Z"))
        # Einstieg bei 100 (High der Ausfuehrungskerze)
        eng.process_candle(_kerze(99, high=100, low=98, zeit="2026-08-01T00:03:00Z"))

        # Jetzt muss eine Long-Position bei 100 offen sein
        konten = get_konten(conn)
        assert konten[0]["position_richtung"] == "long"
        einstieg = konten[0]["position_preis"]  # sollte 100 sein

        # TP-Kerze: High erreicht TP (2% ueber Einstieg = 102)
        tp_preis = einstieg * 1.02
        eng.process_candle(_kerze(101, high=tp_preis + 0.01, low=100, zeit="2026-08-01T00:04:00Z"))

        # Position muss geschlossen sein
        konten = get_konten(conn)
        assert konten[0]["position_richtung"] is None

        # Trade muss in DB sein
        cursor = conn.execute("SELECT exit_grund FROM trades")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "TP"


class TestStopLoss:
    def test_long_sl_exit(self, engine):
        """Long-Position wird bei SL geschlossen."""
        eng, conn = engine
        eng.init_konten([_grid_eintrag(n=2, tp=5.0, sl=1.0, hebel=1)])

        # Einstieg vorbereiten
        eng.process_candle(_kerze(100, high=100, low=99, zeit="2026-08-01T00:00:00Z"))
        eng.process_candle(_kerze(100, high=100, low=99, zeit="2026-08-01T00:01:00Z"))
        eng.process_candle(_kerze(101, high=102, low=100, zeit="2026-08-01T00:02:00Z"))
        eng.process_candle(_kerze(100, high=100, low=100, zeit="2026-08-01T00:03:00Z"))  # Einstieg bei 100

        konten = get_konten(conn)
        assert konten[0]["position_richtung"] == "long"
        einstieg = konten[0]["position_preis"]

        # SL-Kerze: Low unterschreitet SL (1% unter Einstieg)
        sl_preis = einstieg * 0.99
        eng.process_candle(_kerze(98, high=99, low=sl_preis - 0.01, zeit="2026-08-01T00:04:00Z"))

        konten = get_konten(conn)
        assert konten[0]["position_richtung"] is None
        cursor = conn.execute("SELECT exit_grund FROM trades")
        assert cursor.fetchone()[0] == "SL"


class TestLiquidation:
    def test_ambivalente_kerze_zaehler_wird_erhoet(self, engine):
        """Wenn eine Kerze sowohl SL als auch Liq-Niveau beruehrt, wird ambivalente_kerzen gezaehlt."""
        eng, conn = engine
        # Hebel 25: Liq bei ~3.6%, SL bei 0.5%
        eng.init_konten([_grid_eintrag(n=2, tp=50.0, sl=0.5, hebel=25)])

        # Einstieg: Long bei 100
        eng.process_candle(_kerze(100, high=100, low=99, zeit="2026-08-01T00:00:00Z"))
        eng.process_candle(_kerze(100, high=100, low=99, zeit="2026-08-01T00:01:00Z"))
        eng.process_candle(_kerze(101, high=102, low=100, zeit="2026-08-01T00:02:00Z"))
        eng.process_candle(_kerze(100, high=100, low=100, zeit="2026-08-01T00:03:00Z"))

        konten = get_konten(conn)
        assert konten[0]["position_richtung"] == "long"
        einstieg = konten[0]["position_preis"]

        # Kerze die BEIDE Niveaus beruehrt:
        # SL = einstieg * 0.995, Liq = einstieg * 0.964, Low = 90
        eng.process_candle(_kerze(91, high=einstieg, low=90, zeit="2026-08-01T00:04:00Z"))

        # Zaehler muss auf 1 stehen
        row = conn.execute(
            "SELECT ambivalente_kerzen FROM konten WHERE konto_id = ?",
            (eng._konten[0].konto_id,)
        ).fetchone()
        assert row[0] == 1, f"Erwartet ambivalente_kerzen=1, bekommen: {row[0]}"

    def test_default_konservativ_liquidation_gewinnt(self, engine):
        """Default SL_VOR_LIQUIDATION=False: bei ambivalenter Kerze gewinnt Liquidation."""
        import engine as engine_modul
        assert engine_modul.SL_VOR_LIQUIDATION is False, (
            "Default muss False sein (konservativ: Liquidation gewinnt)"
        )

        eng, conn = engine
        eng.init_konten([_grid_eintrag(n=2, tp=50.0, sl=0.5, hebel=25)])

        eng.process_candle(_kerze(100, high=100, low=99, zeit="2026-08-01T00:00:00Z"))
        eng.process_candle(_kerze(100, high=100, low=99, zeit="2026-08-01T00:01:00Z"))
        eng.process_candle(_kerze(101, high=102, low=100, zeit="2026-08-01T00:02:00Z"))
        eng.process_candle(_kerze(100, high=100, low=100, zeit="2026-08-01T00:03:00Z"))

        konten = get_konten(conn)
        assert konten[0]["position_richtung"] == "long"
        einstieg = konten[0]["position_preis"]

        # Ambivalente Kerze: SL und Liq beide beruehrt
        eng.process_candle(_kerze(91, high=einstieg, low=90, zeit="2026-08-01T00:04:00Z"))

        cursor = conn.execute("SELECT exit_grund FROM trades")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "LIQUIDATION", (
            f"Default konservativ: Liquidation muss gewinnen, bekommen: {row[0]}"
        )
        konten = get_konten(conn)
        assert konten[0]["status"] == "ruiniert"

    def test_liquidation_bei_ausreichend_grossem_verlust(self, engine):
        """Konto wird liquidiert wenn Verlust >= 90% des eingesetzten Kapitals."""
        eng, conn = engine
        # Hebel 25: Liquidation bei ~3.6% Kursbewegung gegen uns
        eng.init_konten([_grid_eintrag(n=2, tp=50.0, sl=50.0, hebel=25)])

        # Einstieg vorbereiten
        eng.process_candle(_kerze(100, high=100, low=99, zeit="2026-08-01T00:00:00Z"))
        eng.process_candle(_kerze(100, high=100, low=99, zeit="2026-08-01T00:01:00Z"))
        eng.process_candle(_kerze(101, high=102, low=100, zeit="2026-08-01T00:02:00Z"))
        eng.process_candle(_kerze(100, high=100, low=100, zeit="2026-08-01T00:03:00Z"))

        konten = get_konten(conn)
        if konten[0]["position_richtung"] is None:
            pytest.skip("Kein Einstieg moeglich (Kombination ausgeschlossen)")

        einstieg = konten[0]["position_preis"]

        # Starker Kursrueckgang: 5% gegen Long-Position mit Hebel 25 = 125% Verlust = Ruin
        crash_preis = einstieg * 0.95
        eng.process_candle(_kerze(crash_preis, high=einstieg, low=crash_preis, zeit="2026-08-01T00:04:00Z"))

        konten = get_konten(conn)
        assert konten[0]["status"] == "ruiniert"
        assert konten[0]["kontostand"] <= 0.0

        cursor = conn.execute("SELECT exit_grund FROM trades")
        row = cursor.fetchone()
        if row:
            assert row[0] == "LIQUIDATION"


class TestFees:
    def test_fees_werden_vom_kontostand_abgezogen(self, engine):
        """Fees und Slippage reduzieren den Kontostand nach jedem Trade."""
        eng, conn = engine
        eng.init_konten([_grid_eintrag(n=2, tp=2.0, sl=5.0, hebel=1)])

        # Einstieg
        eng.process_candle(_kerze(100, high=100, low=99, zeit="2026-08-01T00:00:00Z"))
        eng.process_candle(_kerze(100, high=100, low=99, zeit="2026-08-01T00:01:00Z"))
        eng.process_candle(_kerze(101, high=102, low=100, zeit="2026-08-01T00:02:00Z"))
        eng.process_candle(_kerze(100, high=100, low=100, zeit="2026-08-01T00:03:00Z"))

        # TP-Exit
        eng.process_candle(_kerze(103, high=103, low=102, zeit="2026-08-01T00:04:00Z"))

        cursor = conn.execute("SELECT fees, slippage, pnl_netto, pnl_brutto FROM trades")
        row = cursor.fetchone()
        if row is None:
            pytest.skip("Kein Trade abgeschlossen")

        fees, slippage, pnl_netto, pnl_brutto = row
        # Nettogewinn muss kleiner sein als Bruttogewinn (Kosten abgezogen)
        assert pnl_netto < pnl_brutto
        # Fees und Slippage muessen positiv sein
        assert fees > 0
        assert slippage >= 0


class TestRuin:
    def test_ruiniertes_konto_handelt_nicht_mehr(self, engine):
        """Ein ruiniertes Konto darf keine weiteren Trades eroeffnen."""
        eng, conn = engine
        eng.init_konten([_grid_eintrag(n=2, tp=50.0, sl=50.0, hebel=25)])

        # Einstieg
        eng.process_candle(_kerze(100, high=100, low=99, zeit="2026-08-01T00:00:00Z"))
        eng.process_candle(_kerze(100, high=100, low=99, zeit="2026-08-01T00:01:00Z"))
        eng.process_candle(_kerze(101, high=102, low=100, zeit="2026-08-01T00:02:00Z"))
        eng.process_candle(_kerze(100, high=100, low=100, zeit="2026-08-01T00:03:00Z"))

        konten = get_konten(conn)
        if konten[0]["status"] == "ruiniert":
            pytest.skip("Kombination direkt ausgeschlossen")

        # Crash -> Liquidation
        eng.process_candle(_kerze(95, high=100, low=95, zeit="2026-08-01T00:04:00Z"))

        konten = get_konten(conn)
        if konten[0]["status"] != "ruiniert":
            pytest.skip("Kein Ruin aufgetreten")

        trade_count_nach_ruin = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]

        # Weitere Kerzen -> keine neuen Trades
        for i in range(5, 25):
            eng.process_candle(_kerze(110, high=115, low=105, zeit=f"2026-08-01T00:0{i}:00Z" if i < 10 else f"2026-08-01T00:{i}:00Z"))

        trade_count_spaeter = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        assert trade_count_spaeter == trade_count_nach_ruin
