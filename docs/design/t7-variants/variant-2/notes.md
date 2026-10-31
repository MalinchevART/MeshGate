# Т7 „Критични събития: бекенд" — Вариант 2: „Фонов evaluator + материалализация"

Дата: 2026-10-28. Точка: Т7 (docs/16) · F2 (docs/design/review-2026-10-24.md,
Доклад 2). Стратегия на В2: критичното събитие е РЕД в таблица, не изчисление
на заявка. Периодичен работник (модел: `NotificationEngine` — async task в
lifespan) преизчислява детекторите на всеки ~30 s и прави upsert в
`critical_events` (миграция 010); `GET /v1/critical-events` чете САМО
таблицата (евтин индекс + пагинация); ack/silence са чисти UPDATE-и;
условие, изчезнало от данните, се само-разрешва (`resolved` + ts).
Праговете са settings ключ — четат се на ВСЕКИ цикъл, смяна без рестарт.

Прочетени шаблони (проверено в кода 2026-10-28): `app/notify/engine.py`
(worker + `_digest_tick(now)` — тестируем цикъл с инжектирано време),
`app/main.py` (lifespan + retention_loop — `settings` ключът `retention`
се чете в цикъла, не при старта), `app/routes/meta.py` (`/v1/anomalies`),
`app/routes/routing.py` (executions/deadletter-resend), `app/routes/`
`devices.py` (клампване limit + jsonb декод на батерии),
`app/security.py` (`require_viewer/operator/admin`, `audit()`),
`app/db.py` (миграциите вървят последователно; следващата е **010**),
`apps/web/src/hooks/useAnomalyCount.ts` (превключвателят
`'critical-events'` чака в `ADAPTERS`), `apps/web/src/pages/System.tsx`
(мястото за полетата на праговете — Т32 ги стилизра).

---

## 1. Защо В2 — ИСТОРИЯТА, която изчислението на заявка няма

В1 (детектори на заявка, без таблица) отговаря само на „какво е критично
СЕГА". В2 пази **епизода** на събитието и затова отговаря и на:

| Въпрос | В1 (на заявка) | В2 (таблица) |
| --- | --- | --- |
| Кога възникна? | — (вижда се само текущият щам) | `first_seen` |
| Кога затвори? | — | `resolved_at` / `acked_at` |
| Кой потвърди и кога? | невъзможно (няма състояние) | `acked_by` / `acked_at` |
| До кога е заглушено? | невъзможно | `silenced_until` |
| Колко дълго трая? | — | `resolved_at − first_seen` |
| Точен брой активни? | капациран/скъп при обем | `count(*)` по парциален индекс |

Освен историята — **разместването на цената**: скъпите сканирания
(jsonb-ти по `events`, regexp по `packets.topic`, дедуп батерии по възел)
в В1 тичат на ВСЯКА заявка на ВСЕКИ потребител (шел-брояч полинго на 10 s!);
в В2 те тичат веднъж на 30 s в фоновия работник, а read пътят е
`Index Scan` върху редове, които са единици/десетки. Пагинацията е истинска
(`LIMIT/OFFSET` по индекс), не „първите 200".

**Цената на В2** (честно): +1 фонов работник (рестарт семантика, пропуснат
цикъл), +1 миграция/таблица, машина на състоянията с преходи, които
искачат тестове (open→acked, silenced→open при изтичане, reopen, resolve),
и риск от churn на двойки събития при смяна на праг (§7). За F2 това е
печеливша размяна: панелът на Т9 изисква ack/silence от реда и връзка към
епизода, а не само списък „в момента".

## 2. Схема — миграция `010_critical_events.sql`

