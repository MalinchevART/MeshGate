-- Т36 (първи срез): регистър на възлите — decoded User от NODEINFO /
-- MAP_REPORT пакети. Името се учи ВЕДНЪЖ и се показва до ID-то навсякъде;
-- по public_key fingerprint се групира по-късно (стабилна идентичност при
-- смяна на node номера — рефлаш/сблъсък).
CREATE TABLE IF NOT EXISTS node_registry (
  node_id text PRIMARY KEY,          -- !hex, lower-case (като devices.external_id)
  long_name text,
  short_name text,
  hw_model int,
  role int,
  pubkey_fp text,                    -- sha256(public_key), първите 4 байта hex
  first_seen timestamptz NOT NULL DEFAULT now(),
  last_heard timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS node_registry_short_idx ON node_registry (short_name);
