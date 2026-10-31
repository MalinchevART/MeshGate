-- Т36 срез 2: история на преименуванията. NODEINFO учи имената на възлите —
-- при смяна записваме старата употреба като затворен период; така личи КОГА
-- възелът е сменил името (преименувание/ре-флаш). Групиране по pubkey е
-- заявка (node_registry.pubkey_fp от Т36 срез 1) — без нова таблица.

CREATE TABLE IF NOT EXISTS node_names_history (
    id          BIGSERIAL   PRIMARY KEY,
    node_id     TEXT        NOT NULL,
    long_name   TEXT,
    short_name  TEXT,
    pubkey_fp   TEXT,
    valid_from  TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS node_names_history_node_idx
    ON node_names_history (node_id, valid_from DESC);
