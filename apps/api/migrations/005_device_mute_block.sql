-- Управление на възли (по желание на собственика, октомври 2026):
-- заглушаване на шумни/тестови възли и блокиране за защита.
ALTER TABLE devices ADD COLUMN IF NOT EXISTS muted boolean NOT NULL DEFAULT false;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS blocked boolean NOT NULL DEFAULT false;
