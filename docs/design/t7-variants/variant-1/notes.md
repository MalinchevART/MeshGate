# Т7 „Критични събития: бекенд" — Вариант 1 „Изчислено на заявка + ACK/SILENCE таблица" — notes

Дата: 2026-10-28. Обхват: ДИЗАЙН + СКИЦА. Никакъв код не е променян.
Изходни точки: docs/16-design-and-functionality-plan.md Т7 (Етап 3) + F2 в
docs/design/review-2026-10-24.md (Доклад 2). Вариантът е подетап 1/В1 от
phase-execution цикъла на Т7.

## 0. Изходна позиция — какво вече съществува (проверено в кода)

| Градивен блок | Къде | Какво носи |
|---|---|---|
| `/v1/anomalies` | `apps/api/app/routes/meta.py:254-297` | брои deadletter (от `packets` тема `deadletter/%`) + `notify_failed` за 24 ч — ВРЕЕВА лента на случилите се събития, без „критично СЕГА", без ack |
| dead-letter запис | `apps/api/app/routing/service.py:151-170` (`_dead_letter`, `DEAD_LETTER_PREFIX` ред 25) | мъртва буква = пакет с тема `deadletter/<име-на-правило>` (retain, qos 1); името на правилото е 2-ят токен — точно какво извлича и `/anomalies` (`split_part(topic,'/',2)`) |
| устройства | `apps/api/app/ingest/service.py:213-222` | `devices.last_seen_at` се опреснява с всеки пакет (`ON CONFLICT DO UPDATE`); `muted`/`blocked` от миграция 005; `status` никога не става `offline` ( няма фонова работа ) — НЕ може да се ползва за мълчание |
| батерия | няма колона в `devices`; `device_observations` е празна ( 0 употреби в кода ) — реалният източник е `packets`: decode на `meshtastic-telemetry` по образеца на `stats/overview` ( meta.py:333-364 ) и `/v1/devices/map` ( devices.py:40-70 ); НЮАНСА: демо възлите на емулатора пишат батерия и в `mesh/emul/…` JSON ( `{node, battery}` ) — детекторът ТРЯБВА да хваща и двата извора, иначе живото QA с демо възел не работи |
| settings услуга | таблица `settings (key, value jsonb)` от 001_init.sql; upsert модел: `INSERT … ON CONFLICT (key) DO UPDATE` — `routes/ha.py:29-32`, `routes/profiles.py:144-152`; четене: `SELECT value FROM settings WHERE key=$1` | Т7 праговете са нов ключ тук — БЕЗ миграция на схемата |
| RBAC | `app/security.py:116-132` — `require_viewer/operator/admin` ( ROLE_ORDER viewer<operator<admin ); прецедент: routing enable/disable = **operator** ( routing.py:473,489 ), конфиг изменения = **admin** | виж §4 |
| audit | `security.py:135-153` `audit(pool, user, action, entity, entity_id, details)`; стил на имената: `device.mute`, `routing.deadletter_resend`, `integration.homeassistant` | виж §4 |
| миграции | `app/db.py:24-58` — САМО напред ( последователни `*.sql` под advisory lock ); следващият номер е **010** ( 001–009 съществуват ) | виж §6 |
| шел-брояч | `apps/web/src/hooks/useAnomalyCount.ts` ( ADAPTERS ред 173-179 ; `critical-events` е багнат да reject-ва „включва се след Т7" ); `components/Shell.tsx` проп `alarmSource` ( ред 429, 439-441 ) | виж §5 — контрактът тук е задължителен за drop-in |
| тестове | unit: `tests/unit/` чисти модули; integration: `tests/integration/` ВЪТРЕ в api контейнера срещу жив стек ( conftest.py `mg-itest` admin ; `test_checklist.py` има `publish_mqtt` + MQTT креденшъл fixtures ) | виж §7 |

## 1. Дизайн — принципът на В1

**Събитията са ИЗВОДИМО състояние, не записи.** При всяка `GET /v1/critical-events`
детекторите пресмятат от живите данни ( батерия < праг; dead-letter брой по
правило ≥ праг; last_heard по-стар от N часа ). В базата живее ЕДИНСТВЕНО
човешкият отговор — `critical_events_state` ( миграция 010 ): кой/кога е
ack-нал и до кога е заглушил дадено събитие. Никакъв фонов процес, никакъв
scheduler, никакво разминаване между „изчислена истина" и „съхранена истина":
рестарт на API-то, publish на нова версия, бекъп/restore — състоянието на
събитията се възстановява от данните без реплей.

### 1.1 Модулна подредба ( скица ; конвенции като routing/ notify/ )

```
apps/api/app/critical/
  __init__.py
  detectors.py    # ЧИСТИ функции — само вход → събития ; нула I/O ; unit тествани
  service.py      # SQL четения ( телеметрии, dead-letter, devices, state ) + settings merge
apps/api/app/routes/critical.py     # тънък router: GET/ack/silence/thresholds
apps/api/migrations/010_critical_events_state.sql
apps/api/tests/unit/test_critical_detectors.py
apps/api/tests/integration/test_critical_events.py
apps/api/app/main.py                # +1 ред: include_router(critical.router)
```

### 1.2 event_key — формат ( СТАБИЛЕН между заявките )

Ключът се извежда детерминирано от самите данни, не от ids на редове:

| вид | формат | пример | източник на идентичност |
|---|---|---|---|
| батерия | `battery:!hex` | `battery:!1a2b3c04` | `devices.external_id` / декодирания `node_id`, нормализован **lowercase** ( пулсът вече lower-ва — devices.py:133 ) |
| мъртви букви | `deadletter:<име-на-правило>` | `deadletter:tele-export` | 2-ят токен на темата `deadletter/<име>` — единственото, което данните носят ; работи и когато правилото е изтрито ( мъртвите букви остават до retention — точно тогава искаш да ги броиш ) |
| мълчание | `silence:!hex` | `silence:!1a2b3c04` | като батерията |

Стабилност: една и съща „инцидентна история" ( възел с ниска батерия /
правило със шторм от мъртви букви / замлъкнал възел ) дава един и същ ключ
при всяка заявка. Клиентът URL-encode-ва ключа в path ( `!` е безопасен
sub-delim, но имената на правила допускат интервал/кирилица —
RuleDefinition е само min 2 / max 64 без charset правило, model.py:75 ).

