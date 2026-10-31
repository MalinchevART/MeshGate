# Т7 „Критични събития: бекенд" — Вариант 3: „Нула миграция — изчислено сега, ack в settings"

Дата: 2026-10-28. Част от П1 (варианти) на фаза Т7 по `docs/16` (ред 30).
Изходни точки: спекът на Т7 („прагове като settings ключове + полета в System
(без миграция)") + F2 в `docs/design/review-2026-10-24.md` (ред 70: детектори
батерия/dead-letter/мълчание, ack/silence, deep links, конфигурируеми прагове);
съществуващият код: `settings` таблицата (`migrations/001_init.sql` ред 40),
патърнът „настройка + поле в System" от homeassistant интеграцията
(`app/routes/ha.py` + `app/integrations/ha_engine.py`), профилният патърн за
многоключова транзакционна писане на settings (`app/routes/profiles.py` ред
144–160), форматът на `/v1/anomalies` (`app/routes/meta.py` ред 254+),
RBAC/audit (`app/security.py`), шел-хукът с готов слот за Т7
(`apps/web/src/hooks/useAnomalyCount.ts` ред 173+: `ADAPTERS['critical-events']`).

## Стратегия В3 в едно изречение

`GET /v1/critical-events` изчислява „критично СЕГА" при всяка заявка върху
готовите данни (точно като `/v1/anomalies` днес) от три чисти детекторни
функции, а ЕДИНСТВЕНОТО ново състояние — кой какво е потвърдил/заглушил —
живее като JSON в съществуващата settings таблица (ключ `meta.critical_ack`),
пише се атомарно с едномерни jsonb операции и се чисти мързеливо при четене:
**нула нови таблици, нула миграции, нула worker, нула кеширани рамки**.

```
 GET /v1/critical-events                 POST .../ack|silence   PUT thresholds
 ┌──────────────────────────────┐        ┌──────────────┐      ┌───────────┐
 │ SQL: батерии (events, 24ч)   │        │require_      │      │require_   │
 │ SQL: deadletter/… (packets)  │        │operator      │      │admin      │
 │ SQL: devices.last_seen_at    │        └──────┬───────┘      └─────┬─────┘
 │ GET settings: critical       │               │                    │
 │ GET settings: meta.          │               ▼                    ▼
 │      critical_ack (JSON)     │    UPDATE settings SET             UPDATE settings
 │        │                     │    value = value ∥ {ключ:…}        SET value=…
 │        ▼                     │    (ЕДНО изречение = атомарно)     + audit
 │ детектори (чисти ф-ции,      │               │                    │
 │ now се подава) → events[]    │◄──────────────┘                    │
 │ + статус open/acked/silenced │  audit: critical.ack / .silence
 └──────────────────────────────┘
```

## 0. Какво заварихме (важно за честността на „без миграция")

- **Няма отделен settings-сервис модул** — ключовете се четат/пишат с inline
  SQL на четири места (`ha.py`, `ha_engine.load()`, `profiles.py`, `main.py`
  retention). Таблицата е `settings(key text PRIMARY KEY, value jsonb,
  updated_at)` (миграция 001). В3 НЕ въвежда нова услуга — новият код следва
  същия inline стил, но в ЕДИН нов модул `app/critical/`, за да не разпилява
  пети-шести екземпляр на патърна.
- **Патърнът „настройка + поле в System" съществува по дух** (homeassistant:
  `settings['homeassistant'] = {"enabled": bool}`, UI превключвател в
  Integrations.tsx, engine-ът го презарежда от DB), но System routes
  (`app/routes/system.py`) днес нямат НИТО ЕДНО settings поле — страницата
  System е потребители + audit. Праговете на Т7 ще са първият „настройка с
  форма в System" — вдигаме мини-патърн: GET връща ключове с default-и,
  PUT валидира и одитва.
- **Забележка за `updated_at`:** `ha.py` прави `ON CONFLICT … DO UPDATE SET
  value = …` БЕЗ `updated_at = now()` — колоната остава от INSERT-а
  (микро-бъг). `profiles.py` го пише коректно. Всички писания на В3 включват
  `updated_at = now()` изрично.
