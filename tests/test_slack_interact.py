"""Offline checks for /slack/interact — the app's only unauthenticated route.

The point of these: `/slack/*` is exempt from the session CSRF check, so the Slack
request signature is the *whole* of its authentication. If that check ever weakens,
an unauthenticated stranger can drive the bot. Nothing here touches the network —
views.open is stubbed.

Run: python -m tests.test_slack_interact (from the repo root) or pytest.
"""
import hashlib
import hmac
import json
import os
import tempfile
import time
import urllib.parse

from cryptography.fernet import Fernet

_TMP = tempfile.mkdtemp()
os.environ["GEO_DB"] = os.path.join(_TMP, "t.db")
os.environ.setdefault("GEO_FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("SECRET_KEY", "test-only")

from geobot import db, migrate, queries, slack_api  # noqa: E402
from geobot.app import create_app  # noqa: E402

SIGNING = "8f742231b10e8888abcd99yyyzzz85a5"
OTHER_SIGNING = "0000000000000000000000000000aaaa"
opened = []          # views.open calls captured instead of sent


def setup():
    """Fresh DB + app, one bot credential in team T0ACME owning league `lid`, plus a
    second workspace's credential owning `other_lid` (the IDOR target)."""
    del opened[:]
    conn = db.conn()
    for t in ("player_links", "scores", "challenges", "games", "leagues",
              "credentials", "maps", "users", "schema_migrations"):
        conn.execute(f"DROP TABLE IF EXISTS {t}")
    conn.commit()
    migrate.migrate(conn)

    uid = queries.create_user(conn, "a@b.c", "x")
    gc = queries.add_credential(conn, uid, "geoguessr", "cookie", "ncfa")

    def bot(label, team, signing):
        return queries.add_credential(
            conn, uid, "slack", label,
            json.dumps({"bot_token": "xoxb-test", "signing_secret": signing}),
            json.dumps({"mode": "bot", "team_id": team, "team_name": label}),
        )

    cred = bot("acme", "T0ACME", SIGNING)
    other = bot("other", "T0OTHER", OTHER_SIGNING)
    mk = dict(geo_cred_id=gc, cron_results="0 18 * * *", slack_channel_id="C0ABC")
    lid = queries.add_league(conn, uid, name="Daily", transport_cred_id=cred, **mk)
    other_lid = queries.add_league(conn, uid, name="Theirs", transport_cred_id=other, **mk)

    mid = queries.add_map(conn, uid, "World", "m1", None)
    gid = queries.add_game(conn, lid, name="normal", map_ref=mid, time_limit=0,
                           forbid_moving=0, forbid_zooming=0, forbid_rotating=0,
                           weight=1.0, cron_challenge="0 8 * * *")
    queries.add_challenge(conn, lid, gid, "t1", "https://gg/c/t1", "2026-07-24")
    queries.upsert_scores(conn, lid, "t1", {"countries": [], "players": [
        {"user_id": "ana", "name": "Ana", "score": 1000},
        {"user_id": "bertil", "name": "Bertil", "score": 900},
    ]})

    slack_api.open_view = lambda token, trigger_id, view: opened.append(view)
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client(), lid, other_lid


def post(client, payload, signing=SIGNING, ts=None, tamper=False):
    body = urllib.parse.urlencode({"payload": json.dumps(payload)}).encode()
    ts = ts or str(int(time.time()))
    sig = "v0=" + hmac.new(signing.encode(), b"v0:" + ts.encode() + b":" + body,
                           hashlib.sha256).hexdigest()
    if tamper:
        body += b"&extra=1"
    return client.post("/slack/interact", data=body,
                       content_type="application/x-www-form-urlencoded",
                       headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig})


def _click(lid, action_id="link_player"):
    return {
        "type": "block_actions", "team": {"id": "T0ACME"}, "trigger_id": "trig.1",
        "user": {"id": "U0BERTIL"}, "channel": {"id": "C0ABC"},
        "container": {"message_ts": "1700000000.000100"},
        "actions": [{"action_id": action_id, "value": str(lid)}],
    }


def _submit(lid, value="bertil"):
    return {
        "type": "view_submission", "team": {"id": "T0ACME"}, "user": {"id": "U0BERTIL"},
        "view": {"private_metadata": str(lid), "state": {"values": {
            "player": {"choice": {"selected_option": {"value": value}}}}}},
    }


# --- authentication ----------------------------------------------------------

def test_unsigned_request_is_rejected():
    """The CSRF exemption must not mean 'no authentication'."""
    client, lid, _ = setup()
    r = client.post("/slack/interact", data={"payload": json.dumps(_click(lid))})
    assert r.status_code == 401, r.status_code
    assert opened == []


def test_tampered_body_is_rejected():
    client, lid, _ = setup()
    assert post(client, _click(lid), tamper=True).status_code == 401
    assert opened == []


def test_wrong_signing_secret_is_rejected():
    """Signed by a real credential — but not the one that serves this team."""
    client, lid, _ = setup()
    assert post(client, _click(lid), signing=OTHER_SIGNING).status_code == 401
    assert opened == []


def test_replayed_old_request_is_rejected():
    client, lid, _ = setup()
    stale = str(int(time.time()) - slack_api.MAX_SKEW - 5)
    assert post(client, _click(lid), ts=stale).status_code == 401


