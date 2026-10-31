-- Т36/Т37 поддръжка: FK-triggerът events.packet_id (ON DELETE SET NULL)
-- без индекс прави всяко триене на пакети seq-scan (499K демо реда = часове).
-- С индекса: секунди. Създаден ръчно на живо (CONCURRENTLY); тук е за
-- свежите инсталации. IF NOT EXISTS — идемпотентно.
CREATE INDEX IF NOT EXISTS events_packet_id_idx ON events (packet_id);