- **Форматът-модел** е `/v1/anomalies`: клампване на параметри, `{data: …}`
  обвивка, плосък списък с `ts/kind/label`, LIMIT-и срещу разширяване
  (200/200/100), сортиране и рязане в Python.

## 1. Settings ключове

| Ключ | Стойност (default) | Кой пише | Кой чете |
| --- | --- | --- | --- |
| `critical` | `{"battery_pct": 20, "deadletter_24h": 10, "silence_hours": 24}` | PUT от admin (форма в System, Т32 я плитка) | всяка GET заявка (с клампване + defaults при липсващ/невалиден ключ — безчувствено като `_parse_hhmm` в notify) |
| `meta.critical_ack` | `{"<event_key>": {"acked_at": ISO, "acked_by": "admin"} \| {"silenced_until": ISO, "silenced_by": "…"}}` | САМО API-то (ack/silence POST + мързелив GC) | всяка GET заявка |

Дизайн решения:

1. **Праговете — ЕДИН ключ `critical`, не три.** Три отделни ключа значи три
   реда, три форми, три ON CONFLICT-а за една форма в System; един JSON е
   атомарна единица за OE crowds… за оператора („Запази праговете" = една
   операция, един audit ред). Точно патърнът `retention` в profiles.py.
2. **Ack-ът е ОТДЕЛЕН ключ от праговете — нарочно.** Ако ack живееше вътре в
   `critical`, всеки ack на оператор пренаписва целия JSON с праговете и се
   състезава с admin-а, който едновременно бута форма в System (класически
   read-modify-write загубен ъпдейт между ДВЕ различни функции). Отделни
   ключове = отделни редове = row-lock изолация между двата потока.
3. **`meta.` префикс** маркира „машинно състояние, не потребителска
   настройка": никога не се показва във формата в System; backup/restore го
   носи безплатно (той е ред в settings); ако някога мигрираме към таблица
   (В1/В2), ключът се разпознава по име.
4. Кламвания: `battery_pct` 5..90 (int), `deadletter_24h` 1..1000 (int),
   `silence_hours` 1..336 (int). Извън диапазон → 422 с човешко съобщение
   (патърнът на emulator `422 „действието е pause или resume"`).

## 2. Детектори — чисти функции

