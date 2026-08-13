"""SQLite-Schema und Hilfsfunktionen fuer den Paper-Trader.

Dieses Modul verwaltet alle Datenbankoperationen:
- Schema anlegen (4 Tabellen: konten, trades, equity, meta)
- Daten einfuegen und lesen
- Kontostatus aktualisieren
"""

import sqlite3


def get_connection(db_path: str = "paper.db") -> sqlite3.Connection:
    """Verbindung zur SQLite-Datenbank herstellen.

    Verwendet WAL-Modus fuer bessere Performance bei gleichzeitigem Lesen.
    Row-Factory erlaubt dict-artigen Zugriff auf Spalten.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Alle Tabellen anlegen, falls sie nicht existieren.

    Tabellen:
    - konten: Alle simulierten Konten mit Parametern und aktuellem Zustand
    - trades: Abgeschlossene Trades mit allen Kostenarten einzeln
    - equity: Kontostand-Snapshots alle 15 Minuten
    - meta: Globale Metainformationen (Anzahl Varianten, Startzeit)
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS konten (
            konto_id          TEXT PRIMARY KEY,
            n                 INTEGER NOT NULL,
            tp                REAL NOT NULL,
            sl                REAL NOT NULL,
            hebel             INTEGER NOT NULL,
            status            TEXT NOT NULL DEFAULT 'aktiv',
            kontostand        REAL NOT NULL DEFAULT 100.0,
            strategie         TEXT NOT NULL DEFAULT 'breakout',
            warnung           TEXT,
            position_richtung TEXT,
            position_preis    REAL,
            position_zeit     TEXT,
            position_groesse   REAL,
            ruin_zeitpunkt     TEXT,
            ambivalente_kerzen INTEGER NOT NULL DEFAULT 0
        );

        -- Migration: Spalte nachtraeglich hinzufuegen falls DB schon existiert
        -- (SQLite ignoriert "duplicate column" nicht nativ, daher kein IF NOT EXISTS)
        -- Wird beim naechsten Schema-Init ausgefuehrt und ist idempotent da DEFAULT 0.

        CREATE TABLE IF NOT EXISTS trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            konto_id    TEXT NOT NULL,
            zeit_ein    TEXT NOT NULL,
            zeit_aus    TEXT NOT NULL,
            richtung    TEXT NOT NULL,
            preis_ein   REAL NOT NULL,
            preis_aus   REAL NOT NULL,
            exit_grund  TEXT NOT NULL,
            pnl_brutto  REAL NOT NULL,
            pnl_netto   REAL NOT NULL,
            fees        REAL NOT NULL,
            slippage    REAL NOT NULL,
            funding     REAL NOT NULL,
            FOREIGN KEY (konto_id) REFERENCES konten(konto_id)
        );

        CREATE INDEX IF NOT EXISTS idx_trades_konto
            ON trades(konto_id);

        CREATE TABLE IF NOT EXISTS equity (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            konto_id    TEXT NOT NULL,
            zeit        TEXT NOT NULL,
            kontostand  REAL NOT NULL,
            FOREIGN KEY (konto_id) REFERENCES konten(konto_id)
        );

        CREATE INDEX IF NOT EXISTS idx_equity_konto_zeit
            ON equity(konto_id, zeit);

        CREATE TABLE IF NOT EXISTS meta (
            id                INTEGER PRIMARY KEY CHECK (id = 1),
            anzahl_varianten  INTEGER NOT NULL,
            startzeitpunkt    TEXT NOT NULL
        );
    """)

    # Migration fuer bestehende DBs: Spalte hinzufuegen falls noch nicht vorhanden.
    # SQLite unterstuetzt kein ALTER TABLE ADD COLUMN IF NOT EXISTS, daher try/except.
    try:
        conn.execute(
            "ALTER TABLE konten ADD COLUMN ambivalente_kerzen INTEGER NOT NULL DEFAULT 0"
        )
    except Exception:
        pass  # Spalte existiert bereits

    conn.commit()


def insert_trade(
    conn: sqlite3.Connection,
    konto_id: str,
    zeit_ein: str,
    zeit_aus: str,
    richtung: str,
    preis_ein: float,
    preis_aus: float,
    exit_grund: str,
    pnl_brutto: float,
    pnl_netto: float,
    fees: float,
    slippage: float,
    funding: float,
) -> None:
    """Einen abgeschlossenen Trade in die Datenbank einfuegen.

    Alle Kostenarten werden einzeln gespeichert (fees, slippage, funding),
    damit spaetere Analysen genau sehen, was die Rendite gefressen hat.
    """
    conn.execute(
        "INSERT INTO trades "
        "(konto_id, zeit_ein, zeit_aus, richtung, preis_ein, preis_aus, "
        "exit_grund, pnl_brutto, pnl_netto, fees, slippage, funding) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            konto_id, zeit_ein, zeit_aus, richtung, preis_ein, preis_aus,
            exit_grund, pnl_brutto, pnl_netto, fees, slippage, funding,
        ),
    )
    conn.commit()


def insert_equity(
    conn: sqlite3.Connection,
    konto_id: str,
    zeit: str,
    kontostand: float,
) -> None:
    """Equity-Snapshot speichern (wird alle 15 Minuten aufgerufen).

    Speichert den aktuellen Kontostand fuer spaetere Equity-Kurven.
    """
    conn.execute(
        "INSERT INTO equity (konto_id, zeit, kontostand) VALUES (?, ?, ?)",
        (konto_id, zeit, kontostand),
    )
    conn.commit()


def get_konten(conn: sqlite3.Connection) -> list[dict]:
    """Alle Konten als Liste von Dictionaries zurueckgeben.

    Sortiert nach Kontostand absteigend (Beste zuerst).
    """
    cursor = conn.execute("SELECT * FROM konten ORDER BY kontostand DESC")
    return [dict(row) for row in cursor.fetchall()]


def get_equity_history(conn: sqlite3.Connection, konto_id: str) -> list[dict]:
    """Equity-Verlauf fuer ein bestimmtes Konto zurueckgeben.

    Chronologisch sortiert fuer Equity-Kurven.
    """
    cursor = conn.execute(
        "SELECT zeit, kontostand FROM equity "
        "WHERE konto_id = ? ORDER BY zeit",
        (konto_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def update_konto_status(
    conn: sqlite3.Connection,
    konto_id: str,
    status: str,
    kontostand: float,
    ruin_zeitpunkt: str | None = None,
) -> None:
    """Status und Kontostand eines Kontos aktualisieren.

    Wird aufgerufen wenn ein Konto ruiniert wird oder sich der
    Kontostand durch einen Trade aendert.
    """
    conn.execute(
        "UPDATE konten SET status = ?, kontostand = ?, ruin_zeitpunkt = ? "
        "WHERE konto_id = ?",
        (status, kontostand, ruin_zeitpunkt, konto_id),
    )
    conn.commit()


def set_meta(
    conn: sqlite3.Connection,
    anzahl_varianten: int,
    startzeitpunkt: str,
) -> None:
    """Meta-Informationen setzen oder aktualisieren (UPSERT).

    Es gibt immer nur einen Meta-Datensatz (id=1).
    """
    conn.execute(
        "INSERT INTO meta (id, anzahl_varianten, startzeitpunkt) "
        "VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "anzahl_varianten = excluded.anzahl_varianten, "
        "startzeitpunkt = excluded.startzeitpunkt",
        (anzahl_varianten, startzeitpunkt),
    )
    conn.commit()
