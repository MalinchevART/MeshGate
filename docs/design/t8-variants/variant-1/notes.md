# Т8 „Dashboard агрегати: бекенд" — Вариант 1 „Един endpoint, всичко веднъж" — notes

Дата: 2026-10-28. Обхват: ДИЗАЙН. Никакъв код не е променян.
Изходни точки: docs/16-design-and-functionality-plan.md Т8 (Етап 3, F7/F15) +
потреблението на Т9-pre в `apps/web/src/pages/Overview.tsx`. Подетап 1/В1 от
phase-execution цикъла на Т8.

## 0. Изходна позиция — какво вече съществува (проверено в кода)

| Градивен блок | Къде | Какво носи / какво липсва |
|---|---|---|
| `GET /v1/stats/overview` | `apps/api/app/routes/meta.py:300-390` | часови кофи `date_trunc('hour', ts)` + запълване с нули (ред. 306-318), families по regex на ред (326-331), батерии с decode на ≤300 реда (333-364), rules join. Т9-pre вика с `hours=6/24/168`. **Липсва:** изпратени 24ч, стабилни връзки |
| `GET /v1/packets/facets` | `apps/api/app/routes/packets.py:101-143` | канали/възли през `topic_parts` в Python върху **последните 20 000 реда** (кап!) — `nodes` листът е капнат на 50, channels на 60. Т9-pre вика с `hours=min(period,24)`; „Активни възли" = `facets.nodes.length` → **застива на 50 при по-голяма мрежа** |
| `GET /v1/devices/topology` | `apps/api/app/routes/devices.py:179-239` | ребра от decode на ≤2000 `meshtastic-neighbor` пакета в Python; `edges` кап 400; `snr_avg/snr_max`; Т9-pre брои „стабилни" на клиента: `snr_avg ?? -99 >= -8` (Overview.tsx:158) |
| `GET /v1/devices/pulse` | `apps/api/app/routes/devices.py:99-176` | **моделът за перформанс**: двустепенна агрегация — стъпка 1 групира по `(topic, кофа)` само върху индексирани колони (частичния индекс 008), стъпка 2 вади възела с regex от ~стотинте ГРУПИ, не от редовете (7д ≈ 110K реда ≈ само ~630 теми; regex на ред ≈ 2.5s CPU — урокът) |
| индекси | миграции 001/008/009/010 | `packets_ts_idx (ts DESC)`, `packets_topic_idx (topic)`, частичен `packets_msh_pulse_idx ON packets (ts DESC) INCLUDE (topic, packet_type) WHERE topic LIKE 'msh/%'` (тъкмо за msh агрегациите), `critical_events_active_idx (status, last_seen_at DESC) WHERE status <> 'resolved'` |
| `counts.alarm` | `apps/api/app/routes/critical.py:85-99` | шел-броячът: `count(*) … WHERE last_seen_at > now() - make_interval(hours => $1) GROUP BY status` → `alarm = counts.open`. Шелът ползва `useAnomalyCount(source='critical-events', hours=24)` (Т7) |
| „изпратени" — източник | `apps/api/app/ingest/service.py:150-166, 253-265` + `routing/service.py:172-205` | всяко препращане на правило към **локалния брокер** минава през `publish_local` с origin marker `routing:<rule_id>` → записва се в `packets` с `origin='routing:<rule_id>'`; мъртвите букви са теми `deadletter/<правило>` (така ги брои и `/anomalies`, meta.py:264-269). RETAIN преигравките на routing:* се пропускат (Т7 фикс) → няма дубликати |
| `routing_executions` | `routing/service.py:220-230, 256-266` | Журналът се **подрязва до 200 записи на правило при всеки load()/restart** (`EXEC_KEEP_PER_RULE=200`) → 24-ч агрегат от него под-брои след рестарт. `routing_stats` е кумулативен брояч без ts → не се кофира. **Затова В1 не ги ползва за кофи** |
| канален token | `topic_parts` (mesh_decode.py:33-42) / филтърът в packets.py:58-64 | Meshtastic темата е `msh/<регион>/2/e|c|json/<канал>/!<възел>` — **каналът е 5-ият токен**; емулаторът пише `msh/emul/2/e/LongFast/!hex` (tools/emulator/nodes.py:113) |
| тестова платформа | `tests/integration/conftest.py` (asyncpg достъп до БД в контейнера), `test_facets.py` (уникални канали + `publish_mqtt` + sleep 2.5), `test_meta.py` (stats/overview: „25 buckets"), `test_checklist.py` (`API`, `login`, `publish_mqtt`, MQTT креденшъл фикстура) | образци за изолирани фикстури и RBAC |

Т9-pre прави **4 заявки на 10 секунди** (`stats/overview` + `facets` +
`topology` + критични за шел-чипа), като `stats/overview` върши и работа,
 която дашбордът не ползва (батерии + rules + families regex на ред).

## 1. Принципът на В1

**Едно GET носи целия дашборд.** `GET /v1/dashboard?hours=24` връща KPI ред +
кофи за трафика + изпратени 24ч по 3-ч кофи + канален пончик — изводимо от
`packets` / `devices` / `critical_events` при всяка заявка, **нула
материализация, нула миграция, нула фонов процес** (условието на Т8).
Числата се изчисляват от СЪЩИТЕ SQL фрагменти / споделен helper, с които
и съществуващите endpoints → консистентност **по конструкция**, не по
обещание (§5 я заключва с тестове).

Производителността копие похватите на `pulse`: (а) всичко върху индексирани
колони (`ts`, `topic`, `origin`), (б) regex само върху групи (~630 теми),
никога върху редовете (~110K при 7д), (в) каналът се вади с `split_part`,
не с regex, (г) топологията ползва вече платения decode (≤2000 реда) през
споделен helper. Кеш не се въвежда: оценка §6 ≈ 0.5s при жив обем на 7д —
поносимо на 10s полинг; лостът при нужда е TTL 5s (прецедент T7-В1 §8),
не е в този срез.

### 1.1 Модулна подредба (скица)

```
apps/api/app/routes/dashboard.py    # НОВ тънък router: GET /v1/dashboard (+1 ред include в main.py:192+)
apps/api/app/routes/meta.py         # рефактор: запълването на кофи (306-318) става функция _fill_hour_buckets —
                                    #   споделена със stats/overview (нула поведенческа промяна там)
apps/api/app/routes/devices.py      # рефактор: тялото на device_topology (ред. 190-238) става helper
                                    #   _topology_edges(pool, hours) -> list[dict]; /v1/devices/topology го вика
apps/api/tests/unit/test_dashboard.py
apps/api/tests/integration/test_dashboard.py
```

Няма миграция (следващият номер остава 011 за Т24).

## 2. API контракт

### `GET /v1/dashboard?hours=24` — RBAC: viewer

`hours` кламп `1..168` (като /stats/overview и /anomalies). Прозорци:
`hours` управлява **трафика**; KPI числата имат собствени смислени прозорци
(виж `kpi.windows` — самописащ се отговор, T9 показва етикетите без догатки):

| блок | прозорец | защо |
|---|---|---|
| `traffic` | `hours` (6/24/168) | период-селекторът на графиката |
| `kpi.nodes.active` | `min(hours, 24)` | 7д „активни" надува числото с мъртви възли; днес T9-pre пак показва „· 24 ч" на 7д (`Math.min(period,24)`, Overview.tsx:110) |
| `kpi.rf` | `min(hours, 24)` | същото — днес topology се вика с `min(period,24)` (Overview.tsx:111) |
| `kpi.alarms` | фикс. 24 | шел-броячът е 24ч (`useAnomalyCount hours=24`); критичното е „сега" |
| `sent_24h` | фикс. 24ч, кофи по 3ч | името на панела в docs/16 Т9 е „Изпратени последните 24ч" — стабилен контракт, не зависи от `hours` |

Отговор (пълен пример):

```json
{ "data": {
  "hours": 24,
  "generated_at": "2026-10-28T11:20:03+00:00",
  "kpi": {
    "windows": {"nodes": 24, "rf": 24, "alarms": 24},
    "nodes":  {"active": 42, "total": 57},
    "packets": {"total": 12345, "per_hour": 514.4, "last_hour": 380},
    "rf":     {"links": 18, "stable": 11, "stable_snr_db": -8.0,
               "nodes": 23},
    "alarms": {"open": 3}
  },
  "traffic":  [{"bucket": "2026-10-27T11:00:00+00:00", "count": 380}, …],
  "sent_24h": [{"bucket": "2026-10-28T09:00:00+00:00", "sent": 12, "failed": 1}, …],
  "channels": [{"name": "LongFast", "count": 9123}, …]
}}
```

- `traffic`: `hours+1` почасови кофи (като stats/overview — текущият час е
  последната, непълна кофа), наляво запълнени с нули. При `hours=168` → 169
  почасови кофи; групирането по ДЕН остава на клиента, ТОЧНО както T9-pre
  прави днес (Overview.tsx:164-185) → нулева видима промяна на графиката.
- `sent_24h`: точно 8 кофи по 3 часа, стени на стенен часовник
  (00:00, 03:00, 06:00 … UTC), запълнени с нули; `sent` = препратени от
  правилата към локалния брокер пакети, `failed` = мъртви букви (§3.4).
- `channels`: топ 12 (`name`, `count`) — данните за пончика; msh/scoped (§3.3).
- `rf.stable_snr_db` ехо-ва прага, UI пише „стабилни (SNR ≥ −8 dB)" без
  хардкод; `rf.nodes` = брой различни възли в ребрата (същата сметка като
  topology отговора).

Грешки: 401 без сесия (стандартното); невалидни стойности на `hours` се
клампват, не гърмят (както навсякъде в meta.py).

## 3. Точните SQL заявки (и планът им)

Всички заявки са четения; handler-ът ги пуска последователно в един
`pool` (като stats/overview). Параметър `$1` = часове.

### 3.1 Трафик + KPI.packets — IDENTICAL на stats/overview (meta.py:306-309)

```sql
SELECT date_trunc('hour', ts) AS h, count(*) AS n
FROM packets
WHERE ts > now() - make_interval(hours => $1)
GROUP BY 1 ORDER BY 1
```

План: index-only scan по `packets_ts_idx (ts DESC)` над диапазона. Python
запълва нулите със споделения `_fill_hour_buckets` (изнесен от meta.py) —
**същият код, същите числа**. От същите редове: `total = sum(n)`,
`per_hour = round(total/hours, 1)`, `last_hour = кофата преди последната`
(T9-pre: Overview.tsx:152) — нула допълнителна SQL.

### 3.2 KPI.nodes.active — двустепенна, похватът на pulse (без regex на ред)

```sql
WITH per AS (
  SELECT topic
  FROM packets
  WHERE topic LIKE 'msh/%'
    AND ts > now() - make_interval(hours => $1)
  GROUP BY topic
)
SELECT count(DISTINCT lower((regexp_match(topic, '(![0-9a-fA-F]+)$'))[1])) AS active
FROM per
```

План: частичният `packets_msh_pulse_idx` (миграция 008) дава index-only scan
сам върху msh редовете; стъпка 1 свива ~110K реда (7д) в ~630 теми; regex-ът
върху ГРУПИТЕ. `lower()` е по прецедента на pulse (devices.py:133) — реален
Meshtastic възел `!ABC…`/`!abc…` се брои веднъж. Общо възли:

```sql
SELECT count(*) AS total FROM devices
WHERE protocol = 'meshtastic' AND external_id LIKE '!%'
```

(същият обхват като `critical._silence_rows` — app/critical.py:233-236;
„възел" значи mesh възел, не произволна MQTT тема).

### 3.3 Канален пончик — split_part, не regex; пак двустепенно

```sql
WITH per AS (
  SELECT topic, count(*) AS n
  FROM packets
  WHERE topic LIKE 'msh/%'
    AND ts > now() - make_interval(hours => $1)
  GROUP BY topic
)
SELECT split_part(topic, '/', 5) AS name, sum(n)::int AS count
FROM per
WHERE split_part(topic, '/', 5) <> ''
GROUP BY 1 ORDER BY 2 DESC LIMIT 12
```

Каналът е 5-ият токен и при трите варианта `msh/<регион>/2/e|c|json/<канал>/!<възел>`
(константата `2` е на 3-та позиция — същите шаблони, по които мачва и
каналният филтър в packets.py:58-64). `split_part` е евтина операция, но я
вършим пак върху групите (~630), заради симетрия с pulse и заедно с 3.2 тя
е безплатна странична продукция на същия CTE (в имплементацията 3.2+3.3
 са ЕДНО завръщане: `SELECT count(DISTINCT lower(regex)) AS active,
 split_part(topic,'/',5) AS name, sum(n) … GROUP BY …` — 1 SQL за двете).

### 3.4 sent_24h — от origin маркера (24ч фиксирани, кофи по 3ч)

```sql
SELECT date_trunc('hour', ts)
         - make_interval(hours => (extract(hour FROM ts)::int % 3)) AS bucket,
       count(*) FILTER (WHERE origin LIKE 'routing:%'
                           AND topic NOT LIKE 'deadletter/%') AS sent,
       count(*) FILTER (WHERE topic LIKE 'deadletter/%') AS failed
FROM packets
WHERE ts > now() - interval '24 hours'
  AND (origin LIKE 'routing:%' OR topic LIKE 'deadletter/%')
GROUP BY 1 ORDER BY 1
```

- `sent` = изходните пакети на правилата (локален брокер) — записвани от
  Фаза 2 с `origin='routing:<rule_id>'`; мъртвите букви също носят
  routing: origin → изключени от `sent` с `topic NOT LIKE 'deadletter/%'`,
  за да не се двойнят.
- `failed` = мъртви букви — ИЗЦЯЛО същият източник/прозорец като
  `/v1/anomalies` (meta.py:264-269): сумата на `failed` по кофите ==
  броят deadletter събития на anomalies за 24ч (до кап 200 на anomalies).
- План: `ts` диапазон през `packets_ts_idx` (24ч ≈ 16K реда на живия обем),
  филтърът `origin/topic` е по евтини LIKE върху вече донесените редове —
  без regex; резултатните групи са ≤ 8.
- Защо НЕ `routing_executions`: подрязва се до 200/правило при всеки
  рестарт (service.py:256-266) → 24-ч кофи под-броят след рестарт;
  `routing_stats` е кумулативен без ts. Двата остават „истината за всички
  дестинации", но не са кофируеми — честно документирано в §8.

Python запълва нулите на 8-те 3-ч кофи (стени 00/03/06… UTC, последната
съдържа `now`).

### 3.5 KPI.alarms — IDENTICAL на critical.py counts (routes/critical.py:85-88)

```sql
SELECT status, count(*) AS n FROM critical_events
WHERE last_seen_at > now() - make_interval(hours => 24)
GROUP BY 1
```

`alarms.open = counts['open']` == `counts.alarm` от
`GET /v1/critical-events?hours=24` == числото в шел-чипа. (Това е един
ред SQL по `critical_events_active_idx` — не е конкурент на тежкия list
endpoint; шел-чипът продължава да ползва своя източник.)

### 3.6 KPI.rf — споделен helper с /v1/devices/topology

`_topology_edges(pool, hours)` (изнесен от devices.py:190-238) връща
ребрата с `snr_avg`; dashboard-ът смята:

```python
STABLE_SNR_DB = -8.0   # == прага на T9-pre (Overview.tsx:158)
links  = len(edges)                       # кап 400, както topology отговора
stable = sum(1 for e in edges if (e["snr_avg"] ?? -99) >= STABLE_SNR_DB)
nodes  = len({e["from"] for e in edges} | {e["to"] for e in edges})
```

Гаранцията за еднакви числа с картата е СПОДЕЛЕНИЯТ код (двата endpoints
викат един helper), не копието на логиката. Цената: decode на ≤2000
`meshtastic-neighbor` реда в Python — вече се плаща днес от topology
извикването на T9-pre на всеки 10s; при В1 общият брой тежки заявки
НАМАЛЯВА (§6).

## 4. Кеширане — не (в този срез)

По оценка (§6) целият endpoint е ~0.1-0.2s на 24ч и ~0.5s на 7д при живия
обем; T9 ползва полинг 10s за 6/24ч — бюджетът е отрупан. Лостове при
нужба (в ред): (1) TTL 5s in-process кеш на цялата единица отговор —
споделен между табовете; (2) по-рядък полинг на 7д (30-60s, stale-гвардът
в Overview вече съществува); (3) материализация (В2/В3 територия). Никой
не се въвежда сега — условието на Т8 е „без материализация в първия срез".

## 5. Консистентност със съществуващите endpoints (матрица)

| Число на дашборда | Двойник днес | Гаранция / документирана разлика |
|---|---|---|
| `traffic[].count` | `stats/overview.buckets[].count` | **Тождество по конструкция** — същата SQL + споделен `_fill_hour_buckets`; integration тест №2 го заключва |
| `kpi.packets.total/last_hour` | сумата на кофите / предпоследна кофа | производни на 3.1 — винаги равни на графиката |
| `kpi.alarms.open` | `critical-events counts.alarm` (шел-чип) | **Тождество** — същата SQL (3.5); тест №3 |
| `kpi.rf.links/stable` | `len(topology.edges)` / derived.stable на T9-pre | **Тождество** — спос. helper + праг −8 преместен на сървъра с ехо `stable_snr_db`; тест №4 |
| `kpi.nodes.active` | `facets.nodes.length` | **Замяна с по-чистото**: facets е капнат (50 възела / 20 000 реда) и не lower-ва; дашбордът е авторитетният брой. Разлика ВИДИМА само >50 активни възли или >20K пакета в прозореца — T9 превключва KPI-то на дашборда, не показва двете едновременно |
| `channels[].count` | `facets.channels` / `stats.families` | пончикът = Meshtastic логическите канали (msh/), пълен прозорец. facets брои същите канали, но върху capped 20 000 реда (под-брои при натоварен прозорец); families (stats/overview) групира и НЕ-msh семейства (alerts/, mesh/emul) — друг смисъл. На тихи прозорци facets.channels == channels по число (тест №5); панел „семейства" извън mesh остава достъпен от stats/overview, ако T9 го иска |
| `sent_24h[].failed` (сума) | `/v1/anomalies` deadletter за 24ч | **Тождество по източник и прозорец** (до кап 200 събития на anomalies — нашият е точният брой); тест №6 |
| `sent_24h[].sent` | — (НОВО число) | няма съществуващ двойник; най-близък `routing_stats.forwarded` (кумулативен, всички дестинации) — честно: нашето е „препратени към локалния брокер по кофи", bridge/HTTP дестинации не минават през packets (§8.3) |

Правило за T9: на екрана никога не стоят две числа за един и същи смисъл
от различни endpoints — дашбордът е източникът за KPI реда, трафика,
пончика и изпратените; шел-чипът остава на critical-events (30s полинг,
не зависи от дашборд страницата).

## 6. Производителност + риск при 7д прозорец

Оценка на живия обем (по урока от 009: 7д ≈ 110K пакета, ~630 теми;
24ч ≈ 16K):

| заявка | план | 24ч | 7д (168ч) |
|---|---|---|---|
| 3.1 трафик | index-only `packets_ts_idx`, GROUP BY hour | ~30-60ms | ~150-300ms |
| 3.2+3.3 възли+канали | index-only частичен `packets_msh_pulse_idx` (само msh редовете), regex/split върху ~630 групи | ~30-50ms | ~100-200ms |
| 3.4 sent_24h | ФИКСИРАН 24ч прозорец — не расте с `hours` | ~20-40ms | ~20-40ms |
| 3.5 аларми | `critical_events_active_idx`, редове = броя активни събития | <5ms | <5ms |
| 3.6 топология | ≤2000 neighbor реда + Python decode (споделен с /devices/topology) | ~100-250ms | ~100-250ms (LIMIT 2000 кап) |
| общо | 5 последователни четения | **~0.2-0.5s** | **~0.4-0.8s** |

Сравнение с днес: T9-pre вади тези числа с `stats/overview` (кофи + families
regex на ред + батерии decode + rules join — по-тежък) + `facets` (20 000
реда към Python) + `topology` — общо ≥ 3 пъти по-скъпо от В1 на същия полинг.

**Рискове при 7д (hours=168):**
1. **CPU на всеки полинг**: 169-кофна групировка + 110K msh индексни реда на
   10s полинг × отворени табове. Митигация: T9 полира 6/24ч на 10s, но 7д на
   30-60s (stale-гвардът вече е в кода; прописано в контракта на Т9);
   реалистично NOC = 1-2 таба.
2. **Не-msh редовете** (alerts/, deadletter/, mesh/emul legacy) в 3.1/3.4
   минават през `packets_ts_idx` с heap достъп за `topic/origin` — техният
   дял е малък (deadletters са единични, alerts са умерени); ако някога
   тръгне bridge-флуд, лостът е частичен индекс `WHERE origin LIKE 'routing:%'`
   (миграция 011+, не сега — преждевременно).
3. **Топология decode** е единствената Python-тежка част и е КАПНА на 2000
   реда —constant при всякакъв `hours`; рискът е разминаване с картата при
   отсичане, но споделеният helper гарантира СЪЩОТО отсичане и на двата
   endpoints.
4. **Пикове от връзки на ingest** (флуд при reconnect на публичен мост)
   изкривяват кофите — същото поведение има и днешната графика; не е
   регресия, не се „поправя" тук.

## 7. Тестове

### 7.1 Unit — `tests/unit/test_dashboard.py` (чисти функции)

- `_fill_hour_buckets(rows, hours, now)`: връща `hours+1` кофи; нули
  наляво; последната е текущия час; мачва броя/стойностите на stats/overview
  теста („25 buckets" — test_meta.py:70) върху една и съща входна редова
  кура (двойно изпълнение на споделената функция).
- 3-ч кофи: фиктивни редове в 09:59/10:00/11:59/12:00 → стени 09:00/12:00;
  запълване на 8 кофи с нули; последната кофа съдържа `now`.
- `_assemble_kpi`: `per_hour` закръгляне; `last_hour` = предпоследната кофа;
  `stable` брои `snr_avg=None` като НЕстабилна (−99 семантика на
  Overview.tsx:158); `nodes.total=0` при празна devices;
  `windows` = min(hours,24) за nodes/rf и фикс 24 за alarms.
- кламп: `hours=0 → 1`, `hours=999 → 168`, echo на клампнатата стойност.

### 7.2 Integration — `tests/integration/test_dashboard.py` (жив стек)

1. **Форма + нули**: `?hours=24` → 25 кофи `traffic`, 8 кофи `sent_24h`,
   `kpi.windows == {nodes:24, rf:24, alarms:24}`; `?hours=0` → 2 кофи;
   `?hours=999` → echo 168 и 169 кофи; RBAC: 401 без сесия; viewer (създаден
   през /v1/users, по рецепата на test_critical_e2e) → 200.
2. **Консистентност трафик**: `GET /dashboard?hours=24` и
   `GET /stats/overview?hours=24` едно след друго → timestamp-ите на кофите
   СЪВПАДАТ елемент-по-елемент; сумите се равняват с толеранс ≤ 30 пакета
   (емулаторът пише между двете заявки; детерминизмът е по структуры, не
   по живи числа).
3. **Консистентност аларми**: `kpi.alarms.open` ==
   `counts.alarm` от `GET /v1/critical-events?hours=24` (нула разлика —
   източникът е критичните събития, не живия трафик; детерминирано).
4. **Консистентност RF**: `kpi.rf.links == len(topology.edges)` при
   `?hours=24`; `stable <= links`; при реални ребра `stable` == броят с
   `snr_avg >= -8` пресметнат върху topology отговора (двойна проверка на
   споделения helper).
5. **Канален пончик — изолиран**: уникален канал `Dsh<rand>` + възел
   `!<hex>`; публикуват се точно N=3 пакета през `publish_mqtt` (рекетата на
   test_facets: MQTT креденшъл + sleep 2.5) → `channels` съдържа
   `{name: Dsh…, count: 3}` И `facets.channels` брои 3 за същия канал
   (двойна консистентност на тих прозорец). teardown трие тестовия възел
   по темата (правило №5).
6. **sent/failed — изолиран, детерминирано**: директен asyncpg INSERT в
   `packets` (тестовете имат PG достъп — conftest.py) на 4 реда с
   фиксиран `ts = now() - interval '90 minutes'`: 2 с
   `origin='routing:t8itest-<rand>'` + тема `alerts/t8itest/…`, 1 с тема
   `deadletter/t8itest-<rand>`, 1 контролен с `origin='local'` → кофата
   преди последната на `sent_24h`: `sent==2, failed==1`; контролният не
   се брои никъде. teardown трие 4-те реда по уникалните си теми.
   (Живият път през правило + deadletter политика е скъп за капризен тест —
   декодерният път е вече покрит от test_routing; тук тестваме
   АГРЕГАТА, изолирано.)
7. **7д допустимост**: `?hours=168` → 200, 169 кофи, отговор < 5s (мека
   горна граница срещу CI флак; реалната оценка §6 е ≤1s).

## 8. Присъда — силни / слаби страни на В1

**Силни:**
1. **Едно GET = цял дашборд**: T9 заменя 3-4 тежки заявки на 10s
   (stats/overview + facets + topology) с една ПО-ЛЕКА — нетно намаление
   на товара спрямо T9-pre, при което се появяват и числата, които днес
   липсват (изпратени 24ч по кофи, стабилни връзки, авторитетен брой
   активни възли без кап-50).
2. **Консистентност по конструкция**: кофите са същата SQL+функция като
   stats/overview, алармата — като critical-events, RF — споделен helper с
   topology; тестове №2-№4 заключват двойките.
3. **Нула ново състояние**: без миграция, без фонов процес, без кеш —
   рестарт-безопасно, изводимо от packets/devices/critical_events
   (буквално условието на Т8).
4. **Perf похватите са вече доказани**: частичният индекс 008 + двустепенна
   агрегация + split_part вместо regex — това са точните уроци от pulse
   (009), не нови експерименти.
5. **Малък, тестваем срез**: 1 route + 2 pure helper-а + 2 мини-рефактора
   (изнасяне на вече съществуващи блокове); unit тестовете са без БД.

**Слаби / рискове (и митигация):**
1. **Монолитен отговор**: бавният компонент (topology decode) defining общото
   време; частична повреда в един агрегат закъснява цялото. Митигация: 4 от
   5-те заявки са <
   250ms; ако topology стане проблем — KPI rf прозорецът се сепарира в
   собствено леко SQL (events.payload->decoded->neighbors double-check) —
   отложено, понеже днес НЕ се разминава с картата.
2. **sent под-брои спрямо routing_stats.forwarded** (bridge/HTTP
   дестинации не минават през packets; routing_executions е pruned) —
   панелът значи „препратени към локалния брокер"; честно документирано и
   в отговора (`sent_24h` семантика в notes + Т9 tooltip). Ако собственикът
   поиска всички дестинации по кофи → нова колона/материализация (В2/Т25
   територия).
3. **Пончикът не е families**: non-msh семейства (alerts/, mesh/emul) не са
   в пончика; ако T9 иска и тях — остава втори източник (stats/overview) и
   се връща част от ползата „един endpoint". Решение се взема в Т9 по
   визията на панела.
4. **7д полинг**: ~0.5-0.8s CPU на заявка; при NOC с няколко таба на 10s —
   видимо натоварване. Митигация в контракта на Т9 (7д → 30-60s полинг,
   stale-гвард съществува); лост №2 — TTL 5s кеш.
5. **Две числа за „активни възли" в прехода** (facets кап 50 vs дашборд):
   разминаване само >50 възела; T9 превключва източника изцяло, не ги
   показва едновременно.
6. **`extract(hour …) % 3` кофите са UTC**: стенен часовник UTC, не локално
   време на браузъра — етикетите на Т9 се форматират от ISO timestamp-а
   (както днес `toLocaleTimeString`), визуално без разлика; отбелязано за
   честност.

**Кога В1 НЕ е правилният избор:** при нужда от исторически сравнения
(седмица срещу седмица), при >500K пакета/24ч (тогава rollup таблица /
materialized view — В2 стил), или ако Т9 реши да ползва ДРУГИ периоди за
различните панели едновременно (В2: разделени endpoints с независими
`hours`). За среза „дашборд на живо, 6/24/7д, от съществуващите данни" В1
е с най-малко движещи се части и с най-добра консистентна история с
натоварването, което T9-pre вече генерира.
