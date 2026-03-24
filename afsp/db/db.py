"""Database initialisation and connection management for AFSP."""

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = "/var/afsp/db/afsp.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_db_path() -> str:
    return os.environ.get("AFSP_DB_PATH", DEFAULT_DB_PATH)


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str | None = None) -> sqlite3.Connection:
    conn = get_connection(db_path)
    schema = SCHEMA_PATH.read_text()
    conn.executescript(schema)
    conn.commit()
    return conn
