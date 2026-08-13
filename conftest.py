"""Gemeinsame pytest-Fixtures fuer alle Paper-Trader-Tests."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from db import get_connection, init_schema


@pytest.fixture
def db_conn():
    """In-Memory-SQLite-Datenbank mit vollstaendigem Schema."""
    conn = get_connection(":memory:")
    init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Temporaeres Verzeichnis fuer Parquet-Testdateien."""
    d = tmp_path / "data"
    d.mkdir()
    return d
