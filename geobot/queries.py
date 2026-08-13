"""Thin SQL helpers over the sqlite3 connection. No ORM.

Isolation rule: owned-resource reads take `user_id` (games go through their
league) and return None/[] on a miss so callers 404. Credential secrets are
encrypted going in and decrypted only via get_credential_secret().
"""
from __future__ import annotations

import json
import sqlite3

from . import db


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


# --- credentials ------------------------------------------------------------

def add_credential(conn, user_id, kind, label, secret_plain, meta=None) -> int:
    cur = conn.execute(
        "INSERT INTO credentials(user_id, kind, label, secret, meta) VALUES(?,?,?,?,?)",
        (user_id, kind, label, db.encrypt(secret_plain), meta),
    )
    conn.commit()
    return cur.lastrowid


def list_credentials(conn, user_id, kind=None) -> list[sqlite3.Row]:
    if kind:
        return conn.execute(
            "SELECT * FROM credentials WHERE user_id=? AND kind=? ORDER BY id", (user_id, kind)
        ).fetchall()
    return conn.execute(
        "SELECT * FROM credentials WHERE user_id=? ORDER BY kind, id", (user_id,)
    ).fetchall()


def get_credential(conn, cred_id, user_id) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM credentials WHERE id=? AND user_id=?", (cred_id, user_id)
    ).fetchone()


def get_credential_secret(conn, cred_id, user_id) -> str | None:
    row = get_credential(conn, cred_id, user_id)
    return db.decrypt(row["secret"]) if row else None


def slack_bot_credentials(conn, team_id: str | None = None) -> list[sqlite3.Row]:
    """Every bot-mode Slack credential, across all users — an inbound Slack
    interaction has no logged-in session to scope by, so ownership can't narrow this.
    `team_id` narrows to one workspace; the request *signature* is what actually
    authenticates (see blueprints/slack_bot.py), this only picks candidates.

    Filtered in Python rather than with json_extract so nothing depends on the
    SQLite build having JSON1; the table holds a handful of rows."""
    out = []
    for r in conn.execute("SELECT * FROM credentials WHERE kind='slack' ORDER BY id"):
        meta = json.loads(r["meta"]) if r["meta"] else {}
        if meta.get("mode") != "bot":
            continue
        if team_id and meta.get("team_id") != team_id:
            continue
        out.append(r)
    return out


def delete_credential(conn, cred_id, user_id) -> None:
    conn.execute("DELETE FROM credentials WHERE id=? AND user_id=?", (cred_id, user_id))
    conn.commit()


# --- maps -------------------------------------------------------------------

def add_map(conn, user_id, name, map_id, thumbnail) -> int:
    cur = conn.execute(
        "INSERT INTO maps(user_id, name, map_id, thumbnail) VALUES(?,?,?,?)",
        (user_id, name, map_id, thumbnail),
    )
    conn.commit()
    return cur.lastrowid


def list_maps(conn, user_id) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM maps WHERE user_id=? ORDER BY name", (user_id,)
    ).fetchall()


def get_map(conn, map_pk, user_id) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM maps WHERE id=? AND user_id=?", (map_pk, user_id)
    ).fetchone()


def delete_map(conn, map_pk, user_id) -> None:
    conn.execute("DELETE FROM maps WHERE id=? AND user_id=?", (map_pk, user_id))
    conn.commit()


# --- leagues ----------------------------------------------------------------

_LEAGUE_COLS = ("name", "transport_cred_id", "geo_cred_id", "cron_results", "tz",
                "public_slug", "pull_minutes", "cron_reminder", "reminder_title",
                "reminder_body", "slack_channel_id", "slack_channel_name",
                "reminder_delivery")
_LEAGUE_DEFAULTS = {"pull_minutes": 60, "cron_reminder": None, "public_slug": None,
                    "tz": "UTC", "reminder_title": "⏰ Still to play today",
                    "reminder_body": "", "slack_channel_id": None,
                    "slack_channel_name": None, "reminder_delivery": "channel"}


def _league_values(f: dict) -> list:
    """Column values in _LEAGUE_COLS order, defaulting anything the caller omitted.
    Keyword-style like add_game(**f) — the positional signature grew a parameter per
    migration, so the column list is the single place a new one gets added."""
    return [f.get(c, _LEAGUE_DEFAULTS.get(c)) for c in _LEAGUE_COLS]


