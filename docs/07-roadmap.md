# MeshGate — roadmap (фази и условия за преминаване)

Правило: фаза не се затваря без (а) тестове на завършените модули,
(б) чиста инсталация по документацията, (в) обновен `AGENTS.md` статус + commit.

## Продуктова посока (от собственика, октомври 2026)

MeshGate да е **максимално удобен и иновативен** за:
1. **Мрежово рутиране Meshtastic ↔ MeshCore ↔ външни MQTT сървъри** — правила,
   дедупликация, трансформация на съобщения между двете mesh мрежи и външни брокери
   (настоящият bridge engine с allow/deny + dedupe + loop prevention е основата).
2. **Мониторинг + автоматизация с известия**: имейл, Telegram, WhatsApp (и др.) при
   аларми/събития.
3. **Home automation** — Home Assistant / Zigbee2MQTT интеграция след горното.

## Фаза 0 — Основа ✅ (имплементирана)

Работеща инфраструктура + най-малкият end-to-end slice: Docker Compose
(EMQX 5.8.8, PostgreSQL 16.9, FastAPI, React, Traefik v3.7.14), автентикация на
клиентите (built-in DB + ACL deny-by-default), ingestion → packets/events,
Packet Explorer с live WebSocket, мостове с правила, backup/restore,
модулни (17) + интеграционни (11) теста + e2e приемъчен скрипт (`deploy/e2e.sh`).

## Фаза 1 — Завършване на MVP конзолата

- Broker Management екрани в пълен обем (клиенти, subscription-и, тестова публикация).
- Профили: UI за прилагане/diff/rollback (API-то вече е налице).
- Потребители/роли екран; audit преглед.
- **Gate:** приемъчният checklist минава автоматизирано + ръчно от UI.

## Фаза 2 — Routing Rules MVP (R1)

Ядро на продуктовата посока: **Routing Rules Editor** по концепцията от
`docs/concept/` (MeshGate.docx), планът е в `docs/09-routing-rules-plan.md`.

- Версиониран JSON модел на правила (`routing_rules`, `_versions`, `_executions`,
  `_stats`); topic include/exclude + payload условия; трансформации (topic
  template, set/remove полета); дестинации локален брокер / bridge; errorPolicy.
- Deterministic engine с пълен execution trace; dry-run без публикуване;
  loop prevention чрез `mg_origin=routing:<id>` (наследено от bridge engine).
- UI: страница Routing Rules — wizard в 5 стъпка с live проверка срещу реални
  съобщения + шаблони; лист с броячи; версии + rollback.
- **Gate:** приемъчните критерии 1–12 от `docs/09-routing-rules-plan.md` §8
  минават автоматизирано (модулни + интеграционни + e2e §11).

## Фаза 3 — Mesh: Meshtastic + Packet Explorer (пълен)

- Meshtastic адаптер по официалните protobuf дефиниции и документираното MQTT поведение.
- Decoder registry (регистрируеми декодери; грешка → raw + причина).
- Devices & Mesh екран, телеметрия, позиции (филтри по подразбиране!), топология.
- VictoriaMetrics навлиза (ADR-003): метрики + ECharts графики; retention отделен.
- Аларми (rules/alert engine): IF–THEN върху events → alerts.
- **Gate:** жив източник на пакети (реално устройство или recorded stream) + графики.

## Фаза 4 — Routing reliability (R2) + Visual editor (R3)

- R2: retry/queue/backpressure per destination, dead-letter + повторно
  изпращане, метрики per rule, лимити, Rule Groups, webhook дестинация,
  bridge-като-source (входящо рутиране, изключено по подразбиране).
- R3: визуален canvas редактор (React Flow — след ADR): palette с 6-те блока от
  концепцията, Router/Branch, import/export; компилира към същия JSON модел —
  wizard-ът остава бързият път.
- Bidirectional връзки (двойно потвърждение), TLS verify, креденшъли, retry/health.
- **Gate:** провалена дестинация не спира останалите; canvas-правило се
  изпълнява еднакво с wizard-правило (property тест); отказ на външна връзка
  не руши локалния брокер.

## Фаза 5 — Автоматизация, известия и интеграции

- **Известия: имейл (SMTP), Telegram (Bot API), WhatsApp** — notification адаптери
  към alert engine + Node-RED; канал-политика (кое събитие накъде).
- Node-RED контейнер през Admin API + вграждане с отделна автентикация (ADR-004).
- Home Assistant MQTT Discovery + Zigbee2MQTT + generic webhooks; explicit state.
- Automation екран: flows статус, история на изпълнения, известия.
- **Gate:** провалена интеграция/канал не спира платформата (тест).

## Фаза 6 — Product readiness

- MeshCore адаптер (документиран протокол — без предполагане на еквивалентност с Meshtastic).
- Плъгин SDK (декларативен), права по роли финал, лицензена таблица на всички зависимости.
- Документация за крайния потребител, миграции при ъпгрейд, тестове при отказ на
  отделни услуги, reproducible deployment от чиста машина.

## Текущо състояние

- **Phase 0 имплементирана** — работещ стек + тестове (виж `AGENTS.md`).
- **Phase 1 почти завършена** — конзолата е пълна; чака преглед от собственика.
- **Следваща: Фаза 2 (R1 Routing MVP)** — планът е контракт в
  `docs/09-routing-rules-plan.md` (адаптация на концепцията MeshGate.docx).
