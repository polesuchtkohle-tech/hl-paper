"""Tests fuer status.py Terminal-Uebersicht."""

import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db import get_connection, init_schema
from status import render_status


@pytest.fixture
def db_mit_daten(tmp_path):
    """Datenbank mit Testdaten fuer Status-Ausgabe."""
    db_pfad = str(tmp_path / "test.db")
    conn = get_connection(db_pfad)
    init_schema(conn)

    # Konten einfuegen
    konten = [
        # (konto_id, n, tp, sl, hebel, status, kontostand, strategie)
        ("brk_10_5.0_0.2_25", 10, 5.0, 0.2, 25, "aktiv",    234.50, "breakout"),
        ("brk_20_1.0_0.5_5",  20, 1.0, 0.5,  5, "aktiv",    115.30, "breakout"),
        ("brk_50_2.0_1.0_3",  50, 2.0, 1.0,  3, "aktiv",    102.10, "breakout"),
        ("brk_10_0.3_0.2_1",  10, 0.3, 0.2,  1, "ruiniert",   0.00, "breakout"),
        ("bah_0_0_0_1",        0, 0.0, 0.0,  1, "aktiv",    142.30, "buy_and_hold"),
        ("rnd_0_0_0_1",        0, 0.0, 0.0,  1, "aktiv",    101.20, "zufall"),
    ]
    for k in konten:
        conn.execute(
            "INSERT INTO konten (konto_id, n, tp, sl, hebel, status, kontostand, strategie) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", k
        )
    conn.commit()
    conn.close()
    return db_pfad


def test_render_status_nicht_leer(db_mit_daten):
    """Status-Ausgabe darf nicht leer sein."""
    ausgabe = render_status(db_pfad=db_mit_daten)
    assert len(ausgabe) > 100


def test_render_status_enthaelt_top_konto(db_mit_daten):
    """Das beste Konto muss in der Ausgabe erscheinen."""
    ausgabe = render_status(db_pfad=db_mit_daten)
    assert "234" in ausgabe  # Top-Kontostand


def test_render_status_enthaelt_ruinquote(db_mit_daten):
    """Ruinquote-Tabelle muss enthalten sein."""
    ausgabe = render_status(db_pfad=db_mit_daten)
    assert "Ruin" in ausgabe or "ruin" in ausgabe


def test_render_status_enthaelt_zufallsschwelle(db_mit_daten):
    """Zufallsschwelle (sqrt(2*ln(M))) muss erwaehnt werden."""
    ausgabe = render_status(db_pfad=db_mit_daten)
    assert "Schwelle" in ausgabe or "schwelle" in ausgabe or "Sigma" in ausgabe


def test_render_status_enthaelt_bah_vergleich(db_mit_daten):
    """Buy-and-Hold-Vergleich muss enthalten sein."""
    ausgabe = render_status(db_pfad=db_mit_daten)
    assert "Buy" in ausgabe or "Hold" in ausgabe or "BaH" in ausgabe


def test_render_status_ohne_konten(tmp_path):
    """Auch ohne Daten kein Absturz."""
    db_pfad = str(tmp_path / "leer.db")
    conn = get_connection(db_pfad)
    init_schema(conn)
    conn.close()
    ausgabe = render_status(db_pfad=db_pfad)
    assert isinstance(ausgabe, str)