Модул `app/critical/detectors.py`. Вход: прости структури (списъци от
речници), `now: datetime` се подава отвън, изход: `list[CriticalEvent]`.
Нито един детектор не пипа DB/клок — това ги прави тестируеми на 100% unit
ниво (изискването на спека „unit+integration (детектори)").

Общ изход (dataclass → dict в route-а):

```python
class CriticalEvent(TypedDict):
    key: str            # стабилна идентичност: "battery:!a1b2c3" | "deadletter:<rule>" | "silence:!a1b2c3"
    kind: str           # "battery" | "deadletter" | "silence"  (Т18 по-късно добавя "canary")
    severity: str       # "critical" (съвместимо с notification severity: info|important|critical)
    label: str          # човешки: "батерия 12% · !a1b2c3"
    value: float | None # 12 (проценти) / брой мъртви букви / часове мълчание
    since: str | None   # ISO, най-добро усилие „откъде го знаем" (вж. слабост №2)
    ref: dict           # суровина за deep link: {"node": "!a1b2c3"} / {"rule": "името"} / {"topic": "deadletter/x"}
```

### 2.1 `detect_battery(rows, threshold_pct, now)` — батерия под праг

- Вход (`rows`): последна телеметрия per възел — SQL по патърна на брифа
  (`notify/engine.py` ред 57–65): `events.payload->'decoded'->>'battery'` за
  24 ч, `max() per node`… всъщност ПОСЛЕДНАТА стойност: `DISTINCT ON (node)
  … ORDER BY node, ts DESC` (батерията пада с времето; последната е истина).
  Проверка на числовост с regex `~ '^[0-9]+(\.[0-9]+)?$'` — пак от брифа
  (jsonb-ът търпи боклук).
- Гърми: `value < threshold_pct` (строго; `==` не е събитие — границата е
  „под праг", плаката казва „<20%").
- `since` = ts на четенето, от което го знаем.
- MUTED/BLOCKED възли не се изключват тук (това е слой на заявката към
  devices — виж 2.3; батерията на заглушен възел е ИСТИНСКА информация,
  само не бива да алармира чипа — решение: изключваме и нея, иначе чипът
  не е „нула шум" след mute; изрично `NOT d.muted AND NOT d.blocked`).

### 2.2 `detect_deadletter(rows, threshold_24h, now)` — мъртви букви по правило

- Вход: `SELECT split_part(topic,'/',2) AS rule, count(*) AS n, min(ts) AS first`
  върху `packets WHERE topic LIKE 'deadletter/%' AND ts > now() - 24h GROUP BY 1`
  (същият LIKE + split_part като anomalies, ред 265).
- Гърми: `n >= threshold_24h` — ЕДНО събитие per правило (не per буква;
  агрегаторът „критично СЕГА" брои проблеми, не инциденти).
- `since` = `min(ts)` — капсатирано от прозореца (вж. слабост №2).
- Тежест на заявката: LIKE-prefix + `packets_ts_idx`; anomalies вече върти
  същата форма на живия обем всеки 10 s — аргумент за достатъчност.

### 2.3 `detect_silence(rows, silence_hours, now)` — мълчание по last-heard

- Вход: `SELECT external_id, last_seen_at, first_seen_at FROM devices WHERE
  external_id LIKE '!%' AND NOT muted AND NOT blocked` (mesh възлите;
  `last_seen_at` се поддържа от ingest при всеки пакет — `ingest/service.py`
  ред 215–218).
- Гърми: `now - last_seen_at >= silence_hours`.
- **Фантом-гвард (важен):** възел, чут ВЕДНЪЖ преди месец, не е „мълчалив
  възел", а шум. Изключваме: `last_seen_at < now() - interval '14 days'` —
  мрежа без трафик 2 седмици значи „възлят е изваден", не „мълчи". Прозорецът
  е `[silence_hours, 14d]` — същият дух като тихите фаворити в брифа
  (12–48 ч), разширен. Освен това `first_seen_at > now() - silence_hours`
  не гърми (нов възел, още не е имал шанс) — посреща и Т18 канаря-урока
  „нов възел без история — не алармира".

## 3. GET `/v1/critical-events` — форма

```
GET /v1/critical-events            (require_viewer)
→ 200 {"data": {
      "generated_at": "2026-10-28T…",
      "thresholds": {"battery_pct":20, "deadletter_24h":10, "silence_hours":24},   # ефективните (след клампване)
      "open": 2,                    # ЧИСЛОТО ЗА БРОЯЧА: статус == "open"
      "events": [
        {"key":"battery:!a1b2c3","kind":"battery","severity":"critical",
         "label":"батерия 12% · !a1b2c3","value":12.0,"since":"…",
         "status":"open",           # "open" | "acked" | "silenced"
         "acked_at":null,"acked_by":null,
         "silenced_until":null,
         "link":{"p":"explorer","topic":"msh/…"} },
        {"key":"deadletter:alert-rule", …,
         "link":{"p":"explorer","topic":"deadletter/alert-rule"}, …},
        {"key":"silence:!f00d","value":37.5, …,
         "link":{"p":"devices","node":"!f00d"}}
      ]}}
```

- Сортиране: `deadletter → battery → silence`, вътре по `-value` (по-лошото
  първо); LIKE anomalies — в Python, след като трите списъка се съберат.
- **Статусната сметка е чиста функция** `apply_ack_state(events, ack_json,
  now) -> (events, stale_keys)`: `silenced_until > now` → `silenced`;
  `acked_at` съществува → `acked`; иначе `open`. **Изтекъл silence пада
  автоматично** — той просто не отговаря на `> now` и става `open` (ако не е
  и ack-нат). Нищо не се трие, за да се случи това.
- **Deep links:** бекендът дава суровината (`link.p` + филтърните полета),
  фронтендът прави `?p=explorer&topic=…` (навигацията е `?p=` без router —
  docs/16 ред 121). Три мишени: Explorer с topic филтър (deadletter),
  Explorer/детайл на възел (battery), Devices/пулс (silence). Никакви URL-и
  се не пекат в DB — линкът е производим от `key`/`ref` всеки път.

### 3.1 Мързелив GC при четене (единственият страничен ефект на GET)

След `apply_ack_state`: ключове в JSON-а, които НЕ са в текущия open набор
(събитието се е разрешило) или са ack-нати преди >7 дни, се трият с ЕДНО
изречение `UPDATE settings SET value = value - $1::text[] WHERE key =
'meta.critical_ack'` — само ако `stale_keys` не е празен (иначе GET-ът е
чисто четене). Това държи JSON-а ограничен до „текущо отворените + съвсем
скорошни" без worker. Цена: GET понякога пише — вж. слабост №5.

## 4. POST ack/silence — писане в settings JSON, конкурентност

Два endpoint-а (+разрешаване на грешка):

```
POST /v1/critical-events/{key}/ack            (require_operator)
POST /v1/critical-events/{key}/silence        (require_operator)  body: {"hours": 4}  (кламп 1..72)
POST /v1/critical-events/{key}/clear          (require_operator)  — маха записа (разбъркано ack? нов старт)
PUT  /v1/system/critical-thresholds           (require_admin)    body: частичен {"battery_pct": 15}
```

Всеки POST връща СЪЩИЯ shape като GET (списък + статуси) — фронтендът сменя
състоянието на място, точно както `ha_enable` връща GET-статуса на HA
(`ha.py` ред 37–45). Не се валидира дали `key` е „истинско" текущо
събитие срещу DB (събитието е изчислено, не съхранено) — валидира се формата
на ключа; ack на несъществуващ ключ е безобиден (GC го чисти при следващия
read) и одитиран.

### 4.1 Атомарност без migration: едномерни jsonb операции

Опасният наивен вариант е read-modify-write в Python (вземи JSON → добави →
запиши целия): два оператора, които ack-ват различни събития едновременно,
си губят взаимно записа. В3 НЕ прави това. Всеки запис ЕДНО изречение,
което PostgreSQL изпълнява под row-lock на засегнатия ред:

```sql
-- ack / silence (merge на ЕДИН ключ в съществуващия JSON):
INSERT INTO settings (key, value)
VALUES ('meta.critical_ack', jsonb_build_object($1, $2::jsonb))
ON CONFLICT (key) DO UPDATE
  SET value = settings.value || jsonb_build_object($1, $2::jsonb),
      updated_at = now()

-- clear / GC (махане на ЕДИН или МНОГО ключове):
UPDATE settings
   SET value = value - $1::text[],           -- jsonb − text[] трие по имена
       updated_at = now()
 WHERE key = 'meta.critical_ack'
```

Операторите `||` (merge) и `-` (изваждане) се оценяват вътре в самия
UPDATE върху текущата стойност на реда; втората конкурентна заявка чака
row-lock-а и бленди върху НЕЙНИЯ резултат. Две различни събития от двама
оператора → и двата записа оцеляват. Ack и GC едновременно → и двете
коректни (GC трие само ключове, които е сметнал за стари; ако ack-ът е
добавил нов междувременно, той не е в stale списъка и не се пипа).
Многоключови операции (ако някога трябват) минават в `conn.transaction()`
както profiles.py — не ни трябва тук.

Останалите изводи за коректност:

- **Праговете (`critical`) и ack-ът (`meta.critical_ack`) са различни редове**
  — никога не се състезават (вж. §1.2).
- `acked_by` се взима от `CurrentUser` (не от тялото) — не се лъже.
- Idempотентност: повторен ack презаписва `{key: {acked_at, acked_by}}` с
  нов момент — приемливо („потвърдено отново"); silence удължава до
  `now + hours` от СЕГА (документирано в details на audit-а).

### 4.2 RBAC + audit

| Операция | Роля | audit action | entity / entity_id / details |
| --- | --- | --- | --- |
| GET списък | viewer | — | — |
| ack | **operator** | `critical.ack` | `critical-events` / `<event_key>` / `{kind, label}` |
| silence | **operator** | `critical.silence` | `critical-events` / `<key>` / `{hours, until}` |
| clear | operator | `critical.clear` | `critical-events` / `<key>` / `{}` |
| thresholds PUT | **admin** | `critical.thresholds` | `settings` / `critical` / `{before, after}` (патърнът на profiles diff) |

Изборът operator (не admin) е съзнателен: mute/block на възел днес е admin,
но ack/silence е оперативно „видях го / дай ми мир за 4 ч" — ежедневие на
NOC оператор;destructive операции остават админски. Аудитът ползва
съществуващия `security.audit()` → audit_log → видимо в System журнала с
филтър `critical.`.

## 5. Слабости — честна оценка и ум-братчета

1. **JSON-ът расте без лимит (без GC).** Истина е само ако никой не чете:
   GC на §3.1 чисти при всеки GET. Остатъчни случаи: (а) възел, ack-нат и
   после изобщо спрял да съществува в open множеството → чисти се при
   следващия GET; (б) stack без НИТО ЕДИН отворен таб с GET (никой не
   гледа) → JSON-ът застива, но е ограничен от размера на флота
   (възли+правила, стотици ключове най-много = десетки KB). **Приемаме:**
   таванът е структурен (флотът), не времеви. Ум-братче без миграция:
   `open`/`GET selftest` да репортира `ack_entries` брой (видимост, не
   по-малко пространство).
2. **Липса на история — „кога се появи".** Всичко е СЕГА: `since` е
   най-добро усилие от суровината (battery: ts на телеметрията; deadletter:
   `min(ts)` в 24-часовия прозорец — по-старото изчезва; silence: последния
   `last_seen_at`). Няма „първи път критично", няма архив на минали
   критични, няма тренд. **Приема се изрично** — за история е В2
   (материализация); междинно покритие: audit_log пази кога кой е ack-вал,
   notification_log/digest пazi повечето причинни събития. Събитието носи
   `since` с честен характер („известно от"), не birth-certificate.
3. **Конкурентен record-update на същия ключ.** Решено за читимите случаи с
   едномерни jsonb операции (§4.1) — на ниво заявку, не на ниво приложение.
   Истински остатъчен прозорец: ДВА едновременни ack-а на ЕДИН и същия
   `event_key` — последният печели `acked_at/by` (микроскопично: и двамата
   са „видели"; audit-ът пази и двата опита). Приемаме.
4. **Аудит-слем на настройки vs събития.** Събитиен ACK пише в settings
   таблицата — семантично е действие над събитие, физически ред в
   „настройки". Решение: audit action имената (`critical.ack`…) са
   събитийни, а `entity='critical-events'`; settings-редът е öffentlich
   невидим (не се показва във формата). Ограничение: филтърът в System по
   entity `settings` ще хваща и thresholds, и нищо друго — имената на
   action-а разграничават. GC при GET НЕ се одитира (иначе всеки poll от
   всеки таб плюе audit редове) — приемаме с отворени очи: GC не е човешко
   решение.
5. **GET със страничен ефект (мързелив GC).** GET понякога пише в settings —
   изключение от чистата четимост (анomalies днес е чисто четене). Омекотено:
   пише САМО при непразен stale списък (нормален случай: нищо). Алтернативата
   — cron worker — е точно това, което В3 отхвърля; ръчното чистене е
   забравяемо. Приемаме с декларация в код-коментар.
6. **Flapping / re-arm без история.** Батерия, която се люлее около прага
   (19.8% → 20.1% → 19.7%), произвежда отворено/затворено/отворено; след
   всяко „затворено" GC трие ack-а → следващото „отворено" алармира отново.
   Ум-братче (евтино, чиста функция): **хистерезис** — детекторът гърми под
   `battery_pct`, но събитието се счита за „затворено" чак над
   `battery_pct + 5` (rearm margin, константа или ключ в `critical`).
   Предложението на В3: първи срез БЕЗ хистерезис (демо възлите пасват чисто),
   полето `battery_rearm_pct` добавимо в `critical` без никаква миграция,
   когато живи данни покажат люлеене.
7. **Броячът е „поне толкова" при STOP на света** — не: за разлика от
   anomalies (капсатиран на 400 събития за feed), тук `open` е точно число
   (броят на отворените е малък по конструкция — детектори per възел/правило,
   не per пакет). Това е ЪПГРЕЙД спрямо днешния брояч (useAnomalyCount.ts
   ред 33–36 си признава „поне толкова").

## 6. Интеграция със Shell / useAnomalyCount

Хукът вече има слота: `ADAPTERS: Record<'anomalies' |
'critical-events', …>` и днес хвърля четима грешка за втория. В3 се
включва с ТОЧНО един нов fetcher (_hook файлът е на същия точно адрес
`apps/web/src/hooks/useAnomalyCount.ts`):

```ts
interface CriticalEventsResponse {
  generated_at?: string
  open?: number
  events?: { key: string; kind: string; status: string; since?: string | null; label?: string }[]
}
async function fetchCriticalEvents(hours: number): Promise<AnomalySummary> {
  const raw = await api<CriticalEventsResponse>('/v1/critical-events')
  const events = Array.isArray(raw?.events) ? raw.events : []
  // броячът = ТОЧНО отворените (не-ACK-нати, не-заглушени)
  // byKind: battery/deadletter/silence се събират от отворените;
  // lastAlarmTs = max(since) на отворените; deadletter/notifyFailed от
  // anomalies се излагат като 0/analog — AnomalySummary остава непипнат
  // типово (правило „нула чупещи промени" на Т6).
}
```

- **Drop-in shape:** Shell сменя само `alarmSource={'critical-events'}` (проп
  съществува); броячната стойност е `raw.open` — при нужда преизчислима от
  events (`status==='open'`), двойна проверка без значение кой печели.
- Кадансът остава 10 s; ГЕТ-ът е 4 SQL заявки (battery, deadletter,
  devices, settings ×2 в едно fetch на ключовете) — сравнимо със
  stats/overview, който вече върти по-тежката форма на живия обем.
- Т9 панел „Критични събития" (ред 34 на docs/16) консумира същия GET:
  ред със статус чип + ack/silence бутони → POST → същият shape → на място
  обновяване + `refresh()` на хука (вече го има, ред 199).

## 7. Тестове

### Unit (нов `tests/unit/test_critical.py`) — детектори + ack логика, `now` инжектиран

- battery: под прага гърми / на прага (`== 20`) НЕ / над НЕ; последна
  стойност печели при няколко телеметрии; невалиден низ в jsonb се прескача
  (regex-гвард); muted възел отсъства от входа (fixtures само с валидни
  редове — mute филтърът е в SQL, тестван в integration).
- deadletter: `n == threshold` гърми (>=), per-правило групиране,
  `since = min(ts)`.
- silence: над прага гърми; под НЕ; фантом (>14 дни) НЕ; нов възел НЕ;
  точно на границата (24.0h) гърми.
- `apply_ack_state`: open без запис; acked с acked_at; silenced с валидно
  until; **изтекъл silence → open** (ключовият тест на автоматичното падане);
  stale_keys = записани, но не в open множеството.
- Клемпи на праговете (5..90 / 1..1000 / 1..336) и merge-помощните
  функции за jsonb аргументи (строеж на `$2::jsonb`).

### Integration (нов `tests/integration/test_critical.py`, жив Postgres, патърн test_meta.py)

1. **Събитие → ack → изчезва от брояча:** засичане на реален open (демо
   възлите имат ниски батерии — инсталаторът ги прави такива нарочно,
   `MANUAL_CHECKS` m-alarm) ИЛИ вмъкване на events ред с
   `payload->decoded->>{node,battery}` през asyncpg (conftest вече има
   връзка към DB); GET → kind=battery присъства; POST ack (admin/operator
   логин) → GET → статус `acked`, `open` намалява с 1; 403 за viewer на
   POST; 401 без сесия.
2. **Silence изтича (fake clock през SQL):** POST silence `hours=1` →
   статус `silenced`; после директно `UPDATE settings SET value =
   jsonb_set(...)` със `silenced_until` в миналото (жив Postgres, часовникът
   на API-то не се пипа) → GET → статус `open` пак. Това е „fake clock" без
   да чакаме реален час и без sqlite (integration е на жив postgres).
3. **Deadletter:** INSERT на 10 packets реда `topic='deadletter/itest-rule'`
   (или реално генериране през тестово правило с недостижима HTTP дестинация
   — патърн от т6 QA рецептата) → GET → kind=deadletter за itest-rule; тестът
   трие собствените си редове (docs/16 правило №5: „тестовете трият
   собствените си мъртви букви").
4. **Прагове:** PUT с валидна частична стойност → GET `thresholds` я
   показва; PUT с `battery_pct: 0` → 422; viewer PUT → 403; before/after в
   audit details.
5. **Конкурентност (лек удар):** `asyncio.gather` на 10 ack-а на различни
   ключове → GET → всичките 10 присъстват в JSON-а (проверка през GET
   статусите/директен SELECT на settings стойността).
6. **Форма/права:** GET с viewer 200; неавтентикиран 401; `open` е число и
   `len([e for e in events if e.status=='open']) == open`.

## 8. Присяда: кога В3 е ДОБРИЯТ избор

**Взема, ако:** (а) обемът е NOC на собственик/малък екип — десетки възли,
шепа правила, 1–3 оператора; (б) „без миграция" е писано в плана и има
цена (всеки commit на миграция върви последователно, правило №5 на docs/16,
а следващата свободна е обявена за 009/priority в Т24 — В3 не гори номера
ѝ); (в) нуждата е „какво е критично СЕГА + кой го е видял", не регулаторен
журнал; (г) искаме Т18 (канаря) да добави четвърти детектор като ПРЕЧИСТА
функция без допир до състоянието — В3 е архитектурно най-гостоприемната
за нови детектори.

**Губи срещу материализация (В1/В2) на:** история/първи път (слабост №2),
строги occurrence идентичности и re-arm без хистерезис-трикове (№6),
евтин „критични през октомври" отчет, independent от суровината
(напр. deadletter `since` отвъд retention прозореца), брояч без recompute
при всеки poll (4 заявки на 10 s на таб — на този мащаб е шум, на
10× флот вече не е). Формулирано грубо: **В3 купува простота с парите на
паметта за миналото.** Ако някога панелът стане основа за SLA/отчети или
флотът мине ~250 възла с жив канар-детектор на Т18 — тогава миграцията
(В1/В2) се оправомощава сама, а `meta.critical_ack` се мигрира едностранно
с един INSERT SELECT.

## 9. Обем при внедряване (за детайлния преглед)

| Файл | Съдържание | ~реда |
| --- | --- | --- |
| `app/critical/__init__.py` | — | 0 |
| `app/critical/detectors.py` | 3 детектора + `apply_ack_state` + клемпи + `CriticalEvent` | ~120 |
| `app/routes/critical.py` | GET / POST ack/silence/clear / GET+PUT thresholds (или в system.py — решение: отделен router, регистрира се в main.py след meta) | ~130 |
| `tests/unit/test_critical.py` | виж §7 unit | ~150 |
| `tests/integration/test_critical.py` | виж §7 integration | ~160 |

Нищо друго не се пипа: Shell/useAnomalyCount имат слотове; System форма и
Т9 панел са фронтенд фази (Т32/Т9); `/v1/anomalies` остава непипнат
(браузърът му остава за времева лента на Мониторинг).
