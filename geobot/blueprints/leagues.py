"""Leagues: a channel + combined leaderboard + results schedule, owning many
games. Every referenced credential is re-checked against the caller before save.
"""
from __future__ import annotations

import sqlite3

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, session, url_for,
)

from .. import cron_builder, db, jobs, queries, scheduler
from ..security import login_required

bp = Blueprint("leagues", __name__, url_prefix="/leagues")


def _hm(s: str) -> tuple[int, int]:
    try:
        h, m = (s or "").split(":")
        return int(h), int(m)
    except ValueError:
        return 9, 0


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
    try:
        lid = queries.add_league(db.conn(), uid, name, transport_id, geo_id, cron, tz, slug)
    except sqlite3.IntegrityError:
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
    try:
        queries.update_league(db.conn(), league_id, uid, name, transport_id, geo_id, cron, tz, slug)
    except sqlite3.IntegrityError:
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


@bp.post("/<int:league_id>/run-results")
@login_required
def run_results(league_id):
    if not queries.get_league(db.conn(), league_id, session["uid"]):
        abort(404)
    try:
        flash("Results: " + jobs.post_results(league_id))
    except Exception as e:  # surface network/API failures, don't 500
        flash(f"Results failed: {e}")
    return redirect(url_for("leagues.detail", league_id=league_id))
