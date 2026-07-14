-- Separate "pull results" (silent, frequent) from "post leaderboard" (daily Slack).
-- pull_minutes: how often to fetch+upsert scores in the background; 0 = off.
-- The existing cron_results now drives only the Slack post.
ALTER TABLE leagues ADD COLUMN pull_minutes INTEGER NOT NULL DEFAULT 60;
