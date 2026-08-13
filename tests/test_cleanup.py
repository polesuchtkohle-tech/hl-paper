"""Tests fuer cleanup.py."""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db import get_connection, init_schema
from cleanup import ausduennen_equity, pruefe_speicher, cleanup_durchfuehren


@pytest.fixture
def db_mit_equity(tmp_path):
    """DB mit Equity-Daten fuer verschiedene Zeitpunkte."""
    db_pfad = str(tmp_path / "test.db")
    conn = get_connection(db_pfad)
    init_schema(conn)

    # Konto anlegen
    conn.execute(
        "INSERT INTO konten (konto_id, n, tp, sl, hebel, status, kontostand) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("brk_20_1.0_0.5_5", 20, 1.0, 0.5, 5, "aktiv", 100.0)
    )

    # Alte Equity-Daten (40 Tage alt) mit verschiedenen Minuten
    alte_eintraege = [
        ("brk_20_1.0_0.5_5", "2026-07-01T00:00:00Z", 100.0),  # volle Stunde -> behalten
        ("brk_20_1.0_0.5_5", "2026-07-01T00:15:00Z", 100.5),  # 15 Minuten -> loeschen
        ("brk_20_1.0_0.5_5", "2026-07-01T01:00:00Z", 101.0),  # volle Stunde -> behalten
        ("brk_20_1.0_0.5_5", "2026-07-01T01:30:00Z", 101.5),  # 30 Minuten -> loeschen
    ]
    for kid, zeit, stand in alte_eintraege:
        conn.execute(
            "INSERT INTO equity (konto_id, zeit, kontostand) VALUES (?, ?, ?)",
            (kid, zeit, stand)
        )

    # Neue Equity-Daten (heute) -> duerfen nicht geloescht werden
    conn.execute(
        "INSERT INTO equity (konto_id, zeit, kontostand) VALUES (?, ?, ?)",
        ("brk_20_1.0_0.5_5", "2026-08-13T14:15:00Z", 102.0)  # heute, 15 Minuten
    )
    conn.commit()
    return conn, db_pfad


def test_ausduennen_loescht_nicht_volle_stunden(db_mit_equity):
    """Eintraege auf vollen Stunden muessen nach Ausduennung erhalten bleiben."""
    conn, _ = db_mit_equity
    ausduennen_equity(conn, vor_tagen=30)

    cursor = conn.execute(
        "SELECT zeit FROM equity WHERE zeit LIKE '2026-07-01%' ORDER BY zeit"
    )
    verbleibende = [row[0] for row in cursor.fetchall()]

    # Nur volle Stunden sollen uebrig bleiben
    assert "2026-07-01T00:00:00Z" in verbleibende
    assert "2026-07-01T01:00:00Z" in verbleibende

    # Nicht-volle-Stunden muessen weg sein
    assert "2026-07-01T00:15:00Z" not in verbleibende
    assert "2026-07-01T01:30:00Z" not in verbleibende


def test_ausduennen_belaesst_neue_daten(db_mit_equity):
    """Neuere Daten (< 30 Tage) duerfen nicht geloescht werden."""
    conn, _ = db_mit_equity
    ausduennen_equity(conn, vor_tagen=30)

    cursor = conn.execute(
        "SELECT COUNT(*) FROM equity WHERE zeit LIKE '2026-08-13%'"
    )
    assert cursor.fetchone()[0] == 1  # Heutiger Eintrag muss erhalten bleiben


def test_pruefe_speicher_gibt_dict(tmp_path):
    """Speichercheck gibt Dictionary mit erwarteten Feldern zurueck."""
    ergebnis = pruefe_speicher()
    assert "free_mb" in ergebnis
    assert "free_pct" in ergebnis
    assert "warnung" in ergebnis
    assert "kritisch" in ergebnis
    assert ergebnis["free_mb"] > 0
    assert 0 < ergebnis["free_pct"] <= 100


def test_cleanup_durchfuehren(tmp_path, db_mit_equity):
    """Vollstaendiger Cleanup laeuft ohne Fehler durch."""
    _, db_pfad = db_mit_equity
    ergebnis = cleanup_durchfuehren(db_pfad=db_pfad, vor_tagen=30)

    assert "equity_zeilen_geloescht" in ergebnis
    assert ergebnis["equity_zeilen_geloescht"] >= 0
    assert "speicher" in ergebnis
