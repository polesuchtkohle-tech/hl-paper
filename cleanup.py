"""Speicher-Cleanup fuer den Paper-Trader.

Taeglich ausgefuehrt (systemd-Timer):
- Equity-Daten aelter als 30 Tage auf Stundenwerte ausduennen
- Speicherplatz pruefen
- Alte Logs zusammenfassen

Aufruf: uv run python cleanup.py [--db-pfad paper.db]
"""

import argparse
import logging
import os
import shutil
from datetime import datetime, timezone, timedelta

from db import get_connection

logger = logging.getLogger(__name__)


def ausduennen_equity(conn, vor_tagen: int = 30) -> int:
    """Equity-Snapshots aelter als vor_tagen Tage auf Stundenwerte ausduennen.

    Behaelt nur Datenpunkte zu vollen Stunden (00, 01, 02, ...).
    Gibt Anzahl geloeschter Zeilen zurueck.
    """
    grenze = (datetime.now(tz=timezone.utc) - timedelta(days=vor_tagen)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    # Datenpunkte loeschen die:
    # 1. Aelter als Grenze sind UND
    # 2. Nicht zu einer vollen Stunde gehoeren (Minutenteil != "00")
    # ISO 8601 Format: "2026-08-01T14:23:00Z" -> Minute ist Zeichen 15-16 (1-basiert)
    geloescht = conn.execute(
        """
        DELETE FROM equity
        WHERE zeit < ?
        AND substr(zeit, 15, 2) != '00'
        """,
        (grenze,)
    ).rowcount
    conn.commit()
    return geloescht


def pruefe_speicher(warnung_mb: int = 500) -> dict:
    """Speicherplatz pruefen und Status zurueckgeben."""
    total, used, free = shutil.disk_usage("/")
    free_mb = free // (1024 * 1024)
    free_pct = free / total * 100
    return {
        "free_mb": free_mb,
        "free_pct": free_pct,
        "warnung": free_mb < warnung_mb,
        "kritisch": free_pct < 5.0,
    }


def cleanup_durchfuehren(db_pfad: str = "paper.db", vor_tagen: int = 30) -> dict:
    """Vollstaendigen Cleanup durchfuehren.

    Gibt Statistiken ueber durchgefuehrte Aktionen zurueck.
    """
    conn = get_connection(db_pfad)

    geloescht = ausduennen_equity(conn, vor_tagen=vor_tagen)

    conn.close()

    speicher = pruefe_speicher()

    ergebnis = {
        "equity_zeilen_geloescht": geloescht,
        "speicher": speicher,
    }

    if speicher["warnung"]:
        logger.warning(
            "Wenig Speicher: %.0f MB frei (%.1f%%)",
            speicher["free_mb"], speicher["free_pct"]
        )
    if speicher["kritisch"]:
        logger.critical(
            "KRITISCH: Nur %.1f%% Speicher frei!", speicher["free_pct"]
        )

    logger.info(
        "Cleanup abgeschlossen: %d Equity-Zeilen ausgeduennt. Speicher: %.0f MB frei.",
        geloescht, speicher["free_mb"]
    )

    return ergebnis


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Speicher-Cleanup fuer Paper-Trader")
    parser.add_argument("--db-pfad", default="paper.db")
    parser.add_argument("--vor-tagen", type=int, default=30,
                        help="Equity-Daten aelter als X Tage ausduennen")
    args = parser.parse_args()

    ergebnis = cleanup_durchfuehren(db_pfad=args.db_pfad, vor_tagen=args.vor_tagen)
    print(f"Cleanup fertig: {ergebnis['equity_zeilen_geloescht']} Zeilen gelöscht, "
          f"{ergebnis['speicher']['free_mb']:.0f} MB frei")


if __name__ == "__main__":
    main()
