"""Production entrypoint: migrate, then serve with waitress.

Single process on purpose — the in-process scheduler (added later) must run
exactly once, so do NOT put this behind a multi-worker WSGI server.
"""
from __future__ import annotations

import os

from waitress import serve

from . import db, migrate, scheduler
from .app import create_app


def main() -> None:
    migrate.migrate(db.conn())
    scheduler.start()
    app = create_app()
    port = int(os.environ.get("PORT", "8080"))
    print(f"serving on :{port}")
    serve(app, host="0.0.0.0", port=port, threads=8)


if __name__ == "__main__":
    main()
