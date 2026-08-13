"""Signal-Definitionen fuer die drei Handelsstrategien.

Drei Strategien:
1. BreakoutStrategy: Long/Short bei Ausbruch ueber/unter N-Kerzen-Range (Donchian-Channel)
2. BuyAndHoldStrategy: Einmal Long, dann fuer immer halten
3. RandomStrategy: Zufaellige Trades als statistische Vergleichsbasis
"""

import random


class BreakoutStrategy:
    """Donchian-Channel-Breakout-Strategie (stateless - alle Methoden sind Klassenmethoden).

    Long wenn Close > hoechstes Hoch der letzten N Kerzen.
    Short wenn Close < tiefstes Tief der letzten N Kerzen.

    Wichtig: Das Signal nutzt NUR Daten aus der VERGANGENHEIT.
    candles[-1] ist die aktuelle Kerze, deren Close geprueft wird.
    candles[-(n+1):-1] sind die N Vergleichskerzen davor.
    """

    @staticmethod
    def signal(candles: list[dict], n: int) -> str | None:
        """Berechnet das Handelssignal basierend auf dem Kerzenhistorie.

        Args:
            candles: Liste von OHLCV-Kerzen (älteste zuerst, neueste zuletzt)
            n: Anzahl der Vergleichskerzen fuer die Breakout-Berechnung

        Returns:
            "long", "short" oder None
        """
        # Mindestens N+1 Kerzen benoetigt (N fuer Lookback + 1 aktuelle)
        if len(candles) < n + 1:
            return None

        # Lookback: die N Kerzen VOR der aktuellen (kein Look-ahead!)
        lookback = candles[-(n + 1):-1]
        aktuelle = candles[-1]

        hoechstes_hoch = max(k["high"] for k in lookback)
        tiefstes_tief  = min(k["low"]  for k in lookback)
        close          = aktuelle["close"]

        if close > hoechstes_hoch:
            return "long"
        elif close < tiefstes_tief:
            return "short"
        return None


class BuyAndHoldStrategy:
    """Kauf-und-Halte-Strategie als einfachste Vergleichsbasis.

    Gibt einmalig 'long' zurueck und dann fuer immer None.
    Repraesentiert den Marktdurchschnitt ohne aktives Trading.
    """

    def __init__(self):
        # Merkt sich ob bereits gekauft wurde
        self._hat_gekauft = False

    def signal(self, candles: list[dict]) -> str | None:
        """Gibt beim ersten Aufruf 'long' zurueck, danach immer None."""
        if not self._hat_gekauft:
            self._hat_gekauft = True
            return "long"
        return None


class RandomStrategy:
    """Zufaellige Handelssignale als statistische Vergleichsbasis.

    Handelt mit einer einstellbaren Wahrscheinlichkeit pro Kerze.
    Richtung (Long/Short) ist immer 50/50.

    Repraesentiert die Erwartung eines zufalligen Traders.
    Wenn die Breakout-Strategie schlechter als Zufall abschneidet,
    ist sie nicht nutzbar.
    """

    def __init__(self, seed: int | None = None):
        # Eigener Zufallsgenerator fuer Reproduzierbarkeit
        self._rng = random.Random(seed)

    def signal(self, candles: list[dict], trade_wahrscheinlichkeit: float = 0.01) -> str | None:
        """Gibt mit gegebener Wahrscheinlichkeit ein zufaelliges Signal zurueck.

        Args:
            candles: Kerzenhistorie (wird hier nicht ausgewertet)
            trade_wahrscheinlichkeit: 0.0 bis 1.0, wie oft ein Trade ausgefuehrt wird

        Returns:
            "long", "short" oder None
        """
        if self._rng.random() < trade_wahrscheinlichkeit:
            # Richtung ist 50/50
            return "long" if self._rng.random() < 0.5 else "short"
        return None
