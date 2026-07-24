"""In-process APScheduler. One BackgroundScheduler for the whole app, built from
the DB on startup and kept in sync as leagues/games are saved/deleted.

The DB is the source of truth — the job store is just a cache rebuilt by start()
on every boot, so a missed on_*_saved call self-heals on restart. Sync helpers
no-op when the scheduler isn't running (tests, imports), so config CRUD never
depends on it.

MUST run in a single process. Behind a multi-worker WSGI server every worker
would start its own scheduler and each job would fire once per worker — so
serve.py uses waitress (one process, many threads).
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from . import cron_builder, db, jobs, queries

_scheduler: BackgroundScheduler | None = None
_JOB_DEFAULTS = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600}

_GAME_ROW = (
    "SELECT g.*, l.tz AS league_tz, l.enabled AS league_enabled "
    "FROM games g JOIN leagues l ON l.id=g.league_id"
)


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _trigger(expr: str, tz_name: str) -> CronTrigger:
    p = cron_builder.parse_cron(expr)
    return CronTrigger(
        day_of_week=",".join(p["days"]) or None,
        hour=p["hour"], minute=p["minute"], timezone=_tz(tz_name),
    )


def start() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(job_defaults=_JOB_DEFAULTS)
        _scheduler.start()
        reload_all()
    return _scheduler


def reload_all() -> None:
    if _scheduler is None:
        return
    for league in queries.all_leagues(db.conn()):
        _sync_league(league)
    for game in queries.all_games(db.conn()):
        _sync_game(game)


def _remove(job_id: str) -> None:
    try:
        _scheduler.remove_job(job_id)
    except Exception:
        pass


def _sync_league(league) -> None:
    lid = league["id"]
    post_id, pull_id = f"league:{lid}:post", f"league:{lid}:pull"
    rem_id = f"league:{lid}:reminder"
    if not league["enabled"]:
        _remove(post_id); _remove(pull_id); _remove(rem_id)
        return
    # daily Slack post
    _scheduler.add_job(
        jobs.post_leaderboard, _trigger(league["cron_results"], league["tz"]),
        args=[lid], id=post_id, replace_existing=True,
    )
    # frequent silent pull (0 = off)
    minutes = league["pull_minutes"] or 0
    if minutes > 0:
        _scheduler.add_job(
            jobs.pull_results, IntervalTrigger(minutes=minutes),
            args=[lid], id=pull_id, replace_existing=True,
        )
    else:
        _remove(pull_id)
    # optional "still to play" reminder (NULL cron = off)
    if league["cron_reminder"]:
        _scheduler.add_job(
            jobs.send_reminder, _trigger(league["cron_reminder"], league["tz"]),
            args=[lid], id=rem_id, replace_existing=True,
        )
    else:
        _remove(rem_id)


def _sync_game(g) -> None:
    jid = f"game:{g['id']}:challenge"
    if g["enabled"] and g["league_enabled"]:
        _scheduler.add_job(
            jobs.post_challenge, _trigger(g["cron_challenge"], g["league_tz"]),
            args=[g["league_id"], g["id"]], id=jid, replace_existing=True,
        )
    else:
        _remove(jid)


# --- hooks the blueprints call after a save/delete ---------------------------

def on_league_saved(league_id: int) -> None:
    if _scheduler is None:
        return
    league = db.conn().execute("SELECT * FROM leagues WHERE id=?", (league_id,)).fetchone()
    if not league:
        return
    _sync_league(league)
    for g in db.conn().execute(_GAME_ROW + " WHERE g.league_id=?", (league_id,)):
        _sync_game(g)


def on_league_deleted(league_id: int, game_ids: list[int]) -> None:
    if _scheduler is None:
        return
    _remove(f"league:{league_id}:post")
    _remove(f"league:{league_id}:pull")
    _remove(f"league:{league_id}:reminder")
    for gid in game_ids:
        _remove(f"game:{gid}:challenge")


def on_game_saved(league_id: int, game_id: int) -> None:
    if _scheduler is None:
        return
    row = db.conn().execute(_GAME_ROW + " WHERE g.id=?", (game_id,)).fetchone()
    if row:
        _sync_game(row)


def on_game_deleted(game_id: int) -> None:
    if _scheduler is None:
        return
    _remove(f"game:{game_id}:challenge")


def get_jobs() -> list:
    return _scheduler.get_jobs() if _scheduler else []


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
