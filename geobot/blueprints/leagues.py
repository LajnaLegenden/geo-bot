"""Leagues: a channel + combined leaderboard + results schedule, owning many
games. Every referenced credential is re-checked against the caller before save.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, session, url_for,
)

from .. import cron_builder, db, jobs, queries, scheduler, store
from ..security import login_required
from .stats import season_context

bp = Blueprint("leagues", __name__, url_prefix="/leagues")


def _hm(s: str) -> tuple[int, int]:
    try:
        h, m = (s or "").split(":")
        return int(h), int(m)
    except ValueError:
        return 9, 0


def _pull_minutes(v) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 60
    return n if n in (0, 15, 30, 60) else 60  # restrict to the dropdown's values


def _reminder_fields():
    """(cron_reminder, title, body) from the form. An unchecked "reminder_enabled"
    box means reminders off -> cron_reminder=None (scheduler skips the job)."""
    title = (request.form.get("reminder_title") or "").strip() or "⏰ Still to play today"
    body = (request.form.get("reminder_body") or "").strip()
    if not request.form.get("reminder_enabled"):
        return None, title, body
    h, m = _hm(request.form.get("reminder_time"))
    cron = cron_builder.build_cron(request.form.getlist("reminder_days"), h, m)
    return cron, title, body


def _cred_lists(uid):
    return (
        queries.list_credentials(db.conn(), uid, kind="geoguessr"),
        queries.list_credentials(db.conn(), uid, kind="slack")
        + queries.list_credentials(db.conn(), uid, kind="discord"),
    )


def _validated_creds(uid, transport_id, geo_id):
    tc = queries.get_credential(db.conn(), transport_id, uid)
    gc = queries.get_credential(db.conn(), geo_id, uid)
    if not tc or tc["kind"] not in ("slack", "discord") or not gc or gc["kind"] != "geoguessr":
        abort(400, "invalid credential selection")
    return tc, gc


@bp.get("/new")
@login_required
def new():
    geo, transports = _cred_lists(session["uid"])
    return render_template("league_form.html", league=None, geo=geo,
                           transports=transports, cron=cron_builder)


@bp.post("")
@login_required
def create():
    uid = session["uid"]
    name = (request.form.get("name") or "").strip()
    transport_id = int(request.form.get("transport_cred_id") or 0)
    geo_id = int(request.form.get("geo_cred_id") or 0)
    if not name:
        flash("Name is required.")
        return redirect(url_for("leagues.new"))
    _validated_creds(uid, transport_id, geo_id)
    h, m = _hm(request.form.get("results_time"))
    cron = cron_builder.build_cron(request.form.getlist("days"), h, m)
    tz = (request.form.get("tz") or "UTC").strip()
    slug = (request.form.get("public_slug") or "").strip() or None
    pull = _pull_minutes(request.form.get("pull_minutes"))
    cron_reminder, rtitle, rbody = _reminder_fields()
    try:
        lid = queries.add_league(db.conn(), uid, name, transport_id, geo_id, cron, tz,
                                 slug, pull, cron_reminder, rtitle, rbody)
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
    seasons, selected, is_current = season_context(db.conn(), league_id)
    # Default the new season to next Monday: seasons are scored from weekly
    # podiums, so a boundary on any other day splits one week into two and hands
    # out two podiums for it.
    next_monday = store.week_start() + timedelta(days=7)
    return render_template("league_detail.html", league=league, games=games,
                           cron=cron_builder, seasons=seasons, season=selected,
                           is_current=is_current,
                           next_name=f"Season {len(seasons) + 1}",
                           next_start=next_monday.isoformat())


@bp.get("/<int:league_id>/data")
@login_required
def data(league_id):
    """Read-only row dump of everything this league owns — for eyeballing what
    the DB actually holds when a board looks wrong. Owner-scoped like every other
    league read; no paging, so Ctrl-F is the filter."""
    league = queries.get_league(db.conn(), league_id, session["uid"])
    if not league:
        abort(404)
    return render_template("league_data.html", league=league,
                           tables=queries.league_dump(db.conn(), league_id))


@bp.get("/<int:league_id>/edit")
@login_required
def edit(league_id):
    uid = session["uid"]
    league = queries.get_league(db.conn(), league_id, uid)
    if not league:
        abort(404)
    geo, transports = _cred_lists(uid)
    return render_template("league_form.html", league=league, geo=geo,
                           transports=transports, cron=cron_builder)


@bp.post("/<int:league_id>/edit")
@login_required
def update(league_id):
    uid = session["uid"]
    if not queries.get_league(db.conn(), league_id, uid):
        abort(404)
    name = (request.form.get("name") or "").strip()
    transport_id = int(request.form.get("transport_cred_id") or 0)
    geo_id = int(request.form.get("geo_cred_id") or 0)
    _validated_creds(uid, transport_id, geo_id)
    h, m = _hm(request.form.get("results_time"))
    cron = cron_builder.build_cron(request.form.getlist("days"), h, m)
    tz = (request.form.get("tz") or "UTC").strip()
    slug = (request.form.get("public_slug") or "").strip() or None
    pull = _pull_minutes(request.form.get("pull_minutes"))
    cron_reminder, rtitle, rbody = _reminder_fields()
    try:
        queries.update_league(db.conn(), league_id, uid, name, transport_id, geo_id, cron, tz,
                              slug, pull, cron_reminder, rtitle, rbody)
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


@bp.post("/<int:league_id>/seasons")
@login_required
def start_season(league_id):
    """Cut a new season. Pure data — no scheduler call: the current season is
    whichever has the greatest starts_on <= today, so a future-dated one rolls
    over on its own date."""
    if not queries.get_league(db.conn(), league_id, session["uid"]):
        abort(404)
    name = (request.form.get("name") or "").strip()
    starts_on = (request.form.get("starts_on") or "").strip()
    if not name:
        flash("Season name is required.")
        return redirect(url_for("leagues.detail", league_id=league_id))
    try:
        starts_on = date.fromisoformat(starts_on).isoformat()
    except ValueError:
        flash("Season start must be a valid date.")
        return redirect(url_for("leagues.detail", league_id=league_id))
    try:
        queries.add_season(db.conn(), league_id, name, starts_on)
    except sqlite3.IntegrityError:
        db.conn().rollback()
        flash(f"A season already starts on {starts_on}.")
        return redirect(url_for("leagues.detail", league_id=league_id))
    flash(f"{name} starts {starts_on}.")
    return redirect(url_for("leagues.detail", league_id=league_id))


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
