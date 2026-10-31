-- Вълна 1 „Пулс-ленти": частичен покриващ индекс за msh агрегациите
-- (pulse/map/topology). topic LIKE 'msh/%' не ползва topic btree индекса
-- (LIKE без text_pattern_ops); така планърът минава index-only по ts
-- само върху msh редовете, без heap достъп до всеки пакет.
CREATE INDEX IF NOT EXISTS packets_msh_pulse_idx
  ON packets (ts DESC) INCLUDE (topic, packet_type)
  WHERE topic LIKE 'msh/%';

ANALYZE packets;
