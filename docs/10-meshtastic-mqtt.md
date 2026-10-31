# MeshGate — Meshtastic/MeshCore по MQTT: изследване и план за автоматично разпознаване

Източници (официални, октомври 2026): meshtastic.org/docs/software/integrations/mqtt,
meshtastic.org/docs/configuration/module/mqtt, общностни guides (LocalMesh,
meshmonitor.org). Този документ е контрактът за Фаза 3 (Meshtastic адаптер) и за
готовността при свързване на публични брокери от собственика.

## 1. Meshtastic по MQTT — какво идва по жицата

### Теми (topics)

| Тема | Какво носи |
|---|---|
| `msh/<REGION>/2/e/<CHANNEL>/!<nodehex>` | protobuf `ServiceEnvelope` (текущи фирмуери; `2/e/` = версия/encrypted; преди 2.3.0 е било `/c/`) |
| `msh/<REGION>/2/json/<CHANNEL>/!<nodehex>` | JSON вариант (ако възелът е с включен JSON output) |
| `msh/<REGION>/2/json/mqtt/` | downlink: публикуваш тук → gateway възел предава в мрежата |
| `msh/<REGION>/2/map/` | map report (позиции с ограничена прецизност при default PSK) |
| канал по подразбиране | `LongFast` с PSK `AQ==` (слаб/known — затова позицията се реже до 10–16 бита) |

- REGION: `US`, `EU`, `ANZ`… или `1`/`2` на официалния брокер.
- Публичният брокер `mqtt.meshtastic.org` вече НЕ позволява `msh/#` — абонираш
  се за конкретен регион (`msh/EU/#`) или канал.
- Нулев hop на публичния сървър: не ретранслира всичко — метаданни+приоритетни типове.

### Payload — ServiceEnvelope

Protobuf (по подразбиране) или JSON. JSON полета (пример nodeinfo): `id`,
`channel` (индекс), `from` (decimal node id; 2.2.0+ unsigned), `sender`
(шестнайсетично `!hex` на gateway-а), `timestamp`, `to` (`-1` = broadcast),
`type`, `payload` (самото съобщение). Protobuf вариантът е същата структура,
но binary — декодира се с официалните .proto дефиниции.

### Типове съобщения (portnum)

Приоритетни на публичния сървър: **NodeinfoApp, TextMessageCompressedApp,
TextMessageApp, PositionApp, TelemetryApp, MapReportApp, RoutingApp**.
JSON-ват се при включен JSON output: TEXT_MESSAGE_APP, TELEMETRY_APP,
NODEINFO_APP, POSITION_APP, WAYPOINT_APP, NEIGHBORINFO_APP, TRACEROUTE_APP,
DETECTION_SENSOR_APP, PAXCOUNTER_APP, REMOTE_HARDWARE_APP.

### Ключови експлоатирани факти за MeshGate

1. **Дедупликация по packet id е задължителна** — много gateway-а препубликуват
   едно и също съобщение (вече имаме DedupeCache; ключът става `id` полето).
2. **JSON вариантът стига без protobuf декодер** — част от възлите публикуват
   JSON; P0 на адаптера се насочва към JSON + суров protobuf с честен статус
   „не е декодирано" (методата от decoder registry).
3. **Позиции с default PSK са нарочно груби** — не ги „подобряваме"; показваме
   каквото идва, с бележка за прецизност.
4. **Downlink** (`json/mqtt/`) е изход към мрежата — опасен по подразбиране:
   MeshGate го поддържа като destination тип чак с изрично потвърждение (R2+).

## 2. MeshCore по MQTT (за Фаза 6)

MeshCore мости чрез Companion App/Serial-BLE → JSON на брокера (по-четим,
друг topic layout — обикновено `meshcore/<...>` според bridge конфигурацията;
вж. github.com/ipnet-mesh/meshcore-mqtt и meshcore-dev/docs HA MQTT). Форматът
е „packet JSON" (LetsMesh-съвместим) с метаданни + payload по тип. Без
предполагане на еквивалентност с Meshtastic — собствен декодер по документация.

## 3. Автоматично разпознаване в MeshGate (дизайн)

1. **Детектор по тема** (`ingest`): `msh/+/#` → proto=meshtastic; записва
   region/channel/node от topic токените автоматично (devices вече стават по
   `!nodehex`, не по цялата тема).
2. **Декодер JSON-first**: JSON ServiceEnvelope → `type`/`portnum` →
   device_metrics (battery, SNR/RSSI от Telemetry/Nodeinfo), позиция от
   Position/MapReport, текст от TextMessage. Protobuf payload → статус
   `not_attempted` + причина (protobuf декодер е P1 на фазата).
3. **Канали в Помощника автоматично**: familyOf вече групира; за `msh/` теми
   семейството става `msh/<region>/<channel>` → етикет „Meshtastic EU — LongFast".
   Правило „съвпадащи канали между две мрежи" става буквално:
   `msh/EU_868/LongFast/#` → `msh/US/LongFast/#` (шаблонът вече съществува).
4. **Дедупликация**: Routing engine добавя втора ключалка — по Meshtastic
   packet `id` (при наличието му), не само (topic,payload).
5. **Емулатор v2**: демо възлите минават на Meshtastic-подобни теми
   (`msh/emul/2/e/LongFast/!hex...`) и JSON ServiceEnvelope payload, така че
   целият вертикал (разпознаване → правила → мониторинг → аларми) се тества
   без реално устройство. Старата схема `mesh/emul/...` се пази като legacy
   профил на емулатора.

## 4. Какво става, когато собственикът закачи публични брокери (2 броя)

Днес (без нов код): добавят се като мостове (Bridges, inbound не съществува
като посока — виж по-долу) ИЛИ по-правилно: локалният EMQX има client-и, които
публикуват в него. Реалният път: **външен bridge → локална тема** е inbound
рутиране (Фаза R2 „bridge-като-source", изключено по подразбиране). За тест
този път ще се включи с `confirm_risky` и мапинг `msh/# → msh/<брокер>/#`,
за да не се смесват двата публични източника; след това детекторът от т.3
разпознава всичко автоматично и Помощникът показва реалните канали
(напр. „Meshtastic EU — LongFast, N съобщения"). Ограничение на публичния
брокер: абонираме се за `msh/<REGION>/#`, не `msh/#`.

## 5. Фази (кое кога)

- **3a (следващо):** детектор по тема + JSON декодер + devices по `!nodehex`
  + емулатор v2 (Meshtastic-режим) + kanali в Помощника/Мониторинга.
- **3b:** protobuf декодер (официални .proto → pure-python, без тежки deps —
  ADR), дедупликация по packet id, топология от NeighborInfo/Routing.
- **R2:** bridge-като-source (inbound) с потвърждение — така се закичат
  публичните брокери за тест.
- **6:** MeshCore декодер + междумрежов мост по съвпадащи канали.
