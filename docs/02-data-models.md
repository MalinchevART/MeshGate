# MeshGate — модели на данните (PostgreSQL)

Обвързващо за `migrations/`. Идентификаторите са на английски; коментарите тук — български.
Всички таблици с `id uuid PRIMARY KEY DEFAULT gen_random_uuid()` и
`created_at timestamptz NOT NULL DEFAULT now()`, освен где differently указано.

## Диаграма (основни връзки)

```
users ──< audit_log
users ──< configuration_changes >── profiles ──< profile_versions
devices ──< device_observations          │
devices ──< events >── packets ──< packet_decodings
bridge_configs ──< bridge_rules ──< bridge_events
alert_rules ──< alerts
integrations    mqtt_credentials >── devices
```

## Идентичност и одит

### users
- `username citext UNIQUE NOT NULL`
- `password_hash text NOT NULL` (argon2id)
- `role text NOT NULL CHECK (role IN ('viewer','operator','admin'))`
- `disabled boolean DEFAULT false`

### audit_log
- `ts timestamptz NOT NULL DEFAULT now()`, индекс по `ts DESC`
- `user_id uuid REFERENCES users` (NULL за системни действия)
- `action text NOT NULL` — напр. `bridge.create`, `profile.apply`, `auth.login_failed`
- `entity text NOT NULL`, `entity_id uuid`
- `details jsonb NOT NULL DEFAULT '{}'`
- `ip inet`
- САМО append (без UPDATE/DELETE от приложението). Изтриване — изрична retention политика.

## Устройства и наблюдения

### devices
- `protocol text NOT NULL` — `mqtt` | `meshtastic` | `meshcore` | ...
- `external_id text NOT NULL` — client_id / node num / ...
- `name text`, `UNIQUE(protocol, external_id)`
- `first_seen_at`, `last_seen_at timestamptz NOT NULL`
- `metadata jsonb DEFAULT '{}'` — хардуер, версия, източник
- `capabilities jsonb DEFAULT '{}'` — какво поддържа адаптерът
- `status text NOT NULL DEFAULT 'unknown'` — `online|offline|unknown`

### device_observations
- `device_id uuid REFERENCES devices ON DELETE CASCADE`
- `ts timestamptz NOT NULL DEFAULT now()`, PK `(device_id, ts)`
- `rssi real`, `snr real`, `battery_level real`, `channel text`, `extra jsonb`
- **RSSI/SNR са NULL-able — не всяко съобщение ги носи.** Никаква логика не ги предполага.

## Пакети и събития

### packets
- `ts timestamptz NOT NULL DEFAULT now()` — BRIN индекс + btree `(ts DESC)`
- `topic text NOT NULL`, `protocol text NOT NULL`, `node_id text`
- `packet_type text` — напр. `text`, `telemetry`, `position`, `nodeinfo`, `unknown`
- `payload_raw bytea` — суровият payload; **изтрива се от retention**, метаданните остават
- `payload_text text` — когато payload-ът е текстов (UTF-8 валиден)
- `payload_size int NOT NULL`
- `qos smallint`, `retain boolean DEFAULT false`
- `decoder_id text`, `decode_status text NOT NULL DEFAULT 'pending'`
  (`decoded|partial|failed|not_attempted`), `decode_error text`
- `origin text NOT NULL DEFAULT 'local'` — `local|bridge:<bridge_id>` (loop prevention)

### packet_decodings
- `packet_id uuid REFERENCES packets ON DELETE CASCADE`
- `decoder_id text NOT NULL`, `attempted_at timestamptz NOT NULL DEFAULT now()`
- `decoded jsonb`, `error text`

### events (нормализирани)
- `ts timestamptz NOT NULL DEFAULT now()`
- `device_id uuid REFERENCES devices ON DELETE SET NULL`
- `packet_id uuid REFERENCES packets ON DELETE SET NULL`
- `source text NOT NULL` — адаптерът (`generic-mqtt`, `meshtastic`, ...)
- `event_type text NOT NULL` — `message`, `telemetry`, `position`, `nodeinfo`, `status`
- `payload jsonb NOT NULL DEFAULT '{}'` — нормализирано съдържание
- Индекси: `(event_type, ts DESC)`, `(device_id, ts DESC)`, GIN по `payload`

## Bridge

