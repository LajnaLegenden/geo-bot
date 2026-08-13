"""Actions shared by the scheduler and the 'Run now' buttons: create a challenge
for one game, and fetch scores + post the leaderboard for one league. The real
GeoGuessr + transport network work happens here; each call runs on its own DB
thread (an APScheduler worker or a Flask request thread).
"""
from __future__ import annotations

import datetime
import json
import os
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
    """(transport, dest) for a league's channel, or (None, None) if it can't deliver.

    Bot-mode Slack credentials hold *two* secrets, so their `secret` column is an
    encrypted JSON blob rather than the bare webhook URL the other modes store; the
    channel and reminder delivery come off the league, not the credential."""
    cred = queries.get_credential(conn, league["transport_cred_id"], league["user_id"])
    if not cred:
        return None, None
    meta = json.loads(cred["meta"]) if cred["meta"] else {}
    dest = {**meta, "league_id": league["id"]}
    if meta.get("mode") == "bot":
        dest.update(json.loads(db.decrypt(cred["secret"])))
        dest["channel_id"] = league["slack_channel_id"]
        dest["delivery"] = league["reminder_delivery"]
        if not dest["channel_id"]:
            return None, None      # a bot credential with no channel bound yet
    else:
        dest["url"] = db.decrypt(cred["secret"])
    return transports.get(cred["kind"]), dest


_NO_DEST = "missing credential (or no Slack channel bound to the league)"


def _links(league, data) -> dict:
    """Clickable-button targets for the leaderboard post. Stats needs the app's
    public URL (BASE_URL env) + the league's opted-in public slug; omitted (None)
    if either is missing so we never post a dead link. Challenges are ORDER BY
    date, so the last one is the newest."""
    base = (os.environ.get("BASE_URL") or "").rstrip("/")
    stats_url = (
        f"{base}/s/{league['public_slug']}" if base and league["public_slug"] else None
    )
    challenge_url = data["challenges"][-1]["url"] if data["challenges"] else None
    return {"stats_url": stats_url, "challenge_url": challenge_url}


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
        return _NO_DEST + " or map"
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


def _fetch_scores(conn, league_id, gg) -> int:
    """Fetch highscores for recent challenges and upsert them. No posting."""
    n = 0
    for token in queries.recent_tokens(conn, league_id, days=7):
        try:
            queries.upsert_scores(conn, league_id, token, gg.highscores(token))
            n += 1
        except Exception as e:  # one bad token shouldn't sink the run
            print(f"skip {token}: {e}")
    return n


def pull_results(league_id: int) -> str:
    """Refresh scores into the DB (keeps stats pages fresh). Never posts to Slack.
    Runs on the league's `pull_minutes` interval + the 'Pull now' button."""
    conn = db.conn()
    league = conn.execute("SELECT * FROM leagues WHERE id=?", (league_id,)).fetchone()
    if not league:
        return "league no longer exists"
    gg = _client(conn, league)
    transport, dest = _transport(conn, league)
    if gg is None:
        return "missing GeoGuessr credential"
    if not gg.check_auth():
        if transport is not None:
            transport.send_alert(dest, "cookie_expired")
        return "GeoGuessr cookie invalid"
    return f"pulled {_fetch_scores(conn, league_id, gg)} challenge(s)"


def post_leaderboard(league_id: int) -> str:
    """Post the current weekly leaderboard to the channel — the once/day action.
    Does one courtesy pull first so the posted board is up-to-the-minute."""
    conn = db.conn()
    league = conn.execute("SELECT * FROM leagues WHERE id=?", (league_id,)).fetchone()
    if not league:
        return "league no longer exists"
    gg = _client(conn, league)
    transport, dest = _transport(conn, league)
    if gg is None or transport is None:
        return _NO_DEST
    if not gg.check_auth():
        transport.send_alert(dest, "cookie_expired")
        return "GeoGuessr cookie invalid"
    n = _fetch_scores(conn, league_id, gg)  # courtesy pull before posting
    data = queries.load_league_data(conn, league_id)
    rows = queries.attach_slack_ids(conn, league_id, store.weekly_leaderboard(data))
    transport.send_leaderboard(dest, rows, league["name"], _links(league, data))
    return f"pulled {n}, posted leaderboard"


def refresh_leaderboard(league_id: int, channel_id: str, message_ts: str) -> str:
    """The 🔄 Refresh button: re-pull, then edit the existing post in place instead of
    adding another one.

    Runs on a scheduler thread, not the request thread — Slack wants an interaction
    acked within 3s and a GeoGuessr pull takes longer (see scheduler.run_soon). A
    dead cookie skips the pull rather than alerting: the click already has a visible
    outcome, and the scheduled jobs are what should be nagging about credentials."""
    conn = db.conn()
    league = conn.execute("SELECT * FROM leagues WHERE id=?", (league_id,)).fetchone()
    if not league:
        return "league no longer exists"
    gg = _client(conn, league)
    transport, dest = _transport(conn, league)
    if transport is None or dest.get("mode") != "bot":
        return "not a bot-mode league"
    if gg is not None and gg.check_auth():
        _fetch_scores(conn, league_id, gg)
    data = queries.load_league_data(conn, league_id)
    rows = queries.attach_slack_ids(conn, league_id, store.weekly_leaderboard(data))
    dest["channel_id"] = channel_id  # edit the message where it was actually clicked
    transport.update_leaderboard(dest, rows, _links(league, data), message_ts)
    return "refreshed leaderboard"


def send_reminder(league_id: int) -> str:
    """Nag this-week's players who haven't finished all of today's challenges.
    Courtesy-pulls fresh scores first so "played today" is current; sends nothing
    when nobody's missing (no challenges today, or everyone's played them all)."""
    conn = db.conn()
    league = conn.execute("SELECT * FROM leagues WHERE id=?", (league_id,)).fetchone()
    if not league:
        return "league no longer exists"
    gg = _client(conn, league)
    transport, dest = _transport(conn, league)
    if gg is None or transport is None:
        return _NO_DEST
    if not gg.check_auth():
        transport.send_alert(dest, "cookie_expired")
        return "GeoGuessr cookie invalid"
    _fetch_scores(conn, league_id, gg)  # so "played today" reflects the latest scores
    data = queries.load_league_data(conn, league_id)
    entries = store.players_not_played_today(data, _today(league["tz"]))
    if not entries:
        return "nobody to remind"
    # Players who linked themselves become real @-mentions; the rest stay plain text.
    queries.attach_slack_ids(conn, league_id, entries)
    title = league["reminder_title"] or "⏰ Still to play today"
    # entries is non-empty => there's a challenge dated today, so this is one of them
    play_url = _links(league, data)["challenge_url"]
    transport.send_reminder(dest, title, league["reminder_body"] or "", entries, play_url)
    pinged = sum(1 for e in entries if e.get("slack_user_id"))
    return f"reminded {len(entries)} player(s), {pinged} @-mentioned"
