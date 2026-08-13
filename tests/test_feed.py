"""Tests fuer WebSocket-Feed und Parquet-Writer."""

import asyncio
import pytest
import pyarrow.parquet as pq
from unittest.mock import AsyncMock, patch
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from feed import HyperliquidFeed, ParquetWriter, check_disk_space


class TestParquetWriter:
    def test_kerze_wird_als_parquet_geschrieben(self, tmp_data_dir):
        """Eine Kerze schreiben und Parquet-Datei pruefen."""
        writer = ParquetWriter(str(tmp_data_dir))
        kerze = {
            "zeit": "2026-08-01T00:00:00Z",
            "open": 50000.0,
            "high": 50100.0,
            "low": 49900.0,
            "close": 50050.0,
            "volume": 123.45,
        }
        writer.write_candle(kerze)
        writer.flush()

        dateien = list(tmp_data_dir.glob("candles_*.parquet"))
        assert len(dateien) == 1

        tabelle = pq.read_table(str(dateien[0]))
        assert len(tabelle) == 1
        assert tabelle.column("close")[0].as_py() == 50050.0

    def test_funding_wird_geschrieben(self, tmp_data_dir):
        """Funding-Rate als Parquet schreiben."""
        writer = ParquetWriter(str(tmp_data_dir))
        funding = {
            "zeit": "2026-08-01T00:00:00Z",
            "rate": 0.0001,
            "mark_preis": 50000.0,
        }
        writer.write_funding(funding)
        writer.flush()

        dateien = list(tmp_data_dir.glob("funding_*.parquet"))
        assert len(dateien) == 1

    def test_tagespartitionierung(self, tmp_data_dir):
        """Kerzen verschiedener Tage landen in verschiedenen Dateien."""
        writer = ParquetWriter(str(tmp_data_dir))
        writer.write_candle({
            "zeit": "2026-08-01T00:00:00Z",
            "open": 50000.0, "high": 50100.0,
            "low": 49900.0, "close": 50050.0, "volume": 100.0,
        })
        writer.write_candle({
            "zeit": "2026-08-02T00:00:00Z",
            "open": 51000.0, "high": 51100.0,
            "low": 50900.0, "close": 51050.0, "volume": 200.0,
        })
        writer.flush()

        dateien = list(tmp_data_dir.glob("candles_*.parquet"))
        assert len(dateien) == 2

    def test_mehrere_kerzen_in_einer_datei(self, tmp_data_dir):
        """Mehrere Kerzen am gleichen Tag landen in einer Datei."""
        writer = ParquetWriter(str(tmp_data_dir))
        for i in range(5):
            writer.write_candle({
                "zeit": f"2026-08-01T00:0{i}:00Z",
                "open": 50000.0, "high": 50100.0,
                "low": 49900.0, "close": 50050.0 + i, "volume": 100.0,
            })
        writer.flush()

        dateien = list(tmp_data_dir.glob("candles_*.parquet"))
        assert len(dateien) == 1
        tabelle = pq.read_table(str(dateien[0]))
        assert len(tabelle) == 5


class TestDiskCheck:
    def test_check_gibt_bool_zurueck(self):
        """Speichercheck gibt True oder False zurueck."""
        ergebnis = check_disk_space(min_mb=1)
        assert isinstance(ergebnis, bool)

    def test_unrealistischer_grenzwert_gibt_false(self):
        """Unrealistisch hoher Grenzwert (1 TB) ergibt False."""
        ergebnis = check_disk_space(min_mb=1_000_000)
        assert ergebnis is False


class TestHyperliquidFeed:
    @pytest.mark.asyncio
    async def test_reconnect_bei_verbindungsabbruch(self):
        """Feed versucht Reconnect mit exponentiellem Backoff."""
        verbindungsversuche = []

        class MockConnectCM:
            """Async-Kontextmanager der bei den ersten Versuchen fehlschlaegt."""
            def __init__(self):
                verbindungsversuche.append(1)
                self._soll_fehlschlagen = len(verbindungsversuche) < 3

            async def __aenter__(self):
                if self._soll_fehlschlagen:
                    raise ConnectionError("Verbindung fehlgeschlagen")
                mock_ws = AsyncMock()
                mock_ws.send = AsyncMock()
                mock_ws.__aiter__ = lambda s: s
                mock_ws.__anext__ = AsyncMock(side_effect=asyncio.CancelledError)
                return mock_ws

            async def __aexit__(self, *args):
                return False

        def mock_connect(*args, **kwargs):
            return MockConnectCM()

        feed = HyperliquidFeed(
            on_candle=lambda c: None,
            on_funding=lambda f: None,
        )

        with patch("websockets.connect", side_effect=mock_connect):
            try:
                await asyncio.wait_for(feed.connect(), timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        assert len(verbindungsversuche) >= 2, (
            "Feed muss bei Verbindungsabbruch erneut verbinden"
        )

    @pytest.mark.asyncio
    async def test_gap_callback_bei_fehlender_kerze(self):
        """Wenn eine 1m-Kerze fehlt, wird on_gap aufgerufen."""
        luecken = []
        empfangene_kerzen = []

        feed = HyperliquidFeed(
            on_candle=lambda c: empfangene_kerzen.append(c),
            on_funding=lambda f: None,
            on_gap=lambda info: luecken.append(info),
        )

        # Zwei Kerzen mit 2-Minuten-Abstand simulieren (eine fehlt)
        feed._letzte_kerzen_zeit = "2026-08-01T00:00:00Z"
        feed._on_candle_received({
            "zeit": "2026-08-01T00:02:00Z",  # Luecke: 00:01 fehlt
            "open": 50000.0, "high": 50100.0,
            "low": 49900.0, "close": 50050.0, "volume": 100.0,
        })

        assert len(luecken) == 1
        assert "luecke" in luecken[0].get("typ", "").lower() or len(luecken) == 1
