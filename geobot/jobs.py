"""Actions shared by the scheduler and the 'Run now' buttons: create a challenge
for one game, and fetch scores + post the leaderboard for one league. The real
GeoGuessr + transport network work happens here; each call runs on its own DB
thread (an APScheduler worker or a Flask request thread).
"""
from __future__ import annotations

import datetime
import json
from zoneinfo import ZoneInfo

from . import db, queries, store, transports
from .geoguessr import GeoGuessr


def _today(tz_name: str) -> str:
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.datetime.now(tz).date().isoformat()


def _client(conn, league) -> GeoGuessr | None:
    cred = queries.get_credential(conn, league["geo_cred_id"], league["user_id"])
    return GeoGuessr(db.decrypt(cred["secret"])) if cred else None


def _transport(conn, league):
    cred = queries.get_credential(conn, league["transport_cred_id"], league["user_id"])
    if not cred:
        return None, None
    meta = json.loads(cred["meta"]) if cred["meta"] else {}
    dest = {"url": db.decrypt(cred["secret"]), **meta}
    return transports.get(cred["kind"]), dest


def post_challenge(league_id: int, game_id: int) -> str:
    conn = db.conn()
    league = conn.execute("SELECT * FROM leagues WHERE id=?", (league_id,)).fetchone()
    game = conn.execute(
        "SELECT * FROM games WHERE id=? AND league_id=?", (game_id, league_id)
    ).fetchone()
    if not league or not game:
        return "league/game no longer exists"
    m = conn.execute("SELECT map_id FROM maps WHERE id=?", (game["map_ref"],)).fetchone()
    gg = _client(conn, league)
    transport, dest = _transport(conn, league)
    if gg is None or transport is None or m is None:
        return "missing credential or map"
    if not gg.check_auth():
        transport.send_alert(dest, "cookie_expired")
        return "GeoGuessr cookie invalid"
    token = gg.create_challenge(
        map_id=m["map_id"],
        time_limit=game["time_limit"],
        forbid_moving=bool(game["forbid_moving"]),
        forbid_zooming=bool(game["forbid_zooming"]),
        forbid_rotating=bool(game["forbid_rotating"]),
    )
    url = gg.challenge_url(token)
    queries.add_challenge(conn, league_id, game_id, token, url, _today(league["tz"]))
    transport.send_challenge(dest, url, league["name"])
    return f"posted challenge {token}"


def post_results(league_id: int) -> str:
    conn = db.conn()
    league = conn.execute("SELECT * FROM leagues WHERE id=?", (league_id,)).fetchone()
    if not league:
        return "league no longer exists"
    gg = _client(conn, league)
    transport, dest = _transport(conn, league)
    if gg is None or transport is None:
        return "missing credential"
    if not gg.check_auth():
        transport.send_alert(dest, "cookie_expired")
        return "GeoGuessr cookie invalid"
    n = 0
    for token in queries.recent_tokens(conn, league_id, days=7):
        try:
            queries.upsert_scores(conn, league_id, token, gg.highscores(token))
            n += 1
        except Exception as e:  # one bad token shouldn't sink the run
            print(f"skip {token}: {e}")
    rows = store.weekly_leaderboard(queries.load_league_data(conn, league_id))
    transport.send_leaderboard(dest, rows, league["name"])
    return f"updated {n} challenge(s), posted leaderboard"