```sql
-- Т7/F2 (docs/16): критични събития като материалализирано състояние.
-- Един ред = ЕДИНИЦА ЕПИЗОД на детектирано условие (event_key). Работникът
-- прави upsert; ack/silence са UPDATE-и; изчезналото условие → resolved.
CREATE TABLE IF NOT EXISTS critical_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_key text UNIQUE NOT NULL,          -- 'low_battery:!a4f12c98' | 'deadletter:<rule_id>' | 'silence:!a4f12c98'
  kind text NOT NULL CHECK (kind IN ('low_battery','deadletter','silence')),  -- Т18 добавя 'silence_learned'
  severity text NOT NULL DEFAULT 'important'
    CHECK (severity IN ('important','critical')),  -- СЪЩИТЕ нива като SEVERITY_RANK в notify (info/important/critical)
  payload jsonb NOT NULL DEFAULT '{}',    -- стойности + deep links (§5)
  status text NOT NULL DEFAULT 'open'
    CHECK (status IN ('open','acked','silenced','resolved')),
  first_seen timestamptz NOT NULL DEFAULT now(),
  last_seen timestamptz NOT NULL DEFAULT now(),   -- последен цикъл, в който условието Е било вярно
  acked_by uuid REFERENCES users(id) ON DELETE SET NULL,
  acked_at timestamptz,
  silenced_until timestamptz,
  resolved_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  occurrences int NOT NULL DEFAULT 1      -- брой епизоди по този ключ (reopen ги трупа)
);

-- read пътят на шел-брояча и панела: само НЕ-resolved, по тежест и свежест
CREATE INDEX IF NOT EXISTS critical_events_active_idx
  ON critical_events (last_seen DESC)
  INCLUDE (kind, severity)                -- броя по kind без table access
  WHERE status <> 'resolved';
-- историята (?include=resolved, разследване „кога се затвори")
CREATE INDEX IF NOT EXISTS critical_events_resolved_idx
  ON critical_events (resolved_at DESC)
  WHERE status = 'resolved';
```

Защо `event_key` уникален, а не „нов ред на всяко възникване": броячът и
панелът искат текущия епизод без дедуп; историята на отминали епизоди е
втори срез (audit_log вече пази ack/silence/resolve с	ts). `occurrences`
запазва броя повторения през resolved-границата — евтино, без втора таблица.

Severity: използваме `important|critical` — съвпада с
`SEVERITY_RANK` в notify engine-а, та Т18 (канаря) и бъдещо известие за
критично събитие да мачват канали без преводач. („Предупреждение" в
концепта = `important`.)

## 3. Машина на състоянията

```
                условие детектирано (първи път)
   ┌─────────────────────────────►  open  ───────────────────────────┐
   │                                    │  │                          │ POST /ack (operator)
   │ reopen (resolved + условие         │  │ условие изчезнало        │ (идемпотентен на open)
   │ пак активно; occurrences+=1)   POST│  │ (батерия се вдигнала,    ▼
   │                                    │  │  мълчанието прекратено,  acked ──────────────────┐
   │                                    │  │  мъртви букви < праг)   │  │                    │ условие
   │   ┌────────────────────────────────┘  ▼                         │  │ POST /silence      │ изчезнало
   │   │            (worker: self-resolve → resolved + resolved_at)  │  ▼                    │
   │   │                                                               silenced ────► resolved
   │   │ silenced_until изтече:  условие още активно → open;  иначе → resolved                  ▲
   └───┘                                                                                          │
        resolved + условие пак активно → open (reopen) ─────────────────────────────────────────┘
```

Правила (изпълнява САМО работникът, освен POST ack/silence):

- **upsert не пипа status**: `ON CONFLICT (event_key) DO UPDATE SET
  last_seen=now(), payload=…, severity=…, updated_at=now()` — никога
  не презаписва `acked_by/silenced_until/resolved_at`. Така UPDATE-ът на
  потребителя (ack) и цикълът на работника не се състезават: ack между
  SELECT и UPDATE на работника е безвреден.
- **self-resolve**: активен ред (`open|acked|silenced`), чийто ключ НЕ
  е сред детектираните → `status='resolved', resolved_at=now()`
  (запазат се acked_at/silenced_until за историята).
- **изтекъл silence**: `silenced AND now() > silenced_until` → ако
  условието пак е активно → `open` (и `silenced_until=NULL`); ако го
  няма → `resolved`.
- **reopen**: `resolved` + ключът пак е детектиран → `open`,
  `first_seen=now(), resolved_at=NULL, occurrences+=1`.
- **resolved не се сканира от детекторите** — работникът го хваща само
  при reopen проверка (евтино: `WHERE event_key = ANY($detected)`).

## 4. Работник — `apps/api/app/critical/engine.py` (нов пакет `critical/`)

