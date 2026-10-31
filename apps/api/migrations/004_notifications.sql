-- Фаза 5 (първи срез): канали за известия + журнал на изпратеното
CREATE TABLE IF NOT EXISTS notification_channels (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text UNIQUE NOT NULL,
  kind text NOT NULL CHECK (kind IN ('telegram','email','webhook')),
  topic_pattern text NOT NULL,              -- напр. 'alerts/#' или 'msh/Bulgaria/2/e/#'
  config jsonb NOT NULL DEFAULT '{}',       -- telegram: bot_token+chat_id; email: to; webhook: url
  min_interval_s int NOT NULL DEFAULT 30,   -- анти-спам: мин. интервал между изпращания
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notification_log (
  id bigserial PRIMARY KEY,
  channel_id uuid REFERENCES notification_channels(id) ON DELETE CASCADE,
  topic text NOT NULL,
  message text NOT NULL,
  status text NOT NULL CHECK (status IN ('sent','failed','skipped')),
  error text,
  ts timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notification_log_ts ON notification_log (ts DESC);
