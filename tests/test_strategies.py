"""Tests fuer Handelssignale der drei Strategien."""

import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from strategies import BreakoutStrategy, BuyAndHoldStrategy, RandomStrategy, AlwaysLongStrategy


def _kerze(open_p, high, low, close, zeit="2026-08-01T00:00:00Z"):
    """Hilfskerze fuer Tests."""
    return {"open": open_p, "high": high, "low": low, "close": close, "zeit": zeit}


class TestBreakout:
    def test_long_signal_bei_breakout_ueber_highs(self):
        """Long wenn Close > hoechstes Hoch der letzten N Kerzen."""
        kerzen = [
            _kerze(99, 100, 98, 99),
            _kerze(100, 102, 99, 101),
            _kerze(100, 101, 99, 100),
            # Aktuelle Kerze: Close 103 > 102 -> Long
            _kerze(101, 103, 100, 103),
        ]
        signal = BreakoutStrategy.signal(kerzen, n=3)
        assert signal == "long"

    def test_short_signal_bei_breakout_unter_lows(self):
        """Short wenn Close < tiefstes Tief der letzten N Kerzen."""
        kerzen = [
            _kerze(100, 102, 98, 100),
            _kerze(99, 101, 97, 99),
            _kerze(98, 100, 96, 98),
            # Aktuelle Kerze: Close 95 < 96 -> Short
            _kerze(97, 98, 94, 95),
        ]
        signal = BreakoutStrategy.signal(kerzen, n=3)
        assert signal == "short"

    def test_kein_signal_bei_seitwaertsbewegung(self):
        """Kein Signal wenn Close innerhalb der Range bleibt."""
        kerzen = [
            _kerze(100, 102, 98, 100),
            _kerze(100, 101, 99, 100),
            _kerze(100, 101, 99, 100),
            _kerze(100, 101, 99, 100),
        ]
        signal = BreakoutStrategy.signal(kerzen, n=3)
        assert signal is None

    def test_nicht_genug_kerzen_kein_signal(self):
        """Kein Signal wenn weniger als N+1 Kerzen vorhanden."""
        kerzen = [_kerze(100, 102, 98, 100)]
        signal = BreakoutStrategy.signal(kerzen, n=3)
        assert signal is None

    def test_genau_n_plus_1_kerzen_reichen(self):
        """N+1 Kerzen sind genug fuer ein Signal."""
        kerzen = [
            _kerze(99, 100, 98, 99),
            _kerze(100, 102, 99, 101),
            _kerze(100, 101, 99, 100),
            # Aktuelle Kerze: Close 103 > 102 -> Long
            _kerze(101, 103, 100, 103),
        ]
        signal = BreakoutStrategy.signal(kerzen, n=3)
        assert signal == "long"

    def test_kein_lookahead_durch_aktuelle_kerze(self):
        """Das High der aktuellen Kerze darf NICHT in die Berechnung einfliessen."""
        kerzen = [
            _kerze(99, 100, 98, 99),
            _kerze(100, 102, 99, 101),
            _kerze(100, 101, 99, 100),
            # Aktuelle Kerze hat High=110, aber das zaehlt nicht fuer die Range
            # Close=103 > 102 (hoechstes Hoch der VORHERIGEN 3) -> Long
            _kerze(101, 110, 100, 103),
        ]
        signal = BreakoutStrategy.signal(kerzen, n=3)
        assert signal == "long"


class TestBuyAndHold:
    def test_erstes_signal_ist_long(self):
        """Buy-and-Hold gibt beim ersten Aufruf 'long' zurueck."""
        strat = BuyAndHoldStrategy()
        kerzen = [_kerze(100, 101, 99, 100)]
        assert strat.signal(kerzen) == "long"

    def test_danach_kein_signal(self):
        """Nach dem ersten Long kein weiteres Signal."""
        strat = BuyAndHoldStrategy()
        kerzen = [_kerze(100, 101, 99, 100)]
        strat.signal(kerzen)  # Erstes Signal konsumieren
        assert strat.signal(kerzen) is None
        assert strat.signal(kerzen) is None  # Auch beim dritten Aufruf None

    def test_jede_instanz_unabhaengig(self):
        """Zwei Instanzen sind unabhaengig voneinander."""
        strat1 = BuyAndHoldStrategy()
        strat2 = BuyAndHoldStrategy()
        kerzen = [_kerze(100, 101, 99, 100)]
        strat1.signal(kerzen)  # strat1 hat gekauft
        # strat2 hat noch nicht gekauft
        assert strat2.signal(kerzen) == "long"


