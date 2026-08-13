"""Slack Web API calls (outbound) + request signature verification (inbound).

Outbound: bot-token calls over `requests`. No `slack_sdk` — six methods and a
15-line wrapper don't justify the dependency next to this app's six small ones.

Inbound: `verify_request` is the *only* thing authenticating Slack's POSTs to
/slack/interact. Those carry no session cookie, so `/slack/*` is exempt from the
app's CSRF check (see app.py) and the signature stands in its place. See
blueprints/slack_bot.py for how the right signing secret gets picked.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import requests

API = "https://slack.com/api/"


class SlackError(RuntimeError):
    """Slack answered HTTP 200 with {"ok": false, "error": ...}."""


def call(token: str, method: str, **payload):
    # ponytail: form-encoded, not JSON. Every Web API method accepts
    # x-www-form-urlencoded; JSON support is per-method, so form is the one code
    # path that can't be wrong. Cost is having to serialize the nested bits
    # (blocks, view) ourselves, which is the dict/list branch below.
    data = {}
    for k, v in payload.items():
        if v is None:
            continue
        if isinstance(v, (list, dict)):
            v = json.dumps(v)
        elif isinstance(v, bool):
            v = "true" if v else "false"   # requests would send "True"
        data[k] = v
    r = requests.post(API + method, data=data, timeout=15,
                      headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    body = r.json()
    if not body.get("ok"):
        raise SlackError(f"{method}: {body.get('error') or 'unknown error'}")
    return body


def auth_test(token: str) -> dict:
    """Validate a bot token and learn who/where it is: team_id, team, user_id
    (the bot's own user id). Called when a credential is saved so a dead token is
    rejected at paste time rather than at 07:50 tomorrow."""
    return call(token, "auth.test")


def post_message(token: str, channel: str, text: str, blocks: list | None = None) -> dict:
    return call(token, "chat.postMessage", channel=channel, text=text, blocks=blocks)


def update_message(token: str, channel: str, ts: str, text: str,
                   blocks: list | None = None) -> dict:
    return call(token, "chat.update", channel=channel, ts=ts, text=text, blocks=blocks)


def channels(token: str) -> list[dict]:
    """[{id, name}] for the channels the bot was *invited* to — with no
    chat:write.public scope, that invite is what grants posting, so this list is
    exactly the set of legal delivery channels. 200 is Slack's recommended page
    size and we don't paginate: a bot in >200 channels isn't this app's problem."""
    body = call(token, "users.conversations",
                types="public_channel,private_channel", exclude_archived=True, limit=200)
    return sorted(
        ({"id": c["id"], "name": c.get("name") or c["id"]} for c in body.get("channels") or []),
        key=lambda c: c["name"],
    )


def open_dm(token: str, user_id: str) -> str:
    """Channel id of the bot's DM with a user (opens it if needed). Needs im:write."""
    return call(token, "conversations.open", users=user_id)["channel"]["id"]


def open_view(token: str, trigger_id: str, view: dict) -> dict:
    """Open a modal. Needs no scope — the trigger_id from the interaction is the
    authorization, and it expires a few seconds after the click."""
    return call(token, "views.open", trigger_id=trigger_id, view=view)


# --- inbound -----------------------------------------------------------------

MAX_SKEW = 300  # seconds; Slack's own recommendation, and the replay window


def verify_request(raw_body: bytes, timestamp: str, signature: str,
                   signing_secret: str) -> bool:
    """True iff this really is Slack, per the documented v0 scheme: HMAC-SHA256 of
    b"v0:{timestamp}:{raw_body}" keyed by the app's signing secret.

    The timestamp check is the replay defence, so it is not optional. Comparison is
    constant-time. Anything malformed is a `False`, never an exception — this runs on
    a public endpoint and must not 500 on garbage.
    """
    try:
        if abs(time.time() - int(timestamp)) > MAX_SKEW:
            return False
        basestring = b"v0:" + timestamp.encode() + b":" + raw_body
        expected = "v0=" + hmac.new(
            signing_secret.encode(), basestring, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
    except (TypeError, ValueError, AttributeError):
        return False


if __name__ == "__main__":  # python -m geobot.slack_api — self-check (no network)
    secret = "8f742231b10e8888abcd99yyyzzz85a5"
    body = b"payload=%7B%22type%22%3A%22block_actions%22%7D"

    def sign(ts, b=body, s=secret):
        return "v0=" + hmac.new(s.encode(), b"v0:" + ts.encode() + b":" + b,
                                hashlib.sha256).hexdigest()

    now = str(int(time.time()))
    assert verify_request(body, now, sign(now), secret)
    assert not verify_request(body + b"x", now, sign(now), secret), "tampered body must fail"
    assert not verify_request(body, now, sign(now, s=secret + "x"), secret), "wrong secret"
    # correctly signed but outside the window — isolates the replay check itself
    stale = str(int(now) - MAX_SKEW - 1)
    assert not verify_request(body, stale, sign(stale), secret), "stale ts must fail"
    assert not verify_request(body, "not-a-number", sign(now), secret)
    assert not verify_request(body, now, None, secret)
    print("slack_api ok")
