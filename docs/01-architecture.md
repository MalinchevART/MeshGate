# MeshGate — архитектура

Обвързващ документ. Промяна → нов ADR или ревизия с причина.

## 1. Цел и принципи

MeshGate е самостоятелна платформа за управление на MQTT инфраструктура, наблюдение
на mesh мрежи, контролирано свързване между брокери и автоматизация. Принципи:

1. **MQTT трафикът не минава през Web UI / API.** EMQX обработва съобщенията директно;
   Core API управлява конфигурация и чете състояние. Рестарт на UI/API не прекъсва
   брокера или exchange-а между устройствата.
2. **Реални данни или ясно обозначен празен/demo статус.** Никога mock данни, представени
   за живи.
3. **Safe by default.** Изходящото препращане е изключено, докато няма изрична политика.
   Лични съобщения, локации и неизвестни payload типове не се препращат по подразбиране.
4. **Всичко оцелява рестарт.** Конфигурация, събития и метаданни — в PostgreSQL с миграции;
   томовете на Docker са именувани и backup-вани.
5. **Малки проверими стъпки.** Фаза не се затваря без тестове и чиста инсталация
   (`docs/07-roadmap.md`).

## 2. Компоненти

```
                        ┌─────────────────────────────────────────────┐
                        │                Docker Compose               │
  интернет ── 80/443 ──▶│  Traefik v3 (единствен публичен вход, TLS)   │
                        │    │ web (React statics)                    │
                        │    │ /api → FastAPI (Core API)              │
                        │    │ /api/ws → WebSocket live потоци        │
                        │    │ /nodered → (Фаза 4, отделна auth)      │
                        └────┼────────────────────────────────────────┘
                             │ вътрешна compose мрежа (без публикувани портове)
   ┌─────────────┐   ┌──────▼──────┐   ┌──────────────┐   ┌──────────────────┐
   │ EMQX 5.8.x  │◀──│ FastAPI Core│──▶│ PostgreSQL 16│   │ VictoriaMetrics  │
   │ broker      │   │ - config/   │   │ config,      │   │ (Фаза 2)         │
   │ :1883/:8883 │   │   RBAC,     │   │ devices,     │   │ time-series      │
   │ публикувани │   │   audit,    │   │ events,      │   │ метрики          │
   │ за MQTT     │   │   ingest*,  │   │ packets,     │   └──────────────────┘
   │             │   │   bridge*   │   │ alerts,      │   ┌──────────────────┐
   │ dashboard   │   │ - adapter   │   │ audit, users │   │ Node-RED         │
   │ :18083      │   │   EMQX API  │   └──────────────┘   │ (Фаза 4, Admin   │
   │ ВЪТРЕШЕН    │   └─────────────┘                      │   API + AdminAuth)│
   └─────────────┘                                        └──────────────────┘
        ▲   ▲
        │   └── ingestion модула е MQTT клиент (+ wildcard subscription)
        └── MQTT устройства и клиенти (външни/локални)
```

`*` ingestion и bridge engine стартират като модули в Core API процеса (Фаза 0–3);
отделят се в собствени сервиси само при конкретна необходимост (натоварване изолация).

## 3. Логически модули (съответствие с изискваните 11)

