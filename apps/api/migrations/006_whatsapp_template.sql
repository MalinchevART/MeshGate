-- Фаза 5 (втори срез, docs/12): WhatsApp канал (CallMeBot) + шаблон на
-- съобщението per канал ({topic}/{node}/{text}/{battery}/… променливи)
ALTER TABLE notification_channels
  DROP CONSTRAINT IF EXISTS notification_channels_kind_check;
ALTER TABLE notification_channels
  ADD CONSTRAINT notification_channels_kind_check
  CHECK (kind IN ('telegram','email','webhook','whatsapp'));

ALTER TABLE notification_channels
  ADD COLUMN IF NOT EXISTS template text;  -- NULL → стандартният формат на двигателя