Модел: `NotificationEngine` (start/stop + тask в lifespan) + тестируемостта
на `_digest_tick` — целият цикъл е `run_once(now)`, вызван и от тестовете
без чакане на интервала.

```python
class CriticalEventsEngine:
    # settings ключ 'critical_events' (jsonb) се чете ВСЕКИ цикъл →
    # смяна на праг от System UI действа без рестарт (модел: retention_loop)
    DEFAULTS = {
        "battery_important_pct": 20,   # под → важно събитие
        "battery_critical_pct": 10,    # под → критично
        "battery_hysteresis_pct": 2,   # resolve чак при ≥ праг+hyst (§7)
        "battery_window_hours": 24,    # броня се последната стойност в прозореца
        "deadletter_count": 3,         # мъртви букви по правило в прозореца ≥ → събитие
        "deadletter_hours": 24,
        "silence_hours": 24,           # last-heard по-стар от → мълчание
        "silence_seen_days": 7,        # само възли, чувани някога в последните N дни
        "interval_s": 30,              # период на цикъла
        "cleanup_resolved_days": 30,   # resolved по-стари се трият (audit пази следата)
    }

    def __init__(self, pool): ...
    def start(self):   # asyncio.create_task(self._loop(), name="critical-events")
    async def stop(self): ...                      # като notify.stop()

    async def run_once(self, now: datetime | None = None) -> dict:
        cfg = await self._load_cfg()               # settings + DEFAULTS (1 ред)
        detected: dict[str, Detected] = {}         # event_key → (kind, severity, payload)
        detected |= await self._detect_battery(cfg)
        detected |= await self._detect_deadletter(cfg)
        detected |= await self._detect_silence(cfg)
        return await self._apply(detected, now or datetime.now(timezone.utc))

    async def _loop(self):                          # като _digest_loop: грешка в ЕДИН
        while not self._stop.is_set():              # цикъл не убива работника
            try: await self.run_once()
            except asyncio.CancelledError: raise
            except Exception: log.exception("критични събития: грешка в цикъла")
            try: await asyncio.wait_for(self._stop.wait(), timeout=self._interval_s)
            except asyncio.TimeoutError: pass
```

### 4.1 Детектори (чисти SQL-снимки; източници = съществуващи данни)

**а) `low_battery`** — последна батерия на възел под праг (източник:
`events.payload->decoded->battery` — същият израз като `build_digest`
и пулса; regex-пазач срещу некастими стрингове):

```sql
SELECT (e.payload->'decoded'->>'node') AS node,
       max((e.payload->'decoded'->>'battery')::numeric) AS bat
FROM events e
JOIN devices d ON d.id = e.device_id AND NOT d.muted AND NOT d.blocked
WHERE e.ts > now() - make_interval(hours => $window)
  AND (e.payload->'decoded'->>'battery') ~ '^[0-9]+(\.[0-9]+)?$'
GROUP BY 1
HAVING max((e.payload->'decoded'->>'battery')::numeric) < $important_pct
```

- `event_key = 'low_battery:<node>'`; severity: `bat < critical_pct →
  critical`, иначе `important`; payload: `{node, battery, threshold_pct,
  links}` (§5). Възел без нова телеметрия в `battery_window_hours` не се
  брои (стара ниска стойност ≠ текущ проблем) — точно обратното на В1
  „всичко под праг в 24ч", и затова silent-детекторът е отделен.
- **resolve с хистерезис**: събитието се затваря чак когато последната
  батерия ≥ `important_pct + hysteresis_pct` (default 20+2) — щамаща
   около 20–21% батерия не генерира open/resolve чифт на всеки цикъл.

**б) `deadletter`** — брой мъртви букви по правило над праг:

```sql
SELECT split_part(topic, '/', 2) AS rule, count(*) AS n, max(ts) AS last_ts
FROM packets
WHERE topic LIKE 'deadletter/%'
  AND ts > now() - make_interval(hours => $dl_hours)
GROUP BY 1 HAVING count(*) >= $dl_count
```

- `event_key = 'deadletter:<rule>'`; severity `critical` (рутирането
  губи пакети); payload: `{rule, count, window_hours, last_ts,
  sample_packet_id, links}` (sample = последният deadletter packet id —
  директен drill до детайла му в Explorer и до deadletter-resend).
