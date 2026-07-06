#!/usr/bin/env bash
# Invoked by Coolify scheduled tasks, e.g. `/opt/run.sh new normal`.
# Pulls latest store.json, runs the bot, commits + pushes the update back.
set -euo pipefail

cd /app
git pull --rebase --autostash origin main

python -m geobot.main "$@"

git add data/store.json
git commit -m "update store [skip ci]" || echo "nothing to commit"
git push origin HEAD:main
