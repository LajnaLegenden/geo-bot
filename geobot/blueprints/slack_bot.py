"""Slack interactivity endpoint — ONE public URL shared by every user's Slack app.

Trust model, because this is the app's only unauthenticated route:

* No session cookie exists on a Slack POST, so `/slack/*` is exempt from the CSRF
  check in app.py. Slack's `v0=` request signature replaces it, which is strictly
  stronger for a caller that has no session.
* Each user runs their *own* Slack app, so each has its own signing secret. The
  payload's `team.id` narrows the candidates and the HMAC decides between them — the
  signature is the discriminator, so two apps in one workspace sort themselves out
  and the user never has to copy an App ID. `team.id` is read pre-verification, which
  is safe: it only selects which secrets to try, and a forged one matches none.
* A button's `value` (or a modal's `private_metadata`) carries a league id, which is
  attacker-controlled. Every handler re-checks that the league is actually served by
  the credential that signed the request — otherwise another workspace's app could
  aim a crafted payload at someone else's league.

Handlers always return 200. A non-2xx makes Slack retry and show the user an error,
and there's nothing useful to retry here.
"""
from __future__ import annotations

import json

from flask import Blueprint, abort, jsonify, request

from .. import db, jobs, queries, scheduler, slack, slack_api, store

bp = Blueprint("slack_bot", __name__, url_prefix="/slack")

_ACK = ("", 200)


@bp.post("/interact")
def interact():
    raw = request.get_data()           # must precede request.form; Flask caches it
    payload = _payload()
    if payload is None:
        abort(400, "unparseable Slack payload")
    verified = _verified_credential(raw, payload)
    if verified is None:
        abort(401, "bad Slack signature")
    cred, secrets = verified

    kind = payload.get("type")
    if kind == "block_actions":
        return _on_action(payload, cred, secrets)
    if kind == "view_submission":
        return _on_submission(payload, cred)
    return _ACK                        # url_verification, unknown types: nothing to do


# --- authentication ----------------------------------------------------------

def _payload() -> dict | None:
    """Interactivity arrives form-encoded as payload=<json>."""
    body = request.form.get("payload")
    if not body:
        return None
    try:
        parsed = json.loads(body)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _verified_credential(raw: bytes, payload: dict):
    """(credential row, decrypted secrets) for the app that signed this, else None."""
    ts = request.headers.get("X-Slack-Request-Timestamp", "")
    sig = request.headers.get("X-Slack-Signature", "")
    team_id = (payload.get("team") or {}).get("id")
    for cred in queries.slack_bot_credentials(db.conn(), team_id):
        secrets = json.loads(db.decrypt(cred["secret"]))
        if slack_api.verify_request(raw, ts, sig, secrets.get("signing_secret") or ""):
            return cred, secrets
    return None


def _league(league_id, cred):
    """The league this credential delivers for, or None. The pairing check *is* the
    authorization — league ids arrive from the payload and are not to be trusted."""
    if league_id is None:
        return None
    return db.conn().execute(
        "SELECT * FROM leagues WHERE id=? AND transport_cred_id=?",
        (league_id, cred["id"]),
    ).fetchone()


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# --- block_actions -----------------------------------------------------------

def _on_action(payload, cred, secrets):
    action = (payload.get("actions") or [{}])[0]
    league = _league(_int(action.get("value")), cred)
    if league is None:
        return _ACK
    action_id = action.get("action_id")
    if action_id == "link_player":
        _open_link_modal(secrets["bot_token"], payload, league)
    elif action_id == "refresh_leaderboard":
        _start_refresh(league, payload)
    return _ACK


def _candidates(league_id) -> list[dict]:
    """Players in this league nobody has claimed yet, best-scoring first.

    all_time_leaderboard already returns the {key, name} pairs the boards aggregate
    on, so the roster costs no extra query. Keys longer than a static_select value
    are dropped rather than truncated — a truncated key would write a link that
    silently never matches."""
    data = queries.load_league_data(db.conn(), league_id)
    linked = set(queries.player_links(db.conn(), league_id))
    return [
        {"key": r["key"], "name": r["name"]}
        for r in store.all_time_leaderboard(data)
        if r["key"] not in linked and len(r["key"]) <= slack.OPT_MAX
    ]


def _open_link_modal(token, payload, league) -> None:
    candidates = _candidates(league["id"])
    view = (
        slack.link_modal(league["id"], league["name"], candidates) if candidates
        else slack.notice_modal(
            "Everyone with a score in *{}* is already linked. If one of them is you, "
            "ask whoever claimed it to re-link.".format(league["name"])
        )
    )
    slack_api.open_view(token, payload.get("trigger_id"), view)


def _start_refresh(league, payload) -> None:
    """chat.update needs no stored message ts — the interaction payload carries both
    the channel and the ts of the message the button lives on."""
    ts = (payload.get("container") or {}).get("message_ts")
    channel = (payload.get("channel") or {}).get("id")
    if ts and channel:
        scheduler.run_soon(
            f"league:{league['id']}:refresh",
            jobs.refresh_leaderboard, league["id"], channel, ts,
        )


# --- view_submission ---------------------------------------------------------

def _on_submission(payload, cred):
    view = payload.get("view") or {}
    league = _league(_int(view.get("private_metadata")), cred)
    slack_uid = (payload.get("user") or {}).get("id")
    if league is None or not slack_uid:
        return _ACK
    try:
        chosen = view["state"]["values"]["player"]["choice"]["selected_option"]["value"]
    except (KeyError, TypeError):
        return _ACK

    # Re-derive the roster: the modal could be stale (someone else linked that player
    # meanwhile), and this is what turns a bad value into a visible error rather than
    # a wrong row.
    names = {c["key"]: c["name"] for c in _candidates(league["id"])}
    if chosen not in names:
        return jsonify({"response_action": "errors", "errors": {
            "player": "That player was just linked by someone else — close and try again.",
        }})

    queries.link_player(db.conn(), league["id"], chosen, slack_uid)
    return jsonify({"response_action": "update", "view": slack.notice_modal(
        f"✅ Linked — you're *{names[chosen]}* in *{league['name']}*.\n"
        "Reminders will @-mention you from now on."
    )})