- Self-resolve: след изтичане на прозореца броят пада под прага →
  `resolved`. Resend на мъртвите букви НЕ намалява броя (те си остават в
  `deadletter/%`) — resolve идва от прозореца; честно и просто.

**в) `silence`** — мълчание по last-heard (новото от Т7):

```sql
SELECT d.external_id AS node, d.last_seen_at
FROM devices d
WHERE d.protocol = 'meshtastic' AND d.external_id LIKE '!%'
  AND NOT d.muted AND NOT d.blocked
  AND d.last_seen_at <  now() - make_interval(hours => $silence_hours)
  AND d.last_seen_at >  now() - make_interval(days  => $seen_days)
```

- `event_key = 'silence:<node>'`; severity `important`; payload:
  `{node, last_seen_at, silence_hours, links}`. Горната граница
  (`seen_days`) е честността: възел, минал веднъж покрай брокера преди
  месец, не е „замлкал възел" — не алармираме вечно.
- Self-resolve: `last_seen_at` се освежава от ingest при всеки пакет →
  условието изчезва → `resolved` („мълчанието прекратено").
- Т18 (канаря) по-късно добавя вид `silence_learned` (p95 каденс) —
  `kind` CHECK-ът се разширява с една миграция, таблицата и API не се
  менят.

### 4.2 `_apply(detected, now)` — единици преходи, по транзакция

1. `SELECT id, event_key, status, silenced_until FROM critical_events`
   (активните + тези с ключ от `detected` — за reopen).
2. Upsert на детектираните (не пипа status; §3).
3. Активни без ключ → self-resolve (+ `resolved_at`).
4. `silenced` с изтекъл `silenced_until` → open (условие активно) или
   resolved.
5. `resolved` с ключ в `detected` → reopen.
6. `DELETE FROM critical_events WHERE status='resolved' AND resolved_at <
   now() - cleanup_resolved_days` (същият цикъл, веднъж на час стига —
   евтино условие по `critical_events_resolved_idx`).

Всичко в ЕДНА транзакция на цикъл: или цикълът е приложен, или не е —
рестарт по средата не оставя полу-състояние.

### 4.3 Включване в `main.py` (lifespan)

```python
critical = CriticalEventsEngine(pool)   # след notify; без load() — cfg е в run_once
critical.start()
app.state.critical = critical
...
finally: await critical.stop()
```

Рестарт семантика: състоянието е ЦЯЛОТО в таблицата (работникът е без
памет — няма in-memory `_seen` като notify). Първият цикъл след рестарт
изчислява наново и сверява: закъснело откриване ≤ 1 интервал; никакви
дублирати (`event_key` UNIQUE).

## 5. API контракт — `apps/api/app/routes/critical.py` (нов router)

### `GET /v1/critical-events` — само таблицата

Параметри: `status=open|acked|silenced|active|resolved|all` (default
`active` = open+acked+silenced), `kind=`, `limit=` (default 50, max 200),
`offset=` (пагинация). Подредба: `critical` преди `important`, после
`last_seen DESC`.

```json
{ "data": {
    "counts": { "open": 3, "acked": 1, "silenced": 0, "resolved": 12,
                "by_kind_open": { "low_battery": 2, "silence": 1 } },
    "total_active": 4,
    "items": [ {
        "id": "…uuid…", "event_key": "low_battery:!a4f12c98",
        "kind": "low_battery", "severity": "important", "status": "open",
        "first_seen": "…", "last_seen": "…",
        "acked_by": null, "acked_at": null,
        "silenced_until": null, "resolved_at": null,
        "occurrences": 1,
        "payload": {
          "node": "!a4f12c98", "battery": 17, "threshold_pct": 20,
          "links": {
            "device":  { "page": "devices", "params": { "node": "!a4f12c98" } },
            "packets": { "page": "packets", "params": { "node": "!a4f12c98" } }
          }
        }
      } ]
  } }
```

- `counts` идва от ЕДНО `count(*) … GROUP BY status` по парциалния индекс —
  шел-броячът (`limit=1`) не тегли items. `counts.open` Е числото в
  брояча (§6).
- Deep links: `payload.links[].page + params` → UI строи `?p=…&…`
  (навигацията е `?p=`, без router — docs/16 Т6):
  - `low_battery` → Devices (филтър по възел; от Т11 — детайлният панел)
    + Packet Explorer (пакети на възела);
  - `deadletter` → Explorer с филтър тема `deadletter/<rule>` + Routing
    журнал на правилото (`links.packets`, `links.rule`);
  - `silence` → Devices/детайл на възела.
    Линкът е данн, не стринг URL — страниците си имат собствени
    query-параметри и те могат да еволюират без миграция на таблицата.

### Мутации (RBAC: operator; audit при всяка)

- `POST /v1/critical-events/{id}/ack` — `UPDATE … SET status='acked',
  acked_by=$user, acked_at=now() WHERE id=$1 AND status IN ('open',
  'silenced')` (допуска се ack на заглушено — човекът го е видял).
  Вече `acked` → идемпотентен 200; `resolved` → 409
  `"събитието вече е затворено"`. Audit: `critical_events.ack`,
  entity `critical_event`, entity_id = id, details `{event_key, kind}`.
- `POST /v1/critical-events/{id}/silence` с body
  `{"hours": 4}` (1–168) — `status='silenced',
  silenced_until=now()+make_interval(hours=>$h)`; изисква `open|acked`
  (заглушено с ново hours → просто удължава). Audit:
  `critical_events.silence`, details включва `until`.
- `POST /v1/critical-events/{id}/unsilence` — ръчно връщане в `open`
  (обратното на изтекналия silence, без чакане); същите права. Евтин и
  предпазва от „заглуших за 168h, а всъщност се появи слачай".
  Ако детайлният преглед го сметка за обем — може да падне; ядрото е
  ack/silence.

### Настройки (System полета; без миграция — settings ключ)

- `GET /v1/critical-events/settings` (viewer) →
  `{battery_important_pct: 20, battery_critical_pct: 10,
  battery_hysteresis_pct: 2, deadletter_count: 3, deadletter_hours: 24,
  silence_hours: 24, silence_seen_days: 7, interval_s: 30,
  cleanup_resolved_days: 30}` — винаги върху DEFAULTS (липсващ ключ =
  default; модел: retention).
- `PUT` (admin) — валидация: проценти 0–100 и `critical <
  important`, hours/days > 0, `interval_s` 5–600. Запис:
  `INSERT INTO settings (key, value) VALUES ('critical_events', $1::jsonb)
  ON CONFLICT (key) DO UPDATE SET value=$1::jsonb, updated_at=now()`
  (модел: ha.py ред 29). Audit: `critical_events.settings` с diff.
- UI: полета в System (Т32 ги облича в нови Card/Panel); Работникът чете
  ключа всеки цикъл → промяната действа до 30 s, БЕЗ рестарт.

### RBAC матрица

| Операция | viewer | operator | admin |
| --- | --- | --- | --- |
| GET /v1/critical-events(+settings) | ✓ | ✓ | ✓ |
| POST ack / silence / unsilence | ✗ 403 | ✓ | ✓ |
| PUT settings | ✗ 403 | ✗ 403 | ✓ |

(Същите Depends + audit() шаблони като devices/routing; тест 403 в §6.)

## 6. Интеграция със Shell / `useAnomalyCount`

Хукът (Т6 В2) вече има слота: `ADAPTERS['critical-events']` днес хвърля
„включва се след Т7". В2 го запълва с ЕДИН fetcher; Shell сменя само
`alarmSource="critical-events"`. Drop-in на shape-а:

```ts
async function fetchCriticalEvents(hours: number): Promise<AnomalySummary> {
  // counts по индекс; items не се теглят (limit=1)
  const raw = await api<{ counts?: …; items?: { last_seen: string }[] }>(
    '/v1/critical-events?limit=1')
  const c = raw?.counts
  const open = c?.open ?? 0
  return {
    hours,                        // семантично: live снимка; прозорецът е в сървърния cfg
    alarm: open,                  // БРОЯЧЪТ = open събития (спек Т7/Т6)
    deadletter: c?.by_kind_open?.deadletter ?? 0,
    notifyFailed: 0, notifySent: 0, rulePublish: 0,   // не са част от този източник
    byKind: { deadletter: c?.by_kind_open?.deadletter ?? 0,
              notify_failed: 0, notify_sent: 0, rule_publish: 0 },
    total: open,
    lastAlarmTs: raw?.items?.[0]?.last_seen ?? null,  // подредени по свежест
    lastTs: raw?.items?.[0]?.last_seen ?? null,
    updatedAt: Date.now(),
  }
}
```

- `alarm = counts.open` — acked/silenced НЕ вдигат брояча (човек ги е
  видял), resolved също не. Точно число (без „поне толкова" капацита на
  /anomalies — риск №4 от notes на Т6 се затваря).
- `low_battery`/`silence` не са в `ANOMALY_KINDS` — хукът е дефанзивен
  по замисъл; при внедряване Т7 разширява `byKind` с
  `Record<string, number>`-подобно поле или добавя двата kind-а към
  `ANOMALY_KINDS` (избор на детайлния преглед; и двата пътя са чисти).
- Т9 панелът „Критични събития" ползва СЪЩИЯ endpoint с
  `status=active&limit=50` + `refresh()` на хука след ack/silence от
  реда (хукът вече го предлага).

## 7. Рискове и решения

1. **Работник при рестарт**: състоянието е в таблицата, работникът е
   без памет → първият цикъл сверява (upsert/resolve/reopen). Най-лошото
   закъснение = 1 интервал + времето на заявките. Няма дублиране
   (UNIQUE). Опашка като notify (`QUEUE_MAX`) НЕ е нужна — цикълът е
   snapshot, не стрийм.
2. **Пропуснат цикъл при натоварен ingest**: детекторите са snapshot
   заявки върху вече записани данни — пропуснат цикъл не губи събития,
   само забавя откриването/resolve-а с ≤ 30 s (и с `interval_s` от
   settings е тунуем). За разлика от опашков engine, тук „наваксването"
   е автоматично: следващият цикъл вижда всичко. Един цикъл с тежък
   ingest блокира само себе си (`asyncio` на ЕДИН цикъл не спира API-то —
   заявките вървят през пула). Ако `run_once` стане тежък при голям
   обем: парциалният индекс от 009/008 е модел — детекторните заявки
   могат да получат свои (напр. `events` по `decoded->battery`), но
   ПРЕДИ това се мери (пулсът вече работи с този jsonb израз на живо).
3. **Двойки събития при смяна на праг**: праг 20→15 → всички възли в
   15–19% ЗАРЯД mass-resolve; 15→20 → mass-open (burst в брояча, не в
   известията — В2 все още не известява директно; Т18 решава).
   Митигации: (а) батерийният хистерезис (`battery_hysteresis_pct`)
   пази resolve-а стабилен при флип на стойността около прага;
   (б) смяната на праг минава през `PUT settings` → audit с diff
   (видимо КОЙ е вдигал прага и кога се е появила вълната); (в)
   `occurrences` + `first_seen` правят reopen-а честен (нов епизод, нов
   timestamp), не „същото събитие гледа различно".
4. **Надпревара UPDATE (ack) vs цикъл (upsert)**: upsert-ът не пипа
   status полетата → ack по средата на цикъла е безопасен; FIND-ът на
   `_apply` е в същата транзакция с writes-а.
5. **Растеж на таблицата**: редовете са по брой активни условия (десетки)
   + resolved история → `cleanup_resolved_days` (default 30) в самия
   цикъл; audit_log пази човешките действия завинаги.
6. **silence false-positive** (възел с рядък каденс): `silence_hours`
   е настройка; Т18 канарята (p95 inter-arrival) е правилният дългосрочен
   отговор — `kind` колоната е готова за него.
7. **Timeline-съответствие с /v1/anomalies**: anomalies си остава лента
   на СЛУЧИЛИТЕ се събития (мъртви букви като маркери), critical-events
   е състоянието „критично СЕГА + епизод". Двата източника живеят
   паралелно; Shell превключва с проп, Monitor запазва аномалиите.

## 8. Тестове

### Unit (без event loop — чисти функции + fake clock; модел `_digest_tick`)

- **Детектори** (fixtures като редове → извикват SQL-тата срещу тестова
  база или чистата част се тества с подадени редове):
  батерия 19/праг 20 → детектиран; 20 → не; 9 → `critical`;
  възел само с телеметрия преди 25 h (извън window) → не се брои;
  muted/blocked възел → никога.
- **silence граници**: `last_seen` 23 h → не; 25 h → да; 8 дни (извън
  `seen_days`) → не.
- **deadletter**: 2 при праг 3 → не; 3 → да; извън прозореца → не.
- **Преходи `apply(detected, now)` с fake clock** (`now` параметър):
  нов ключ → open; активен без ключ → resolved (+resolved_at);
  resolved + ключ → reopen (occurrences 2, нов first_seen); silenced,
  `now > silenced_until`, ключ присъства → open; ключ липсва → resolved;
  acked + ключ → само last_seen refresh (status оста); upsert не
  променя acked_by (състезание §7.4).
- **cfg от settings**: ред в settings ключ `critical_events` бие
  DEFAULTS; боклучива стойност (стринг) → fallback + warning.

### Integration (httpx + жив стек; helpers `login/publish_mqtt` от
test_checklist, `ensure_itest_admin` от conftest; работникът се кара с
`await app.state.critical.run_once()` — без sleep на 30 s)

