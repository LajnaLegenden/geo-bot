# GeoGuessr Slack bot

Posts a daily GeoGuessr challenge to Slack and keeps a weekly leaderboard that
resets every Monday. Runs entirely on GitHub Actions (free cron) and stores state
in a committed JSON file — no database, no server.

## How it works

- **07:00 UTC** — creates a new challenge, posts the link to Slack.
- **19:00 UTC** — fetches scores for every challenge in the last 7 days, recomputes
  **this week's** leaderboard (scores since Monday), posts it to Slack, and commits
  the updated scores back to the repo.

The week boundary is the runner's local date: Monday 00:00 in `TZ` on Coolify
(e.g. Europe/Stockholm), or UTC on GitHub Actions. All scores are kept in
`data/store.json` forever, so the all-time views on the stats site still work.

Edit the cron lines in `.github/workflows/bot.yml` to match your timezone.

## Deploy on Coolify (self-hosted scheduler)

GitHub cron runs scheduled jobs late (often 1–2h). To fire on time, run it on
Coolify instead — it owns the scheduling. The container just idles; Coolify's
**Scheduled Tasks** exec the bot inside it on a cron.

1. **New Resource → your repo**, build pack **Dockerfile** (this repo's `Dockerfile`).
2. **Environment Variables** — set the vars from [`.env.example`](.env.example):
   `GITHUB_REPO`, `GITHUB_TOKEN` (fine-grained PAT, **Contents: read/write** on this
   repo — used to pull latest and push `data/store.json` back), `GEO_NCFA`,
   `SLACK_SINK`, and the matching Slack URL. Also set `TZ=Europe/Stockholm` so the
   cron times below are local (DST handled automatically).
3. Deploy. The container clones the repo, wires up git auth, then idles.
4. **Scheduled Tasks** — add three, each a cron + command:

   | Cron (in `TZ`)   | Command                          | What it does            |
   |------------------|----------------------------------|-------------------------|
   | `50 9 * * 1-5`   | `/opt/run.sh new normal`         | create "normal" challenge |
   | `24 13 * * 1-5`  | `/opt/run.sh new fast`           | create "fast" challenge   |
   | `15 16 * * 1-5`  | `/opt/run.sh update`             | refresh scores + leaderboard |

State still lives in git: each run pulls latest `data/store.json`, runs, and
pushes the update back — same model as Actions, just on-time. Disable the GHA
`schedule:` block so you don't get double runs (keep `workflow_dispatch` for
manual/backup runs).

## Stats website

The container also serves a small stats site (this week + all-time leaderboards,
per-map averages, per-player breakdown) on **port 8080**, refreshed via htmx.
It reads `data/store.json` server-side and serves **only computed stats** — the
raw store, `data/` and `.git` are never exposed. Data is as fresh as the last
`update` run (each run pulls latest before serving).

To reach it, add a **Domain** (or exposed port) for the resource in Coolify
pointing at container port `8080`. Nothing else to configure. Run it locally with
`GEO_STORE=data/store.json python -m geobot.web` and open http://localhost:8080.

## Setup

1. **Fork/create the repo** and push these files.

2. **Get your GeoGuessr session cookie.** Log in at geoguessr.com, open DevTools →
   Application → Cookies → copy the value of `_ncfa`. (Treat it like a password; it
   grants access to your account. Use a throwaway account if you'd rather.)

3. **Create a Slack Incoming Webhook** for your channel:
   api.slack.com/apps → Create app → Incoming Webhooks → Add to channel → copy the URL.

4. **Add repo secrets** (Settings → Secrets and variables → Actions):
   - `GEO_NCFA` — the cookie value
   - `SLACK_WEBHOOK_URL` — the webhook URL

5. **Enable Actions** and either wait for the cron or trigger manually
   (Actions tab → geoguessr-bot → Run workflow → pick `new` or `update`).

## Slack Workflow Builder (alternative)

Instead of an incoming webhook you can post through a Slack **Workflow Builder**
"From a webhook" trigger. Slack owns the message layout, so non-technical users
can edit the wording in Slack without touching this repo. Tradeoff: no Block Kit —
plainer formatting (no bold, links posted as bare URLs).

1. In Slack: **Automations → Workflows → New Workflow → From a webhook**.
2. Add two **variables** named exactly `title` and `body` (both text).
3. Add a **Send a message** step and drop the `title`/`body` variables into it.
4. Publish, then copy the webhook **URL**.
5. Add it as the `SLACK_WORKFLOW_URL` repo secret.
6. In `.github/workflows/bot.yml`, set `SLACK_SINK: workflow`.

Leave `SLACK_SINK` unset or `incoming` to keep using the incoming webhook.

## Maps

Map configs live in [`geobot/maps.py`](geobot/maps.py) — the `MAPS` dict, one
entry per named map. Each entry is the challenge settings (`map_id`,
`time_limit`, `forbid_moving`, …) plus an optional `weight`:

```python
MAPS = {
    "normal": {"map_id": "…", "time_limit": 120, "forbid_moving": True},
    "fast":   {"map_id": "…", "time_limit": 15,  "forbid_moving": True, "weight": 1.75},
}
```

The workflow picks a map by name — one `new` cron per map (see `bot.yml`), or the
`map` input when you run it manually. Add a map by adding a dict entry and (if you
want it scheduled) a cron; validate with `python -m geobot.maps`.

`weight` scales that map's scores in the **combined** 7-day leaderboard, so an
easier map doesn't dominate the raw-score sum (`1.0` if omitted). Raw scores are
stored unchanged; tuning a weight re-scales the board retroactively.

## Cookie expiry

Before doing anything, each run pings an authenticated endpoint to confirm the
`_ncfa` cookie still works. If it's dead (expired, password changed, or logged out in
that browser session), the bot posts a ⚠️ warning to Slack and exits instead of failing
silently. To fix: grab a fresh `_ncfa` cookie and update the `GEO_NCFA` repo secret —
no code change. Using a dedicated GeoGuessr account for the bot keeps your personal
logins and password changes from ever killing it.

## Caveats
GeoGuessr has no official API. These endpoints are unofficial, can break when
GeoGuessr changes their site, and may run against their Terms of Service — fine for a
private friend group, think twice before scaling it. The leaderboard only counts people
who actually played each day's challenge with the account that has the link.

## Local test

```bash
pip install -r requirements.txt
export GEO_NCFA=... SLACK_WEBHOOK_URL=...
python -m geobot.main new
python -m geobot.main update
```
