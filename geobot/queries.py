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

def add_league(conn, user_id, name, transport_cred_id, geo_cred_id,
               cron_results, tz, public_slug, pull_minutes=60,
               cron_reminder=None, reminder_title="⏰ Still to play today",
               reminder_body="") -> int:
    cur = conn.execute(
        "INSERT INTO leagues(user_id, name, transport_cred_id, geo_cred_id, "
        "cron_results, tz, public_slug, pull_minutes, cron_reminder, "
        "reminder_title, reminder_body) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, name, transport_cred_id, geo_cred_id, cron_results, tz,
         public_slug, pull_minutes, cron_reminder, reminder_title, reminder_body),
    )
    # Keep "a league always has >= 1 season" true for new leagues too, the way
    # migration 0005 made it true for existing ones. Season 1 is open-ended at
    # the front (season_window), so history imported later still counts.
    conn.execute(
        "INSERT INTO seasons(league_id, name, starts_on) "
        "VALUES(?, 'Season 1', date('now'))",
        (cur.lastrowid,),
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


def update_league(conn, league_id, user_id, name, transport_cred_id, geo_cred_id,
                  cron_results, tz, public_slug, pull_minutes=60,
                  cron_reminder=None, reminder_title="⏰ Still to play today",
                  reminder_body="") -> None:
    conn.execute(
        "UPDATE leagues SET name=?, transport_cred_id=?, geo_cred_id=?, "
        "cron_results=?, tz=?, public_slug=?, pull_minutes=?, cron_reminder=?, "
        "reminder_title=?, reminder_body=? WHERE id=? AND user_id=?",
        (name, transport_cred_id, geo_cred_id, cron_results, tz, public_slug,
         pull_minutes, cron_reminder, reminder_title, reminder_body,
         league_id, user_id),
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


# --- seasons ----------------------------------------------------------------
#
# A season is defined only by where it starts: it runs from `starts_on`
# (inclusive) to the next season's `starts_on` (exclusive). No end column to keep
# in sync, and gaps/overlaps are impossible. See migrations/0005_seasons.sql.

def add_season(conn, league_id, name, starts_on) -> int:
    cur = conn.execute(
        "INSERT INTO seasons(league_id, name, starts_on) VALUES(?,?,?)",
        (league_id, name, starts_on),
    )
    conn.commit()
    return cur.lastrowid


def list_seasons(conn, league_id) -> list[sqlite3.Row]:
    """Newest first, each row carrying a derived `ends_on` (NULL on the newest —
    it has no successor to end against). `ends_on` is display-only; the filter
    uses the successor's `starts_on` exclusively, see season_window()."""
    return conn.execute(
        "SELECT id, name, starts_on, date(next_start, '-1 day') AS ends_on FROM ("
        "  SELECT id, name, starts_on,"
        "         LEAD(starts_on) OVER (ORDER BY starts_on) AS next_start"
        "  FROM seasons WHERE league_id=?"
        ") ORDER BY starts_on DESC, id DESC",
        (league_id,),
    ).fetchall()


def get_season(conn, season_id, league_id) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM seasons WHERE id=? AND league_id=?", (season_id, league_id)
    ).fetchone()


def current_season(conn, league_id) -> sqlite3.Row | None:
    """The live season: the latest one that has already started. A future-dated
    season is therefore 'upcoming' and becomes current on its own date — no
    scheduler job rolls seasons over, the calendar does."""
    return conn.execute(
        "SELECT * FROM seasons WHERE league_id=? AND starts_on <= date('now') "
        "ORDER BY starts_on DESC, id DESC LIMIT 1",
        (league_id,),
    ).fetchone()


def season_window(conn, season_id, league_id) -> tuple[str | None, str | None]:
    """(since, until) date bounds for load_league_data — `until` exclusive.

    The *oldest* season gets since=None so it absorbs anything dated before it:
    a league created today starts its Season 1 today, and MIGRATION.md's flow
    imports history afterwards. Open-ended at the front means no score can fall
    into a gap between "before all seasons" and season 1."""
    row = conn.execute(
        "SELECT starts_on,"
        "       (SELECT MIN(starts_on) FROM seasons"
        "         WHERE league_id=s.league_id AND starts_on > s.starts_on) AS next_start,"
        "       (SELECT MIN(starts_on) FROM seasons WHERE league_id=s.league_id) AS first_start "
        "FROM seasons s WHERE s.id=? AND s.league_id=?",
        (season_id, league_id),
    ).fetchone()
    if row is None:
        return None, None
    since = None if row["starts_on"] == row["first_start"] else row["starts_on"]
    return since, row["next_start"]


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


# --- raw row dump (the /data inspector) --------------------------------------

def league_dump(conn, league_id) -> dict[str, list[sqlite3.Row]]:
    """Every row this league owns, exactly as stored, newest first where there's
    a date. The template renders columns straight off `row.keys()`, so a later
    migration that adds a column shows up here without touching this function.
    Names are joined in where an id alone tells you nothing (map, game)."""
    def q(sql):
        return conn.execute(sql, (league_id,)).fetchall()

    return {
        "games": q("SELECT g.*, m.name AS map_name FROM games g "
                   "JOIN maps m ON m.id=g.map_ref WHERE g.league_id=? ORDER BY g.id"),
        "seasons": q("SELECT * FROM seasons WHERE league_id=? "
                     "ORDER BY starts_on DESC, id DESC"),
        "challenges": q("SELECT c.*, g.name AS game FROM challenges c "
                        "JOIN games g ON g.id=c.game_id WHERE c.league_id=? "
                        "ORDER BY c.date DESC, c.token"),
        "scores": q("SELECT * FROM scores WHERE league_id=? "
                    "ORDER BY date DESC, score DESC"),
    }


# --- stats seam -------------------------------------------------------------

def load_league_data(conn, league_id, since=None, until=None) -> dict:
    """Rebuild the {'challenges', 'scores'} dict store.py's stat functions expect,
    scoped to one league. Each challenge is stamped with its game's `weight` and
    the game `name` (store.py's `map` field) so the combined weighted board + the
    per-game ('Maps') split work unchanged — a game is the new unit of play.

    `since`/`until` are optional ISO dates narrowing it to one season (`until`
    exclusive, i.e. the next season's `starts_on`) — see season_window(). Both
    default to None = the league's whole history, so every stat function becomes
    season-scoped from this one place without knowing seasons exist."""
    # one predicate, spelled twice because the challenges query is aliased `c`
    args = [league_id]
    window = ""
    if since:
        window, args = window + " AND {p}date>=?", args + [since]
    if until:
        window, args = window + " AND {p}date<?", args + [until]
    challenges = [
        {"token": r["token"], "date": r["date"], "url": r["url"],
         "countries": json.loads(r["countries"]) if r["countries"] else None,
         "weight": r["weight"], "map": r["game_name"]}
        for r in conn.execute(
            "SELECT c.token, c.date, c.url, c.countries, g.weight, g.name AS game_name "
            "FROM challenges c JOIN games g ON g.id=c.game_id "
            "WHERE c.league_id=?" + window.format(p="c.") + " ORDER BY c.date",
            args,
        )
    ]
    scores = [
        {"token": r["token"], "date": r["date"], "user_id": r["user_id"],
         "name": r["name"], "score": r["score"], "pin": r["pin"],
         "guesses": json.loads(r["guesses"]) if r["guesses"] else []}
        for r in conn.execute(
            "SELECT * FROM scores WHERE league_id=?" + window.format(p="")
            + " ORDER BY date", args
        )
    ]
    return {"challenges": challenges, "scores": scores}


if __name__ == "__main__":  # python -m geobot.queries — self-check (in-memory DB)
    import sqlite3 as _s
    from . import migrate as _m

    c = _s.connect(":memory:")
    c.row_factory = _s.Row
    _m.migrate(c)
    c.execute("INSERT INTO users(id, email, password_hash) VALUES(1,'a@b','x')")
    c.execute("INSERT INTO credentials(id,user_id,kind,label,secret) "
              "VALUES(1,1,'slack','s','x'),(2,1,'geoguessr','g','x')")
    c.execute("INSERT INTO maps(id,user_id,name,map_id) VALUES(1,1,'m','m')")
    lid = add_league(c, 1, "L", 1, 2, "0 9 * * mon", "UTC", None)
    assert [r["name"] for r in list_seasons(c, lid)] == ["Season 1"], "new league seeds Season 1"

    c.execute("DELETE FROM seasons WHERE league_id=?", (lid,))
    s1 = add_season(c, lid, "Season 1", "2026-07-06")   # oldest -> open-ended front
    s2 = add_season(c, lid, "Season 2", "2026-07-13")
    s3 = add_season(c, lid, "Season 3", "2099-01-01")   # future-dated -> upcoming
    c.execute("INSERT INTO games(id,league_id,name,map_ref,cron_challenge) "
              "VALUES(1,?,'normal',1,'0 9 * * mon')", (lid,))
    gid = 1
    for i, d in enumerate(["2026-07-01", "2026-07-08", "2026-07-15"]):  # 07-01 predates S1
        add_challenge(c, lid, gid, f"t{i}", "u", d)
        c.execute("INSERT INTO scores(league_id,token,date,user_id,name,score) "
                  "VALUES(?,?,?,'u1','Ann',100)", (lid, f"t{i}", d))
    c.commit()

    assert season_window(c, s1, lid) == (None, "2026-07-13"), season_window(c, s1, lid)
    assert season_window(c, s2, lid) == ("2026-07-13", "2099-01-01")
    assert season_window(c, s3, lid) == ("2099-01-01", None)
    assert current_season(c, lid)["id"] == s2, "the future season must not be current"
    assert get_season(c, s1, lid + 1) is None, "seasons are league-scoped"

    def _dates(*w):
        return sorted(r["date"] for r in load_league_data(c, lid, *w)["scores"])

    # S1 absorbs the pre-S1 challenge; S2 sees only its own; unbounded sees all.
    assert _dates(*season_window(c, s1, lid)) == ["2026-07-01", "2026-07-08"]
    assert _dates(*season_window(c, s2, lid)) == ["2026-07-15"]
    assert _dates(*season_window(c, s3, lid)) == []
    assert _dates() == ["2026-07-01", "2026-07-08", "2026-07-15"]
    assert len(load_league_data(c, lid, *season_window(c, s1, lid))["challenges"]) == 2

    dump = league_dump(c, lid)
    assert [t for t, rs in dump.items() if not rs] == [], dump      # every table populated
    assert [r["date"] for r in dump["scores"]] == ["2026-07-15", "2026-07-08", "2026-07-01"]
    assert dump["challenges"][0]["game"] == "normal", "id-only columns get a name joined in"
    assert "guesses" in dump["scores"][0].keys(), "columns come straight off the row"

    rows = list_seasons(c, lid)
    assert [r["name"] for r in rows] == ["Season 3", "Season 2", "Season 1"], "newest first"
    assert rows[0]["ends_on"] is None and rows[1]["ends_on"] == "2098-12-31"
    assert rows[2]["ends_on"] == "2026-07-12"
    print("queries ok")
