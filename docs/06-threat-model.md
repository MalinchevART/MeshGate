# MeshGate — модел на заплахите

Обхваща MVP обхвата (`docs/04-mvp-scope.md`); преразглежда се при всяка нова фаза.

## Активи

- MQTT трафик и устройства (наличност, цялост)
- Потребителски акаунти и роли; per-device MQTT креденшъли
- Конфигурация (ACL, bridges, профили) и audit запис
- Сурови пакети (възможна чувствителна телеметрия/локации)
- EMQX admin API key, DB креденшъли, `MESHGATE_SECRET_KEY`

## Актори

viewer / operator / admin (приложни); MQTT устройство; външен bridge брокер
(контролиран и неконтролиран); интернет посетител; компрометиран контейнер.

## Матрица (STRIDE-подредени мерки)

### 1. Неоторизирано публикуване / абониране (checklist §7)
- Per-device MQTT креденшъли; **ACL deny-by-default** — разрешено само изрично.
- Приложно RBAC: viewer не може publish/промяна; операциите минават през audit.
- Тест: неоторизиран клиент publish → отхвърлен от брокера; viewer POST → 403.

### 2. Излагане на креденшъли
- EMQX API ключът живее само като env на api контейнера; никога не се праща към
  браузъра и не се логва (log-filters за резервни полета).
- Пароли: argon2id; тайни в DB — само референции; `.env` не се комитва.
- WebSocket/SSE изискват сесия; не се предават тайни в URL (токен-по-cookie).

### 3. SSRF през потребителски broker URL-и (bridge)
- Валидация при запис: hostname → resolve → **блокиране на private/loopback/link-local
  адреси** (RFC1918, 169.254/16, ::1, fc00::/7), освен изричен allow-list от admin.
- Re-resolve при connect (DNS rebinding) + pin на resolved адрес за сесията.
- Изходящият трафик на bridge минава само от api контейнера; мрежата му може да се
  ограничи допълнително (Фаза 3).
- Тест: bridge към `http://localhost:18083` → `ssrf_blocked`.

### 4. Bridge цикли и изтичане на данни (checklist §10)
- Всяко препратено съобщение носи origin marker (`origin=bridge:<id>` в свойство/тема);
  входящи с чужд/наш origin marker → `loop_blocked` + брояч.
- Dedupe кеш (тема+payload_hash, TTL) като втора линия.
- Изходът е **disabled by default**; deny-by-default правила — personal/position/
  unknown типове се блокират, освен изрично разрешени (Фаза 3 разширява).
- Тест: две bridge-нати инсталации; цикълът се прекъсва ≤ 2 хопа; забранена тема →
  `rejected` с причина в `bridge_events`.

### 5. Излагане на админ портове
- Нищо от {18083, 5432, 1880, 8428, api порт} не се публикува на host-а.
- Единствен вход: Traefik (80/443) с TLS; EMQX dashboard (ако се ползва) — през
  Traefik + forward-auth с MeshGate сесия (admin-only). Node-RED — собствена автентикация (ADR-004).

### 6. Вредоносен/повреден payload (декодери, import)
- Декодерите връщат или structured данни, или `{status:failed, error}` — никога не
  crash-ват ingestion-а (per-packet try/except + лимит на време/памет).
- Export/import на конфигурация: Pydantic схеми, без изпълнение на код (никакъв eval
  на чужд JSON). Плъгин SDK (Фаза 5) — декларативен, не произволен код.
- Bounded queries: `limit` ≤ 200 (list) / 10 000 (export); raw payload над размер
  (по подразбиране 256 KB) се съхранява, но не се изпраща целият към браузъра (hex view
  на първите N bytes + изтегляне при нужда).

### 7. Достъпност/ресурси (DoS-lite)
- Rate limit на login и тестови публикации; WebSocket backpressure (drop → heartbeat).
- Retention задачите са пакетни (LIMIT+BATCH), за да не заключват таблиците.

### 8. Цялост на аудита
- `audit_log` е append-only на ниво приложение; правата по таблицата са за вмъкване
  и четене (admin); UPDATE/DELETE липсват от API/ORM интерфейса.
- Конфигурационните промени винаги пишат diff (before/after) — rollback-ваеми.

## Останали рискове (приети, документирани)

- Windows host Docker: Docker Desktop трябва да е активен за локален stack — едноточкова
  зависимост на dev машината (не на продуктната инсталация).
- EMQX 5.8.x вече не получава ъпдейти (ADR-001) — мониторим за CVE; при нужда смяна
  през adapter-а с нов ADR.
- Self-hosted единичен node: няма HA — приемливо за целевия потребител; backup процедурата
  е задължителна част от дефиницията „готово“.
