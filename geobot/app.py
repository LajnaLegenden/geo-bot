"""Flask application factory.

Only wires config + routes — no migrations, no scheduler here (those live in
serve.py so they run exactly once, in one process). CSRF is a synchronizer
token: minted in a context processor, checked in before_request for unsafe verbs.
"""
from __future__ import annotations

import os
import secrets

from flask import Flask, abort, render_template, request, session

from . import db, queries
from .blueprints import auth, credentials, games, leagues, maps, stats
from .security import login_required


def create_app() -> Flask:
    app = Flask(__name__)

    key = os.environ.get("SECRET_KEY")
    if not key:
        key = secrets.token_hex(32)
        print("WARNING: SECRET_KEY not set — using a random key (logins reset on restart)")
    app.config["SECRET_KEY"] = key
    app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True)

    @app.before_request
    def _csrf_protect():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
            if not sent or sent != session.get("_csrf"):
                abort(400, "bad or missing CSRF token")

    @app.context_processor
    def _inject_csrf():
        token = session.get("_csrf")
        if not token:
            token = session["_csrf"] = secrets.token_urlsafe(32)
        return {"csrf_token": token}

    app.register_blueprint(auth.bp)
    app.register_blueprint(credentials.bp)
    app.register_blueprint(maps.bp)
    app.register_blueprint(leagues.bp)
    app.register_blueprint(games.bp)
    app.register_blueprint(stats.bp)

    @app.route("/")
    @login_required
    def dashboard():
        user = queries.get_user(db.conn(), session["uid"])
        return render_template(
            "dashboard.html", user=user,
            leagues=queries.list_leagues(db.conn(), session["uid"]),
        )

    return app
