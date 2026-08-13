"""Simulations-Engine fuer Paper-Trading.

Verarbeitet jede neue 1m-Kerze und aktualisiert alle simulierten Konten:
- Breakout-Signale berechnen (kein Look-ahead)
- Trades eroeffnen und schliessen (konservative Fills)
- Liquidation pruefen bei jeder Kerze
- PnL und Fees berechnen
- Ergebnisse in SQLite speichern
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from db import (
    get_konten, insert_trade, insert_equity,
    update_konto_status, set_meta,
)
from strategies import BreakoutStrategy, BuyAndHoldStrategy, RandomStrategy, AlwaysLongStrategy

logger = logging.getLogger(__name__)

# --- Kostenparameter ---
TAKER_FEE = 0.00045   # 0.045%
SPREAD = 0.0001        # 0.01%
ORDER_KOSTEN = TAKER_FEE + SPREAD  # Kosten je Order (Ein- oder Ausstieg)

# Mindestordergroesse in USD
MIN_NOTIONAL = 10.0

# Wie oft Equity-Snapshots gespeichert werden (jede 15. Kerze = 15 Minuten)
EQUITY_INTERVALL = 15

# --- Reihenfolge-Annahme bei ambivalenten Kerzen ---
# Wenn eine 1m-Kerze sowohl SL- als auch Liquidationsniveau beruehrt,
# ist unbekannt welches Niveau zuerst erreicht wurde.
#
# False (Default, konservativ): Liquidation gewinnt.
#   Begruendung: Bei starken Gaps versagen Stops in der Praxis.
#   Projektgrundregel: "Bei Zweifel zuungunsten der Strategie."
#
# True (optimistisch): SL gewinnt.
#   Begruendung: SL liegt geometrisch naeher am Einstieg, also
#   muss der Kurs ihn zuerst beruehrt haben — sofern kein Gap.
SL_VOR_LIQUIDATION: bool = False


class Konto:
    """Repraesentiert ein simuliertes Handelskonto.

    Haelt den vollstaendigen Zustand: Kontostand, offene Position,
    Strategieobjekt und Kerzenhistorie.
    """

    def __init__(self, konto_data: dict):
        self.konto_id      = konto_data["konto_id"]
        self.n             = konto_data["n"]
        self.tp_pct        = konto_data["tp"] / 100.0   # Prozent -> Dezimal
        self.sl_pct        = konto_data["sl"] / 100.0
        self.hebel         = konto_data["hebel"]
        self.strategie     = konto_data["strategie"]
        self.kontostand    = konto_data["kontostand"]
        self.status        = konto_data["status"]        # "aktiv" oder "ruiniert"
        self.warnung       = konto_data.get("warnung")

        # Offene Position (None wenn keine)
        self.position_richtung: Optional[str] = konto_data.get("position_richtung")
        self.position_preis: Optional[float]  = konto_data.get("position_preis")
        self.position_zeit: Optional[str]     = konto_data.get("position_zeit")
        self.position_groesse: Optional[float] = konto_data.get("position_groesse")

        # Kerzenhistorie fuer Breakout-Signal
        self.kerzen_history: list[dict] = []

        # Strategieobjekte (stateful fuer Buy-and-Hold)
        if self.strategie == "buy_and_hold":
            self._strat = BuyAndHoldStrategy()
            # Wenn bereits eine Position offen ist, als "schon gekauft" markieren
            if self.position_richtung == "long":
                self._strat._hat_gekauft = True
        elif self.strategie == "zufall":
            self._strat = RandomStrategy()
        else:
            self._strat = None  # Breakout: stateless, kein Objekt noetig

        # Zaehler fuer Equity-Snapshots
        self._kerzen_seit_snapshot = 0

        # Pending-Signal: Richtung wenn Signal auf letzter Kerze, Trade kommt naechste Kerze
        self._pending_signal: Optional[str] = None

        # Zaehlt gesammelte Funding-Zahlungen fuer den aktuellen Trade
        self._funding_seit_einstieg: float = 0.0

        # Zaehlt Kerzen bei denen sowohl SL als auch Liq ausgeloest wurden.
        # Hoher Wert = 1m-Kerzen zu grob fuer diesen Hebel.
        self.ambivalente_kerzen: int = konto_data.get("ambivalente_kerzen", 0)

    @property
    def ist_ruiniert(self) -> bool:
        return self.status == "ruiniert"

    def liquidations_preis(self, richtung: str, einstieg: float) -> float:
        """Berechnet den Preis bei dem das Konto liquidiert wird.

        Liquidation wenn Verlust >= 90% des eingesetzten Kapitals.
        Eingesetztes Kapital = Positionsgroesse / Hebel.
        """
        # Liquidationsdistanz in Prozent des Einstiegspreises
        liq_distanz = 0.9 / self.hebel
        if richtung == "long":
            return einstieg * (1 - liq_distanz)
        else:  # short
            return einstieg * (1 + liq_distanz)


class SimulationEngine:
    """Verarbeitet Marktdaten und aktualisiert alle simulierten Konten.

    Haelt alle Konto-Objekte im Speicher und schreibt Zustandsaenderungen
    in die SQLite-Datenbank.
    """

    def __init__(self, db_conn, data_dir: str, testmodus: bool = False):
        self._conn = db_conn
        self._data_dir = data_dir
        self._testmodus = testmodus
        self._konten: list[Konto] = []
        self._kerzen_zaehler = 0

    def init_konten(self, grid: list[dict]) -> None:
        """Laedt oder erstellt alle Konten aus dem Grid.

        Bestehende Konten (aus DB geladen) werden fortgefuehrt.
        Neue Konten werden mit 100 USDC Startkapital angelegt.
        """
        # Bestehende Konten aus DB laden
        bestehende = {k["konto_id"]: k for k in get_konten(self._conn)}

        konten_zu_erstellen = []
        for eintrag in grid:
            kid = eintrag["konto_id"]
            if kid in bestehende:
                # Konto aus DB wiederherstellen
                konto_data = dict(bestehende[kid])
                konto_data.update({
                    "tp": eintrag["tp"],
                    "sl": eintrag["sl"],
                    "n": eintrag["n"],
                    "hebel": eintrag["hebel"],
                    "strategie": eintrag["strategie"],
                })
                self._konten.append(Konto(konto_data))
            else:
                # Neues Konto anlegen
                konto_data = {
                    "konto_id": kid,
                    "n": eintrag["n"],
                    "tp": eintrag["tp"],
                    "sl": eintrag["sl"],
                    "hebel": eintrag["hebel"],
                    "strategie": eintrag["strategie"],
                    "kontostand": eintrag["startkapital"],
                    "status": "aktiv",
                    "warnung": eintrag.get("warnung"),
                    "position_richtung": None,
                    "position_preis": None,
                    "position_zeit": None,
                    "position_groesse": None,
                }
                konten_zu_erstellen.append(konto_data)
                self._konten.append(Konto(konto_data))

        # Neue Konten in DB speichern
        for kd in konten_zu_erstellen:
            self._conn.execute(
                "INSERT OR IGNORE INTO konten "
                "(konto_id, n, tp, sl, hebel, status, kontostand, strategie, warnung) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kd["konto_id"], kd["n"], kd["tp"], kd["sl"], kd["hebel"],
                 kd["status"], kd["kontostand"], kd["strategie"], kd.get("warnung"))
            )
        self._conn.commit()

        # Meta-Information aktualisieren
        set_meta(
            self._conn,
            anzahl_varianten=len(grid),
            startzeitpunkt=datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

        logger.info("Engine initialisiert: %d Konten geladen.", len(self._konten))

    def process_candle(self, candle: dict) -> None:
        """Verarbeitet eine neue 1m-Kerze fuer alle aktiven Konten.

        Reihenfolge:
        1. Pending-Signals ausfuehren (Einstieg auf Kerze t+1)
        2. Offene Positionen pruefen (TP, SL, Liquidation)
        3. Neue Signale berechnen (fuer naechste Kerze)
        """
        self._kerzen_zaehler += 1

        for konto in self._konten:
            if konto.ist_ruiniert:
                continue

            # Schritt 1: Pending-Signal aus vorheriger Kerze ausfuehren
            gerade_eingestiegen = False
            if konto._pending_signal and konto.position_richtung is None:
                self._einstieg(konto, candle, konto._pending_signal)
                konto._pending_signal = None
                gerade_eingestiegen = True

            # Schritt 2: Offene Position pruefen (nur wenn nicht gerade erst eingestiegen)
            # Kein TP/SL/Liq auf der Einstiegskerze selbst — Trade wurde am Ende der Kerze eroeffnet
            if konto.position_richtung is not None and not gerade_eingestiegen:
                self._pruefe_position(konto, candle)

            # Schritt 3: Kerze zur History hinzufuegen und neues Signal berechnen
            konto.kerzen_history.append(candle)
            # History auf N+2 begrenzen (N fuer Lookback + 1 aktuelle + 1 Puffer)
            if len(konto.kerzen_history) > konto.n + 2:
                konto.kerzen_history.pop(0)

            # Nur neues Signal wenn keine offene Position
            if konto.position_richtung is None and not konto.ist_ruiniert:
                konto._pending_signal = self._signal_berechnen(konto)

            # Equity-Snapshot alle 15 Kerzen
            konto._kerzen_seit_snapshot += 1
            if konto._kerzen_seit_snapshot >= EQUITY_INTERVALL:
                insert_equity(self._conn, konto.konto_id, candle["zeit"], konto.kontostand)
                konto._kerzen_seit_snapshot = 0

    def process_funding(self, funding: dict) -> None:
        """Wendet Funding-Zahlungen auf alle offenen Positionen an."""
        rate = funding.get("rate", 0.0)
        if rate == 0.0:
            return

        for konto in self._konten:
            if konto.ist_ruiniert or konto.position_richtung is None:
                continue
            if konto.position_groesse is None:
                continue

            # Funding: Long zahlt rate * Positionswert (negative Rate = Gewinn)
            # Short bekommt rate * Positionswert (negative Rate = Verlust)
            if konto.position_richtung == "long":
                funding_betrag = -rate * konto.position_groesse
            else:
                funding_betrag = rate * konto.position_groesse

            konto.kontostand += funding_betrag
            konto._funding_seit_einstieg += funding_betrag

            # Ruinpruefung nach Funding
            if konto.kontostand <= 0:
                self._konto_ruinieren(konto, funding["zeit"])

    def get_stats(self) -> dict:
        """Gibt Gesamtstatistiken aller Konten zurueck."""
        aktiv = sum(1 for k in self._konten if not k.ist_ruiniert)
        ruiniert = sum(1 for k in self._konten if k.ist_ruiniert)
        kontostaende = [k.kontostand for k in self._konten if not k.ist_ruiniert]
        gesamt_ambivalent = sum(k.ambivalente_kerzen for k in self._konten)
        gesamt_trades = self._conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        return {
            "total": len(self._konten),
            "aktiv": aktiv,
            "ruiniert": ruiniert,
            "median_kontostand": sorted(kontostaende)[len(kontostaende) // 2] if kontostaende else 0,
            "ambivalente_kerzen_gesamt": gesamt_ambivalent,
            "trades_gesamt": gesamt_trades,
            "sl_vor_liquidation": SL_VOR_LIQUIDATION,
        }

    # --- Private Hilfsmethoden ---

    def _signal_berechnen(self, konto: Konto) -> Optional[str]:
        """Berechnet das Handelssignal fuer das naechste Candle."""
        if konto.strategie == "breakout":
            return BreakoutStrategy.signal(konto.kerzen_history, konto.n)
        elif konto.strategie == "buy_and_hold":
            return konto._strat.signal(konto.kerzen_history)
        elif konto.strategie == "zufall":
            return konto._strat.signal(konto.kerzen_history)
        elif konto.strategie == "always_long":
            return AlwaysLongStrategy.signal(konto.kerzen_history)
        return None

    def _einstieg(self, konto: Konto, candle: dict, richtung: str) -> None:
        """Eroeffnet eine neue Position zum schlechtesten Preis der Kerze."""
        # Schlechtester Einstiegspreis: Long zum High, Short zum Low
        if richtung == "long":
            einstiegspreis = candle["high"]
        else:
            einstiegspreis = candle["low"]

        # Positionsgroesse: Kontostand * Hebel / Einstiegspreis (in BTC)
        positionswert = konto.kontostand * konto.hebel
        if positionswert < MIN_NOTIONAL:
            logger.debug(
                "Konto %s: Positionsgroesse %f USD < Minimum %f, kein Trade",
                konto.konto_id, positionswert, MIN_NOTIONAL
            )
            return

        position_btc = positionswert / einstiegspreis

        # Einstiegs-Fees: Taker-Fee + Spread auf Positionswert
        fees = positionswert * ORDER_KOSTEN
        slippage = 0.0  # Bereits durch Worst-Case-Preis abgedeckt

        konto.kontostand -= fees
        konto.position_richtung = richtung
        konto.position_preis = einstiegspreis
        konto.position_zeit = candle["zeit"]
        konto.position_groesse = position_btc
        konto._funding_seit_einstieg = 0.0

        # In DB speichern
        self._conn.execute(
            "UPDATE konten SET position_richtung=?, position_preis=?, "
            "position_zeit=?, position_groesse=?, kontostand=? "
            "WHERE konto_id=?",
            (richtung, einstiegspreis, candle["zeit"],
             position_btc, konto.kontostand, konto.konto_id)
        )
        self._conn.commit()

        logger.info(
            "Konto %s: %s bei %.2f (Positionsgroesse: %.6f BTC, Fees: %.4f)",
            konto.konto_id, richtung.upper(), einstiegspreis, position_btc, fees
        )

    def _pruefe_position(self, konto: Konto, candle: dict) -> None:
        """Prueft ob TP, SL oder Liquidation ausgeloest wurde.

        Ambivalente Kerzen: Kerzen die sowohl SL als auch Liq-Niveau beruehren.
        Die Reihenfolge innerhalb der Kerze ist unbekannt. Verhalten gesteuert
        durch SL_VOR_LIQUIDATION (Modul-Konstante).
        """
        preis = konto.position_preis
        richtung = konto.position_richtung

        tp_preis = preis * (1 + konto.tp_pct) if richtung == "long" else preis * (1 - konto.tp_pct)
        sl_preis = preis * (1 - konto.sl_pct) if richtung == "long" else preis * (1 + konto.sl_pct)
        liq_preis = konto.liquidations_preis(richtung, preis)

        sl_ausgeloest = (
            (richtung == "long" and candle["low"] <= sl_preis) or
            (richtung == "short" and candle["high"] >= sl_preis)
        )
        liq_ausgeloest = (
            (richtung == "long" and candle["low"] <= liq_preis) or
            (richtung == "short" and candle["high"] >= liq_preis)
        )

        # Ambivalente Kerze: beide Niveaus beruehrt — Reihenfolge unbekannt.
        # Zaehlen und in DB persistieren.
        if sl_ausgeloest and liq_ausgeloest:
            konto.ambivalente_kerzen += 1
            self._conn.execute(
                "UPDATE konten SET ambivalente_kerzen = ambivalente_kerzen + 1 "
                "WHERE konto_id = ?",
                (konto.konto_id,)
            )
            self._conn.commit()
            logger.debug(
                "Konto %s: ambivalente Kerze #%d (SL=%.2f, Liq=%.2f, Low=%.2f)",
                konto.konto_id, konto.ambivalente_kerzen,
                sl_preis, liq_preis, candle["low"],
            )

        if SL_VOR_LIQUIDATION:
            # Optimistische Annahme: SL greift zuerst (geometrisch naeher)
            if sl_ausgeloest:
                if richtung == "long":
                    exit_preis = min(sl_preis, candle["low"])
                else:
                    exit_preis = max(sl_preis, candle["high"])
                self._ausstieg(konto, candle, exit_preis, "SL")
                return
            if liq_ausgeloest:
                self._ausstieg(konto, candle, liq_preis, "LIQUIDATION")
                self._konto_ruinieren(konto, candle["zeit"])
                return
        else:
            # Konservative Annahme (Default): Liquidation gewinnt bei ambivalenten Kerzen.
            # Begruendung: Gaps und Slippage lassen Stops in der Praxis versagen.
            if liq_ausgeloest:
                self._ausstieg(konto, candle, liq_preis, "LIQUIDATION")
                self._konto_ruinieren(konto, candle["zeit"])
                return
            if sl_ausgeloest:
                if richtung == "long":
                    exit_preis = min(sl_preis, candle["low"])
                else:
                    exit_preis = max(sl_preis, candle["high"])
                self._ausstieg(konto, candle, exit_preis, "SL")
                return

        # Pruefe Take-Profit
        tp_ausgeloest = (
            (richtung == "long" and candle["high"] >= tp_preis) or
            (richtung == "short" and candle["low"] <= tp_preis)
        )
        if tp_ausgeloest:
            # Exit-Preis: TP-Niveau
            exit_preis = tp_preis
            self._ausstieg(konto, candle, exit_preis, "TP")

    def _ausstieg(self, konto: Konto, candle: dict, exit_preis: float, grund: str) -> None:
        """Schliesst eine offene Position und berechnet den PnL."""
        einstieg = konto.position_preis
        richtung = konto.position_richtung
        groesse = konto.position_groesse

        # Brutto-PnL: Kursbewegung * Positionsgroesse
        if richtung == "long":
            pnl_brutto = (exit_preis - einstieg) * groesse
        else:
            pnl_brutto = (einstieg - exit_preis) * groesse

        # Ausstiegs-Fees
        positionswert_aus = groesse * exit_preis
        fees = positionswert_aus * ORDER_KOSTEN
        slippage = 0.0  # Durch Worst-Case-Preis abgedeckt

        # Netto-PnL
        funding = konto._funding_seit_einstieg
        pnl_netto = pnl_brutto - fees + funding

        # Kontostand aktualisieren (Einstiegs-Fees wurden bereits abgezogen)
        konto.kontostand += pnl_brutto - fees

        # Trade in DB speichern
        insert_trade(
            self._conn,
            konto_id=konto.konto_id,
            zeit_ein=konto.position_zeit,
            zeit_aus=candle["zeit"],
            richtung=richtung,
            preis_ein=einstieg,
            preis_aus=exit_preis,
            exit_grund=grund,
            pnl_brutto=pnl_brutto,
            pnl_netto=pnl_netto,
            fees=fees,
            slippage=slippage,
            funding=funding,
        )

        # Kontostand in DB aktualisieren
        self._conn.execute(
            "UPDATE konten SET position_richtung=NULL, position_preis=NULL, "
            "position_zeit=NULL, position_groesse=NULL, kontostand=? "
            "WHERE konto_id=?",
            (konto.kontostand, konto.konto_id)
        )
        self._conn.commit()

        # Position im Objekt loeschen
        konto.position_richtung = None
        konto.position_preis = None
        konto.position_zeit = None
        konto.position_groesse = None
        konto._funding_seit_einstieg = 0.0
        konto._pending_signal = None

        logger.info(
            "Konto %s: %s-Exit (%s) bei %.2f, PnL netto: %.4f, Kontostand: %.4f",
            konto.konto_id, richtung.upper(), grund, exit_preis, pnl_netto, konto.kontostand
        )

    def _konto_ruinieren(self, konto: Konto, zeitpunkt: str) -> None:
        """Markiert ein Konto als ruiniert."""
        konto.status = "ruiniert"
        konto.kontostand = max(konto.kontostand, 0.0)
        update_konto_status(self._conn, konto.konto_id, "ruiniert", 0.0, zeitpunkt)
        logger.warning("Konto %s RUINIERT um %s!", konto.konto_id, zeitpunkt)
