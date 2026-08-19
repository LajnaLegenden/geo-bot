"""One-shot importer for the legacy data/store.json — NOT auto-run.

Maps each stored challenge's `map` value ("normal"/"fast") to a game of the same
name in the target league, so create those games first. Idempotent: challenges
upsert by (league_id, token) and per-token scores are wiped + reinserted, so
re-running never duplicates. Orphan scores / challenges whose map has no matching
game are skipped and counted.

Usage: python -m geobot.import_store <league_id> [store.json path]
"""
from __future__ import annotations

import json
import sys

from . import db, migrate, queries


def import_store(conn, league_id: int, path: str) -> tuple[int, int, int]:
    data = json.load(open(path))
    # Games are per-season; imported history predates everything, so it maps onto
    # the league's OLDEST season (whose window is open-ended at the front). In the
    # documented flow that's the only season there is.
    seasons = queries.list_seasons(conn, league_id)          # newest first
    games = {g["name"]: g["id"]
             for g in queries.list_games(conn, league_id, seasons[-1]["id"] if seasons else None)}
    scores_by_token: dict[str, list] = {}
    for s in data.get("scores", []):
        scores_by_token.setdefault(s["token"], []).append(s)

    challenges = scores = skipped = 0
    for c in data.get("challenges", []):
        gid = games.get(c.get("map") or "normal")
        if gid is None:  # no game named for this challenge's map — skip it and its scores
            skipped += 1
            continue
        conn.execute(
            "INSERT INTO challenges(league_id, game_id, token, date, url, countries) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(league_id, token) DO UPDATE SET "
            "date=excluded.date, url=excluded.url, "
            "countries=COALESCE(excluded.countries, challenges.countries)",
            (league_id, gid, c["token"], c["date"], c.get("url", ""),
             json.dumps(c["countries"]) if c.get("countries") else None),
        )
        challenges += 1
        conn.execute("DELETE FROM scores WHERE league_id=? AND token=?", (league_id, c["token"]))
        for s in scores_by_token.get(c["token"], []):
            conn.execute(
                "INSERT INTO scores(league_id, token, date, user_id, name, score, pin, guesses) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (league_id, c["token"], s.get("date") or c["date"], s.get("user_id"),
                 s["name"], s["score"], s.get("pin"),
                 json.dumps(s.get("guesses") or [])),
            )
            scores += 1
    conn.commit()
    return challenges, scores, skipped


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m geobot.import_store <league_id> [store.json path]", file=sys.stderr)
        sys.exit(1)
    league_id = int(sys.argv[1])
    path = sys.argv[2] if len(sys.argv) > 2 else "data/store.json"
    migrate.migrate(db.conn())
    ch, sc, sk = import_store(db.conn(), league_id, path)
    print(f"imported {ch} challenges, {sc} scores"
          + (f" ({sk} challenges skipped — no matching game name)" if sk else ""))
