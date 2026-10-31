-- Routing Rules (Фаза R1, docs/09-routing-rules-plan.md §3)

CREATE TABLE IF NOT EXISTS routing_rules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    description text,
    enabled boolean NOT NULL DEFAULT false,
    priority int NOT NULL DEFAULT 100,
    execution_mode text NOT NULL DEFAULT 'first_match'
        CHECK (execution_mode IN ('first_match', 'all_match')),
    definition jsonb NOT NULL,
    draft jsonb,
    current_version int NOT NULL DEFAULT 0,
    created_by text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS routing_rule_versions (
    rule_id uuid NOT NULL REFERENCES routing_rules(id) ON DELETE CASCADE,
    version int NOT NULL,
    definition jsonb NOT NULL,
    note text,
    published_by text,
    published_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (rule_id, version)
);

CREATE TABLE IF NOT EXISTS routing_executions (
    id bigserial PRIMARY KEY,
    rule_id uuid NOT NULL REFERENCES routing_rules(id) ON DELETE CASCADE,
    ts timestamptz NOT NULL DEFAULT now(),
    input_topic text NOT NULL,
    decision text NOT NULL,
    steps jsonb,
    error text,
    duration_ms int
);

CREATE INDEX IF NOT EXISTS idx_routing_exec_rule_ts
    ON routing_executions (rule_id, ts DESC);

CREATE TABLE IF NOT EXISTS routing_stats (
    rule_id uuid PRIMARY KEY REFERENCES routing_rules(id) ON DELETE CASCADE,
    matched bigint NOT NULL DEFAULT 0,
    forwarded bigint NOT NULL DEFAULT 0,
    errors bigint NOT NULL DEFAULT 0,
    last_fired_at timestamptz
);
