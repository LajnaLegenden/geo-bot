"""Offline DB-seam checks for the Slack bot schema: migration 0004, the keyword-style
league writers, and the player_links join that turns a GeoGuessr name into an
@-mention. In-memory SQLite, no network.

Run: python -m tests.test_player_links (from the repo root) or pytest.
"""
import os
import sqlite3

from cryptography.fernet import Fernet

# db.encrypt needs a key; generate a throwaway one before importing (no real secrets).
os.environ.setdefault("GEO_FERNET_KEY", Fernet.generate_key().decode())

from geobot import migrate, queries, store  # noqa: E402


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    migrate.migrate(c)
    return c


def _league(c, **over):
    uid = queries.create_user(c, "a@b.c", "x")
    tc = queries.add_credential(c, uid, "slack", "bot", "tok", '{"mode":"bot"}')
    gc = queries.add_credential(c, uid, "geoguessr", "cookie", "ncfa")
    f = {"name": "Daily", "transport_cred_id": tc, "geo_cred_id": gc,
         "cron_results": "0 18 * * *", **over}
    return uid, queries.add_league(c, uid, **f)


def test_migration_adds_columns_and_table():
    c = _conn()
    cols = {r["name"] for r in c.execute("PRAGMA table_info(leagues)")}
    assert {"slack_channel_id", "slack_channel_name", "reminder_delivery"} <= cols, cols
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "player_links" in tables


def test_league_writers_default_omitted_columns():
    """add_league/update_league take **f, so a caller that doesn't know about a new
    column still gets the schema default rather than a TypeError."""
    c = _conn()
    _, lid = _league(c)
    row = c.execute("SELECT * FROM leagues WHERE id=?", (lid,)).fetchone()
    assert row["pull_minutes"] == 60 and row["tz"] == "UTC"
    assert row["reminder_delivery"] == "channel" and row["slack_channel_id"] is None
    assert row["cron_reminder"] is None and row["public_slug"] is None


def test_channel_binding_round_trips():
    c = _conn()
    uid, lid = _league(c, slack_channel_id="C0ABC", slack_channel_name="geo-guessr",
                       reminder_delivery="both")
    row = queries.get_league(c, lid, uid)
    assert row["slack_channel_id"] == "C0ABC"
    assert row["slack_channel_name"] == "geo-guessr"
    assert row["reminder_delivery"] == "both"


def test_relinking_moves_the_claim_instead_of_failing():
    """One Slack user holds at most one player per league (UNIQUE index). Picking a
    different player must move the link, not trip the constraint."""
    c = _conn()
    _, lid = _league(c)
    queries.link_player(c, lid, "geo-ana", "U0ANA")
    queries.link_player(c, lid, "geo-bertil", "U0BERTIL")
    assert queries.player_links(c, lid) == {"geo-ana": "U0ANA", "geo-bertil": "U0BERTIL"}

    queries.link_player(c, lid, "geo-cecilia", "U0ANA")     # same Slack user, new player
    assert queries.player_links(c, lid) == {"geo-cecilia": "U0ANA", "geo-bertil": "U0BERTIL"}

    queries.link_player(c, lid, "geo-bertil", "U0DAVID")    # same player, new Slack user
    assert queries.player_links(c, lid) == {"geo-cecilia": "U0ANA", "geo-bertil": "U0DAVID"}


def test_links_are_scoped_per_league():
    c = _conn()
    _, l1 = _league(c)
    uid = c.execute("SELECT user_id FROM leagues WHERE id=?", (l1,)).fetchone()["user_id"]
    tc = queries.add_credential(c, uid, "slack", "bot2", "tok2", '{"mode":"bot"}')
    gc = queries.add_credential(c, uid, "geoguessr", "c2", "n2")
    l2 = queries.add_league(c, uid, name="Other", transport_cred_id=tc, geo_cred_id=gc,
                            cron_results="0 9 * * *")
    queries.link_player(c, l1, "geo-ana", "U0ANA")
    assert queries.player_links(c, l2) == {}


def test_deleting_a_league_cascades_links():
    c = _conn()
    uid, lid = _league(c)
    queries.link_player(c, lid, "geo-ana", "U0ANA")
    queries.delete_league(c, lid, uid)
    assert c.execute("SELECT COUNT(*) FROM player_links").fetchone()[0] == 0


def test_attach_slack_ids_joins_reminder_entries():
    """The end-to-end shape of the ping: challenges/scores in the DB ->
    load_league_data -> players_not_played_today -> attach_slack_ids -> the
    slack_user_id the message builder renders as a mention."""
    c = _conn()
    uid, lid = _league(c, tz="UTC")
    mid = queries.add_map(c, uid, "World", "6029991c5048850001d572a9", None)
    gid = queries.add_game(c, lid, name="normal", map_ref=mid, time_limit=0,
                           forbid_moving=0, forbid_zooming=0, forbid_rotating=0,
                           weight=1.0, cron_challenge="0 8 * * *")
    queries.add_challenge(c, lid, gid, "t1", "https://gg/c/t1", "2026-07-24")
    queries.add_challenge(c, lid, gid, "t2", "https://gg/c/t2", "2026-07-24")
    for token, players in (("t1", ["ana", "bertil"]), ("t2", ["ana"])):
        queries.upsert_scores(c, lid, token, {"countries": [], "players": [
            {"user_id": p, "name": p.title(), "score": 1000} for p in players
        ]})

    data = queries.load_league_data(c, lid)
    entries = store.players_not_played_today(data, "2026-07-24")
    assert [e["key"] for e in entries] == ["bertil"], entries   # Ana played both

    queries.link_player(c, lid, "bertil", "U0BERTIL")
    queries.attach_slack_ids(c, lid, entries)
    assert entries[0]["slack_user_id"] == "U0BERTIL"

    # an unlinked player simply carries no id — the builder then renders plain text
    unlinked = [{"key": "nobody", "name": "Nobody"}]
    queries.attach_slack_ids(c, lid, unlinked)
    assert "slack_user_id" not in unlinked[0]


def test_slack_bot_credentials_filters_by_mode_and_team():
    """Inbound interactions have no session, so candidates are found by workspace and
    then decided by signature. Webhook creds must never be candidates."""
    c = _conn()
    uid = queries.create_user(c, "z@b.c", "x")
    queries.add_credential(c, uid, "slack", "hook", "https://hooks/x", '{"mode":"incoming"}')
    bot = queries.add_credential(c, uid, "slack", "acme", "blob",
                                 '{"mode":"bot","team_id":"T0ACME"}')
    queries.add_credential(c, uid, "slack", "other", "blob",
                           '{"mode":"bot","team_id":"T0OTHER"}')

    assert [r["id"] for r in queries.slack_bot_credentials(c, "T0ACME")] == [bot]
    assert len(queries.slack_bot_credentials(c)) == 2          # both bots, no webhook
    assert queries.slack_bot_credentials(c, "T0NOPE") == []


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
    print("player links ok")
