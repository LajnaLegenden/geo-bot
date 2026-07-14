"""Credential pool: GeoGuessr cookies + transport tokens (Slack/Discord).
Secrets are encrypted by queries.add_credential; the plaintext is never shown
back after saving.
"""
from __future__ import annotations

import json
import sqlite3

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from .. import db, queries
from ..security import login_required

bp = Blueprint("credentials", __name__, url_prefix="/credentials")

KINDS = {"geoguessr": "GeoGuessr cookie", "slack": "Slack", "discord": "Discord"}


@bp.get("")
@login_required
def index():
    creds = queries.list_credentials(db.conn(), session["uid"])
    return render_template("credentials.html", creds=creds, kinds=KINDS)


@bp.post("")
@login_required
def create():
    kind = request.form.get("kind")
    label = (request.form.get("label") or "").strip()
    secret = (request.form.get("secret") or "").strip()
    if kind not in KINDS or not label or not secret:
        flash("Kind, label, and secret are all required.")
        return redirect(url_for("credentials.index"))
    meta = json.dumps({"mode": request.form.get("mode") or "incoming"}) if kind == "slack" else None
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
