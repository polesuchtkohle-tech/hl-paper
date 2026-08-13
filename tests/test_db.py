"""Tests fuer SQLite-Schema und Hilfsfunktionen."""

import sqlite3
import pytest
import sys
import os

# paper/ Verzeichnis im Suchpfad, damit Imports funktionieren
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db import get_connection, init_schema, insert_trade, insert_equity, get_konten, update_konto_status, set_meta


@pytest.fixture
def conn():
    """In-Memory-Datenbank fuer Tests."""
    c = get_connection(":memory:")
    init_schema(c)
    return c


def test_schema_erstellt_alle_tabellen(conn):
    """Alle vier Tabellen muessen existieren."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tabellen = [row[0] for row in cursor.fetchall()]
    assert "equity" in tabellen
    assert "konten" in tabellen
    assert "meta" in tabellen
    assert "trades" in tabellen


def test_konto_einfuegen_und_lesen(conn):
    """Ein Konto einfuegen und wieder lesen."""
    conn.execute(
        "INSERT INTO konten (konto_id, n, tp, sl, hebel, status, kontostand) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("brk_20_1.0_0.5_5", 20, 1.0, 0.5, 5, "aktiv", 100.0)
    )
    konten = get_konten(conn)
    assert len(konten) == 1
    assert konten[0]["konto_id"] == "brk_20_1.0_0.5_5"
    assert konten[0]["kontostand"] == 100.0


def test_trade_einfuegen(conn):
    """Trade einfuegen und zuruecklesen."""
    # Erst Konto anlegen (Foreign Key)
    conn.execute(
        "INSERT INTO konten (konto_id, n, tp, sl, hebel, status, kontostand) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("brk_20_1.0_0.5_5", 20, 1.0, 0.5, 5, "aktiv", 100.0)
    )
    insert_trade(
        conn,
        konto_id="brk_20_1.0_0.5_5",
        zeit_ein="2026-08-01T00:00:00Z",
        zeit_aus="2026-08-01T01:00:00Z",
        richtung="long",
        preis_ein=50000.0,
        preis_aus=50500.0,
        exit_grund="TP",
        pnl_brutto=50.0,
        pnl_netto=47.5,
        fees=2.0,
        slippage=0.5,
        funding=0.0,
    )
    cursor = conn.execute("SELECT COUNT(*) FROM trades")
    assert cursor.fetchone()[0] == 1


def test_equity_snapshot(conn):
    """Equity-Snapshot einfuegen und lesen."""
    conn.execute(
        "INSERT INTO konten (konto_id, n, tp, sl, hebel, status, kontostand) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("brk_20_1.0_0.5_5", 20, 1.0, 0.5, 5, "aktiv", 100.0)
    )
    insert_equity(conn, "brk_20_1.0_0.5_5", "2026-08-01T00:00:00Z", 100.0)
    insert_equity(conn, "brk_20_1.0_0.5_5", "2026-08-01T00:15:00Z", 101.5)
    cursor = conn.execute("SELECT COUNT(*) FROM equity")
    assert cursor.fetchone()[0] == 2


def test_konto_status_update(conn):
    """Kontostatus aendern (aktiv -> ruiniert)."""
    conn.execute(
        "INSERT INTO konten (konto_id, n, tp, sl, hebel, status, kontostand) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("brk_10_0.3_0.2_25", 10, 0.3, 0.2, 25, "aktiv", 100.0)
    )
    update_konto_status(conn, "brk_10_0.3_0.2_25", "ruiniert", 0.0)
    konten = get_konten(conn)
    assert konten[0]["status"] == "ruiniert"
    assert konten[0]["kontostand"] == 0.0


def test_meta_setzen(conn):
    """Meta-Informationen setzen und lesen."""
    set_meta(conn, anzahl_varianten=1280, startzeitpunkt="2026-08-13T00:00:00Z")
    cursor = conn.execute("SELECT anzahl_varianten, startzeitpunkt FROM meta")
    row = cursor.fetchone()
    assert row[0] == 1280
    assert row[1] == "2026-08-13T00:00:00Z"


def test_meta_upsert(conn):
    """Meta-Informationen koennen ueberschrieben werden."""
    set_meta(conn, anzahl_varianten=1280, startzeitpunkt="2026-08-13T00:00:00Z")
    set_meta(conn, anzahl_varianten=900, startzeitpunkt="2026-08-14T00:00:00Z")
    cursor = conn.execute("SELECT COUNT(*) FROM meta")
    assert cursor.fetchone()[0] == 1  # Nur ein Datensatz durch UPSERT
