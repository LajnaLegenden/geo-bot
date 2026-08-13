"""Leagues: a channel + combined leaderboard + results schedule, owning many
games. Every referenced credential is re-checked against the caller before save.
"""
from __future__ import annotations

import json
import sqlite3

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, session, url_for,
)

from .. import cron_builder, db, jobs, queries, scheduler, slack_api
from ..security import login_required

bp = Blueprint("leagues", __name__, url_prefix="/leagues")

DELIVERY = {"channel": "In the channel", "dm": "Direct message only",
            "both": "Channel + direct message"}


def _hm(s: str) -> tuple[int, int]:
    try:
        h, m = (s or "").split(":")
        return int(h), int(m)
    except ValueError:
        return 9, 0


def _cred_id(v) -> int:
    """A credential id from the form. Garbage is a bad request, not a 500 — these
    are hand-craftable even though the selects only ever emit integers."""
    try:
        return int(v)
    except (TypeError, ValueError):
        abort(400, "invalid credential selection")


def _pull_minutes(v) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 60
    return n if n in (0, 15, 30, 60) else 60  # restrict to the dropdown's values


def _reminder_fields() -> dict:
    """Reminder columns from the form. An unchecked "reminder_enabled" box means
    reminders off -> cron_reminder=None (the scheduler then skips the job)."""
    f = {
        "reminder_title": (request.form.get("reminder_title") or "").strip()
                          or "⏰ Still to play today",
        "reminder_body": (request.form.get("reminder_body") or "").strip(),
        "reminder_delivery": request.form.get("reminder_delivery") or "channel",
        "cron_reminder": None,
    }
    if f["reminder_delivery"] not in DELIVERY:
        f["reminder_delivery"] = "channel"
    if request.form.get("reminder_enabled"):
        h, m = _hm(request.form.get("reminder_time"))
        f["cron_reminder"] = cron_builder.build_cron(
            request.form.getlist("reminder_days"), h, m
        )
    return f


def _transport_creds(uid):
    return (queries.list_credentials(db.conn(), uid, kind="slack")
            + queries.list_credentials(db.conn(), uid, kind="discord"))


def _geo_creds(uid):
    return queries.list_credentials(db.conn(), uid, kind="geoguessr")


def _channel_groups(uid, league=None) -> list[dict]:
    """<optgroup>s for the league form's single "Channel" select.

    One field, not two, so switching workspace needs no JS/htmx round-trip to
    repopulate channels. Option values are "<cred_id>:<channel_id>:<name>" — the name
    rides along because channel names can't contain ':', which saves an API call on
    save just to look it up again.

    A bot credential whose token or API call fails still renders, carrying a note, and
    the league's existing binding is re-added below if it went missing — editing an
    unrelated field must never silently drop a league's channel.
    """
    groups = []
    for c in _transport_creds(uid):
        meta = json.loads(c["meta"]) if c["meta"] else {}
        if c["kind"] == "slack" and meta.get("mode") == "bot":
            name = meta.get("team_name") or c["label"]
            try:
                token = json.loads(db.decrypt(c["secret"]))["bot_token"]
                chans = slack_api.channels(token)
                note = None if chans else "invite the bot to a channel, then reload"
            except Exception as e:
                chans, note = [], f"couldn't list channels — {e}"
            groups.append({
                "label": f"{name} (bot)", "note": note,
                "options": [(f"{c['id']}:{ch['id']}:{ch['name']}", "#" + ch["name"])
                            for ch in chans],
            })
        else:
            mode = meta.get("mode") or c["kind"]
            note = ("Workflow Builder mode was removed — pick a bot channel instead"
                    if mode == "workflow" else None)
            # Always three ':'-separated segments, even with no channel/name, so the
            # "is this the current binding" prefix test below works for every mode.
            groups.append({
                "label": f"legacy {mode}", "note": note,
                "options": [(f"{c['id']}::", c["label"])],
            })

    if league and league["slack_channel_id"]:
        current = f"{league['transport_cred_id']}:{league['slack_channel_id']}"
        listed = any(v.startswith(current + ":") for g in groups for v, _ in g["options"])
        if not listed:
            groups.insert(0, {
                "label": "currently bound", "note": "couldn't be re-listed from Slack",
                "options": [(f"{current}:{league['slack_channel_name'] or ''}",
                             "#" + (league["slack_channel_name"] or league["slack_channel_id"]))],
            })
    return groups


def _channel_fields(uid) -> dict:
    """Parse the Channel select back into columns, validating the credential.

    Bot mode requires a channel: the options never offer a bot credential without
    one, so an empty channel there means hand-crafted input."""
    raw = request.form.get("channel") or ""
    cred_part, _, rest = raw.partition(":")
    channel_id, _, channel_name = rest.partition(":")
    cred = queries.get_credential(db.conn(), _cred_id(cred_part or 0), uid)
    if not cred or cred["kind"] not in ("slack", "discord"):
        abort(400, "invalid channel selection")
    meta = json.loads(cred["meta"]) if cred["meta"] else {}
    if meta.get("mode") == "bot" and not channel_id:
        abort(400, "a Slack bot credential needs a channel")
    return {
        "transport_cred_id": cred["id"],
        "slack_channel_id": channel_id or None,
        "slack_channel_name": channel_name or None,
    }


