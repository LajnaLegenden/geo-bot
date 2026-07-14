"""Apply plain .sql migrations in filename order, tracked by name. Roll-forward
only (no down-migrations) — a single-container app rolls forward, not back.

Called at startup (serve.py) against the real DB. `python -m geobot.migrate`
runs the self-check against an in-memory DB.
"""
from __future__ import annotations

import pathlib
import sqlite3

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"


def migrate(conn: sqlite3.Connection, migrations_dir: pathlib.Path | None = None) -> list[str]:
    """Apply every migrations/*.sql not yet recorded, in lexical order.
    Returns the filenames applied this run. Idempotent: re-running applies none."""
    d = migrations_dir or MIGRATIONS_DIR
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(filename TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    done = {r[0] for r in conn.execute("SELECT filename FROM schema_migrations")}
    applied = []
    for path in sorted(d.glob("*.sql")):
        if path.name in done:
            continue
        conn.executescript(path.read_text())  # implicit COMMIT precedes the script
        conn.execute("INSERT INTO schema_migrations(filename) VALUES (?)", (path.name,))
        conn.commit()
        applied.append(path.name)
    return applied


if __name__ == "__main__":  # python -m geobot.migrate — self-check
    c = sqlite3.connect(":memory:")
    first = migrate(c)
    assert first, f"first run should apply migrations, got {first}"
    assert migrate(c) == [], "second run must be a no-op"
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "credentials", "maps", "leagues", "games", "challenges", "scores"} <= tables, tables
    print("migrate ok:", ", ".join(first))
