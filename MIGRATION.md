# Migrating the old bot → the app

This moves you from the cron/CLI bot (state in a git-committed `data/store.json`) to the
self-hosted Flask app (accounts, config UI, SQLite). Your history carries over and the running
leaderboard/season points continue unbroken.

## What changes

| | Old bot | New app |
|---|---|---|
| Runs as | GitHub Actions cron / Coolify scheduled tasks | one always-on container + in-process scheduler |
| State | `data/store.json` committed to git | SQLite on a persistent `/data` volume |
| Config | env vars + `geobot/maps.py` | per-account UI; credentials encrypted at rest |
| GeoGuessr cookie | `GEO_NCFA` env | a GeoGuessr **credential** in the UI |
| Slack | `SLACK_WEBHOOK_URL` / `SLACK_WORKFLOW_URL` + `SLACK_SINK` | a Slack **credential** (mode = bot/incoming; see README → *Slack setup*) |
| Scheduling | `bot.yml` cron (`new`/`update`) | per-game challenge schedule + per-league post schedule + a pull interval |

## Before you start — gather

- Your GeoGuessr `_ncfa` cookie (the old `GEO_NCFA` value; DevTools → Application → Cookies).
- Your Slack webhook/trigger URL and which mode you used (`SLACK_SINK`: `incoming` or `workflow`).
- Two new secrets, generated once and kept **stable**:
  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # GEO_FERNET_KEY
  python -c "import secrets; print(secrets.token_hex(32))"                                    # SECRET_KEY
  ```
- Your map settings (reference table in Step 2).

## Step 1 — Deploy the app on Coolify

1. New resource → this repo, build pack **Dockerfile**.
2. **Storage:** add a persistent volume mounted at **`/data`**. *(Critical — without it every redeploy wipes the DB. `GEO_DB` defaults to `/data/geobot.db`.)*
3. **Environment variables:** `GEO_FERNET_KEY`, `SECRET_KEY` (both stable). Optionally `PORT` (default 8080) and `BASE_URL` (the app's public URL, e.g. `https://geo.example.com`) — set it so the leaderboard's **📊 Stats** button links to the public stats page; omitted if unset.
4. Add a **Domain** → container port **8080**.
5. Deploy. On boot the schema migrates itself; you'll get the login page.
6. You can now **remove the old env vars** (`GEO_NCFA`, `SLACK_*`, `GITHUB_REPO`, `GITHUB_TOKEN`) — the app doesn't use them; credentials live inside the app.

## Step 2 — Recreate your setup in the UI

1. **Register** (the first account is yours).
2. **Credentials** → add two:
   - GeoGuessr cookie — paste your `_ncfa`.
   - Slack — create a Slack app and use **mode = bot** (README → *Slack setup*: paste
     the manifest, install, copy the bot token + signing secret, then
     `/invite @GeoBot` in the channel). A bot is what gives you buttons, `@`-mentions
     of the players who owe a challenge, and DMs. If your old `SLACK_SINK` was
     `incoming` you can paste that webhook URL with **mode = incoming** instead, but
     it stays non-interactive. **Workflow Builder mode no longer exists** — a
     `workflow` trigger URL can't be reused as either of the other two, so make a bot.
3. **Maps** → paste + validate each (URL is `https://www.geoguessr.com/maps/<id>`):

   | Game name | Map id | Time | Rules | Weight |
   |---|---|---|---|---|
   | `normal` | `6029991c5048850001d572a9` | 120s | no moving | 1.0 |
   | `fast`   | `67101e71077612dd6ac8de79` | 15s  | no moving | 1.75 |

   *(These are your old `geobot/maps.py` values.)*
4. **New league** (e.g. "Daily GeoGuessr"):
   - Channel = pick the workspace + channel the bot was invited to (one dropdown);
     GeoGuessr account = your cookie credential. Set **reminder delivery** while
     you're there (channel / DM / both).
   - Timezone = your local zone (e.g. `Europe/Stockholm`).
   - **Post leaderboard** schedule = your old evening `update` time (Mon–Fri).
   - **Pull results** interval = every 30 or 60 min (keeps stats fresh between posts).
   - Optionally set a **public slug** for a shareable stats page at `/s/<slug>`.
5. **Games** — add two, **named exactly `normal` and `fast`** (the importer matches the store's
   `map` field to game names). Use the table above for map/time/rules/weight, and set each game's
   **new-challenge** schedule to your old times (GitHub Actions defaults were **07:50 UTC** for
   `normal`, **11:24 UTC** for `fast` — use your own timezone-local equivalents).

## Step 3 — Import your history

1. Open the league; note its id from the URL (`/leagues/<id>`).
2. In the Coolify **container terminal**, run:
   ```bash
   python -m geobot.import_store <league_id> data/store.json
   ```
   It prints `imported N challenges, M scores` and is safe to re-run (idempotent).

> The image bakes `data/store.json` from the commit it was built on. To import the very latest,
> first: `git show origin/main:data/store.json > /tmp/store.json` and import `/tmp/store.json`.

## Step 4 — Verify before cutting over

- Open `/leagues/<id>` — the weekly / season / all-time boards should match your old stats site.
- Click **Pull now** (scores refresh) and **Post to Slack now** (a test leaderboard lands in the
  channel). If the cookie is dead you'll get a ⚠️ alert instead — refresh the credential.
- If you set a public slug, check `/s/<slug>`.

## Step 5 — Cut over (stop the old bot)

**Do this once the app is verified** — otherwise both systems post to the same channel and create
duplicate challenges on the same GeoGuessr account.

- **GitHub Actions:** disable the workflow (Actions tab → the bot workflow → ⋯ → **Disable
  workflow**), or remove its `schedule:` block.
- **Old Coolify bot:** delete its **Scheduled Tasks** (`/opt/run.sh new …` / `update`), or stop the
  old resource entirely.
- Time it right before the app's first scheduled challenge, so there's neither a gap nor an overlap.

The old `data/store.json` simply stops updating — the app owns state now (new scores go straight to
SQLite; nothing writes `store.json` again).

## Rollback

The old bot on `main` is untouched. If anything's wrong, re-enable its schedule to revert — the
app's data stays on the `/data` volume independently, and nothing about the old setup is destroyed
until you disable it in Step 5.
