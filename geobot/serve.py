"""Production entrypoint: migrate, then serve with waitress.

Single process on purpose — the in-process scheduler (added later) must run
exactly once, so do NOT put this behind a multi-worker WSGI server.
"""
from __future__ import annotations

import json
import os

from waitress import serve

from . import db, migrate, scheduler
from .app import create_app


def check_slack_config(conn) -> list[str]:
    """Warnings about Slack setup that only show up at post time otherwise.

    Workflow Builder mode was removed and can't be migrated automatically — a trigger
    URL is not an incoming-webhook URL — so a credential still set to it needs its
    leagues re-pointed by hand. Bot mode needs BASE_URL to build the interactivity
    request URL; without it, buttons and linking silently do nothing.
    """
    warnings = []
    modes = {}
    for r in conn.execute("SELECT label, meta FROM credentials WHERE kind='slack'"):
        meta = json.loads(r["meta"]) if r["meta"] else {}
        modes.setdefault(meta.get("mode") or "incoming", []).append(r["label"])
    if modes.get("workflow"):
        warnings.append(
            "Slack Workflow Builder mode was removed — re-point the leagues using "
            f"{', '.join(modes['workflow'])} to a Slack bot credential, or they will "
            "stop posting."
        )
    if modes.get("bot") and not os.environ.get("BASE_URL"):
        warnings.append(
            "BASE_URL is not set, so Slack can't call back: buttons, player linking "
            "and DMs won't work. Set it to this app's public https URL."
        )
    return warnings


def main() -> None:
    migrate.migrate(db.conn())
    for w in check_slack_config(db.conn()):
        print(f"WARNING: {w}")
    scheduler.start()
    app = create_app()
    port = int(os.environ.get("PORT", "8080"))
    print(f"serving on :{port}")
    serve(app, host="0.0.0.0", port=port, threads=8)


if __name__ == "__main__":
    main()
