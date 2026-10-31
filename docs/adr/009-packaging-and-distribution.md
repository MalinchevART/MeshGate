# ADR-009 — Пакетиране и разпространение (старт с .bat, Linux, git repo, .exe)

Дата: 31.10.2026 · Статус: приет · Искане: собственикът („пакет със старта на
.bat, инсталация за Windows и Linux, подготовка за качване в repo, exe)

## Контекст

Проектът се предава за доработка. Липсват: едно кликване за всекидневния
старт с непрекъсната работа, Linux път, публично/частно git repo с
двуезична документация и един файл-инсталатор (.exe).

## Решения

1. **Windows стартер:** `deploy/start-meshgate.cmd` — вика идемпотентния
   `install-meshgate.cmd` (проверка/инсталация), отваря браузъра и влиза в
   watchdog цикъл (60 s): брои running контейнерите и вдига стека при
   падане (в добавка към restart policy). ASCII-only (.cmd урокът).
2. **Linux:** `deploy/install-linux.sh` — apt инсталация на Docker+Compose,
   gen-env, compose up, чакане на health; `--service` инсталира systemd
   unit (`meshgate.service`, RemainAfterExit) за автостарт при рестарт.
3. **Една команда за нова машина:** `deploy/bootstrap.sh` — клонира repo-то
   (ако не е вътре) и делегира на OS-инсталатора; публикува се като raw URL.
4. **.exe инсталатор:** 7-Zip SFX (`deploy/make-installer.sh`):
   git-tracked файлове → payload.7z → `7z.sfx + config + archive` =
   self-extracting exe, който разопакова в `MeshGate\` и стартира
   `install-meshgate.cmd`. IExpress беше първият опит — заряза се:
   чувствителен е към SED формата (FileN редовете ТРЯБВА да са вътре в
   [SourceFiles0]) и от bash/с скрит изход отваря GUI майстора на екрана
   на потребителя — отказан.
5. **Repo:** GitHub **private** (`nmalinchev-nlm/meshgate`) — в историята
   има 13 срещания на документираната НАЧАЛНА admin парола (UI принуждава
   смяна), затова public е решение на собственика след ротация. README.md
   е двуезично EN+BG със снимки от живата система (docs/images/).

## Последици

- Доработчикът стартира с двоен клик (Windows) или една команда (Linux).
- Кратките скриптове се надграждат върху съществуващите (install-meshgate.cmd
  остава идемпотентната основа; start-*.cmd/sh са обвивката за непрекъснатост).
- .exe-то пакета е с SFX -mx=5 (~6 MB) — съдържа кода, НЕ: .env (секретите),
  backups, node_modules (всичко е извън git).
