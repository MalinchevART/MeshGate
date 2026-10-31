# MeshGate — план: Routing Rules Editor (адаптация на концепцията от MeshGate.docx)

Източник: `docs/concept/MeshGate-routing-concept.docx` (оригиналът е пренесен тук,
текстът е извлечен в `docs/concept/extracted-text.txt`, дизайн-референциите — в
`docs/concept/media/image1..7.jpeg`). Този документ е контракта за имплементация
(правило 1 в `AGENTS.md`): мапва концепцията върху наличния код и фиксира
решенията, включително целенасочени отклонения, които правят решението
**по-практично и по-интуитивно** от първоначалния дизайн в документа.

## 1. Какво вече имаме и се преизползва

Концепцията не тръгва от нулата — значителна част от инфраструктурата вече
съществува и е доказана с тестове:

| От концепцията | Налично в MeshGate днес |
|---|---|
| Deterministic engine + trace | `apps/api/app/bridge/rules.py` (чисти функции, `Decision` с причина) + `_record` в `bridge_events` |
| Topic филтри include/exclude | `mqtt_match` + allow/deny правила по bridge |
| Дедупликация | `DedupeCache` (TTL 60 s) в bridge engine |
| Loop prevention | `mg_origin` user property (MQTТ 5) + филтър в ingest/bridge |
| Rate limiting | `SlidingWindowLimiter` по правило |
| Dry-run / симулация | `POST /v1/bridges/dry-run` + тест-бокс в Bridges UI |
| Версии + rollback | Profiles: `profile_versions`, publish/apply/rollback с потвърждение |
| RBAC + audit | `require()` фабрика, roles viewer/operator/admin, `audit()` журнал |
| Дестинации навън | Bridge клиенти (paho v5, reconnect backoff, health, броячи) |
| Тестови данни | 6- възлов emulator (телеметрия/позиции/съобщения) + remote-broker профил |

Изводът: **Routing Rules е обобщение на bridge engine**, а не нова подсистема.
Мостът става един от типовете дестинация; правилата се оценяват за всяко
входящо съобщение от локалния брокер (по-късно и от mesh адаптерите).

## 2. Ключови решения (вкл. отклонения „по-практично и по-интуитивно")

**D1. Wizard-first, canvas-later (главното отклонение).**
Документът залага 4-зонов визуален редактор (palette / canvas / properties /
test) като основен интерфейс. Това е мощно, но скъпо за изграждане и
непосилно за бързото правило „тези теми → онзи брокер", което е 90 % от
реалната употреба. Решение: основният интерфейс е **линеен wizard в 5 стъпки**
(Източник → Условия → Трансформация → Дестинации → Тест & Публикуване), а
визуалният canvas редактор идва по-късно (Фаза R3) за сложни multi-branch
правила. Същият JSON модел стои под двата интерфейса — добавянето на canvas
не променя engine-а.

**D2. Шаблоните са входна точка, не екран.**
„Създай правило" започва с избор от готови шаблони — всеки е предварително
попълнен wizard. Потребителят вижда какво е възможно още на първия екран,
вместо да гледа празна форма. Seed шаблони (сценариите на собственика,.env-независими):

- **„Ниска батерия → аларма"** — payload условие `$.telemetry.battery lt 20`,
  изход `alerts/battery/{device}` (локален брокер, retain).
- **„Копирай зона към външен брокер"** — topic include `mesh/+/up` → bridge
  дестинация със същата тема (нужен е създаден bridge).
- **„Изключи частни съобщения"** — exclude `mesh/+/priv` (предпазен шаблон).
- **„Всичко към архив"** — include `#` → локална тема `archive/{topic}` (P1).
- **„Съвпадащи канали → мост"** *(собственик)*: девайс в една мрежа/честота и
  девайс в друга, каналите съвпадат → двупосочно препращане между тях само по
  съвпадащия канал (Meshtastic↔MeshCore идва с адаптерите; при локални теми е
  налично още в R1: `mesh/{netA}/{ch}/...` → `mesh/{netB}/{ch}/...`).
- **„Канал → канал"** *(собственик)*: пренасочване на трафика от един канал
  към друг (remap на канала в темата, без промяна на payload).
- **„Канал → обществен брокер"** *(собственик)*: вземи съобщенията от даден
  канал и ги препрати към публичен MQTT брокер (bridge дестинация; изключено
  по подразбиране, вкл. с изрично потвърждение).

