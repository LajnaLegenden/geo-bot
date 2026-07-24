-- Optional per-league "still to play" reminder post.
-- cron_reminder: schedule for the reminder (same "min hour * * dow" format as
-- cron_results); NULL = reminders off (the scheduler just doesn't add the job).
-- reminder_title/body: the UI-configured message; not-yet-played names are
-- appended to the body when it's sent.
ALTER TABLE leagues ADD COLUMN cron_reminder TEXT;
ALTER TABLE leagues ADD COLUMN reminder_title TEXT NOT NULL DEFAULT '⏰ Still to play today';
ALTER TABLE leagues ADD COLUMN reminder_body  TEXT NOT NULL DEFAULT '';
