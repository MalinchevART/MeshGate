-- Т15 „Двете уши" П3: компактна чутост-запис. Дедупът по (възел, packet_id)
-- реже второто MQTT копие на същия пакет от ДРУГ гейт — а „кой чу" е точно
-- това. Записваме (packet_id, gateway_id) ПРЕДИ дедуп проверката в ingest:
-- всяко ухо = един ред, повторните копия на същото ухо броят copies.
-- Историческите данни не се бекфилват (гейтът не се пази в events) —
-- чутостта се натрупва от деплоя нататък (моделът на Т16/ACK).

CREATE TABLE IF NOT EXISTS packet_heard (
    packet_id  BIGINT       NOT NULL,
    gateway_id TEXT         NOT NULL,
    first_ts   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_ts    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    copies     INT          NOT NULL DEFAULT 1,
    PRIMARY KEY (packet_id, gateway_id)
);

CREATE INDEX IF NOT EXISTS packet_heard_first_ts_idx ON packet_heard (first_ts);
