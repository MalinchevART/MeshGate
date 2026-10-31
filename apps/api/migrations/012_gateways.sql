-- Т37 „Гейтове и канали" (по сигнал на собственика 30.10): кръстосана
-- референция кой реален MQTT гейтове кой канал излъчва. gateway_id идва от
-- ServiceEnvelope-а (реалният възел, качил пакета в брокера), каналът от
-- темата; мостовете и правилата са отделни пътища (origin маркерите).
CREATE TABLE IF NOT EXISTS gateway_channels (
  gateway_id text NOT NULL,          -- !hex на MQTT гейта (или bridge:<име>)
  channel text NOT NULL,             -- логически канал (5-ият токен) или topic class
  packets bigint NOT NULL DEFAULT 0,
  last_ts timestamptz NOT NULL DEFAULT now(),
  first_ts timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (gateway_id, channel)
);
CREATE INDEX IF NOT EXISTS gateway_channels_last_idx
  ON gateway_channels (last_ts DESC);

-- регистър на гейтовете (име се учи от node_registry — гейтовете са възли)
CREATE TABLE IF NOT EXISTS gateways (
  gateway_id text PRIMARY KEY,
  kind text NOT NULL DEFAULT 'mqtt' CHECK (kind IN ('mqtt', 'bridge', 'rule', 'platform')),
  first_seen timestamptz NOT NULL DEFAULT now(),
  last_heard timestamptz NOT NULL DEFAULT now()
);
