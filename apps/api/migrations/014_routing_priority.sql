-- Т24 „Приоритетно рутиране" (docs/16 Етап 6, F1/F16): изходящата опашка
-- класира пакета по приоритета на ИЗТОЧНИКА (възела). auto = изведено от
-- съдържанието (severity=critical → urgent+).
ALTER TABLE devices ADD COLUMN IF NOT EXISTS routing_priority text
  NOT NULL DEFAULT 'normal' CHECK (routing_priority IN ('normal','urgent','critical','auto'));
CREATE INDEX IF NOT EXISTS devices_priority_idx ON devices (routing_priority)
  WHERE routing_priority <> 'normal';