По-късни шаблони: Home Assistant discovery, n8n webhook, известия
(Telegram/имейл) — когато съответните дестинации станат реални (Фаза 5).

**D3. Live тест на всяка стъпка, не само отделен панел.**
Всяка wizard стъпка показва **реални последни съобщения** от базата и дали
те минават през текущата конфигурация (match/no-match с причина). Тестът не
е етап в края, а постоянен спътник — грешката се хваща там, където се прави.
Финалната стъпка пази пълния execution trace от концепцията.

**D4. Еднозначен версиониран JSON модел като единствен източник на истината.**
Приема се моделът от §7 на концепцията (виж т. 3 по-долу). Canvas-ът (R3) и
wizard-ът са само различни изгледи към него; import/export на JSON е валидиран
начин за копиране на правила между инсталации.

**D5. Trace навсякъде.**
Всяко решение на engine-а се записва със стъпки и причина (както вече правим
в `bridge_events`): защо е match-нато, кой path е взет, каква трансформация е
направена, до кои дестинации е изпратено, каква е грешката при провал.
Празният журнал или „само броячи" не се приемат.

**D6. Без нови Python зависимости в P0.**
Payload условията ползват **собствен мини-path парсер** (`$.a.b.c`, `$.items[2]`,
без wildcards) вместо `jsonpath-ng`. Причина: P0 от концепцията изисква само
прост path достъп; пълният RFC 9535 subset се добавя с ADR само ако се
наложи от реални правила. React Flow (npm) се разглежда чак в R3 — с ADR.

**D7. Safe by default се наследява.**
Новите правила се създават **disabled**; публикуването на версия е отделно
действие; изходящите дестинации (bridge) се отказват при enable на самия
bridge (съществуващата логика с `confirm_risky`); loop marker-ът `mg_origin`
се слага на всяко изходно съобщение и engine-ът не обработва съобщения,
носещи маркер на същото правило.

**D8. Навигацията се разширява поетапно, без празни страници.**
Целевата структура от концепцията (Dashboard, Brokers, Bridges, Routing
Rules, Automation, Monitoring, Integrations, Security) се въвежда когато
модулите зад нея са реални. Сега се добавя само **Routing Rules**; не се
рендват секции-местопълнители.

## 3. Модел на данните и JSON схема

Нови таблици (миграция в `apps/api/migrations/`):

```sql
routing_rules (
  id uuid PK, name text UNIQUE NOT NULL, description text,
  enabled boolean NOT NULL DEFAULT false,
  priority int NOT NULL DEFAULT 100,
  execution_mode text NOT NULL DEFAULT 'first_match',  -- first_match | all_match
  definition jsonb NOT NULL,            -- текуща публикувана версия (денормализирана)
  draft jsonb,                          -- незапазено-като-версия редактирано състояние
  current_version int NOT NULL DEFAULT 0,
  created_by text, created_at timestamptz DEFAULT now(), updated_at timestamptz
)
routing_rule_versions (
  rule_id uuid FK ON DELETE CASCADE, version int,
  definition jsonb NOT NULL, note text, published_by text, published_at timestamptz,
  PRIMARY KEY (rule_id, version)
)
routing_executions (                    -- журнал: последните изпълнения на правило
  id bigserial PK, rule_id uuid FK, ts timestamptz DEFAULT now(),
  input_topic text, decision text,      -- match_forward | no_match | error | skipped_disabled
  steps jsonb, error text, duration_ms int
)
routing_stats (                         -- броячи за лист-изгледа (O(1) четене)
  rule_id uuid PK, matched bigint DEFAULT 0, forwarded bigint DEFAULT 0,
  errors bigint DEFAULT 0, last_fired_at timestamptz
)
```

JSON дефиниция на правило (контрактът,validated с Pydantic):

