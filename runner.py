"""Hauptprozess des Paper-Trader.

Verbindet WebSocket-Feed mit Simulations-Engine.
Laeuft als systemd-Service (Restart=always).
Beim Neustart: Zustand vollstaendig aus SQLite wiederherstellen.

Aufruf:
    uv run python runner.py              # Vollmodus (alle ~1280 Konten)
    uv run python runner.py --testmodus  # Nur 6 Konten, zum Testen
"""

import argparse
import asyncio
import logging
import logging.handlers
import os
import shutil
import signal
import sys
from pythonjsonlogger import jsonlogger

from db import get_connection, init_schema
from engine import SimulationEngine
from feed import HyperliquidFeed, ParquetWriter, check_disk_space
from grid import generate_grid


# --- Logging einrichten ---
def logging_einrichten(log_dir: str = "logs") -> None:
    """Strukturiertes JSON-Logging mit Rotation.

    50 MB pro Datei, maximal 5 Dateien = ca. 250 MB Logs gesamt.
    """
    os.makedirs(log_dir, exist_ok=True)
    log_pfad = os.path.join(log_dir, "paper-trader.log")

    handler = logging.handlers.RotatingFileHandler(
        log_pfad,
        maxBytes=50 * 1024 * 1024,  # 50 MB
        backupCount=5,
        encoding="utf-8",
    )
    # JSON-Format fuer strukturiertes Logging
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    handler.setFormatter(formatter)

    # Auch auf stderr ausgeben fuer systemd journal
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)
    root_logger.addHandler(stderr_handler)


logger = logging.getLogger(__name__)

# Grenzwerte fuer Speicherplatz
WARNUNG_MB = 500  # Warnung unter 500 MB frei
KRITISCH_PCT = 0.05  # Sauberes Beenden unter 5% frei


def pruefe_speicher_kritisch() -> bool:
    """True wenn Speicher kritisch niedrig ist (< 5% frei)."""
    total, used, free = shutil.disk_usage("/")
    return free / total < KRITISCH_PCT


class PaperTrader:
    """Orchestriert Feed, Engine und Parquet-Writer."""

    def __init__(self, testmodus: bool, db_pfad: str):
        self._testmodus = testmodus
        self._db_pfad = db_pfad
        self._conn = None
        self._engine = None
        self._writer = None
        self._feed = None
        self._laeuft = False

    async def starten(self) -> None:
        """Startet den Paper-Trader."""
        logger.info(
            "Paper-Trader startet. Testmodus: %s, DB: %s",
            self._testmodus,
            self._db_pfad,
        )

        # Datenbankverbindung und Schema
        self._conn = get_connection(self._db_pfad)
        init_schema(self._conn)
        logger.info("Datenbankschema initialisiert.")

        # Grid und Engine
        grid = generate_grid(testmodus=self._testmodus)
        logger.info("Grid generiert: %d Konten.", len(grid))

        data_dir = "data"
        os.makedirs(data_dir, exist_ok=True)

        self._engine = SimulationEngine(
            db_conn=self._conn,
            data_dir=data_dir,
            testmodus=self._testmodus,
        )
        self._engine.init_konten(grid)

        # Parquet-Writer
        self._writer = ParquetWriter(data_dir)

        # Feed starten
        self._feed = HyperliquidFeed(
            on_candle=self._on_candle,
            on_funding=self._on_funding,
            on_gap=self._on_gap,
        )

        self._laeuft = True
        logger.info("Verbinde mit Hyperliquid WebSocket...")
        await self._feed.connect()

    def _on_candle(self, candle: dict) -> None:
        """Callback: Neue 1m-Kerze empfangen."""
        # Speichercheck vor jedem Schreibvorgang
        if not check_disk_space(min_mb=WARNUNG_MB):
            logger.warning("Weniger als %d MB frei! Prüfe Speicherplatz.", WARNUNG_MB)

        if pruefe_speicher_kritisch():
            logger.critical(
                "Kritisch wenig Speicher (<5%% frei)! Fahre sauber herunter."
            )
            asyncio.get_event_loop().call_soon_threadsafe(
                asyncio.ensure_future,
                self.herunterfahren(),
            )
            return

        # Kerze an Engine und Parquet-Writer
        self._engine.process_candle(candle)
        self._writer.write_candle(candle)

        # Jede Stunde flushen (60 Kerzen bei 1m-Intervall)
        # (Simpler Zaehler: basierend auf Minutenmarkierung)
        zeit = candle.get("zeit", "")
        if zeit.endswith(":00Z") and not zeit.endswith("00:00Z"):
            self._writer.flush()

    def _on_funding(self, funding: dict) -> None:
        """Callback: Neue Funding-Rate empfangen."""
        self._engine.process_funding(funding)
        self._writer.write_funding(funding)

    def _on_gap(self, info: dict) -> None:
        """Callback: Luecke in der Kerzenserie erkannt."""
        logger.warning(
            "DATENLÜCKE: %d fehlende Kerzen von %s bis %s",
            info.get("fehlende_kerzen", "?"),
            info.get("von", "?"),
            info.get("bis", "?"),
        )

    async def herunterfahren(self) -> None:
        """Sauberes Herunterfahren: Feed stoppen, Daten flushen."""
        if not self._laeuft:
            return
        self._laeuft = False

        logger.info("Fahre sauber herunter...")

        if self._feed:
            await self._feed.close()

        if self._writer:
            self._writer.flush()
            logger.info("Parquet-Daten geflusht.")

        if self._conn:
            self._conn.close()
            logger.info("Datenbankverbindung geschlossen.")

        logger.info("Paper-Trader beendet.")


async def main() -> None:
    """Einstiegspunkt: Argparse, Logging, Trader starten."""
    parser = argparse.ArgumentParser(
        description="Paper-Trader: Simuliert Breakout-Strategien auf Hyperliquid BTC-Perp."
    )
    parser.add_argument(
        "--testmodus",
        action="store_true",
        help="Nur 6 Konten simulieren (schneller Test ob alles laeuft)",
    )
    parser.add_argument(
        "--db-pfad",
        default="paper.db",
        help="Pfad zur SQLite-Datenbank (Standard: paper.db)",
    )
    args = parser.parse_args()

    # Logging als erstes einrichten
    logging_einrichten()

    trader = PaperTrader(testmodus=args.testmodus, db_pfad=args.db_pfad)

    # Graceful Shutdown bei SIGTERM und SIGINT (Ctrl+C)
    loop = asyncio.get_event_loop()

    def signal_handler():
        logger.info("Signal empfangen, fahre herunter...")
        asyncio.ensure_future(trader.herunterfahren())

    # SIGTERM: systemd sendet dieses Signal beim Stoppen des Services
    loop.add_signal_handler(signal.SIGTERM, signal_handler)
    # SIGINT: Ctrl+C im Terminal
    loop.add_signal_handler(signal.SIGINT, signal_handler)

    try:
        await trader.starten()
    except KeyboardInterrupt:
        await trader.herunterfahren()


if __name__ == "__main__":
    asyncio.run(main())
