"""Terminal-Uebersicht fuer den Paper-Trader.

Aufruf: uv run python status.py [--db-pfad paper.db]

Zeigt auf einen Blick:
- Konten-Statistiken (aktiv/ruiniert)
- Top 10 und Flop 10 Konten
- Verteilung aller Konten
- Vergleich mit Buy-and-Hold und Zufallsstrategie
- Ruinquote je Hebelstufe
- Statistische Signifikanzsschwelle
"""

import argparse
import math
import statistics
from datetime import datetime, timezone

from db import get_connection, get_konten


def render_status(db_pfad: str = "paper.db") -> str:
    """Gibt den Status als formatierter String zurueck.

    Wird auch von Tests verwendet, daher als eigene Funktion.
    """
    conn = get_connection(db_pfad)
    alle_konten = get_konten(conn)

    # Letzte Kerzenzeit aus Equity-Tabelle lesen
    letzte_kerze = conn.execute(
        "SELECT MAX(zeit) FROM equity"
    ).fetchone()[0] or "keine Daten"

    # Ambivalente Kerzen: Summe ueber alle Konten + Trades gesamt
    gesamt_ambivalent = conn.execute(
        "SELECT SUM(ambivalente_kerzen) FROM konten"
    ).fetchone()[0] or 0
    gesamt_trades = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]

    conn.close()

    # Konten aufteilen
    breakout_konten = [k for k in alle_konten if k["strategie"] == "breakout"]
    aktive_breakout = [k for k in breakout_konten if k["status"] == "aktiv"]
    ruinierte = [k for k in breakout_konten if k["status"] == "ruiniert"]

    bah = next((k for k in alle_konten if k["strategie"] == "buy_and_hold"), None)
    zufall = next((k for k in alle_konten if k["strategie"] == "zufall"), None)

    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    linien = []

    def h(text=""):
        linien.append(text)

    # --- Header ---
    h("=" * 60)
    h(f"PAPER-TRADER STATUS — {now}")
    h("=" * 60)
    h()

    # --- Bot-Status ---
    h("BOT-STATUS")
    h(f"  Datenbank:   {db_pfad} (letzte Kerze: {letzte_kerze})")
    h(f"  Konten:      {len(aktive_breakout)} aktiv / {len(ruinierte)} ruiniert ({len(breakout_konten)} gesamt)")
    h()

    # --- Top 10 ---
    top10 = sorted(aktive_breakout, key=lambda k: k["kontostand"], reverse=True)[:10]
    h("TOP 10 KONTEN")
    h(f"  {'#':>2}  {'Konto-ID':<30} {'N':>4} {'TP':>5} {'SL':>5} {'Hbl':>3}  {'Kontostand':>10}  {'Δ vs 100':>9}")
    h(f"  {'--':>2}  {'-'*30} {'-'*4} {'-'*5} {'-'*5} {'-'*3}  {'-'*10}  {'-'*9}")
    for i, k in enumerate(top10, 1):
        delta = (k["kontostand"] / 100.0 - 1) * 100
        vorzeichen = "+" if delta >= 0 else ""
        h(
            f"  {i:>2}  {k['konto_id']:<30} {k['n']:>4} {k['tp']:>5.2f} {k['sl']:>5.2f} {k['hebel']:>3}  "
            f"{k['kontostand']:>10.2f}  {vorzeichen}{delta:>8.1f}%"
        )
    if not top10:
        h("  (keine aktiven Konten)")
    h()

    # --- Flop 10 ---
    flop10 = sorted(aktive_breakout, key=lambda k: k["kontostand"])[:10]
    h("FLOP 10 KONTEN")
    h(f"  {'#':>2}  {'Konto-ID':<30} {'N':>4} {'TP':>5} {'SL':>5} {'Hbl':>3}  {'Kontostand':>10}  {'Δ vs 100':>9}")
    h(f"  {'--':>2}  {'-'*30} {'-'*4} {'-'*5} {'-'*5} {'-'*3}  {'-'*10}  {'-'*9}")
    for i, k in enumerate(flop10, 1):
        delta = (k["kontostand"] / 100.0 - 1) * 100
        vorzeichen = "+" if delta >= 0 else ""
        h(
            f"  {i:>2}  {k['konto_id']:<30} {k['n']:>4} {k['tp']:>5.2f} {k['sl']:>5.2f} {k['hebel']:>3}  "
            f"{k['kontostand']:>10.2f}  {vorzeichen}{delta:>8.1f}%"
        )
    if not flop10:
        h("  (keine Daten)")
    h()

    # --- Verteilung ---
    h("VERTEILUNG ALLER KONTEN")
    if len(aktive_breakout) >= 4:
        staende = sorted(k["kontostand"] for k in aktive_breakout)
        n = len(staende)
        median = statistics.median(staende)
        q1 = staende[n // 4]
        q3 = staende[3 * n // 4]
        min_stand = staende[0]
        max_stand = staende[-1]
        h(f"  Median:      {median:>8.2f} USDC")
        h(f"  Q1:          {q1:>8.2f} USDC  (25%)")
        h(f"  Q3:          {q3:>8.2f} USDC  (75%)")
        h(f"  Min:         {min_stand:>8.2f} USDC")
        h(f"  Max:         {max_stand:>8.2f} USDC")
    else:
        h("  (zu wenig Daten fuer Verteilung)")
    h()

    # --- Vergleich mit Benchmarks ---
    h("VERGLEICH MIT BENCHMARKS")
    bah_stand = bah["kontostand"] if bah else None
    zufall_stand = zufall["kontostand"] if zufall else None

    if bah_stand is not None:
        h(f"  Buy-and-Hold:         {bah_stand:>8.2f} USDC")
    if zufall_stand is not None:
        h(f"  Zufallsstrategie:     {zufall_stand:>8.2f} USDC")

    if aktive_breakout and bah_stand is not None:
        besser_bah = sum(1 for k in aktive_breakout if k["kontostand"] > bah_stand)
        pct_bah = besser_bah / len(aktive_breakout) * 100
        h(f"  Konten > BaH:         {besser_bah} von {len(aktive_breakout)} ({pct_bah:.1f}%)")

    if aktive_breakout and zufall_stand is not None:
        besser_zufall = sum(1 for k in aktive_breakout if k["kontostand"] > zufall_stand)
        pct_zufall = besser_zufall / len(aktive_breakout) * 100
        h(f"  Konten > Zufall:      {besser_zufall} von {len(aktive_breakout)} ({pct_zufall:.1f}%)")

    if bah_stand is None and zufall_stand is None:
        h("  (keine Benchmark-Konten in der Datenbank)")
    h()

    # --- Ruinquote je Hebelstufe ---
    h("RUINQUOTE JE HEBELSTUFE")
    h(f"  {'Hebel':>5}  | {'Aktiv':>7} | {'Ruiniert':>8} | {'Ruinquote':>9}")
    h(f"  {'-'*5}  | {'-'*7} | {'-'*8} | {'-'*9}")
    for hebel in [1, 3, 5, 10, 25]:
        aktiv_h = sum(1 for k in breakout_konten if k["hebel"] == hebel and k["status"] == "aktiv")
        ruin_h = sum(1 for k in breakout_konten if k["hebel"] == hebel and k["status"] == "ruiniert")
        total_h = aktiv_h + ruin_h
        ruinquote = ruin_h / total_h * 100 if total_h > 0 else 0.0
        h(f"  {hebel:>5}x | {aktiv_h:>7} | {ruin_h:>8} | {ruinquote:>8.1f}%")
    h()

    # --- Ambivalente Kerzen ---
    h("AMBIVALENTE KERZEN (SL + Liquidation in einer 1m-Kerze)")
    h("  Kerzen bei denen sowohl SL- als auch Liquidationsniveau beruehrt wurde.")
    h("  Die Reihenfolge innerhalb der Kerze ist unbekannt.")
    h()
    anteil = gesamt_ambivalent / gesamt_trades * 100 if gesamt_trades > 0 else 0.0
    h(f"  Gesamt:          {gesamt_ambivalent} Kerzen")
    h(f"  Trades gesamt:   {gesamt_trades}")
    h(f"  Anteil:          {anteil:.2f}% der Trades")
    h()
    if gesamt_trades > 0:
        if anteil < 1.0:
            h("  => Selten. Annahme (SL_VOR_LIQUIDATION) hat kaum Einfluss.")
        elif anteil < 5.0:
            h("  => Gelegentlich. Annahme beeinflusst Ergebnis moderat.")
        else:
            h("  => Haeufig! 1m-Kerzen sind fuer hohe Hebel zu grob aufgeloest.")
            h("     Ergebnis haengt stark von der getroffenen Annahme ab.")
    from engine import SL_VOR_LIQUIDATION
    modus = "optimistisch (SL gewinnt)" if SL_VOR_LIQUIDATION else "konservativ (Liquidation gewinnt)"
    h(f"  Aktuelle Annahme: {modus}")
    h()

    # --- Statistische Schwelle ---
    M = len(breakout_konten)
    h("STATISTISCHE SCHWELLE (Bonferroni-Grenze)")
    if M > 1:
        schwelle = math.sqrt(2 * math.log(M))
        h(f"  M = {M} gueltige Varianten")
        h(f"  Zufallsschwelle: sqrt(2 * ln({M})) = {schwelle:.2f} Sigma")
        h()
        h(f"  Bedeutung: Ein Konto muss mindestens {schwelle:.2f} Standardabweichungen")
        h("  ueber dem Median liegen, damit sein Ergebnis NICHT als statistischer")
        h(f"  Zufall gilt. Bei {M} unabhaengigen Tests erwartet man rein zufaellig")
        h("  ein so extremes Ergebnis.")
    else:
        h("  (zu wenig Daten — mindestens 2 Varianten erforderlich)")

    h()
    h("=" * 60)

    return "\n".join(linien)


def main() -> None:
    """Einstiegspunkt fuer Kommandozeilenaufruf."""
    parser = argparse.ArgumentParser(description="Paper-Trader Status-Uebersicht")
    parser.add_argument("--db-pfad", default="paper.db", help="Pfad zur SQLite-Datenbank")
    args = parser.parse_args()
    print(render_status(db_pfad=args.db_pfad))


if __name__ == "__main__":
    main()
