"""WebSocket-Feed fuer Hyperliquid BTC-Perp Daten.

Dieser Modul:
- Verbindet sich mit dem Hyperliquid WebSocket
- Empfaengt 1m-Kerzen, Funding-Raten und Mark-Preise
- Schreibt Rohdaten als Parquet-Dateien (tagesweise partitioniert)
- Reconnected automatisch bei Verbindungsabbruch (exponentieller Backoff)
- Erkennt Luecken in der Kerzenserie und loggt sie
"""

import asyncio
import json
import logging
import os
import shutil
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Callable
import pyarrow as pa
import pyarrow.parquet as pq
import websockets

logger = logging.getLogger(__name__)

# Hyperliquid WebSocket-Endpunkt
WS_URL = "wss://api.hyperliquid.xyz/ws"

# Schema fuer Kerzendaten
CANDLE_SCHEMA = pa.schema([
    pa.field("zeit",   pa.string()),   # ISO 8601 UTC
    pa.field("open",   pa.float64()),
    pa.field("high",   pa.float64()),
    pa.field("low",    pa.float64()),
    pa.field("close",  pa.float64()),
    pa.field("volume", pa.float64()),
])

# Schema fuer Funding-Daten
FUNDING_SCHEMA = pa.schema([
    pa.field("zeit",       pa.string()),
    pa.field("rate",       pa.float64()),
    pa.field("mark_preis", pa.float64()),
])


def check_disk_space(min_mb: int = 500) -> bool:
    """Prueft ob genuegend Speicherplatz verfuegbar ist.

    Returns:
        True wenn mehr als min_mb MB frei sind, sonst False.
    """
    total, used, free = shutil.disk_usage("/")
    free_mb = free // (1024 * 1024)
    return free_mb > min_mb


class ParquetWriter:
    """Schreibt Marktdaten als Parquet-Dateien, tagesweise partitioniert.

    Puffert Daten im Speicher und schreibt sie beim Flush oder Tageswechsel.
    Jeder Tag bekommt eine eigene Datei (candles_YYYY-MM-DD.parquet).
    """

    def __init__(self, data_dir: str):
        self._data_dir = data_dir
        # Puffer: Tag -> Liste von Zeilen
        self._candle_puffer: dict[str, list[dict]] = defaultdict(list)
        self._funding_puffer: dict[str, list[dict]] = defaultdict(list)

    def _tag_aus_zeit(self, zeit: str) -> str:
        """Extrahiert das Datum (YYYY-MM-DD) aus einem ISO-Timestamp."""
        # "2026-08-01T00:00:00Z" -> "2026-08-01"
        return zeit[:10]

    def write_candle(self, candle: dict) -> None:
        """Kerze in den Puffer schreiben."""
        tag = self._tag_aus_zeit(candle["zeit"])
        self._candle_puffer[tag].append(candle)

    def write_funding(self, funding: dict) -> None:
        """Funding-Datensatz in den Puffer schreiben."""
        tag = self._tag_aus_zeit(funding["zeit"])
        self._funding_puffer[tag].append(funding)

    def flush(self) -> None:
        """Alle gepufferten Daten in Parquet-Dateien schreiben."""
        for tag, kerzen in self._candle_puffer.items():
            if not kerzen:
                continue
            pfad = os.path.join(self._data_dir, f"candles_{tag}.parquet")
            self._schreibe_parquet(pfad, kerzen, CANDLE_SCHEMA)
        self._candle_puffer.clear()

        for tag, funding_eintraege in self._funding_puffer.items():
            if not funding_eintraege:
                continue
            pfad = os.path.join(self._data_dir, f"funding_{tag}.parquet")
            self._schreibe_parquet(pfad, funding_eintraege, FUNDING_SCHEMA)
        self._funding_puffer.clear()

    def _schreibe_parquet(self, pfad: str, daten: list[dict], schema: pa.Schema) -> None:
        """Schreibt Daten als Parquet-Datei. Fuegt an bestehende Datei an."""
        tabelle = pa.table(
            {feld.name: [d[feld.name] for d in daten] for feld in schema},
            schema=schema,
        )

        if os.path.exists(pfad):
            # An bestehende Datei anhaengen
            bestehend = pq.read_table(pfad)
            kombiniert = pa.concat_tables([bestehend, tabelle])
            pq.write_table(kombiniert, pfad, compression="zstd")
        else:
            pq.write_table(tabelle, pfad, compression="zstd")