def _validated_geo(uid, geo_id):
    gc = queries.get_credential(db.conn(), geo_id, uid)
    if not gc or gc["kind"] != "geoguessr":
        abort(400, "invalid credential selection")
    return gc


def _form_fields(uid) -> dict:
    """Every league column the form owns, ready for queries.add_league(**f)."""
    h, m = _hm(request.form.get("results_time"))
    f = {
        "name": (request.form.get("name") or "").strip(),
        "geo_cred_id": _validated_geo(uid, _cred_id(request.form.get("geo_cred_id") or 0))["id"],
        "cron_results": cron_builder.build_cron(request.form.getlist("days"), h, m),
        "tz": (request.form.get("tz") or "UTC").strip(),
        "public_slug": (request.form.get("public_slug") or "").strip() or None,
        "pull_minutes": _pull_minutes(request.form.get("pull_minutes")),
    }
    f.update(_channel_fields(uid))
    f.update(_reminder_fields())
    return f


@bp.get("/new")
@login_required
def new():
    return render_template("league_form.html", league=None, cron=cron_builder,
                           geo=_geo_creds(session["uid"]),
                           channel_groups=_channel_groups(session["uid"]),
                           delivery=DELIVERY)


@bp.post("")
@login_required
def create():
    uid = session["uid"]
    f = _form_fields(uid)
    if not f["name"]:
        flash("Name is required.")
        return redirect(url_for("leagues.new"))
    try:
        lid = queries.add_league(db.conn(), uid, **f)
    except sqlite3.IntegrityError:
        db.conn().rollback()
        flash("That public slug is already taken.")
        return redirect(url_for("leagues.new"))
    scheduler.on_league_saved(lid)
    return redirect(url_for("leagues.detail", league_id=lid))


@bp.get("/<int:league_id>")
@login_required
def detail(league_id):
    uid = session["uid"]
    league = queries.get_league(db.conn(), league_id, uid)
    if not league:
        abort(404)
    games = queries.list_games(db.conn(), league_id)
    return render_template("league_detail.html", league=league, games=games,
                           cron=cron_builder)


@bp.get("/<int:league_id>/edit")
@login_required
def edit(league_id):
    uid = session["uid"]
    league = queries.get_league(db.conn(), league_id, uid)
    if not league:
        abort(404)
    return render_template("league_form.html", league=league, cron=cron_builder,
                           geo=_geo_creds(uid),
                           channel_groups=_channel_groups(uid, league),
                           delivery=DELIVERY)


@bp.post("/<int:league_id>/edit")
@login_required
def update(league_id):
    uid = session["uid"]
    if not queries.get_league(db.conn(), league_id, uid):
        abort(404)
    f = _form_fields(uid)
    try:
        queries.update_league(db.conn(), league_id, uid, **f)
    except sqlite3.IntegrityError:
        db.conn().rollback()
        flash("That public slug is already taken.")
        return redirect(url_for("leagues.edit", league_id=league_id))
    scheduler.on_league_saved(league_id)
    return redirect(url_for("leagues.detail", league_id=league_id))


@bp.post("/<int:league_id>/delete")
@login_required
def delete(league_id):
    uid = session["uid"]
    if queries.get_league(db.conn(), league_id, uid):
        game_ids = [g["id"] for g in queries.list_games(db.conn(), league_id)]
        queries.delete_league(db.conn(), league_id, uid)
        scheduler.on_league_deleted(league_id, game_ids)
        flash("League deleted.")
    return redirect(url_for("dashboard"))


@bp.post("/<int:league_id>/pull-now")
@login_required
def run_pull(league_id):
    if not queries.get_league(db.conn(), league_id, session["uid"]):
        abort(404)
    try:
        flash("Pull: " + jobs.pull_results(league_id))
    except Exception as e:  # surface network/API failures, don't 500
        flash(f"Pull failed: {e}")
    return redirect(url_for("leagues.detail", league_id=league_id))


@bp.post("/<int:league_id>/post-now")
@login_required
def run_post(league_id):
    if not queries.get_league(db.conn(), league_id, session["uid"]):
        abort(404)
    try:
        flash("Post: " + jobs.post_leaderboard(league_id))
    except Exception as e:  # surface network/API failures, don't 500
        flash(f"Post failed: {e}")
    return redirect(url_for("leagues.detail", league_id=league_id))


@bp.post("/<int:league_id>/remind-now")
@login_required
def run_reminder(league_id):
    if not queries.get_league(db.conn(), league_id, session["uid"]):
        abort(404)
    try:
        flash("Reminder: " + jobs.send_reminder(league_id))
    except Exception as e:  # surface network/API failures, don't 500
        flash(f"Reminder failed: {e}")
    return redirect(url_for("leagues.detail", league_id=league_id))
