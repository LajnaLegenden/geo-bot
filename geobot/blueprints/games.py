"""Games nested under a league: one saved map + full challenge settings + weight
+ a new-challenge schedule. Authorized via the parent league (owner-scoped), then
the map is re-checked against the caller.
"""
from __future__ import annotations

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, session, url_for,
)

from .. import cron_builder, db, queries
from ..security import login_required

bp = Blueprint("games", __name__, url_prefix="/leagues/<int:league_id>/games")


def _hm(s: str) -> tuple[int, int]:
    try:
        h, m = (s or "").split(":")
        return int(h), int(m)
    except ValueError:
        return 9, 0


def _require_league(league_id):
    league = queries.get_league(db.conn(), league_id, session["uid"])
    if not league:
        abort(404)
    return league


def _form_fields(uid):
    map_ref = int(request.form.get("map_ref") or 0)
    if not queries.get_map(db.conn(), map_ref, uid):
        abort(400, "invalid map")
    h, m = _hm(request.form.get("challenge_time"))
    return {
        "name": (request.form.get("name") or "").strip() or "Game",
        "map_ref": map_ref,
        "time_limit": int(request.form.get("time_limit") or 0),
        "forbid_moving": 1 if request.form.get("forbid_moving") else 0,
        "forbid_zooming": 1 if request.form.get("forbid_zooming") else 0,
        "forbid_rotating": 1 if request.form.get("forbid_rotating") else 0,
        "weight": float(request.form.get("weight") or 1.0),
        "cron_challenge": cron_builder.build_cron(request.form.getlist("days"), h, m),
    }


@bp.get("/new")
@login_required
def new(league_id):
    league = _require_league(league_id)
    return render_template("game_form.html", league=league, game=None,
                           maps=queries.list_maps(db.conn(), session["uid"]), cron=cron_builder)


@bp.post("")
@login_required
def create(league_id):
    _require_league(league_id)
    queries.add_game(db.conn(), league_id, **_form_fields(session["uid"]))
    flash("Game saved.")
    return redirect(url_for("leagues.detail", league_id=league_id))


@bp.get("/<int:game_id>/edit")
@login_required
def edit(league_id, game_id):
    league = _require_league(league_id)
    game = queries.get_game(db.conn(), game_id, league_id)
    if not game:
        abort(404)
    return render_template("game_form.html", league=league, game=game,
                           maps=queries.list_maps(db.conn(), session["uid"]), cron=cron_builder)


@bp.post("/<int:game_id>/edit")
@login_required
def update(league_id, game_id):
    _require_league(league_id)
    if not queries.get_game(db.conn(), game_id, league_id):
        abort(404)
    queries.update_game(db.conn(), game_id, league_id, **_form_fields(session["uid"]))
    flash("Game updated.")
    return redirect(url_for("leagues.detail", league_id=league_id))


@bp.post("/<int:game_id>/delete")
@login_required
def delete(league_id, game_id):
    _require_league(league_id)
    queries.delete_game(db.conn(), game_id, league_id)
    flash("Game deleted.")
    return redirect(url_for("leagues.detail", league_id=league_id))