| # | Модул | Къде живее (MVP) | Отговорност |
|---|-------|------------------|-------------|
| 1 | Web UI | `apps/web` (React+TS+Vite, статика през Traefik) | конзола, тъмна тема, ECharts |
| 2 | Core API & конфигурация | `apps/api` (FastAPI) | REST CRUD, профили, валидация, WebSocket/SSE |
| 3 | MQTT broker интеграция | `apps/api` + EMQX REST API v5 през adapter | статус, клиенти, теми, ACL, статистика |
| 4 | Приемане и нормализация | `apps/api` (ingestion модул, MQTT клиент) | wildcard $share subscription → normalized events |
| 5 | Протоколни адаптери | `apps/api/adapters/` (generic MQTT първи) | discovery, last-seen, телеметрия |
| 6 | Registry на декодери | `apps/api/decoders/` | регистрируеми декодери; грешка → raw + причина |
| 7 | Bridge и routing engine | `apps/api` (bridge модул) | посоки, mappings, allow/deny, rate limit, loop prevention |
| 8 | Rules и alert engine | `apps/api` | аларми по правила върху events (IF–THEN, без визуален редактор до Фаза 4) |
| 9 | Event/metrics storage | PostgreSQL (+ VictoriaMetrics от Фаза 2) | събития, метаданни, retention |
| 10 | Интеграции и плъгини | `apps/api/integrations/` | Node-RED (Фаза 4), HA Discovery, Z2M, webhooks; state = explicit |
| 11 | Auth/authz/аудит | `apps/api` + DB | сесии, RBAC (viewer/operator/admin), audit log |

## 4. Поток на данните

### 4.1 Входящ пакет (нормализиране и съхранение)

```
MQTT клиент ──PUBLISH──▶ EMQX ──▶ ingestion (MQTT subscriber, # филтър)
   → разпознаване на адаптер (по тема/протокол)
   → декодер (по payload тип) или запазване на raw + decode_status=failed
   → INSERT: packets (метаданни+payload), events (нормализирано), devices (last_seen)
   → push в WebSocket буфер → Packet Explorer (без презареждане)
```

Буферът на WebSocket е ограничен (последни N пакета + backpressure); историята се
тегли с пагинация от DB, не се зарежда в браузъра.

### 4.2 Управление на брокера

```
UI ──REST──▶ Core API ──EMQX REST API v5 (API key, ВЪТРЕШНА мрежа)──▶ EMQX
```
API key-ът на EMQX съществува само в Core API контейнера. Браузърът получава само
прекарани (sanitized) резултати.

### 4.3 Bridge (Фаза 3, ядро на безопасността)

```
ingestion ─▶ bridge engine ─▶ правила (allow/deny по тема/тип/проход)
   ├─ REJECT → bridge_events(причина) + брояч
   └─ ACCEPT → rate limit → loop check (origin marker/dedupe) → publish навън
```

## 5. Мрежови зони и портове

| Зона | Порт | Публикува ли се | Бележка |
|------|------|-----------------|---------|
| Публичен (Traefik) | 80/443 | да | единствен вход за web/api; TLS |
| MQTT listener | 1883, 8883 | да, изрично | устройства; per-device креденшъли + ACL |
| EMQX Dashboard/API | 18083 | **не** | само през Traefik с автентикация |
| PostgreSQL | 5432 | **не** | вътрешна мрежа |
| VictoriaMetrics | 8428 | **не** | вътрешна мрежа (Фаза 2) |
| Node-RED | 1880 | **не** | само през Traefik с отделна автентикация (Фаза 4) |

Правило: нов административен порт никога не се публикува директно; минава през Traefik
с автентикация или остава вътрешен.

## 6. Жизнен цикъл и устойчивост

- Web UI е статика — рестарт = нова версия на файловете, без досег до брокера.
- Core API рестарт: ingestion губи само пакетите in-flight; EMQX (QoS≥1, persistent
  sessions) ги държи докато subscriber-ът се върне.
- Всеки контейнер има healthcheck; зависимостите са `depends_on: condition: healthy`.
- Миграциите се пускат от Core API при старт (Alembic), идемпотентно.

## 7. Какво MeshGate НЕ е

- Не е Home Assistant заместител — интегрира се с HA чрез MQTT Discovery.
- Не е визуален редактор — Node-RED се вгражда като отделна autентикирана компонента.
- Не предполага еквивалентност Meshtastic ↔ MeshCore — отделни адаптери, отделни
  декодери, документирани по протокол (Фаза 2/5).
- Не разпространява EMQX 5.9+ (BSL) — закрепено в ADR-001.
