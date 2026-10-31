# План: Известия при събития (Фаза 5, първи срез)

Продуктова посока №2 от собственика: „Мониторинг + автоматизация с известия:
имейл, Telegram, WhatsApp при аларми/събития“. Този срез покрива Telegram,
имейл и webhook; WhatsApp (CallMeBot) следва по образеца на NetSight notify.py
при поискване.

## Модел

```
ingest (всяко локално съобщение)
   └─ notify.handle_local(topic, decoded, origin)   ← неблокиращо, опашка
        └─ работник: мачва topic_pattern на каналите
             ├─ дедуп (канал+тема+съдържание, 60 s)
             ├─ анти-спам (min_interval_s на канал)
             ├─ send → Telegram / имейл(SMTP) / webhook(JSON POST)
             └─ журнал в notification_log (sent/failed/skipped + грешка)
```

- **Канал** (`notification_channels`): име, вид (telegram|email|webhook),
  `topic_pattern` (MQTT filter, същото съвпадане като навсякъде — `+`/`#`),
  JSON конфиг (telegram: `bot_token`+`chat_id`; email: `to`; webhook: `url`),
  `min_interval_s` (анти-спам), enabled.
- **Съобщение**: `MeshGate · <тема>` + най-смисленото от декодирания блок
  (текст / възел · канал · батерия · позиция · SNR; `via bridge:<id>` при
  входящ мост).
- Провален канал НЕ спира останалите (както при routing дестинациите);
  грешката отива в журнала с причината.
- SMTP настройките са среда (deploy/.env): MESHGATE_SMTP_HOST/PORT/USER/
  PASSWORD/FROM — без хост имейл каналите дават ясна грешка, не мълчат.

## Сигурност

- webhook URL минава през същата SSRF защита като мостовете (частни/
  loopback адреси — изричен `allow_internal` от admin, иначе отказ).
- `bot_token` не се връща от API-то (маскира се с ***).
- RBAC: CRUD/тест — admin; списък/журнал — viewer+.

## API

- `GET /v1/notifications` — канали (конфиг без тайни)
- `POST /v1/notifications` — създаване (валидация на конфиг + SSRF)
- `DELETE /v1/notifications/{id}`; `POST .../enable|disable`
- `POST /v1/notifications/{id}/test` — директно тестово известие
- `GET /v1/notifications/log?limit=` — журнал

## UI

Страница „Известия“: списък с канали (⚡ тест, ⏸/▶ включи/изключи, ✕ изтрий),
форма за нов канал с шаблони per вид, журнал на последните 50.

## Приемка (автоматизирана)

1. Публикуваме в `alerts/...` → webhook получателът хваща JSON с topic и
   message; журналът записва `sent`. (integration)
2. Webhook към loopback без `allow_internal` → 422 (SSRF). (integration)
3. Невалидна конфигурация (телеграм без chat_id) → 422. (integration + unit)
4. Unit: мачване на теми, дедуп, анти-спам, провален канал не спира
   останалите, Telegram тяло/URL през httpx MockTransport.

## Извън обхвата на среза (по-късно)

- WhatsApp (CallMeBot), Matrix, n8n/Node-RED адаптер (ADR-004)
- шаблони на съобщението per канал; ниво на важност; тихи часове
- повторни опити при провал (backoff) — виж R2 reliability план
