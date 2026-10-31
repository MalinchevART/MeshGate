MeshGate — пренос на друг компютър (октомври 2026)
==================================================

НАЙ-ЛЕКИЯТ ПЪТ (препоръчителен): „комплект за пренос“.
На ТАЗИ машина двоен клик `deploy\make-kit.cmd` (или meshgate.cmd → 15) —
прави свеж backup и събира кода + git историята + backups + инструкции в
един zip в `MeshGateProject/_transfer/` (~10 MB). Пренасяш zip-а, разархивираш на новото
място и двоен клик `meshgate\deploy\install-meshgate.cmd` — той проверява
какво липсва (Git/Docker), ПИТА за разрешение, инсталира, вдига стека и
чака да е здрав. Данните се връщат с meshgate.cmd → 14 (Restore от backup).
Пълните инструкции са в README-KIT.txt вътре в zip-а.

РУЧЕН ПЪТ (без комплект):
1. Инсталирай Docker Desktop (ако липсва) и го стартирай.
2. Отвори терминал в MQTT/meshgate/deploy и:
   - docker compose up -d --build          (вдига стека чист)
   - .env липсва по сигурност — генерирай: bash gen-env.sh
     (или копирай .env от старата машина; и двата варианта работят)
3. (По избор) Възстанови данните от backup:
   bash restore.sh backups/<последният>.dump
   → връща правилата, потребителите, мостовете и канала за известия.
   Бележка: потребител mg-itest е тестов (за авто-тестовете) — не го трий.
4. Отвори http://localhost/  •  Управление: deploy/meshgate.cmd
5. Демо възлите: docker compose --profile demo up -d emulator

ПО GIT ПРОТОКОЛА (два компютъра, само код без данни):
прехвърли само _transfer/ от корена на MeshGateProject и пусни
sync/start-of-day.cmd там.

Управление всичко-в-едно (стек, рестарт на услуга, тестове, backup,
restore, нов комплект): deploy/meshgate.cmd