class HyperliquidFeed:
    """Verbindet sich mit Hyperliquid WebSocket und leitet Daten weiter.

    Reconnect mit exponentiellem Backoff (1s, 2s, 4s, ... max 60s).
    Erkennt Luecken in der Kerzenserie (fehlende 1m-Kerzen).
    """

    def __init__(
        self,
        on_candle: Callable,
        on_funding: Callable,
        on_gap: Callable | None = None,
    ):
        self._on_candle = on_candle
        self._on_funding = on_funding
        self._on_gap = on_gap or (lambda info: logger.warning("Luecke erkannt: %s", info))
        self._letzte_kerzen_zeit: str | None = None
        self._laeuft = False

    def _on_candle_received(self, candle: dict) -> None:
        """Verarbeitet eine empfangene Kerze und prueft auf Luecken."""
        if self._letzte_kerzen_zeit is not None:
            # Lueckenerkennung: Mehr als 1 Minute Abstand?
            try:
                letzte = datetime.fromisoformat(
                    self._letzte_kerzen_zeit.replace("Z", "+00:00")
                )
                aktuelle = datetime.fromisoformat(
                    candle["zeit"].replace("Z", "+00:00")
                )
                abstand = aktuelle - letzte
                if abstand > timedelta(minutes=1, seconds=30):
                    fehlende_kerzen = int(abstand.total_seconds() / 60) - 1
                    self._on_gap({
                        "typ": "luecke",
                        "von": self._letzte_kerzen_zeit,
                        "bis": candle["zeit"],
                        "fehlende_kerzen": fehlende_kerzen,
                    })
            except (ValueError, KeyError) as e:
                logger.error("Fehler bei Lueckenerkennung: %s", e)

        self._letzte_kerzen_zeit = candle["zeit"]
        self._on_candle(candle)

    def _parse_candle(self, data: dict) -> dict | None:
        """Parst eine Kerzennachricht von Hyperliquid."""
        try:
            d = data["data"]
            # Timestamp in ms -> ISO 8601 UTC
            ts_ms = int(d["t"])
            zeit = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            return {
                "zeit":   zeit,
                "open":   float(d["o"]),
                "high":   float(d["h"]),
                "low":    float(d["l"]),
                "close":  float(d["c"]),
                "volume": float(d["v"]),
            }
        except (KeyError, ValueError) as e:
            logger.error("Fehler beim Parsen der Kerze: %s", e)
            return None

    def _parse_funding(self, data: dict) -> dict | None:
        """Parst eine Funding-Nachricht von Hyperliquid."""
        try:
            ctx = data["data"]["ctx"]
            zeit = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return {
                "zeit":       zeit,
                "rate":       float(ctx["funding"]),
                "mark_preis": float(ctx["markPx"]),
            }
        except (KeyError, ValueError) as e:
            logger.error("Fehler beim Parsen des Fundings: %s", e)
            return None

    async def connect(self) -> None:
        """Verbindet mit Hyperliquid WebSocket und haelt Verbindung aufrecht.

        Reconnect mit exponentiellem Backoff: 1s, 2s, 4s, ..., max 60s.
        """
        self._laeuft = True
        backoff = 1.0

        while self._laeuft:
            try:
                logger.info("Verbinde mit %s ...", WS_URL)
                async with websockets.connect(WS_URL) as ws:
                    backoff = 1.0  # Backoff zuruecksetzen bei Erfolg

                    # Subscriptions senden
                    await ws.send(json.dumps({
                        "method": "subscribe",
                        "subscription": {"type": "candle", "coin": "BTC", "interval": "1m"},
                    }))
                    await ws.send(json.dumps({
                        "method": "subscribe",
                        "subscription": {"type": "activeAssetCtx", "coin": "BTC"},
                    }))
                    logger.info("WebSocket verbunden, Subscriptions aktiv.")

                    async for nachricht in ws:
                        data = json.loads(nachricht)
                        kanal = data.get("channel", "")

                        if kanal == "candle":
                            kerze = self._parse_candle(data)
                            if kerze:
                                self._on_candle_received(kerze)

                        elif kanal == "activeAssetCtx":
                            funding = self._parse_funding(data)
                            if funding:
                                self._on_funding(funding)

            except asyncio.CancelledError:
                logger.info("Feed gestoppt.")
                break
            except Exception as e:
                logger.warning("Verbindung verloren: %s. Warte %.1fs.", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)  # Exponentieller Backoff, max 60s

    async def close(self) -> None:
        """Stoppt den Feed."""
        self._laeuft = False