def add_league(conn, user_id, **f) -> int:
    cols = ", ".join(_LEAGUE_COLS)
    marks = ", ".join("?" * len(_LEAGUE_COLS))
    cur = conn.execute(
        f"INSERT INTO leagues(user_id, {cols}) VALUES(?, {marks})",
        [user_id] + _league_values(f),
    )
    conn.commit()
    return cur.lastrowid


def list_leagues(conn, user_id) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM leagues WHERE user_id=? ORDER BY name", (user_id,)
    ).fetchall()


def get_league(conn, league_id, user_id) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM leagues WHERE id=? AND user_id=?", (league_id, user_id)
    ).fetchone()


def get_league_by_slug(conn, slug) -> sqlite3.Row | None:
    """Public lookup — only resolves leagues that opted into a public slug."""
    if not slug:
        return None
    return conn.execute(
        "SELECT * FROM leagues WHERE public_slug=?", (slug,)
    ).fetchone()


def all_leagues(conn) -> list[sqlite3.Row]:
    """Every league across all users — the scheduler builds results jobs from this."""
    return conn.execute("SELECT * FROM leagues").fetchall()


def update_league(conn, league_id, user_id, **f) -> None:
    sets = ", ".join(f"{c}=?" for c in _LEAGUE_COLS)
    conn.execute(
        f"UPDATE leagues SET {sets} WHERE id=? AND user_id=?",
        _league_values(f) + [league_id, user_id],
    )
    conn.commit()


def delete_league(conn, league_id, user_id) -> None:
    conn.execute("DELETE FROM leagues WHERE id=? AND user_id=?", (league_id, user_id))
    conn.commit()


# --- games ------------------------------------------------------------------

_GAME_COLS = ("name", "map_ref", "time_limit", "forbid_moving", "forbid_zooming",
              "forbid_rotating", "weight", "cron_challenge")


def add_game(conn, league_id, **f) -> int:
    cur = conn.execute(
        "INSERT INTO games(league_id, name, map_ref, time_limit, forbid_moving, "
        "forbid_zooming, forbid_rotating, weight, cron_challenge) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (league_id, f["name"], f["map_ref"], f["time_limit"], f["forbid_moving"],
         f["forbid_zooming"], f["forbid_rotating"], f["weight"], f["cron_challenge"]),
    )
    conn.commit()
    return cur.lastrowid


def list_games(conn, league_id) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT g.*, m.name AS map_name FROM games g JOIN maps m ON m.id=g.map_ref "
        "WHERE g.league_id=? ORDER BY g.name", (league_id,)
    ).fetchall()


def get_game(conn, game_id, league_id) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM games WHERE id=? AND league_id=?", (game_id, league_id)
    ).fetchone()


def update_game(conn, game_id, league_id, **f) -> None:
    conn.execute(
        "UPDATE games SET name=?, map_ref=?, time_limit=?, forbid_moving=?, "
        "forbid_zooming=?, forbid_rotating=?, weight=?, cron_challenge=? "
        "WHERE id=? AND league_id=?",
        (f["name"], f["map_ref"], f["time_limit"], f["forbid_moving"],
         f["forbid_zooming"], f["forbid_rotating"], f["weight"], f["cron_challenge"],
         game_id, league_id),
    )
    conn.commit()


def delete_game(conn, game_id, league_id) -> None:
    conn.execute("DELETE FROM games WHERE id=? AND league_id=?", (game_id, league_id))
    conn.commit()


def all_games(conn) -> list[sqlite3.Row]:
    """Every enabled game with its league (scheduler builds jobs from this)."""
    return conn.execute(
        "SELECT g.*, l.tz AS league_tz, l.enabled AS league_enabled "
        "FROM games g JOIN leagues l ON l.id=g.league_id"
    ).fetchall()


# --- challenges / scores ----------------------------------------------------

def add_challenge(conn, league_id, game_id, token, url, on, countries=None) -> None:
    conn.execute(
        "INSERT INTO challenges(league_id, game_id, token, date, url, countries) "
        "VALUES(?,?,?,?,?,?) ON CONFLICT(league_id, token) DO UPDATE SET "
        "date=excluded.date, url=excluded.url",
        (league_id, game_id, token, on, url,
         json.dumps(countries) if countries else None),
    )
    conn.commit()


def recent_tokens(conn, league_id, days=7) -> list[str]:
    return [r["token"] for r in conn.execute(
        "SELECT token FROM challenges WHERE league_id=? "
        "AND date >= date('now', ?) ORDER BY date", (league_id, f"-{int(days)} days")
    )]