```json
{
  "id": "uuid",
  "name": "Ниска батерия → аларма",
  "enabled": false,
  "priority": 100,
  "executionMode": "first_match",
  "source": { "type": "mqtt", "broker": "local", "topicFilter": "mesh/+/up" },
  "conditions": {
    "topic": { "include": ["mesh/+/up"], "exclude": ["mesh/+/priv"] },
    "payload": {
      "mode": "all",
      "terms": [ { "path": "$.telemetry.battery", "op": "lt", "value": 20 } ]
    }
  },
  "transform": {
    "topicTemplate": "alerts/battery/{topic_tokens[2]}",
    "setFields": { "severity": "warning" },
    "removeFields": ["raw"],
    "addEnvelope": false
  },
  "destinations": [
    { "id": "uuid", "type": "mqtt", "target": "local",
      "topicTemplate": "alerts/battery/{topic_tokens[2]}", "qos": 1, "retain": false }
  ],
  "errorPolicy": {
    "onDestinationFailure": "continue",
    "retry": { "max": 2, "backoffMs": 1000 },
    "deadLetter": true
  }
}
```

Оператори за payload terms (P0): `eq, ne, gt, gte, lt, lte, contains, exists`.
`executionMode`: `first_match` спира оценката след първото match-нато правило
със същия source (подрежда се по priority), `all_match` изпълнява всички
match-нати правила. Дестинации тип `webhook` са P1/P2 (вж. фазите).
*Бележка: wire форматът на API е snake_case (`topic_filter`, `execution_mode`,
`set_fields`…), консистентен с останалите MeshGate endpoint-и; схемата горе е
логическият модел.*

## 4. Engine архитектура

Нов пакет `apps/api/app/routing/`:

- `model.py` — Pydantic модел на дефиницията (валидация на схемата отгоре).
- `match.py` — чисти функции: `topic_matches(include, exclude, topic)`,
  `payload_matches(terms, mode, payload_doc)` + мини-path парсер (`$.a.b`,
  `$.arr[0]`); несъществуващ path → term не минава (и се отразява в trace).
- `transform.py` — `apply_transform(defn, ctx)`: topic template с
  `{topic_tokens[n]}` и `{field:path}`; set/remove полета; envelope режим
  (оригиналът в `original`, метаданни отгоре). Лимити: ≤ 32 KB payload,
  ≤ 50 KB резултат, ≤ 5 ms на трансформация.
- `engine.py` — `evaluate(rules, message) -> RoutingOutcome` (списък от
  per-rule `Trace(steps[])`, изходни съобщения); `publish(outcomes)` разпраща
  през наличните MQTT клиенти (локално — през ingest клиента; bridge — през
  bridge клиентите). Всяко изходно съобщение носи `mg_origin = routing:<rule_id>`.
- `service.py` — зареждане в памет + reload при промяна (през event bus-а),
  запис в `routing_executions` (rolling, последните ~200 на правило + всички
  грешки), актуализация на `routing_stats`, dead-letter опашки при изчерпани
  retry-та.

Интеграция: `ingest/service.py` след записа на пакета вика
`routing.handle_local(topic, payload, props)` — както днес вика
`bridge.handle_local`. Bridge engine остава непокътнат (тестовете му се
пазят); в по-късна фаза се обединява с routing engine, когато bridge
правилата се презентират като rules с destination.

## 5. API контракт (v1)

| Метод | Път | Роля | Описание |
|---|---|---|---|
| GET | `/v1/routing/rules` | viewer | списък + броячи + last_fired |
| POST | `/v1/routing/rules` | admin | създаване от пълен JSON или `template_id` (created disabled) |
| GET/PATCH | `/v1/routing/rules/{id}` | viewer/admin | четене / редакция на draft |
| POST | `/v1/routing/rules/{id}/publish` | admin | публикува draft като нова версия |
| POST | `/v1/routing/rules/{id}/rollback` | admin | връща `{"version": n}` от `routing_rule_versions` |
| POST | `/v1/routing/rules/{id}/enable` `/disable` | operator | включване/изключване |
| GET | `/v1/routing/rules/{id}/versions` | viewer | версии с note/author |
| GET | `/v1/routing/rules/{id}/executions` | viewer | журнал с филтри |
| POST | `/v1/routing/dry-run` | operator | `{definition?, rule_id?, topic, payload}` → пълен trace, **без публикуване** |
| GET | `/v1/routing/templates` | viewer | шаблони (seed, като profiles) |
| GET | `/v1/routing/recent-topics` | viewer | последни реални теми (за live подсказки в wizard-а) |

Всяко mutation: audit запис (както при bridges/profiles).

## 6. UI план

**Фаза R1 — Routing Rules страница (wizard):**

- Лист с правила: име, статус, приоритет, matched/forwarded/errors, последно
  изпълнение; действия edit / enable-disable / rollback / delete;
  „Създай правило" → Шаблон или Празно.
