"""SQLite connection + at-rest encryption for credential secrets.

One connection per thread: APScheduler jobs and Flask/waitress requests run on
different threads, and SQLite connections aren't safe to share across them.
WAL mode so a scheduled write never blocks a stats read; busy_timeout absorbs
the rare writer-vs-writer collision instead of throwing SQLITE_BUSY.
"""
from __future__ import annotations

import os
import sqlite3
import threading

from cryptography.fernet import Fernet

DB_PATH = os.environ.get("GEO_DB", "data/geobot.db")

_local = threading.local()
_fernet: Fernet | None = None


def _crypto() -> Fernet:
    # Lazy so migrations/tests can open a connection without the key set;
    # only credential encrypt/decrypt requires it. Raises loudly if missing —
    # we never fall back to storing secrets in plaintext.
    global _fernet
    if _fernet is None:
        key = os.environ["GEO_FERNET_KEY"]
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def conn() -> sqlite3.Connection:
    """This thread's connection, opened + PRAGMA-configured on first use."""
    c = getattr(_local, "conn", None)
    if c is None:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        c = sqlite3.connect(DB_PATH, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")   # off by default; needed for ON DELETE CASCADE
        c.execute("PRAGMA busy_timeout=5000")
        _local.conn = c
    return c


def encrypt(plain: str) -> str:
    return _crypto().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    return _crypto().decrypt(token.encode()).decode()
