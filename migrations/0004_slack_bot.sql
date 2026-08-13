-- Slack bot transport.
--
-- A Slack credential can now be a *bot* (bot token + signing secret) instead of a
-- webhook URL. A webhook bakes its channel into the URL; a bot token can post
-- anywhere it's invited, so the channel becomes a property of the league:
--   slack_channel_id   — the bound channel ('C…'); NULL for webhook-mode leagues.
--   slack_channel_name — display cache, so rendering a page needs no API call.
--   reminder_delivery  — channel | dm | both (DMs only reach linked players).
--
-- player_links maps a GeoGuessr player to a Slack user so reminders can @-mention
-- the people who actually owe a challenge instead of @here-ing the whole channel.
-- player_key mirrors store.py's player key — `scores.user_id` when present, else
-- the display name (user_id is nullable) — so the join matches the stat math.
-- The UNIQUE index stops one Slack user from holding two players in a league;
-- queries.link_player clears a prior claim before inserting.

ALTER TABLE leagues ADD COLUMN slack_channel_id   TEXT;
ALTER TABLE leagues ADD COLUMN slack_channel_name TEXT;
ALTER TABLE leagues ADD COLUMN reminder_delivery  TEXT NOT NULL DEFAULT 'channel';

CREATE TABLE player_links (
  league_id     INTEGER NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
  player_key    TEXT NOT NULL,
  slack_user_id TEXT NOT NULL,
  linked_at     TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (league_id, player_key)
);
CREATE UNIQUE INDEX ux_player_links_slack ON player_links(league_id, slack_user_id);
