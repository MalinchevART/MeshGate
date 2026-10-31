-- Т26: hold-back на обикновените пакети до добър SNR прозорец (F16) —
-- на ниво ПЛАТФОРМА: нормални доставки към мостове/изходи се задържат,
-- докато SNR на източника е под прага (конфиг в settings, Т26).
-- Изпратени сега остават в held_back (JSON) до flush или добър прозорец.
ALTER TABLE devices ADD COLUMN IF NOT EXISTS hold_back boolean NOT NULL DEFAULT false;