def all_tokens(conn, league_id) -> list[str]:
    return [r["token"] for r in conn.execute(
        "SELECT token FROM challenges WHERE league_id=? ORDER BY date", (league_id,)
    )]


def game_id_for_token(conn, league_id, token) -> int | None:
    r = conn.execute(
        "SELECT game_id FROM challenges WHERE league_id=? AND token=?", (league_id, token)
    ).fetchone()
    return r["game_id"] if r else None


def upsert_scores(conn, league_id, token, result: dict) -> None:
    """Replace stored scores for a token with the fetched set (mirrors the old
    store.upsert_scores). Countries land on the challenge; pin+guesses per row."""
    countries = result.get("countries") or []
    if countries:  # don't wipe good data on an empty fetch
        conn.execute(
            "UPDATE challenges SET countries=? WHERE league_id=? AND token=?",
            (json.dumps(countries), league_id, token),
        )
    d = conn.execute(
        "SELECT date FROM challenges WHERE league_id=? AND token=?", (league_id, token)
    ).fetchone()
    date = d["date"] if d else None
    conn.execute("DELETE FROM scores WHERE league_id=? AND token=?", (league_id, token))
    for s in result["players"]:
        conn.execute(
            "INSERT INTO scores(league_id, token, date, user_id, name, score, pin, guesses) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (league_id, token, date, s["user_id"], s["name"], s["score"],
             s.get("pin"), json.dumps(s.get("guesses") or [])),
        )
    conn.commit()


# --- slack player links -----------------------------------------------------

def player_links(conn, league_id) -> dict[str, str]:
    """{player_key: slack_user_id} for a league — the join that turns a GeoGuessr
    name into an @-mention. player_key matches store.py's aggregation key."""
    return {r["player_key"]: r["slack_user_id"] for r in conn.execute(
        "SELECT player_key, slack_user_id FROM player_links WHERE league_id=?",
        (league_id,),
    )}


def link_player(conn, league_id, player_key, slack_user_id) -> None:
    """Bind a Slack user to a GeoGuessr player, replacing either side's old claim.

    A Slack user holds at most one player per league (UNIQUE index), so their
    previous claim is cleared first — without the DELETE, re-linking to a different
    player would trip the index instead of moving the link."""
    conn.execute(
        "DELETE FROM player_links WHERE league_id=? AND slack_user_id=?",
        (league_id, slack_user_id),
    )
    conn.execute(
        "INSERT INTO player_links(league_id, player_key, slack_user_id) VALUES(?,?,?) "
        "ON CONFLICT(league_id, player_key) DO UPDATE SET "
        "slack_user_id=excluded.slack_user_id, linked_at=datetime('now')",
        (league_id, player_key, slack_user_id),
    )
    conn.commit()


def attach_slack_ids(conn, league_id, rows: list[dict]) -> list[dict]:
    """Stamp `slack_user_id` onto any row whose `key` has been linked. Mutates and
    returns `rows`. Called from jobs.py so transports never touch the DB — both
    leaderboard rows and reminder entries carry a `key`, so one helper covers both."""
    links = player_links(conn, league_id)
    for r in rows:
        uid = links.get(r.get("key"))
        if uid:
            r["slack_user_id"] = uid
    return rows


# --- stats seam -------------------------------------------------------------

def load_league_data(conn, league_id) -> dict:
    """Rebuild the {'challenges', 'scores'} dict store.py's stat functions expect,
    scoped to one league. Each challenge is stamped with its game's `weight` and
    the game `name` (store.py's `map` field) so the combined weighted board + the
    per-game ('Maps') split work unchanged — a game is the new unit of play."""
    challenges = [
        {"token": r["token"], "date": r["date"], "url": r["url"],
         "countries": json.loads(r["countries"]) if r["countries"] else None,
         "weight": r["weight"], "map": r["game_name"]}
        for r in conn.execute(
            "SELECT c.token, c.date, c.url, c.countries, g.weight, g.name AS game_name "
            "FROM challenges c JOIN games g ON g.id=c.game_id "
            "WHERE c.league_id=? ORDER BY c.date",
            (league_id,),
        )
    ]
    scores = [
        {"token": r["token"], "date": r["date"], "user_id": r["user_id"],
         "name": r["name"], "score": r["score"], "pin": r["pin"],
         "guesses": json.loads(r["guesses"]) if r["guesses"] else []}
        for r in conn.execute(
            "SELECT * FROM scores WHERE league_id=? ORDER BY date", (league_id,)
        )
    ]
    return {"challenges": challenges, "scores": scores}