### bridge_configs
- `name text UNIQUE NOT NULL`, `enabled boolean NOT NULL DEFAULT false`
- `direction text NOT NULL CHECK (direction IN ('inbound','outbound','bidirectional'))`
- `remote_url text NOT NULL` — валидира се срещу SSRF (docs/06-threat-model.md §SSRF)
- `remote_port int NOT NULL DEFAULT 8883`
- `tls_mode text NOT NULL DEFAULT 'verify'` — `verify|insecure` (insecure → изричен флаг + audit)
- `credentials_ref text` — препратка към secret storage, никога plaintext
- `topic_map jsonb NOT NULL DEFAULT '[]'` — [{from, to}]
- `rate_limit_per_min int`, `burst int`
- `health text NOT NULL DEFAULT 'unknown'` — `up|down|degraded|unknown`, `last_error_at`

### bridge_rules
- `bridge_id uuid REFERENCES bridge_configs ON DELETE CASCADE`
- `kind text NOT NULL CHECK (kind IN ('allow','deny'))`
- `topic_pattern text NOT NULL`, `payload_type text` (NULL = всички)
- `priority int NOT NULL DEFAULT 100`, `reason text` — човешки текст, показван в UI

### bridge_events
- `ts timestamptz NOT NULL DEFAULT now()`, индекс `(bridge_id, ts DESC)`
- `bridge_id uuid REFERENCES`, `rule_id uuid REFERENCES`
- `decision text NOT NULL` — `forwarded|rejected|rate_limited|loop_blocked`
- `topic text NOT NULL`, `reason text NOT NULL`

## Профили и конфигурация

### profiles / profile_versions
- profiles: `name text UNIQUE NOT NULL`, `description text`
- profile_versions: `profile_id uuid REFERENCES`, `version int NOT NULL`,
  `spec jsonb NOT NULL`, `created_by uuid REFERENCES users`,
  `UNIQUE(profile_id, version)`

### configuration_changes
- `ts timestamptz`, `user_id uuid REFERENCES users`
- `scope text NOT NULL` — какво е променено (`profile`, `bridge`, `acl`, ...)
- `before jsonb`, `after jsonb`, `diff jsonb NOT NULL`
- `rolled_back_from uuid` — върната промяна сочи източника

Фабрични профили (seed, версионирано съдържание в `profiles/` при имплементация):
Home Gateway, Mesh Monitor, Isolated Lab, Controlled Public Bridge, Developer/Debug.

## Аларми

### alert_rules
- `name text UNIQUE NOT NULL`, `enabled boolean DEFAULT true`
- `condition jsonb NOT NULL` — {source?, event_type?, device_id?, topic?, metric?, op, value}
- `severity text NOT NULL CHECK (severity IN ('info','warning','critical'))`
- `action jsonb NOT NULL DEFAULT '{}'` — {notify?, publish_topic?, webhook?}

### alerts
- `rule_id uuid REFERENCES alert_rules`, `ts timestamptz NOT NULL DEFAULT now()`
- `severity text NOT NULL`, `message text NOT NULL`
- `event_id uuid REFERENCES events ON DELETE SET NULL`
- `acknowledged_by uuid REFERENCES users`, `acknowledged_at timestamptz`

## Интеграции и MQTT достъп

### integrations
- `kind text NOT NULL` — `nodered|homeassistant|zigbee2mqtt|webhook|...`
- `config jsonb NOT NULL DEFAULT '{}'`
- `state text NOT NULL DEFAULT 'disabled'` — `enabled|disabled|failed`
- `last_error text`, `last_checked_at timestamptz`
- Провалена интеграция НЕ спира старта на приложението.

### mqtt_credentials (per-device)
- `device_id uuid REFERENCES devices ON DELETE CASCADE`
- `username text UNIQUE NOT NULL`
- `secret_ref text NOT NULL` — хеш/препратка; plaintext не се съхранява
- `acl jsonb NOT NULL` — [{pattern, access: 'pub'|'sub'|'pubsub'}]
- Синхронизира се с брокера през BrokerAdapter (built-in authn DB на EMQX).

## Retention (стойности по подразбиране; конфигурируемо)

| Данни | Подразбиране | Механизъм |
|-------|--------------|-----------|
| `packets.payload_raw` | 14 дни | периодична задача → NULL-ване + VACUUM |
| `events` | 365 дни | периодична задача |
| `device_observations` | 90 дни | периодична задача |
| `audit_log` | без изтриване | изрична политика |
| метрики (VM, Фаза 2) | отделен живот | конфигурация на VM |
