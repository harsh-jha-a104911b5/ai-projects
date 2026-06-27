-- Scaffold tables for M2+ agent loop. No data written in M1.

CREATE TABLE leads (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT,
    name        TEXT,
    phone       TEXT,
    metadata    JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE conversations (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id     UUID        REFERENCES leads(id) ON DELETE SET NULL,
    channel     TEXT        NOT NULL DEFAULT 'web',
    status      TEXT        NOT NULL DEFAULT 'active',
    metadata    JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_conversations_status CHECK (status IN ('active', 'closed', 'handed_off')),
    CONSTRAINT chk_conversations_channel CHECK (channel IN ('web', 'email', 'whatsapp'))
);
CREATE INDEX ix_conversations_lead_id ON conversations(lead_id);

CREATE TABLE messages (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  UUID        NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role             TEXT        NOT NULL,
    content          TEXT        NOT NULL,
    tool_name        TEXT,
    tool_call_id     TEXT,
    metadata         JSONB       NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_messages_role CHECK (role IN ('user', 'assistant', 'system', 'tool'))
);
CREATE INDEX ix_messages_conversation_id ON messages(conversation_id);

CREATE TABLE traces (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  UUID        REFERENCES conversations(id) ON DELETE CASCADE,
    turn_index       INTEGER     NOT NULL,
    input_tokens     INTEGER,
    output_tokens    INTEGER,
    latency_ms       INTEGER,
    retrieval_chunks JSONB,
    llm_model        TEXT,
    metadata         JSONB       NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_traces_conversation_id ON traces(conversation_id);
