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

    # Deploys have to reach open tabs. The origin sends no Cache-Control of its
    # own, so Cloudflare applies its 4h default to /static/* — new markup could
    # then be styled by an old stylesheet for hours. Fingerprint every static URL
    # with the file's mtime (so a deploy changes the URL, busting browser *and*
    # edge cache) and let the pages themselves say they're never storable.
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 31_536_000  # a year; the URL is versioned

    @app.url_defaults
    def _version_static(endpoint, values):
        if endpoint == "static" and "filename" in values and "v" not in values:
            try:
                values["v"] = int(os.stat(
                    os.path.join(app.static_folder, values["filename"])).st_mtime)
            except OSError:
                pass  # missing file: let url_for build the plain URL and 404 loudly

    @app.after_request
    def _no_store_html(resp):
        # Pages are per-session and per-league state, and htmx fragments are
        # polled — neither should ever come back from a cache.
        if resp.mimetype == "text/html":
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

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

    @app.teardown_request
    def _rollback_on_error(exc):
        # A failed write leaves sqlite's implicit transaction open, holding the
        # WAL write lock -> later requests get "database is locked". Roll back any
        # request that ended in an (uncaught) error so the lock is always released.
        if exc is not None:
            try:
                db.conn().rollback()
            except Exception:
                pass

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