### 1.3 Детектори — чисти функции ( detectors.py )

Общият тип: `CriticalEvent = {key, kind, severity, label, since, last_ts, value, count, node, rule}`.

**`detect_battery(readings, threshold)`** — вход: `(node, battery, ts)` тройки
( последните телеметрии в прозореца; service ги вади по образеца на
stats/overview: `envelope_info` → `decode_envelope_protobuf` → fallback
`json.battery` за `mesh/emul/` демо формата ). Пали се при последното четене
на възела `battery is not None and battery < threshold` ( праг по подразбиране
**20**, от settings ). `since` = последното четене ≥ прага ( точка на
възстановяване, ако е имало ) или началото на прозореца — носи семантиката
на „епизода" за ack ( §1.4 ). `value` = текущата батерия.

**`detect_deadletter(groups, threshold)`** — вход: `(rule, count, first_ts,
last_ts)` от една групираща заявка по `topic LIKE 'deadletter/%'` ( prefix
LIKE ползва `packets_topic_idx` ). Пали се при `count >= threshold` (
праг **3** за прозореца `hours`, по план Т7/F2 ). `since` = `first_ts` —
най-старата мъртва буква в прозореца; когато старите букви излязат от
прозореца, `since` се измества напред ( §1.4 последствие ).

**`detect_silence(devices, now, silence_hours, history_hours)`** — вход:
редове от `devices` (`protocol='meshtastic'`, `NOT muted`, `NOT blocked`,
`last_seen_at`). Пали се при `last_seen_at < now - silence_hours` ( **12 ч**
) И `last_seen_at > now - history_hours` ( **168 ч = 7 дни** ) — „активен
възел с история": изчезнали завинаги тестови възли не дрънчат вечно;
заглушените/блокираните мълчат по желание ( mute вече означава „не ме
интересува" ). `since` = `last_seen_at + silence_hours` ( моментът, в който
мълчанието СТАНА критично ). Само `protocol='meshtastic'` — `mqtt`
устройствата са теми, не възли ( демо мълчанието се покрива от msh/ режима
на емулатора ).

