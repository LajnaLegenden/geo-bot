"""Stats: private fragments behind login (owner-scoped) and a public read-only
page at /s/<slug>. Public routes resolve the slug and 404 unless the league
opted into a public slug, so private leagues never leak.
"""
from __future__ import annotations

from flask import Blueprint, abort, render_template, session

from .. import db, queries, stats_html
from ..security import login_required

bp = Blueprint("stats", __name__)


def _fragment(league_id: int, key: str) -> str:
    out = stats_html.render(key, queries.load_league_data(db.conn(), league_id))
    if out is None:
        abort(404)
    return out


@bp.get("/leagues/<int:league_id>/fragment/<key>")
@login_required
def private_fragment(league_id, key):
    if not queries.get_league(db.conn(), league_id, session["uid"]):
        abort(404)
    return _fragment(league_id, key)


@bp.get("/s/<slug>")
def public(slug):
    league = queries.get_league_by_slug(db.conn(), slug)
    if not league:
        abort(404)
    return render_template("public_stats.html", league=league, slug=slug)


@bp.get("/s/<slug>/fragment/<key>")
def public_fragment(slug, key):
    league = queries.get_league_by_slug(db.conn(), slug)
    if not league:
        abort(404)
    return _fragment(league["id"], key)
