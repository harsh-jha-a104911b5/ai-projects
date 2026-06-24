-- Expand traces table for turn-level logging (M5).
-- Each row = one user turn in a conversation.

ALTER TABLE traces
    ADD COLUMN IF NOT EXISTS user_message    TEXT,
    ADD COLUMN IF NOT EXISTS assistant_message TEXT,
    ADD COLUMN IF NOT EXISTS tool_calls      JSONB NOT NULL DEFAULT '[]';
