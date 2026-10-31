# ADR-005: Meshtastic protobuf декодер — минимален pure-python wire парсер

- Статус: Прието
- Дата: 2026-10-17

## Контекст

Фаза 3b (docs/10-meshtastic-mqtt.md §5) изисква декодиране на бинарните
ServiceEnvelope payloads, с които реалните Meshtastic gateways публикуват по
MQTT (теми `msh/<region>/2/e/...`). Официалният формат е protobuf по
`meshtastic/mqtt.proto` (ServiceEnvelope → MeshPacket → Data). Нужни са само
подмножество от полетата: тип пакет (portnum), източник (from → `!hex`),
текст (TEXT_MESSAGE payload е суров UTF-8), батерия (Telemetry.DeviceMetrics),
позиция (Position.latitude_i/longitude_i), SNR/RSSI и packet id за
дедупликация. Платформата е zero-heavy-deps (FastAPI + asyncpg + aiomqtt) и
всяка нова зависимост тежи на образа и поддръжката.

## Решение

Ръчен минимален protobuf wire парсер в `apps/api/app/ingest/mesh_decode.py`
(`_read_varint`, `_parse_fields`, `decode_envelope_protobuf`) — само varint /
fixed32 / fixed64 / length-delimited, без групи (groups са deprecated в
proto3 и не се срещат в Meshtastic). Свойствата:

- Чист Python (stdlib `struct`), нула нови зависимости.
- **Два wire формата на MeshPacket** (номерата на полетата се сменят във
  firmware 2.6 — потвърдено с реален трафик от публичен брокер, октомври
  2026): fw 2.6+ (`decoded`=4, `encrypted`=5, `id`=6 fixed32, `rx_snr`=8,
  `rx_rssi`=12) и по-стари (`decoded`=12, `encrypted`=13, `id`=4 varint,
  `rx_snr`=6, `rx_rssi`=7). Форматът се разпознава по това къде седи LEN
  блокът Data/encrypted.
- Криптиран пакет (само `encrypted`, без `decoded`) е честен
  `meshtastic-encrypted / partial`: възел/id/SNR/RSSI се извличат,
  съдържанието не се декодира без PSK ключ.
- Декодира само полетата, които платформата използва; непознатите
  структури връщат `None` → пакетът остава честен „binary / not_attempted“.
- Поддържа signed int32 (координатите ×1e7 и RSSI са two's complement,
  sign-разширени до 64 бита при varint) и частичен статус (`partial`) когато
  вътрешният payload не носи очакваното.
- Същата изходна форма като JSON декодера (`envelope_info`), вкл.
  packet_id/snr/rssi — така ingest/routing/мониторинг не се интересуват
  кой декодер е сработил.

## Алтернативи

- `protobuf` + генериран код от официалните .proto: пълно покритие, но нова
  зависимост + build стъпка за генериране на _pb2.py и синхронизация с
  версиите на firmware прототипите. Отложено за пълния декодер (фаза 3
  остатък: NeighborInfo/Routing топология), ако подмножеството срещне
  граници.
- `blackboxprotobuf` (schema-less): по-тежка зависимост, евристики вместо
  схема — по-крехко от ръчния парсер за известна схема.

## Последствия

- (+) Нула зависимости; малка повърхност за ревю; лесни unit тестове с
  ръчно конструирани frames.
- (+) Шифрованите канали (не-TEXT payloads без декод) остават честно
  „partial“ — без опити за разшифроване.
- (−) При промяна на полетата в нов firmware парсерът трябва да се
  допълни ръчно (риско ограничен: proto полетата се добавят, не се
  номерират наново).
- Дедупликацията по packet id (ingest, TTL 180s, ключ възел+id) разчита
  на извлечения packet id и от двата декодера.
