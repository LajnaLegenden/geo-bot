"""Login gate. Sessions are Flask signed cookies (no server-side table);
`session["uid"]` is the logged-in user id. Every owned-resource query elsewhere
filters by this uid and 404s on a miss — that's the whole isolation model.
"""
from __future__ import annotations

from functools import wraps

from flask import g, redirect, session, url_for


def current_uid() -> int | None:
    return session.get("uid")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("uid"):
            return redirect(url_for("auth.login"))
        g.uid = session["uid"]
        return view(*args, **kwargs)

    return wrapped