- Wizard, 5 стъпки (D1–D3): всяка стъпка с live проверка срещу реални теми/пакети
  от DB; последна стъпка — dry-run с пълен trace (стъпки, причините, изходното
  съобщение) върху реален последен пакет или свое съдържание; Publish version.
- Detail изглед: JSON (read-only, с copy), версии, executions журнал, броячи.
- Страницата влиза в навигацията след „Bridges & Routes".

**Фаза R3 — Visual canvas редактор (по дизайн-референциите):**

- React Flow (след ADR): лява palette с 6-те блока от концепцията (Source,
  Topic Filter, Payload Filter, Transform, Router/Branch, Destination),
  canvas с връзки, дясно properties панел, долу Test панел — визуалният език
  от `docs/concept/media/`.
- Canvas-ът компилира към същия JSON (D4); wizard-ът остава бързият път.
- Router/Branch блок и multi-output се появяват тук (P1 от концепцията).

## 7. Фази и гейтове

| Фаза | Обхват | Gate |
|---|---|---|
| **R1 — Routing MVP** | модел/миграции, engine + trace, dry-run, wizard UI, шаблони, versions/rollback, RBAC/audit, тестове | приемъчните критерии от т. 8 минават автоматизирано |
| **R2 — Operational reliability** | retry/queue/backpressure per destination, dead-letter + повторно изпращане, метрики per rule (броячите вече се събират), лимити, Rule Groups, webhook дестинация, bridge-като-source (входящо рутиране, default off) | провалена дестинация не спира останалите; задръстване не руши платформата |
| **R3 — Visual editor** | canvas (React Flow, ADR), Router/Branch, import/export | правило, създадено само от canvas, се изпълнява еднакво с wizard-правило (property тест) |
| **M — Mesh интеграции** | Meshtastic адаптер като source + decoder registry (бивша Фаза 2), MeshCore адаптер (след документиран протокол) | жив mesh източник рутира по тип пакет/съдържание |
| **A — Автоматизация** | известия имейл/Telegram/WhatsApp като destination типове, Node-RED връзка, scheduled правила | провалена интеграция не спира платформата |

`docs/07-roadmap.md` се пренарежда съответно (R1 идва веднага след завършването
на Фаза 1 — преди Meshtastic адаптера, защото работи върху наличния emulator
поток и е ядрото на продуктовата посока).

## 8. Приемъчни критерии (адаптация на §10 от концепцията)

1. Правило се създава от wizard с шаблон, без документация, ≤ 3 мин.
2. Topic include филтър препраща само съответстващи теми (проверимо в DB + trace).
3. Exclude има приоритет над include.
4. Payload условие (`$.telemetry.battery lt 20`) match-ва реален emulator пакет.
5. Transform подменя темата по template и добавя поле (in → out в trace).
6. Едно правило с две дестинации (локална + remote-broker от test профила) доставя и на двете.
7. Dry-run връща trace със стъпки + причини, без да публикува нищо.
8. Disabled правило не изпълнява (decision=skipped_disabled в журнала).
9. Publish v2 → rollback v1 възстановява поведението (проверимо по изходни теми).
10. Цикъл: съобщение с `mg_origin=routing:<id>` не се обработва повторно от същото правило.
11. Провал на една дестинация не спира другите (`errorPolicy.continue`); грешката е в журнала.
12. viewer: 403 на POST/PATCH; operator: може enable/disable + dry-run, не и publish; всичко с audit запис.

Модулни тестове: match/transform/path парсер/evaluate trace (чисти функции).
Интеграционни: критерии 2–12 срещу реалния стек (emulator + remote-broker).
`deploy/e2e.sh` се разширява с routing секция (§11).

## 9. Рискове и отбелязани отлагания

- **Canvas редакторът е най-скъпата част** — затова е последен (R3) и не блокира
  engine-а (D1). Ако React Flow не пасне, canvas-ът се редуцира до read-only
  визуализация на правило.
- **Payload условия върху недекодирани (binary) съобщения**: term-ът не минава,
  причината се записва; reliable payload филтри идват с decoder registry (Фаза M).
- **Between-rules race при first_match**: оценката е единична нишка per
  message (asyncio) — няма нужда от заключвания в P0.
- Router/Branch блокът и разклоненията съзнателно са извън R1 — те са P1 от
  самата концепция и се проектират с canvas-а.
