# MeshGate — API контракт (REST + WebSocket)

Обвързващо за `apps/api`. Базов път: `/api/v1`. JSON навсякъде.

## Конвенции

- Успех: `{ "data": <ресурс или списък> }`
- Грешка: `{ "error": { "code": "<machine_code>", "message": "<човешко>", "details": {} } }`
- Пагинация: `?limit=20&before=<iso8601|id>` (cursor по време/id); `limit` ≤ 200.
- Времена: ISO 8601 UTC.
- RBAC: `viewer` (четене), `operator` (+ операции: publish тест, ack, bridge toggle),
  `admin` (+ конфигурация, потребители, backup). Непосочено = viewer не може.
- Сесии: httpOnly cookie (login) или `Authorization: Bearer <token>` за програмен достъп.

## Auth

| Метод | Път | Роля | Описание |
|-------|-----|------|----------|
| POST | `/auth/login` | — | `{username,password}` → set-cookie; rate-limited |
| POST | `/auth/logout` | всяка | край на сесията |
| GET | `/auth/me` | всяка | текущ потребител + роля |

## System / health / backup

| Метод | Път | Роля | Описание |
|-------|-----|------|----------|
| GET | `/system/health` | всяка | агрегиран статус: api, postgres, broker, ingestion |
| GET | `/system/status` | viewer | версия, uptime, брой услуги, последен backup |
| POST | `/system/backup` | admin | стартира pg_dump → връща job id |
| GET | `/system/backup` | admin | списък backup-и |
| POST | `/system/backup/{id}/restore` | admin | тестов restore в нова инсталация (checklist §9) |

## Broker (прекарани данни от EMQX през BrokerAdapter — без креденшъли)

| Метод | Път | Роля | Описание |
|-------|-----|------|----------|
| GET | `/broker/status` | viewer | uptime, версии, listeners, ресурси |
| GET | `/broker/clients?connected=true` | viewer | списък клиенти (id, user, ip, connected_at, subs) |
| DELETE | `/broker/clients/{client_id}` | operator | принудително прекъсване |
| GET | `/broker/subscriptions` | viewer | списък subscription-и |
| GET | `/broker/topics` | viewer | активни теми + rates |
| GET | `/broker/stats?window=1h` | viewer | трафик: msgs/s, bytes, връзки |
| POST | `/broker/test-publish` | operator | диагностична публикация `{topic,payload,qos}` (audit) |
| GET | `/broker/credentials` | admin | per-device MQTT креденшъли (без тайни) |
| POST | `/broker/credentials` | admin | създаване + ACL; синхрон с брокера |
| DELETE | `/broker/credentials/{id}` | admin | отнемане (audit) |

## Devices

| Метод | Път | Роля | Описание |
|-------|-----|------|----------|
| GET | `/devices?protocol=&online=` | viewer | регистър: last_seen, статус, батерия, сигнал |
| GET | `/devices/{id}` | viewer | детайл + metadata/capabilities |
| GET | `/devices/{id}/observations?limit=` | viewer | времева серия (RSSI/SNR/батерия; NULL-able) |
| GET | `/devices/{id}/events?limit=` | viewer | последни събития на устройството |

## Packets (Packet Explorer)

| Метод | Път | Роля | Описание |
|-------|-----|------|----------|
| GET | `/packets?topic=&protocol=&node_id=&packet_type=&decode_status=&from=&to=&search=&before=&limit=` | viewer | история, пагинация, bounded |
| GET | `/packets/{id}` | viewer | детайл: raw (hex+текст), decoded, trace (декодери, bridge решения) |
| POST | `/packets/export` | viewer | `{format:"json|csv", filters, limit≤10000}` → job/file |

WebSocket live поток:

```
WS /api/v1/ws/packets?filter=<json>
  ← {"type":"packet","data":{id,ts,topic,protocol,node_id,packet_type,decode_status,payload_size}}
  ← {"type":"heartbeat"}     # на всеки 15 s
  → {"type":"pause"} / {"type":"resume"}
```

Буфер: последните 500 пакета на сесия; при `pause` клиентът тегли историята от REST.
SSE алтернатива: `GET /packets/stream` (EventSource) със същите събития.

## Bridges

| Метод | Път | Роля | Описание |
|-------|-----|------|----------|
| GET | `/bridges` | viewer | списък + health + броячи (forwarded/rejected/rate_limited/loops) |
| POST | `/bridges` | admin | създаване — `enabled` се игнорира при `false` по подразбиране |
| PUT | `/bridges/{id}` | admin | промяна (валидация + diff + audit) |
| POST | `/bridges/{id}/enable` | admin | изрично включване (двупосочен → двойно потвърждение) |
| POST | `/bridges/{id}/test` | admin | dry-run: `{topic,payload}` → решение + причина, без publish |
| GET | `/bridges/{id}/events?decision=&limit=` | viewer | журнал на решенията с причини |

Схема на bridge при създаване: полетата от `docs/02-data-models.md` §Bridge.
`remote_url` минава SSRF валидация (threat model §SSRF).

## Profiles

| Метод | Път | Роля | Описание |
|-------|-----|------|----------|
| GET | `/profiles` | viewer | профили + текуща версия |
| GET | `/profiles/{id}/versions` | viewer | версии |
| POST | `/profiles/{id}/validate` | admin | валидация на spec → резултати/грешки, без прилагане |
| POST | `/profiles/{id}/apply` | admin | `{version, confirm_risky}` → diff спрямо текущото, после прилагане |
| POST | `/profiles/{id}/rollback` | admin | връщане към версия (audit + diff) |

Прилагането никога не презаписва тихо: risky промени ( ACL, bridges, listeners )
изискват `confirm_risky=true`.

## Alerts / Audit / Integrations / Users

| Метод | Път | Роля | Описание |
|-------|-----|------|----------|
| GET | `/alerts?severity=&ack=` | viewer | списък; POST `/alerts/{id}/ack` (operator) |
| CRUD | `/alert-rules` | admin | правила за аларми |
| GET | `/audit?user=&action=&from=&to=&limit=` | admin | журнал (cursor пагинация) |
| GET | `/integrations` | viewer | статус по интеграция (explicit state) |
| PUT | `/integrations/{kind}` | admin | конфигурация; enable/disable (audit) |
| CRUD | `/users` | admin | потребители + роли; без изтриване на последния admin |

## Грешки (често срещани кодове)

- `unauthorized` (401), `forbidden` (403 — ролята не стига)
- `validation_failed` (422, details по поле)
- `ssrf_blocked` (422 — URL-ът е вътрешен/забранен)
- `bridge_disabled` (409), `rate_limited` (429)
- `not_found` (404), `conflict` (409)