1. **open**: публикувай телеметрия батерия 15% (демо възел) → `run_once`
   → `GET /v1/critical-events` → 1 open `low_battery`, payload носи
   node/threshold/links.
2. **ack**: `POST …/{id}/ack` като operator → status `acked`;
   `counts.open` падна с 1; ред в `audit_log` с `critical_events.ack`.
3. **silence**: `POST …/{id}/silence {"hours": 2}` → `silenced` +
   `silenced_until ≈ now+2h`; повторен silence с 4 h удължава.
4. **resolved**: публикувай батерия 80% → `run_once` → статус
   `resolved` + `resolved_at` зададен; `GET ?status=resolved` показва
   епизода с first/last seen.
5. **silence self-resolve**: възел мълчи (backdate `last_seen_at` в
   теста) → `run_once` → open `silence`; пак публикувай от него →
   `run_once` → resolved.
6. **Права**: viewer ack → 403; viewer GET → 200; operator PUT settings
   → 403; admin PUT → 200.
7. **Праг без рестарт**: `PUT settings {"battery_important_pct": 50}` →
   `run_once` → нов open за възел с батерия 40% (дотогава под радар);
   връщане на 20 + `run_once` → resolved (и `occurrences` на стария не
   скача — нов ключ/стар ключ reconcile).
