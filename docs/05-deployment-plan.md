# MeshGate — план за деплойване (Docker Compose)

Планът се превръща в `deploy/docker-compose.yml` при Фаза 0 имплементация.
Правила: фиксирани тагове (без `latest`), healthcheck за всеки сервис, админ портът
не се публикува. Точните тагове се потвърждават при първи `docker pull` и се
закрепят тук + в compose файла.

## 1. Сервиси

| Сервис | Образ (закрепен) | Публикувани портове | Томове | Healthcheck | Depends on |
|--------|------------------|---------------------|--------|-------------|------------|
| traefik | `traefik:v3.3` | 80, 443 | `./traefik/acme.json` | `traefik healthcheck --ping` | — |
| emqx | `emqx/emqx:5.8.8` | 1883, 8883 | `emqx_data` | `emqx ctl status` (в контейнера) | — |
| postgres | `postgres:16.6-alpine` | — | `pg_data` | `pg_isready -U $POSTGRES_USER` | — |
| api (Core API) | build: `apps/api` (python:3.13-slim) | — | — | `GET /api/v1/system/health` | postgres+emqx healthy |
| web | build: `apps/web` (node:22-alpine build → nginx служи статиката) | — | — | GET / | — |
| vm (Фаза 2) | `victoriametrics/victoria-metrics:v1.1xx` | — | `vm_data` | HTTP /health | — |
| nodered (Фаза 4) | `nodered/node-red:4.x` | — | `nodered_data` | HTTP / (с adminAuth) | — |

## 2. Мрежи и зони

- `edge` мрежа: traefik ↔ web ↔ api ↔ emqx (dashboard) ↔ nodered.
- `internal` мрежа: api ↔ postgres ↔ vm; postgres е ДОСТЪПЕН само от api.
- Публикувано на host: 80, 443 (traefik), 1883, 8883 (emqx listeners). Нищо друго.
  EMQX 18083 (dashboard/API) остава вътрешен — достъп през Traefik `/emqx` route с
  forward-auth срещу MeshGate admin сесия (пълно внимание: Фаза 1).

## 3. Променливи

Всичко от `.env.example`; задължителни за старт: `POSTGRES_PASSWORD`,
`MESHGATE_SECRET_KEY`, `EMQX_API_KEY/SECRET`, `MESHGATE_ADMIN_PASSWORD`
(bootstrap; изтрива се след първи вход — README указва).

## 4. Първо стартиране (bootstrap)

1. `cp .env.example .env` + попълване.
2. `docker compose up -d` — alembic миграциите се пускат от api при старт.
3. api bootstrap: създава admin от `.env` (ако няма потребители), seed-ва фабричните
   профили, създава EMQX API ключ ако липсва, записва го само в environment-а си.
4. Проверка: `docker compose ps` (всички healthy) → `https://<host>/` → вход.
5. След първи вход: смяна на admin паролата; премахване на `MESHGATE_ADMIN_PASSWORD`
   от `.env` и `docker compose up -d` (recreate без bootstrap променливи).

## 5. Healthchecks и рестарт политика

- Всеки сервис: `restart: unless-stopped` + healthcheck с интервал/timeout/retries.
- api стартира само при healthy postgres+emqx (`depends_on.condition`); при паднал
  EMQX API рестартира, но broker-ът продължава да обслужва MQTT (изискване §8 на checklist).

## 6. Backup / Restore

**Backup (admin от UI или `make backup`):**
1. `docker compose exec postgres pg_dump -Fc -U $POSTGRES_USER $POSTGRES_DB` → файл с
   времеви печат в `backups/` (том или host папка по избор).
2. Експорт на не-DB конфигурация: `docker compose config` + текущ `.env` (без тайни —
   тайните остават в ops секретStore/`.env` на оператора).

**Restore (тест в чиста инсталация — checklist §9):**
1. Нов host/директория: `cp .env.example .env`, попълване.
2. Копирай backup файла; `docker compose up -d postgres`; изчакай healthy.
3. `pg_restore --clean --if-exists -U $POSTGRES_USER -d $POSTGRES_DB <file>`.
4. `docker compose up -d` — api мигрира напред ако е нужно; проверка: събитията от
   старата инсталация се виждат в Packet Explorer.

Автоматизация: скрипт `deploy/backup.sh` + `deploy/restore.sh` (Фаза 0 имплементация),
интеграционен тест изпълнява restore-а в чист контейнер.

## 7. Обновяване

1. Нови тагове → записват се в compose + таблицата горе (никакво `latest`).
2. `docker compose pull` → `docker compose up -d` (rolling per сервис).
3. Миграциите са идемпотентни; при грешка — rollback на образа + `pg_restore` на
   последния backup (затова backup преди обновяване е част от процедурата).
