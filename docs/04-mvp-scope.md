# MeshGate — MVP обхват

MVP = най-малкият работещ slice, който минава **целия** приемъчен checklist (по-долу),
инсталируем от чиста машина. Всичко извън този списък е out-of-scope за MVP и има фаза
в `docs/07-roadmap.md`.

## В обхват (MVP)

1. **Инфраструктура (Фаза 0):** Docker Compose — EMQX 5.8.x, PostgreSQL 16, FastAPI
   (Core API), React UI през Traefik v3; именовани томове; healthchecks; `.env.example`.
2. **Auth/RBAC/аудит:** вход, роли viewer/operator/admin, audit log на всяка конфигурационна
   промяна и операция; bootstrap на първи admin от `.env` (после се маха от `.env`).
3. **Broker Management (Фаза 1):** статус, клиенти, subscription-и, теми, трафик
   статистика, тестова публикация, per-device MQTT креденшъли + ACL през adapter-а.
4. **Ingestion + Packet Explorer (generic MQTT):** wildcard subscription → packets/events
   в DB; live WebSocket поток; история с филтри/пагинация; raw + decoded (generic JSON/
   текст декодер) изгледи; retention задача.
5. **Минимален Bridge engine:** една outbound връзка, allow/deny правила по тема,
   rate limit, loop prevention (origin marker + dedupe), броячи и журнал на решенията
   с причини. Включен изрично, изключен по подразбиране. (Пълният双向/mapping engine — Фаза 3.)
6. **Профили (базово):** seed на фабричните профили като версиониран spec; прилагане с
   валидация + diff + rollback; audit. (UI пълнота — Фаза 1.)
7. **Backup/restore:** `pg_dump` процедура +_restore тест в чиста инсталация.
8. **Тестове:** pytest за adapter-а, ingestion, bridge правилата (вкл. цикли и забранени
   теми), retention; интеграционен тест вдигащ compose и минаващ checklist-а.

## Извън обхват за MVP (с фаза)

- Meshtastic/MeshCore адаптери и декодери, топология (Фаза 2)
- VictoriaMetrics и телеметрични графики (Фаза 2)
- Пълен bridge engine: bidirectional, topic mapping, payload-type филтри, TLS external
  с пълна матрица (Фаза 3 — MVP bridge е само outbound allow/deny)
- Node-RED, Home Assistant Discovery, Zigbee2MQTT, webhooks (Фаза 4)
- MeshCore, плъгин SDK, разширени RBAC екрани (Фаза 5)

## Приемъчен checklist (MVP готов ⇔ 10/10)

Проверява се автоматизирано (интеграционен тест) + ръчно от UI:

1. ☐ Системата стартира от чиста инсталация чрез Docker Compose.
2. ☐ MQTT клиент се свързва и публикува съобщение.
3. ☐ Съобщението се появява в Packet Explorer без презареждане (WebSocket).
4. ☐ Събитието се записва в базата и остава след рестарт на stack-а.
5. ☐ UI показва реалния статус на брокера и клиентите.
6. ☐ Промяна в конфигурацията се валидира и записва в audit log.
7. ☐ Неоторизиран потребител не може да променя конфигурация или да публикува
   (ACL: per-device creds, deny по подразбиране; RBAC: viewer само чете).
8. ☐ Неуспешна външна връзка (bridge) не прекъсва локалния брокер.
9. ☐ Backup може да се възстанови в нова инсталация.
10. ☐ Bridge тестовете доказват: забранени теми се блокират; цикличното препращане
    се открива и спира.

## Най-малък end-to-end slice (първа имплементационна цел)

Стартиран compose → `mosquitto_pub` публикува → ingestion записва packet+event →
UI Packet Explorer показва съобщението live → `docker compose restart` → съобщението
е все още в историята. Това е first milestone на Фаза 0 имплементацията.
