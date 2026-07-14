"""One-shot: re-fetch every challenge in a league to recover per-round data
(guesses, countries, avatars) for old games. Manual, no leaderboard post.

Usage: python -m geobot.backfill <league_id>
"""
from __future__ import annotations

import sys

from . import db, jobs, migrate, queries


def backfill(league_id: int) -> None:
    conn = db.conn()
    league = conn.execute("SELECT * FROM leagues WHERE id=?", (league_id,)).fetchone()
    if not league:
        print("no such league", file=sys.stderr)
        return
    gg = jobs._client(conn, league)
    if gg is None or not gg.check_auth():
        print("missing GeoGuessr credential or invalid cookie", file=sys.stderr)
        return
    n = 0
    for token in queries.all_tokens(conn, league_id):
        try:
            queries.upsert_scores(conn, league_id, token, gg.highscores(token))
            n += 1
            print(f"backfilled {token}")
        except Exception as e:
            print(f"skip {token}: {e}", file=sys.stderr)
    print(f"done: {n} challenge(s)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m geobot.backfill <league_id>", file=sys.stderr)
        sys.exit(1)
    migrate.migrate(db.conn())
    backfill(int(sys.argv[1]))