8. **Мъртви букви**: правило към недостигаема дестинация → 3 провалени
   пакета → `run_once` → open `deadletter` с rule/`sample_packet_id`;
   resend endpoint-ът продължава да работи.
9. **Чистота**: тестовете трият собствените си критични събития и
   deadletter пакети (модел: „тестовете трият собствените си мъртви
   букви", docs/16 правило №5).

### Жива проверка (QA, демо флаг)

Демо възел с батерия <20% (демо възлите вече са ниски — m-alarm в
selftest) → ≤30 s ред в панел/брояч; ack от реда (Т9) сваля брояча;
System поле за прага променя поведението без рестарт.

## 9. Присъда

В2 прави критичното събитие ПЪРВОКЛАСЕН обект: история (epизод с
first/last seen, кой/кога ack, кога resolve), точен евтин брояч за Shell-а
(една GROUP BY по парциален индекс на 10 s полинг), пагиниран панел за Т9
и отворена врата за Т18 (нов kind) и бъдещи известия за критични
събития (severity вече е в езика на каналите). Цената е реална, но
платима и платена веднъж: един фонов работник по утвърдения notify
шаблон, една миграция (010) и машина на състоянията с изчерпателни
тестове на преходите (fake clock, без sleeps). Спрямо В1 (сметка на
заявка) В2 печели точно там, където продуктът отива — NOC изглед с
ack/silence и разследване „кога се случи и кога свърши" — а скъпите
сканирания се плащат веднъж на цикъл, не на всеки потребител на всеки
10 s. Препоръка: В2 за реализация; ако детайлният преглед търси съкращение,
ядрото (таблица + worker + GET/ack/silence) е неразделимо, скъсяваемо е
unsilence и cleanup-ът (ръчно по-късно).
