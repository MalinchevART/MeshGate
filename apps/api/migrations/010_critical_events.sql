-- Т7 „Критични събития: бекенд" (docs/16 Етап 3): материалализирано
-- „критично СЕГА" — фонов evaluator преизчислява три детектора (батерия
-- под праг / мъртви букви по правило / мълчание по last-heard) и прави
-- upsert тук; състоянието е машина open → acked | silenced → resolved.
CREATE TABLE IF NOT EXISTS critical_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  -- стабилен ключ между циклите: battery:!hex | deadletter:<правило> | silence:!hex
  event_key text NOT NULL UNIQUE,
  kind text NOT NULL CHECK (kind IN ('battery', 'deadletter', 'silence')),
  severity text NOT NULL DEFAULT 'critical'
    CHECK (severity IN ('important', 'critical')),
  -- детайли + deep links (възел/пакет/правило) — за UI реда и drill-down
  payload jsonb NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'open'
    CHECK (status IN ('open', 'acked', 'silenced', 'resolved')),
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  -- брой епизоди (reopen след resolved увеличава)
  occurrences int NOT NULL DEFAULT 1,
  acked_by text,
  acked_at timestamptz,
  silenced_until timestamptz,
  resolved_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- шел-броячът и списъкът четат само active (open + изтекъл silence)
CREATE INDEX IF NOT EXISTS critical_events_active_idx
  ON critical_events (status, last_seen_at DESC)
  WHERE status <> 'resolved';
CREATE INDEX IF NOT EXISTS critical_events_kind_idx
  ON critical_events (kind, status);