def test_csrf_check_still_guards_the_web_ui():
    """Only /slack/* is exempt — the rest of the app must still demand a token."""
    client, _, _ = setup()
    assert client.post("/credentials", data={"kind": "slack"}).status_code == 400


# --- authorization -----------------------------------------------------------

def test_cannot_aim_a_forged_league_id_at_another_workspace():
    """The league id rides in the button value, so it's attacker-controlled. A
    correctly-signed click from T0ACME must not reach a league served by another
    credential."""
    client, _, other_lid = setup()
    r = post(client, _click(other_lid))
    assert r.status_code == 200 and opened == [], opened

    r = post(client, _submit(other_lid))
    assert r.status_code == 200
    assert queries.player_links(db.conn(), other_lid) == {}


def test_unknown_league_id_is_ignored():
    client, _, _ = setup()
    assert post(client, _click(999)).status_code == 200
    assert opened == []


# --- linking -----------------------------------------------------------------

def test_link_button_opens_a_modal_of_unlinked_players():
    client, lid, _ = setup()
    assert post(client, _click(lid)).status_code == 200
    view = opened[-1]
    assert view["private_metadata"] == str(lid)
    assert {o["value"] for o in view["blocks"][0]["element"]["options"]} == {"ana", "bertil"}

    queries.link_player(db.conn(), lid, "ana", "U0ANA")
    del opened[:]
    post(client, _click(lid))
    assert [o["value"] for o in opened[-1]["blocks"][0]["element"]["options"]] == ["bertil"]


def test_modal_is_a_notice_when_everyone_is_linked():
    client, lid, _ = setup()
    queries.link_player(db.conn(), lid, "ana", "U0ANA")
    queries.link_player(db.conn(), lid, "bertil", "U0BERTIL")
    post(client, _click(lid))
    assert "submit" not in opened[-1]        # nothing to pick, so nothing to submit


def test_submission_writes_the_link():
    client, lid, _ = setup()
    r = post(client, _submit(lid))
    assert r.status_code == 200
    assert r.get_json()["response_action"] == "update"
    assert queries.player_links(db.conn(), lid) == {"bertil": "U0BERTIL"}


def test_submission_of_an_already_claimed_player_errors_instead_of_writing():
    """A stale modal (someone else linked that player meanwhile) must fail visibly."""
    client, lid, _ = setup()
    queries.link_player(db.conn(), lid, "bertil", "U0SOMEONE")
    r = post(client, _submit(lid))
    body = r.get_json()
    assert body["response_action"] == "errors" and "player" in body["errors"]
    assert queries.player_links(db.conn(), lid) == {"bertil": "U0SOMEONE"}


def test_submission_of_an_unknown_player_writes_nothing():
    client, lid, _ = setup()
    r = post(client, _submit(lid, value="../etc/passwd"))
    assert r.get_json()["response_action"] == "errors"
    assert queries.player_links(db.conn(), lid) == {}


# --- refresh -----------------------------------------------------------------

def test_refresh_click_acks_without_the_scheduler_running():
    """run_soon returns False when there's no scheduler (as here); the click must
    still ack 200 so Slack doesn't show the user an error."""
    client, lid, _ = setup()
    assert post(client, _click(lid, "refresh_leaderboard")).status_code == 200


def test_garbage_payloads_do_not_500():
    client, _, _ = setup()
    assert client.post("/slack/interact", data={"nope": "1"}).status_code == 400
    assert post(client, {"type": "block_actions", "team": {"id": "T0ACME"}}).status_code == 200
    assert post(client, {"type": "something_new", "team": {"id": "T0ACME"}}).status_code == 200


# --- the league form's channel dropdown --------------------------------------
# Not the interact endpoint, but the other half of the Slack integration, and it
# reuses this fixture. slack_api.channels is always stubbed — a real token-less call
# to slack.com would be exactly the live request these tests exist to avoid.

def _login(client):
    with client.session_transaction() as s:
        s["uid"] = 1


def test_channel_dropdown_lists_invited_channels():
    client, lid, _ = setup()
    _login(client)
    slack_api.channels = lambda token: [{"id": "C0ABC", "name": "geo-guessr"},
                                        {"id": "C0RND", "name": "random"}]
    body = client.get(f"/leagues/{lid}/edit").get_data(as_text=True)
    assert "#geo-guessr" in body and "#random" in body
    cred_id = db.conn().execute(
        "SELECT transport_cred_id FROM leagues WHERE id=?", (lid,)).fetchone()[0]
    # value packs cred + channel + name, so switching workspace needs no round-trip
    assert f'value="{cred_id}:C0ABC:geo-guessr"' in body
    assert f'value="{cred_id}:C0ABC:geo-guessr" selected' in body   # current binding


def test_league_form_survives_slack_being_unreachable():
    """A dead token or an API outage must not 500 the form, and must not silently
    drop the league's existing binding — editing an unrelated field would then
    unbind the channel."""
    client, lid, _ = setup()
    _login(client)
    db.conn().execute(
        "UPDATE leagues SET slack_channel_name='geo-guessr' WHERE id=?", (lid,))
    db.conn().commit()

    def boom(token):
        raise slack_api.SlackError("users.conversations: invalid_auth")

    slack_api.channels = boom
    r = client.get(f"/leagues/{lid}/edit")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "couldn&#39;t list channels" in body or "couldn't list channels" in body
    assert "currently bound" in body and "#geo-guessr" in body


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
    print("slack interact ok")
