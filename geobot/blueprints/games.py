"""Games nested under a league: one saved map + full challenge settings + weight
+ a new-challenge schedule. Authorized via the parent league (owner-scoped), then
the map is re-checked against the caller.
"""
from __future__ import annotations

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, session, url_for,
)

from .. import cron_builder, db, jobs, queries, scheduler
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


def _editable_season(league_id, season_id):
    """A game may only be created/changed inside a season that hasn't been
    superseded — see queries.season_is_editable. 404 rather than 403: an
    un-editable season is 'no such editable thing here'."""
    if season_id is None or not queries.season_is_editable(db.conn(), season_id, league_id):
        abort(404)
    return season_id


def _season_of(game):
    return game["season_id"]


def _back(league_id, season_id):
    return redirect(url_for("leagues.detail", league_id=league_id, season=season_id))


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


def _target_season(league_id):
    """The season a new game lands in: ?season=<id> if given (that's how you set
    up an upcoming season), else the live one."""
    sid = request.args.get("season", type=int) or request.form.get("season_id", type=int)
    if sid is None:
        current = queries.current_season(db.conn(), league_id)
        sid = current["id"] if current else None
    return _editable_season(league_id, sid)


@bp.get("/new")
@login_required
def new(league_id):
    league = _require_league(league_id)
    sid = _target_season(league_id)
    return render_template("game_form.html", league=league, game=None,
                           season=queries.get_season(db.conn(), sid, league_id),
                           maps=queries.list_maps(db.conn(), session["uid"]), cron=cron_builder)


@bp.post("")
@login_required
def create(league_id):
    _require_league(league_id)
    sid = _target_season(league_id)
    gid = queries.add_game(db.conn(), league_id, sid, **_form_fields(session["uid"]))
    scheduler.on_game_saved(league_id, gid)
    flash("Game saved.")
    return _back(league_id, sid)


@bp.get("/<int:game_id>/edit")
@login_required
def edit(league_id, game_id):
    league = _require_league(league_id)
    game = queries.get_game(db.conn(), game_id, league_id)
    if not game:
        abort(404)
    _editable_season(league_id, _season_of(game))
    return render_template("game_form.html", league=league, game=game,
                           season=queries.get_season(db.conn(), game["season_id"], league_id),
                           maps=queries.list_maps(db.conn(), session["uid"]), cron=cron_builder)


@bp.post("/<int:game_id>/edit")
@login_required
def update(league_id, game_id):
    _require_league(league_id)
    game = queries.get_game(db.conn(), game_id, league_id)
    if not game:
        abort(404)
    _editable_season(league_id, _season_of(game))
    queries.update_game(db.conn(), game_id, league_id, **_form_fields(session["uid"]))
    scheduler.on_game_saved(league_id, game_id)
    flash("Game updated.")
    return _back(league_id, game["season_id"])


@bp.post("/<int:game_id>/delete")
@login_required
def delete(league_id, game_id):
    _require_league(league_id)
    game = queries.get_game(db.conn(), game_id, league_id)
    if not game:
        abort(404)
    # challenges FK to games ON DELETE CASCADE, so this drops the game's history
    # too — which is exactly why a superseded season's games can't be deleted.
    _editable_season(league_id, _season_of(game))
    queries.delete_game(db.conn(), game_id, league_id)
    scheduler.on_game_deleted(game_id)
    flash("Game deleted.")
    return _back(league_id, game["season_id"])


@bp.post("/<int:game_id>/run")
@login_required
def run(league_id, game_id):
    _require_league(league_id)
    game = queries.get_game(db.conn(), game_id, league_id)
    if not game:
        abort(404)
    try:
        # no season check here — post_challenge owns that rule for every caller
        flash("Challenge: " + jobs.post_challenge(league_id, game_id))
    except Exception as e:  # surface network/API failures, don't 500
        flash(f"Challenge failed: {e}")
    return _back(league_id, game["season_id"])
