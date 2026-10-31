-- MeshGate начална схема (виж docs/02-data-models.md)

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username text UNIQUE NOT NULL,
  password_hash text NOT NULL,
  role text NOT NULL DEFAULT 'viewer' CHECK (role IN ('viewer','operator','admin')),
  disabled boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
  token_hash text PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL
);

CREATE TABLE api_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  token_hash text UNIQUE NOT NULL,
  can_publish boolean NOT NULL DEFAULT false,
  allowed_topics jsonb NOT NULL DEFAULT '[]',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ts timestamptz NOT NULL DEFAULT now(),
  user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  username text,
  action text NOT NULL,
  entity text,
  entity_id text,
  details jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX audit_log_ts_idx ON audit_log (ts DESC);

CREATE TABLE settings (
  key text PRIMARY KEY,
  value jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE devices (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  protocol text NOT NULL DEFAULT 'mqtt',
  external_id text NOT NULL,
  name text,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb NOT NULL DEFAULT '{}',
  capabilities jsonb NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'unknown',
  UNIQUE (protocol, external_id)
);

CREATE TABLE device_observations (
  device_id uuid NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  ts timestamptz NOT NULL DEFAULT now(),
  rssi real,
  snr real,
  battery_level real,
  channel text,
  extra jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (device_id, ts)
);

CREATE TABLE packets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ts timestamptz NOT NULL DEFAULT now(),
  topic text NOT NULL,
  protocol text NOT NULL DEFAULT 'mqtt',
  node_id text,
  packet_type text NOT NULL DEFAULT 'message',
  payload_raw bytea,
  payload_text text,
  payload_size int NOT NULL,
  qos smallint,
  retain boolean NOT NULL DEFAULT false,
  decoder_id text,
  decode_status text NOT NULL DEFAULT 'not_attempted'
    CHECK (decode_status IN ('decoded','partial','failed','not_attempted')),
  decode_error text,
  origin text NOT NULL DEFAULT 'local'
);
CREATE INDEX packets_ts_idx ON packets (ts DESC);
CREATE INDEX packets_topic_idx ON packets (topic);

CREATE TABLE events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ts timestamptz NOT NULL DEFAULT now(),
  device_id uuid REFERENCES devices(id) ON DELETE SET NULL,
  packet_id uuid REFERENCES packets(id) ON DELETE SET NULL,
  source text NOT NULL,
  event_type text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX events_ts_idx ON events (ts DESC);
CREATE INDEX events_device_idx ON events (device_id, ts DESC);

CREATE TABLE bridge_configs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text UNIQUE NOT NULL,
  enabled boolean NOT NULL DEFAULT false,
  direction text NOT NULL DEFAULT 'outbound'
    CHECK (direction IN ('inbound','outbound','bidirectional')),
  remote_host text NOT NULL,
  remote_port int NOT NULL DEFAULT 1883,
  tls_mode text NOT NULL DEFAULT 'plain' CHECK (tls_mode IN ('plain','verify','insecure')),
  allow_internal boolean NOT NULL DEFAULT false,
  topic_map jsonb NOT NULL DEFAULT '[]',
  rate_limit_per_min int NOT NULL DEFAULT 60,
  health text NOT NULL DEFAULT 'unknown',
  last_error text,
  last_error_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE bridge_rules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  bridge_id uuid NOT NULL REFERENCES bridge_configs(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('allow','deny')),
  topic_pattern text NOT NULL,
  payload_type text,
  priority int NOT NULL DEFAULT 100,
  reason text
);

CREATE TABLE bridge_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ts timestamptz NOT NULL DEFAULT now(),
  bridge_id uuid REFERENCES bridge_configs(id) ON DELETE CASCADE,
  decision text NOT NULL,
  topic text NOT NULL,
  reason text NOT NULL,
  detail jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX bridge_events_idx ON bridge_events (bridge_id, ts DESC);

CREATE TABLE mqtt_credentials (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username text UNIQUE NOT NULL,
  device_id uuid REFERENCES devices(id) ON DELETE CASCADE,
  allowed_topics jsonb NOT NULL DEFAULT '[]',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text UNIQUE NOT NULL,
  description text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE profile_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  version int NOT NULL,
  spec jsonb NOT NULL,
  created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (profile_id, version)
);

CREATE TABLE configuration_changes (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ts timestamptz NOT NULL DEFAULT now(),
  user_id uuid REFERENCES users(id),
  scope text NOT NULL,
  before jsonb,
  after jsonb,
  diff jsonb NOT NULL DEFAULT '{}'
);
