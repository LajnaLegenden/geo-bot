"""Thin SQL helpers over the sqlite3 connection. No ORM. Owned-resource reads
take `user_id` and return None/[] on a miss so callers can 404 for isolation.

Grows per phase; this file starts with users/auth and gains credentials, maps,
leagues, games, challenges, scores, and the `load_league_data` stats seam.
"""
from __future__ import annotations

import sqlite3


# --- users / auth -----------------------------------------------------------

def create_user(conn: sqlite3.Connection, email: str, password_hash: str) -> int:
    cur = conn.execute(
        "INSERT INTO users(email, password_hash) VALUES(?, ?)", (email, password_hash)
    )
    conn.commit()
    return cur.lastrowid


def get_user_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def get_user(conn: sqlite3.Connection, uid: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
