"""Database connection helpers."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "bus_booking.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"


def get_connection(db_path=DB_PATH):
    """Open a connection in autocommit mode; transactions are explicit
    (see `transaction`). Use ':memory:' for tests."""
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    """Create all tables, indexes and views (safe to call repeatedly)."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


@contextmanager
def transaction(conn):
    """Run a block atomically.

    BEGIN IMMEDIATE takes the write lock up front, so two people trying to
    book the same seat at the same moment are handled one after the other.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