**`apply_state(events, state_rows, now)`** —_Status машината ( чиста ):
`silenced` ако `silenced_until > now`; иначе `acked` ако `acked_at >= since`;
иначе `open`. Вж. §1.4.

**`merge_thresholds(settings_json, defaults)`** — defaults от кода, override
от settings ключа; невалидни/липсващи полета тихо падат към default.

### 1.4 Семантика на ack / silence ( без фонов процес )

- **ack** = „видяно/обработено" до края на епизода. Епизодът свършва, когато
  условието се изчисти И се върне: батерията се възстанови над прага и после
  пак падне ( нов `since` > `acked_at` → пак `open` ); щормът мъртви букви
  изчезне от прозореца и нов започне; възелът проговори и пак замлъкне.
- **silence {hours}** = „не ми показвай до HH:MM" — `silenced_until =
  now() + hours`; след изтичане статусът се връща според ack ( самата
  заглушеност живее в таблицата, не се изчислява ).
- **unack** ( малко разширение, силно препоръчано ): изчиства реда —
  страховитата.undo на случайно ack-нат ключ; без него грешка в NOC се
  коригира само с `psql`.
- Честно документирано поведение: ack на **вечно замлъкнал** възел стои
  завинаги ( докато `last_seen_at` не излезе от `history_hours` ) — прието:
  операторът явно е казал „знам за този възел".
- Честно документирано поведение №2: **deadletter sliding window** — след
  ack, когато старите мъртви букви излязат от 24-ч прозореца и `since`
  премине `acked_at`, събитието се отваря пак. Това е коректно ( нова
 的证据на база ), но изненадващо ако не е казано — UI ( Т9 ) показва
  `since` до бутона.

### 1.5 Severity ( enum-ът от миграция 007: info|important|critical )

`deadletter` → **critical** ( доставка фактически е изгубена ),
`battery` → **important**, `silence` → **important**. Подреждане в
отговора: severity → since ( най-старото първо ).

## 2. Прагове — settings ключ ( БЕЗ миграция на схемата )

Ключ `critical_events` в таблица `settings` ( jsonb ), upsert по образеца
на ha.py:29-32:

```json
{
  "battery_threshold": 20,
  "deadletter_threshold": 3,
  "silence_hours": 12,
  "silence_history_hours": 168
}
```

- Defaults живеят като константи в `critical/detectors.py`; `GET` отговорът
  винаги ехо-ва ЕФЕКТИВНИТЕ прагове ( за QA + System страницата ).
- Полетата в System страницата идват с **Т32** ( по план „прагове + полета в
  System (без миграция)" ); Т7 носи API повърхността им ( §4 PUT ), така че
  Т32 е чист фронтенд.
- Профилите ( profiles.py ) могат да ги override-нат после без промяна —
  същият key/value модел.

## 3. API контракт

### 3.1 `GET /v1/critical-events?hours=24&status=all` — RBAC: viewer

`hours` кламп 1..168 ( като /anomalies ); `status` филтър
`all|open|acked|silenced` ( default `all` — панелът на Т9 показва контекста,
броячът на шел-а брои `open` ). Отговор:

```json
{ "data": {
  "hours": 24,
  "thresholds": {"battery_threshold": 20, "deadletter_threshold": 3,
                  "silence_hours": 12, "silence_history_hours": 168},
  "events": [
    { "key": "battery:!1a2b3c04", "kind": "battery", "status": "open",
      "severity": "important", "label": "батерия 12% на !1a2b3c04",
      "since": "2026-10-28T06:40:00+00:00", "last_ts": "2026-10-28T09:10:00+00:00",
      "value": 12, "count": null, "node": "!1a2b3c04", "rule": null,
      "acked_by": null, "acked_at": null, "silenced_until": null,
      "links": { "page": "devices", "node": "!1a2b3c04",
                  "url": "?p=packets&node=!1a2b3c04" } },
    { "key": "deadletter:tele-export", "kind": "deadletter", "status": "silenced",
      "severity": "critical", "label": "5 мъртви букви: tele-export",
      "since": "2026-10-27T22:03:00+00:00", "last_ts": "2026-10-28T08:55:00+00:00",
      "value": null, "count": 5, "node": null, "rule": "tele-export",
      "acked_by": null, "acked_at": null, "silenced_until": "2026-10-28T15:00:00+00:00",
      "links": { "page": "routing", "rule": "tele-export",
                  "url": "?p=packets&topic=deadletter/tele-export" } }
  ],
  "summary": { "open": 3, "acked": 1, "silenced": 2, "total": 6,
                "by_kind": {"battery": 2, "deadletter": 3, "silence": 1} }
} }
```

- `summary` е задължителен блок — шел-броячът ( §5 ) го ползва направо, без
  пресмятане на клиента.
- Кап на списъка: 200 събития ( честно като при /anomalies ); `summary.total`
  е истинският брой.
- SQL план на заявката ( 4 четения ): телеметрии за батерия ( 1 ) +
  dead-letter група ( 1 ) + devices ( 1 ) + state `WHERE event_key = ANY($1)`
  ( 1 ). Никакви записващи заявки при GET.

### 3.2 `POST /v1/critical-events/{key}/ack` — RBAC: operator

Upsert в `critical_events_state`: `acked_by/acked_by_name/acked_at=now()`
( `INSERT … ON CONFLICT (event_key) DO UPDATE … RETURNING *` ). Валидация:
префиксът на ключа ∈ {`battery:`,`deadletter:`,`silence:`} и kind колоната
съвпада ( защита от typo-ключове ). 404 НЕ е правилната грешка — ключът
възможно е още да не „горѝ" в момента; връщаме 200 с реда ( ack-ът е
идемпотентен ) или 422 при неканоничен ключ. Audit: action `critical.ack`,
entity `critical_event`, entity_id = ключа.

### 3.3 `POST /v1/critical-events/{key}/silence` — RBAC: operator

Тяло `{ "hours": 6 }` ( int, кламп 1..720 = 30 дена ). `silenced_until =
now() + hours`; НЕ пипа ack колоните ( двете състояния са независими:
silence изтича, ack стои ). Audit: `critical.silence` с hours в details.
Отговор: редът от таблицата ( същият shape като events[].acked_*/silenced_
until полетата ).

### 3.4 `POST /v1/critical-events/{key}/unack` — RBAC: operator

Изтрива реда ( нулира и ack, и silence ). Audit: `critical.unack`. ( §1.4 )

### 3.5 `GET|PUT /v1/critical-events/thresholds` — RBAC: viewer / admin

GET: ефективните прагове; PUT: частичен merge с валидация и клампове (
батерия 0..100, deadletter ≥ 1, silence_hours 1..720, history ≥
silence_hours ), upsert в settings + audit `critical.thresholds` (
entity `settings` — прецедент ha.py:35 ). За System страницата ( Т32 ) и QA.

## 4. RBAC + audit — обосновка

| действие | роля | прецедент в кода |
|---|---|---|
| GET events / thresholds | viewer | /anomalies, /routing list — viewer ( meta.py:256, routing.py:309 ) |
| ack / silence / unack | **operator** | routing enable/disable и dry-run са operator ( routing.py:473, 489, 622 ) — ack-ването на аларма е операционно действие, не конфиг ; NOC оператор без admin права трябва да може да си чисти брояча |
| PUT thresholds | admin | всички конфиг изменения ( notifications CRUD, rule publish ) са admin |

Audit през съществуващата `security.audit()`; actions: `critical.ack`,
`critical.silence`, `critical.unack`, `critical.thresholds`. Показват се в
съществуващия /v1/audit изглед без промяна.

## 5. Интеграция със шел-брояча ( drop-in за useAnomalyCount )

Хукът ( hooks/useAnomalyCount.ts ) очаква `fetchCriticalEvents(hours) →
AnomalySummary` и самата бележка в кода ( ред 169-172 ) казва: „аларма =
незаглушени/не-ACK-нати събития". Затова контрактът горе е огледален на
`/v1/anomalies` envelope-а + готов `summary`:

- `events[].{ts, kind, label}` присъства ( `kind` = battery|deadletter|
  silence; `ts` = `last_ts` ) — адаптерът може да ползва или суровите
  събития, или направо `summary`.
- новият адаптер е ~15 реда в ADAPTERS ( ред 173 ):

```ts
'critical-events': async (hours) => {
  const raw = await api<CriticalEventsResponse>(`/v1/critical-events?hours=${hours}`)
  const ev = Array.isArray(raw?.events) ? raw.events : []
  const open = ev.filter(e => e.status === 'open' && typeof e.ts === 'string')
  const lastTs = (a: string[]) => a.length ? a.reduce((m, t) => Date.parse(t) > Date.parse(m) ? t : m) : null
  return {
    hours: raw?.hours ?? hours,
    alarm: raw?.summary?.open ?? open.length,          // ЧИСЛОТО В БРОЯЧА
    deadletter: raw?.summary?.by_kind?.deadletter ?? 0,
    notifyFailed: 0, notifySent: 0, rulePublish: 0,
    byKind: { deadletter: …, notify_failed: 0, notify_sent: 0, rule_publish: 0 },
    openByKind: raw?.summary?.by_kind,                  // адитивно поле ( долу )
    total: raw?.summary?.total ?? ev.length,
    lastAlarmTs: lastTs(open.map(e => e.ts)),
    lastTs: lastTs(ev.map(e => e.ts)),
    updatedAt: Date.now(),
  }
}
```

- `AnomalySummary` се разширява с **едно адитивно optional поле**
  `openByKind?: {battery: number, deadletter: number, silence: number}` —
  non-breaking за TypeScript strict; tooltip-текстът на AlarmChip/бадж-а (
  „N мъртви букви + M провалени известия" ) се преизговаря в Т9, когато
  панелът „Критични събития" излиза — Т7 НЕ пипа фронтенда.
- Shell сменя само `alarmSource='critical-events'` ( Shell.tsx:429 ).

## 6. Миграция 010

```sql
-- Т7 (docs/16): човешкият отговор на критичните събития (ack/silence).
-- Събитията САМИТЕ се изчисляват от данните при всяка заявка (вариант 1);
-- тук живее само отговорът — един ред на активно събитие.
CREATE TABLE IF NOT EXISTS critical_events_state (
  event_key text PRIMARY KEY
    CHECK (event_key ~ '^(battery|deadletter|silence):.+'),
  kind text NOT NULL CHECK (kind IN ('battery','deadletter','silence')),
  acked_by uuid REFERENCES users(id) ON DELETE SET NULL,
  acked_by_name text,
  acked_at timestamptz,
  silenced_by_name text,
  silenced_until timestamptz,
  note text,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS critical_events_state_silenced_idx
  ON critical_events_state (silenced_until)
  WHERE silenced_until IS NOT NULL;
```

- **Нагоре:** автоматично от `db.migrate()` ( приложението си я вдига при
  старт; advisory lock вече се държи от framework-а ).
- **Надолу:** framework-ът е forward-only ( db.py прилага само `*.sql`
  последователно — няма down механизмъм в никоя миграция до сега ).
  Ръчният downgrade е документен тук: `DROP TABLE IF EXISTS
  critical_events_state;` — нула чужди FK към нея ( references само към
  users с ON DELETE SET NULL ), нула данни за възстановяване ( събитията
  са изводими ). Обратимостта е пълна.
- Периодично почистване ( изтрити възели/правила оставят сиречи редове ):
  излишно за коректност ( merge-ът работи и с мъртви редове ), но ред 1 в
  заявката за state може да ги чисти: `DELETE FROM critical_events_state
  WHERE updated_at < now() - interval '30 days'` — opportunistic, в
  същата транзакция на ack/unack ( нула нов фонов цикъл ).

## 7. Тестове

### 7.1 Unit — `tests/unit/test_critical_detectors.py` ( чисти функции, фиксстури )

- **батерия:** 12 → пали; 20 → НЕ пали ( строго `<` ); без телеметрия → без
  събитие; възел с последно четене 25 след по-старо 12 → не пали И `since`
  се нулира ( епизодът е приключил ); два възела — само критичният.
- **deadletter:** 2 → не; 3 → пали ( `>=` ); rule A 5 + rule B 1 → само A;
  ключ = `deadletter:A`.
- **мълчание:** last_seen преди 13 ч + история → пали; преди 11 ч → не;
  преди 3 дена ( извън history 168 ч ) → не; muted → не; mqtt протокол → не;
  `since == last_seen + silence_hours`.
- **apply_state:** open без ред; `acked_at > since` → acked; `acked_at <
  since` ( нов епизод ) → open; `silenced_until > now` → silenced;
  изтекло silence + валиден ack → acked; изтекло silence без ack → open.
- **merge_thresholds:** липсващ ключ → defaults; частичен override;
  невалидна стойност ( `"bat": "x"` ) → default за полето, без exception.
- **event_key:** lowercase нормализация на `!HEX` → `!hex`.

### 7.2 Integration — `tests/integration/test_critical_events.py` ( жив стек, в api контейнера )

1. **демо възел с ниска батерия → събитие:** MQTT публикация на
   `msh/emul/2/e/LongFast/!<node>` с proto3-JSON `TELEMETRY_APP` +
   `telemetry.device_metrics.battery_level: 12` ( `publish_mqtt` от
   test_checklist; envelope_info:136-146 го декодира ) + една `mesh/emul/`
   JSON телеметрия за втори възел ( покрива и демо формата ) → GET показва
   `battery:!…` open с value 12.
2. **ack → изчезва от open:** POST ack с operator → GET: статус `acked`,
   `summary.open` намалява с 1; audit ред `critical.ack` съществува.
3. **silence 1 ч → silenced:** POST silence `{hours:1}` → статус
   `silenced` + `silenced_until` ≈ now+1h; изтичане се тества в unit (
   apply_state с фиктивно now ), не с реален сън.
4. **права:** viewer ( създаден през /v1/users ) → GET 200, POST ack →
   **403**; operator → 200; PUT thresholds като viewer/operator → 403, като
   admin → 200 + settings редът е обновен.
5. **deadletter:** 3 тестови мъртви букви — или директно_packets INSERT с
   тема `deadletter/t7itest-<rand>` ( тестовете имат psql достъп през
   контейнера ), или живото: правило с недостижима HTTP дестинация ( тест-модел
   от t6-variants рецептата ) → `deadletter:…` critical, count 3. **Тестът
   трие собствените си мъртви букви** ( правило №5 на плана ).
6. **мълчание:** SQL поставя `devices.last_seen_at = now()-13h` на тестов
   възел ( + пакет отпреди 13 ч за „история" ) → `silence:!…` open; teardown
   възстановява/трие реда.
7. **RBAC 401:** без сесия → 401 ( като всички /v1 ).

### 7.3 Жива QA проверка ( по плана на Т7 )

Демо възъл < 20% → аларма в GET; ack от operator акаунт → изчезва от
`summary.open`; change на прага през PUT thresholds ( напр. battery 30 )
→ още възли стават критични без рестарт ( изчислено на заявка! ); rollback
на прага → обратно.

## 8. Производителност ( риск-анализ на заявката )

- Цената на една GET: 4 SQL четения + decode на ≤ 2000 телеметрии в Python.
  Обемът по план: 60–140 възли; шел-броячът пулсира на 10 s на отворен таб
  ( hidden tab → skip, вече в хука ) — реалистично 1–3 конкурентни
  полинг-а = под 1 qps. Като сравнение `/v1/devices/pulse` прави по-тежка
  работа на 60 s цикъл.
- Батерията е скъпата част ( decode на protobuf/JSON на ред ) — същата цена
  вече се плаща от stats/overview и devices/map. Ако стане проблем:
  in-process TTL кеш 5 s ( една заявка на процес на 5 s, споделен между
  табовете ), после чак тогава материализация ( В2 територия ).gzip вече
  е включен ( main.py:185 ).
- deadletter групата върви по `packets_topic_idx` ( prefix LIKE ); мълчанието
  е scan на `devices` ( стотици редове ); state merge е PK lookup по ANY(
  keys ) — всички O(малко).
- Честност за капацитета: батерия READ-ът е `LIMIT 2000` ( DESC ) — при
  възел-флуд Telemetry, възли извън лимита се пропускат за цикъла (
  документирано в отговора ли не — рисковете по-долу ). Devices/map вече
  живее с LIMIT 3000 при същия компромис.

## 9. Присъда — силни / слаби страни на В1

**Силни:**
1. **Нула фонов процес** → нула разсинхронизация, нула "caught-up" след
   рестарт, нула допълнителна инфраструктура за тестове ( детекторите се
   тестват чисто ); най-малкият експлоатационен риск от трите варианта.
2. **Винаги свежо състояние** — промяна на праг или данни се вижда на
   следващия poll ( 10 s ), без да чака evaluation цикъл.
3. **Детекторите са чисти функции** — пълно unit покритие на цялата
   бизнес-логика ( прагове, епизоди, статуси ) без база.
4. **Миграцията е минимална и напълно обратима** ( една таблица, нула
   FK към нея, downgrade = един DROP ).
5. **Drop-in за шел-брояча** — envelope огледален на /anomalies + готов
   `summary`; превключвателят на Shell е 1 проп.

**Слаби / рискове ( и митигация ):**
1. **Цената се плаща на всяка заявка** × на всеки таб: при растеж на
   мрежата ( > 300 възли, чата телеметрия ) decode-ът на батериите ще
   тежи → TTL кеш 5 s; дългосрочно — материализация ( В2 ) или ingest да
   пише `device_observations` ( таблицата вече съществува, празна ).
2. **Battery LIMIT 2000** — възли отвъд лимита не се оценяват този цикъл (
   рядко, флуд сценарий; честно документирано, както при map ).
3. **Rule rename = нов event_key** ( името е идентичността на
   deadletter-събитието ) → ack-ът на старото се осиромашива. Тъй като
   rename изисква пълен definition replace ( PatchIn ), това е рядко
   административно действие; документирано.
4. **Sliding-window re-open при deadletter** след изтичане на прозореца —
   коректно, но изненадващо; покрива се с `since` в UI-то ( Т9 ) + бележка
   тук ( §1.4 ).
5. **`!` и кирилски имена в URL path** — клиентите трябва да encode-ват;
   Starlette decode-ва коректно; интеграционен тест №2 го пази.
6. **devices.status не се поддържа offline** — детекторът изобщо не го
   ползва ( сила ), но значи „активен" се дефинира от history прозореца,
   не от статус поле.

**Кога В1 НЕ е правилният избор:** ако собственикът иска история на
събитията ( first_seen преди 7 дена, resolution timestamp, MTTR ) или
push-известия при възникване ( детекторът тук вижда само „критично сега" )
— тогава трябва evaluator записващ преходи ( В2 стил ); за Т7-обхвата
( панел + брояч + ack/silence ) В1 покрива всичко с най-малко движещи се
части.
