-- Пулс 7д перформанс (продължение на 008): заявка 2 от /v1/devices/pulse —
-- среден SNR на кофа от events.payload->decoded->snr. Планът преди:
-- Parallel Seq Scan върху ~91% от events (~26K buffers с TOAST detoast на
-- всеки ред) + 100–270ms JIT compile. Частичният индекс покрива само
-- редовете със snr (~4%) и носи стойността ѝ → avg() не я преизчислява;
-- INCLUDE (device_id) служи на JOIN-а с devices. БЕЗ expression statistics
-- планърът оценява "snr IS NOT NULL" на ~90% от редовете (jsonb няма stats
-- по подразбиране) и си остава на Seq Scan — statistics-ата е задължителна
-- част от миграцията, не оптимизация. Предикатът е текстово идентичен с
-- WHERE клаузата в devices.py, за да го матчне планърът.
CREATE INDEX IF NOT EXISTS events_snr_pulse_idx
  ON events (ts DESC, ((payload->'decoded'->>'snr')::numeric))
  INCLUDE (device_id)
  WHERE payload->'decoded'->>'snr' IS NOT NULL;

CREATE STATISTICS IF NOT EXISTS events_snr_expr_stats
  ON ((payload->'decoded'->>'snr')) FROM events;

ANALYZE events;
