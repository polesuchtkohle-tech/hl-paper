"""Tagesbericht als Textdatei.

Einmal täglich aufgerufen, vergleicht aktuellen Stand mit gestern.
Schreibt Bericht nach reports/bericht_YYYY-MM-DD.txt.

Aufruf: uv run python report.py [--db-pfad paper.db]
"""

import argparse
import os
from datetime import datetime, timezone, timedelta

from db import get_connection, get_konten


def erstelle_tagesbericht(db_pfad: str = "paper.db", report_dir: str = "reports") -> str:
    """Erstellt einen Tagesbericht und schreibt ihn als Textdatei.

    Gibt den Pfad zur erstellten Datei zurueck.
    """
    os.makedirs(report_dir, exist_ok=True)

    conn = get_connection(db_pfad)
    alle_konten = get_konten(conn)

    # Trades von heute
    heute = datetime.now(tz=timezone.utc).date().isoformat()
    gestern = (datetime.now(tz=timezone.utc).date() - timedelta(days=1)).isoformat()

    heute_trades = conn.execute(
        "SELECT COUNT(*), SUM(pnl_netto) FROM trades WHERE zeit_aus LIKE ?",
        (f"{heute}%",)
    ).fetchone()

    # Neu ruinierte Konten heute
    neu_ruiniert = conn.execute(
        "SELECT konto_id, kontostand FROM konten "
        "WHERE status = 'ruiniert' AND ruin_zeitpunkt LIKE ?",
        (f"{heute}%",)
    ).fetchall()

    # Trades und ambivalente Kerzen
    gesamt_trades = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    gesamt_ambivalent = conn.execute(
        "SELECT SUM(ambivalente_kerzen) FROM konten"
    ).fetchone()[0] or 0

    # Letzte Kerze
    letzte_kerze = conn.execute("SELECT MAX(zeit) FROM equity").fetchone()[0] or "unbekannt"

    conn.close()

    breakout = [k for k in alle_konten if k["strategie"] == "breakout"]
    aktiv = [k for k in breakout if k["status"] == "aktiv"]
    ruiniert = [k for k in breakout if k["status"] == "ruiniert"]
    bah = next((k for k in alle_konten if k["strategie"] == "buy_and_hold"), None)

    # Bericht schreiben
    zeilen = []

    def z(text=""):
        zeilen.append(text)

    z(f"PAPER-TRADER TAGESBERICHT — {heute}")
    z("=" * 50)
    z()
    z("WAS IST SEIT GESTERN PASSIERT?")
    z(f"  Trades heute:      {heute_trades[0] or 0}")
    if heute_trades[1]:
        z(f"  PnL heute (netto): {heute_trades[1]:.2f} USDC gesamt")
    z(f"  Letzte Kerze:      {letzte_kerze}")
    z()

    z("KONTENSTAND")
    z(f"  Aktiv:     {len(aktiv)}")
    z(f"  Ruiniert:  {len(ruiniert)}")
    if aktiv:
        staende = sorted(k["kontostand"] for k in aktiv)
        median = staende[len(staende) // 2]
        z(f"  Median (aktiv): {median:.2f} USDC")
    if bah:
        z(f"  Buy-and-Hold:   {bah['kontostand']:.2f} USDC")
    z()

    z("NEU RUINIERTE KONTEN HEUTE")
    if neu_ruiniert:
        for row in neu_ruiniert:
            z(f"  - {row[0]}")
    else:
        z("  Keine")
    z()

    z("TOP 5 AKTUELL")
    for i, k in enumerate(aktiv[:5], 1):
        delta = (k["kontostand"] / 100.0 - 1) * 100
        z(f"  {i}. {k['konto_id']:<30} {k['kontostand']:>8.2f} USDC ({delta:+.1f}%)")
    z()

    z("DATENQUALITAET")
    z(f"  Trades gesamt in DB:    {gesamt_trades}")
    anteil = gesamt_ambivalent / gesamt_trades * 100 if gesamt_trades > 0 else 0.0
    z(f"  Ambivalente Kerzen:     {gesamt_ambivalent} ({anteil:.2f}% der Trades)")
    z("    (Kerzen die sowohl SL- als auch Liq-Niveau beruehren;")
    z("     haeufig = 1m-Kerzen zu grob fuer hohe Hebel)")
    z(f"  (Datenlücken: Siehe logs/paper-trader.log nach 'DATENLÜCKE')")
    z()
    z("=" * 50)

    inhalt = "\n".join(zeilen)

    pfad = os.path.join(report_dir, f"bericht_{heute}.txt")
    with open(pfad, "w", encoding="utf-8") as f:
        f.write(inhalt)

    return pfad


def main():
    parser = argparse.ArgumentParser(description="Tagesbericht erstellen")
    parser.add_argument("--db-pfad", default="paper.db")
    parser.add_argument("--report-dir", default="reports")
    args = parser.parse_args()
    pfad = erstelle_tagesbericht(db_pfad=args.db_pfad, report_dir=args.report_dir)
    print(f"Bericht geschrieben: {pfad}")


if __name__ == "__main__":
    main()