class TestRandom:
    def test_gibt_nur_gueltige_signale_zurueck(self):
        """Zufallsstrategie gibt nur 'long', 'short' oder None zurueck."""
        strat = RandomStrategy(seed=42)
        kerzen = [_kerze(100, 101, 99, 100)]
        ergebnisse = set()
        for _ in range(1000):
            s = strat.signal(kerzen, trade_wahrscheinlichkeit=0.5)
            ergebnisse.add(s)
        assert ergebnisse <= {"long", "short", None}

    def test_bei_50_prozent_alle_drei_werte(self):
        """Bei 50% Wahrscheinlichkeit sollten alle drei Werte vorkommen."""
        strat = RandomStrategy(seed=42)
        kerzen = [_kerze(100, 101, 99, 100)]
        ergebnisse = set()
        for _ in range(1000):
            s = strat.signal(kerzen, trade_wahrscheinlichkeit=0.5)
            ergebnisse.add(s)
        assert len(ergebnisse) == 3

    def test_deterministisch_mit_seed(self):
        """Gleicher Seed ergibt gleiche Signalfolge."""
        strat1 = RandomStrategy(seed=123)
        strat2 = RandomStrategy(seed=123)
        kerzen = [_kerze(100, 101, 99, 100)]
        for _ in range(100):
            s1 = strat1.signal(kerzen, trade_wahrscheinlichkeit=0.5)
            s2 = strat2.signal(kerzen, trade_wahrscheinlichkeit=0.5)
            assert s1 == s2

    def test_wahrscheinlichkeit_null_gibt_nie_signal(self):
        """Bei 0% Wahrscheinlichkeit niemals ein Signal."""
        strat = RandomStrategy(seed=42)
        kerzen = [_kerze(100, 101, 99, 100)]
        for _ in range(100):
            assert strat.signal(kerzen, trade_wahrscheinlichkeit=0.0) is None


class TestAlwaysLong:
    def test_long_bei_normalen_marktbedingungen(self):
        """Gibt 'long' wenn weniger als 7 von 10 Kerzen rot sind."""
        kerzen = [_kerze(100, 101, 99, 101)] * 15  # alle gruen
        assert AlwaysLongStrategy.signal(kerzen) == "long"

    def test_kein_entry_bei_bearish_markt(self):
        """Gibt None wenn >= 7 von 10 Kerzen rot sind (rote am Ende)."""
        gruene = [_kerze(100, 102, 99, 101)] * 5
        rote = [_kerze(101, 102, 99, 100)] * 8    # close < open = rot, am Ende
        kerzen = gruene + rote
        assert AlwaysLongStrategy.signal(kerzen) is None

    def test_zu_wenig_daten_ergibt_long(self):
        """Gibt 'long' wenn weniger als 10 Kerzen vorhanden."""
        kerzen = [_kerze(101, 102, 99, 100)] * 5  # alles rot, aber nur 5 Kerzen
        assert AlwaysLongStrategy.signal(kerzen) == "long"

    def test_grenzfall_genau_7_rote(self):
        """Genau 7 rote von 10 = kein Entry."""
        rote = [_kerze(101, 102, 99, 100)] * 7
        gruene = [_kerze(100, 102, 99, 101)] * 3
        kerzen = rote + gruene
        assert AlwaysLongStrategy.signal(kerzen) is None

    def test_grenzfall_nur_6_rote(self):
        """Nur 6 rote von 10 = Long erlaubt."""
        rote = [_kerze(101, 102, 99, 100)] * 6
        gruene = [_kerze(100, 102, 99, 101)] * 4
        kerzen = rote + gruene
        assert AlwaysLongStrategy.signal(kerzen) == "long"

    def test_kein_short_signal(self):
        """AlwaysLong gibt niemals 'short' zurueck."""
        kerzen = [_kerze(100, 101, 99, 101)] * 20
        ergebnis = AlwaysLongStrategy.signal(kerzen)
        assert ergebnis != "short"
