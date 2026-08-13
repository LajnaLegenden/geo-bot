"""Credential pool: GeoGuessr cookies + transport tokens (Slack/Discord).
Secrets are encrypted by queries.add_credential; the plaintext is never shown back
after saving.

A Slack credential is one of two things:
  bot      — a Slack app the user created themselves. `secret` is an encrypted JSON
             blob of {bot_token, signing_secret} (two secrets, and `meta` is
             plaintext by design), `meta` caches what auth.test reports about the
             workspace. The channel isn't part of the credential — a bot token posts
             wherever it's invited, so the channel belongs to the league.
  incoming — a legacy per-channel Incoming Webhook URL in `secret`. No interactivity.
"""
from __future__ import annotations

import json
import os
import sqlite3

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from .. import db, queries, slack_api
from ..security import login_required

bp = Blueprint("credentials", __name__, url_prefix="/credentials")

KINDS = {"geoguessr": "GeoGuessr cookie", "slack": "Slack", "discord": "Discord"}

MANIFEST = """display_information:
  name: GeoBot
  description: Daily GeoGuessr challenges, leaderboards and reminders
  background_color: "#12161c"
features:
  bot_user:
    display_name: GeoBot
    always_online: false
oauth_config:
  scopes:
    bot:
      - chat:write
      - channels:read
      - groups:read
      - im:write
settings:
  interactivity:
    is_enabled: true
    request_url: {base_url}/slack/interact
  org_deploy_enabled: false
  socket_mode_enabled: false
  token_rotation_enabled: false
"""


def _manifest() -> tuple[str, bool]:
    """(manifest yaml, base_url_is_set). Without BASE_URL the request_url can't be
    filled in, so the page says so rather than handing over a broken manifest."""
    base = (os.environ.get("BASE_URL") or "").rstrip("/")
    return MANIFEST.format(base_url=base or "https://YOUR-APP-URL"), bool(base)


def _detail(cred) -> str:
    """The muted line under a credential's label: which workspace, which mode."""
    meta = json.loads(cred["meta"]) if cred["meta"] else {}
    mode = meta.get("mode")
    if mode == "bot":
        who = meta.get("team_name") or "unknown workspace"
        return f"bot · {who}" + (f" · @{meta['bot_user_id']}" if meta.get("bot_user_id") else "")
    if mode:
        return f"{mode} webhook"
    return ""


@bp.get("")
@login_required
def index():
    creds = queries.list_credentials(db.conn(), session["uid"])
    manifest, base_url_set = _manifest()
    return render_template(
        "credentials.html", creds=creds, kinds=KINDS, detail=_detail,
        manifest=manifest, base_url_set=base_url_set,
    )


def _slack_bot_fields(bot_token: str):
    """(secret, meta) for a bot credential, or a flash message on failure.

    auth.test runs here on purpose: a typo'd or revoked token fails at paste time
    with Slack's own error, instead of silently at 07:50 tomorrow. It also supplies
    the workspace/bot identity so nothing else has to be typed in."""
    signing = (request.form.get("signing_secret") or "").strip()
    if not signing:
        return None, None, "A Slack bot needs both a bot token and a signing secret."
    try:
        info = slack_api.auth_test(bot_token)
    except Exception as e:
        return None, None, f"Slack rejected that bot token: {e}"
    secret = json.dumps({"bot_token": bot_token, "signing_secret": signing})
    meta = json.dumps({
        "mode": "bot",
        "team_id": info.get("team_id"),
        "team_name": info.get("team"),
        "bot_user_id": info.get("user_id"),
    })
    return secret, meta, None


@bp.post("")
@login_required
def create():
    kind = request.form.get("kind")
    label = (request.form.get("label") or "").strip()
    secret = (request.form.get("secret") or "").strip()
    if kind not in KINDS or not label or not secret:
        flash("Kind, label, and secret are all required.")
        return redirect(url_for("credentials.index"))

    meta = None
    if kind == "slack":
        mode = request.form.get("mode") or "bot"
        if mode == "bot":
            secret, meta, err = _slack_bot_fields(secret)
            if err:
                flash(err)
                return redirect(url_for("credentials.index"))
        else:
            meta = json.dumps({"mode": "incoming"})

    queries.add_credential(db.conn(), session["uid"], kind, label, secret, meta)
    flash("Credential saved.")
    return redirect(url_for("credentials.index"))


@bp.post("/<int:cred_id>/delete")
@login_required
def delete(cred_id):
    try:
        queries.delete_credential(db.conn(), cred_id, session["uid"])
        flash("Credential deleted.")
    except sqlite3.IntegrityError:  # still referenced by a league (RESTRICT)
        db.conn().rollback()
        flash("Can't delete: this credential is still used by a league. Update those leagues first.")
    return redirect(url_for("credentials.index"))
