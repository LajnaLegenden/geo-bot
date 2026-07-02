# GeoGuessr Slack bot

Posts a daily GeoGuessr challenge to Slack and keeps a rolling 7-day leaderboard.
Runs entirely on GitHub Actions (free cron) and stores state in a committed JSON file —
no database, no server.

## How it works

- **07:00 UTC** — creates a new challenge, posts the link to Slack.
- **19:00 UTC** — fetches scores for every challenge in the last 7 days, recomputes the
  leaderboard, posts it to Slack, and commits the updated scores back to the repo.

Edit the cron lines in `.github/workflows/bot.yml` to match your timezone.

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

## Config (env vars in the workflow)

| var | default | meaning |
|-----|---------|---------|
| `GEO_MAP` | `world` | map id/slug for the challenge |
| `GEO_TIME_LIMIT` | `0` | seconds per round, 0 = unlimited |
| `GEO_NO_MOVE` | unset | set to `1` for no-move challenges |

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
