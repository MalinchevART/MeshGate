-- Фаза 5 трети срез (docs/12): ниво на важност + тихи часове per канал.
-- severity на канала: 'info' | 'important' | 'critical' — съобщения под
-- нивото на канала се пропускат (decoded.severity, по подразбиране info);
-- quiet_hours: през нощта канали с severity < 'critical' мълчат.
ALTER TABLE notification_channels
  ADD COLUMN IF NOT EXISTS severity text NOT NULL DEFAULT 'info'
  CHECK (severity IN ('info','important','critical'));
-- тихи часове остават в config (jsonb): {"quiet_hours": {"start": "23:00", "end": "07:00"}}
-- — без нова колона, за да не мърда схемата при tuning от UI-то.
