# MeshGate — модул за външна интеграция (контролиращи връзки)

Този модул е начинът, по който MeshGate се вгражда като **компонент в по-голям
мрежов проект** (централен NMS, NOC платформа, друго управление на инфраструктура) —
без достъп до вътрешната база, без споделяни сесии, с изрични права.

## Модел на интеграция

MeshGate е "управляван компонент": външната система чете състояние и потоци от
него и може да му изпраща команди в рамките на изрично выдадени права.

```
┌─────────────────────┐        Bearer API token          ┌──────────────────────┐
│  Външна система     │ ────────────────────────────────▶ │  MeshGate            │
│  (NMS / NOC / …)    │   REST: статус, устройства,       │                      │
│                     │        история, publish           │  /api/v1/integration │
│                     │   WS:  live поток от пакети       │                      │
└─────────────────────┘                                   └──────────────────────┘
```

## Контролиращи връзки (кой как управлява)

| Връзка | Посока | Механизъм | Ограничение |
|--------|--------|-----------|-------------|
| Наблюдение на статус | външна → MeshGate | `GET /api/v1/integration/status` | read-only; брокер + мостове + здраве |
| Списък устройства | външна → MeshGate | `GET /api/v1/integration/devices` | read-only, bounded (≤200) |
| История на пакети | външна → MeshGate | `GET /api/v1/integration/packets` | bounded (≤200), филтри |
| Live поток | MeshGate → външна | `WS /api/v1/integration/ws/packets?token=…` | push; heartbeat 15 s; bounded buffer |
| Команден publish | външна → MeshGate | `POST /api/v1/integration/publish` | само при `can_publish` и само в теми от `allowed_topics` (MQTT wildcards) |
| Издаване/отнемане на токен | MeshGate admin | `POST/DELETE /api/v1/integration/tokens` | потребителска сесия admin + audit |

Всяко действие през токен се записва в `audit_log` с `action=integration.publish`
(и съответните за управление на токени). Токенът се показва **веднъж** при създаване;
в базата стои само SHA-256 хеш.

## Автентикация

- `Authorization: Bearer mg_…` за REST; `?token=mg_…` за WebSocket (WS не носи
  заглавки от EventSource/по-стари клиенти).
- Токенът НЕ е потребителска сесия: няма достъп до админ API-тата, само до
  изброените по-горе ресурси.
- Отнемане: изтриване на токена от admin UI/API → незабавно недействителен.

## Формати (кратък контракт)

- Статус: `{"data": {"app":"meshgate", "broker": {...}|null, "bridges":[{name,health,counters}], "ts":"…"}}`
- Пакет (live): `{"type":"packet","data":{"ts","topic","packet_type","decode_status","payload_size","origin"}}`
- Publish: заявка `{"topic":"ext/node1/data","payload":"текст"}` → `{"data":{"ok":true}}`;
  отказ: 403 `forbidden` с причина; 401 без/с невалиден токен.
- Грешки: `{"error":{"code","message"}}` — кодовете са стабилни за парсене.

## Правила за вграждане

1. Външната система не чете базата на MeshGate директно — само през този API.
2. Ако ѝ трябва пълен пакетен поток с payload — минава през собствен абонат с
   per-device MQTT креденшъли (виж `docs/03-api-contracts.md` §Broker), не през
   integration токен (той дава само метаданни + bounded история).
3. Всяка нова "контролираща връзка" се добавя тук и в `docs/03-api-contracts.md`
   преди имплементация — контрактът е публичната граница на модула.

## Пример (curl)

```bash
# admin създава токен (само веднъж се вижда!)
curl -X POST https://meshgate.local/api/v1/integration/tokens \
  -H "Cookie: mg_session=…" -H 'Content-Type: application/json' \
  -d '{"name":"central-nms","can_publish":true,"allowed_topics":["ext/+/data"]}'

# външната система: статус
curl -H "Authorization: Bearer mg_…" https://meshgate.local/api/v1/integration/status

# външната система: публикува команда в позволена тема
curl -X POST https://meshgate.local/api/v1/integration/publish \
  -H "Authorization: Bearer mg_…" -H 'Content-Type: application/json' \
  -d '{"topic":"ext/node12/data","payload":"{\"cmd\":\"reboot\"}"}'
```
