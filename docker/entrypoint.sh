#!/usr/bin/env bash
# Set up the git checkout + auth once at container start, then idle.
# Coolify's scheduled tasks exec /opt/run.sh inside this running container.
set -euo pipefail

: "${GITHUB_REPO:?set GITHUB_REPO, e.g. LajnaLegenden/geo-bot}"
: "${GITHUB_TOKEN:?set GITHUB_TOKEN (fine-grained PAT, Contents: read/write)}"

REPO_URL="https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPO}.git"

# State (data/store.json) lives in git — the container is stateless. Clone on
# first boot; every scheduled run pulls latest and pushes its update back.
if [ ! -d /app/.git ]; then
  git clone "$REPO_URL" /app
fi

cd /app
git config --global --add safe.directory /app
git remote set-url origin "$REPO_URL"
git config user.name  "geo-bot"
git config user.email "geo-bot@users.noreply.github.com"

echo "geobot ready — idling for scheduled tasks."
exec sleep infinity
