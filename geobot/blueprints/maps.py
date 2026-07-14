"""Saved maps, added by paste + validate. /maps/resolve is an htmx endpoint that
resolves a pasted id/URL against GeoGuessr (using the user's first GeoGuessr
credential) and returns a preview fragment with a Save form.
"""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from .. import db, queries
from ..geoguessr import GeoGuessr
from ..security import login_required

bp = Blueprint("maps", __name__, url_prefix="/maps")


@bp.get("")
@login_required
def index():
    return render_template("maps.html", maps=queries.list_maps(db.conn(), session["uid"]))


@bp.post("/resolve")
@login_required
def resolve():
    uid = session["uid"]
    pasted = (request.form.get("pasted") or "").strip()
    geo = queries.list_credentials(db.conn(), uid, kind="geoguessr")
    if not geo:
        return render_template("_map_preview.html", error="Add a GeoGuessr credential first.")
    if not pasted:
        return render_template("_map_preview.html", error="Paste a map URL or ID.")
    cookie = queries.get_credential_secret(db.conn(), geo[0]["id"], uid)
    try:
        info = GeoGuessr(cookie).resolve_map(pasted)
    except Exception as e:  # network/HTTP/parse — show it, don't 500
        return render_template("_map_preview.html", error=f"Couldn't resolve that map: {e}")
    return render_template("_map_preview.html", info=info)


@bp.post("")
@login_required
def create():
    map_id = (request.form.get("map_id") or "").strip()
    name = (request.form.get("name") or "").strip()
    thumb = (request.form.get("thumbnail") or "").strip() or None
    if not map_id or not name:
        flash("Resolve a map before saving.")
        return redirect(url_for("maps.index"))
    queries.add_map(db.conn(), session["uid"], name, map_id, thumb)
    flash("Map saved.")
    return redirect(url_for("maps.index"))


@bp.post("/<int:map_pk>/delete")
@login_required
def delete(map_pk):
    queries.delete_map(db.conn(), map_pk, session["uid"])
    flash("Map deleted.")
    return redirect(url_for("maps.index"))
