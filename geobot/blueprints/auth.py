"""Registration, login, logout. Open self-registration; passwords hashed with
werkzeug. On auth success we clear the session (drops any stale CSRF token) and
set `uid` — the only thing the rest of the app trusts.
"""
from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .. import db, queries

bp = Blueprint("auth", __name__)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        pw = request.form.get("password") or ""
        if not email or not pw:
            flash("Email and password are required.")
            return render_template("register.html"), 400
        if queries.get_user_by_email(db.conn(), email):
            flash("That email is already registered.")
            return render_template("register.html"), 400
        uid = queries.create_user(db.conn(), email, generate_password_hash(pw))
        session.clear()
        session["uid"] = uid
        return redirect(url_for("dashboard"))
    return render_template("register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        pw = request.form.get("password") or ""
        user = queries.get_user_by_email(db.conn(), email)
        if not user or not check_password_hash(user["password_hash"], pw):
            flash("Wrong email or password.")
            return render_template("login.html"), 401
        session.clear()
        session["uid"] = user["id"]
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
