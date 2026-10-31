# Т6 „Топбар + sidebar + брояч аларми" — Вариант 2: „Шел като компоненти"

Дата: 2026-10-27. Стратегия: ИЗВЛИЧАНЕ на шел-а от App.tsx в компоненти,
та следващите точки (Т9 Dashboard, Т13 Devices, Т33 tablet) пипат
компоненти, а не 228-редов App. Всичко е в рамките на системата от Т1
(само токени, нищо под 12px, без сенки, radius 4/8/12, z-стълбата се пази)
и на зависимостите (само react/react-dom + готовите примитиви от Т3 —
LiveIndicator/usePacketStream; нула нови npm пакети). DOM дървото на шел-а
е запазено 1:1 (класове и йерархия) — страниците не усещат разликата.

## Файлове

| Файл (вариант) | Дестинация при внедряване |
| --- | --- |
| `shell.tsx` | `apps/web/src/components/Shell.tsx` (нов) |
| `hooks.ts` | `apps/web/src/hooks/useAnomalyCount.ts` (нов; нова папка `hooks/` — `include: ["src"]` я вдига без конфигурация) |
| `shell.css` | подблок „Т6" в секция **4.1 SHELL** на `apps/web/src/styles.css`. ТОЧНО място: МЕЖДУ легаси `.topbar-right { … }` и легаси `@media (max-width: 900px)`. Защо: блокът основява `.topbar`/`.sidebar` на токена `--topbar-h` (същите 52px → нула делта) и трябва да е след базите, но ПРЕДИ легаси media блоковете, чиито (по-късни в файла) правила при <900/<800 трябва да продължат да печелят |
| `app-diff.md` | точният diff на `apps/web/src/App.tsx` (прилага се последен) |
| `notes.md` | този файл — не се внедрява |

Миграцията на `styles.css` е чисто ДОБАВЯНЕ (подблок „Т6" в 4.1), без
редакция на легаси правила. Едната препоръчана ЕДНОКРАТНА редакция
извън 4.1 (незадължителна, нула визуална делта): в 4.3
`.mg-panel__head { top: 52px }` → `top: var(--topbar-h)` — токенът
`--topbar-h` влиза именно с този подблок (препоръка от notes на Т3,
§Рискове 3).

## Компонентно API

### `Shell` — собственикът на сесийните ресурси

```tsx
<Shell
  me={me}                                    // Me (не null — App пази guards)
  page={page}                                // активният PageId
  onPage={setPage}                           // SetState на App (пряко)
  onPassword={() => setPwOpen(true)}         // от 🔑 и от банера
  overlays={<>…модали на App…</>}            // края на div.shell — както днес
  alarmSource="anomalies"                    // 'critical-events' след Т7
>
  <PageBoundary>…страниците…</PageBoundary>  // main е children слот
</Shell>
```

| Проп | Тип | Default | Значение |
| --- | --- | --- | --- |
| `me` | `Me` | — | сесийният потребител: `role` → pill + adminOnly филтър, `default_password` → банер, `username` → топбар |
| `page` | `PageId` | — | активната страница (state-ът остава в App — `?p=` логиката е там) |
| `onPage` | `(p: PageId) => void` | — | смяна на страницата |
| `onPassword` | `() => void` | — | отваря ChangePassword (🔑 в Topbar + банерът) |
| `overlays` | `ReactNode` | — | модалите на App (ChangePassword, Onboarding) — рендерират се в края на `div.shell`, ТОЧНО както днес → нула DOM разместване |
| `alarmSource` | `'anomalies' \| 'critical-events'` | `'anomalies'` | превключвателят от спека; след Т7 се сменя само този проп |
| `children` | `ReactNode` | — | съдържанието на `<main>` |

Shell Е собственикът на двата сесийни ресурса (това е сърцето на В2):

1. **постоянният WS поток** — `usePacketStream()` от Т3 (виж §LIVE по-долу);
2. **броячът на аларми** — `useAnomalyCount({ hours: 24, intervalMs: 10_000, source })`.

Топбарът и sidebar-ът са чисти (без собствени данни) — данните текат от
Shell надолу; при Т9/Т18 други консуматори могат да получат същите обекти
от Shell (или от бъдещия Provider), без нови заявки.

### `Topbar` — лого + приложен LIVE + потребител

| Проп | Тип | Значение |
| --- | --- | --- |
| `me` | `Me` | username + role pill |
| `live` | `{ state: LiveState; pulsing: boolean }` | резен от PacketStream — директно се подава целият обект (структурно съвместим) |
| `onPassword` | `() => void` | 🔑 → ChangePassword |

Структура: `.topbar > .topbar-left(.brand + .topbar-live[LiveIndicator
compact]) + .topbar-right(.topbar-user + .pill[role] + 🔑 + Изход)`.
`Изход` е вътрешен за Topbar (`POST /v1/auth/logout` + reload — чисто
топбар-специфичен страничен ефект, същият код като днес). Ролята слиза от
бранда в потребителския блок (спек: „по-подреден десен блок"); блокът
отива вдясно с `margin-left:auto` — единственото съзнателно разместване.

### `Sidebar` — сегменти, групи, акцент, брояч

| Проп | Тип | Default | Значение |
| --- | --- | --- | --- |
| `sections` | `ShellSection[]` | `SECTIONS` | дефиницията (експортирана — за тестове/Т9) |
| `active` | `string` | — | активният id → акцент-бар + `aria-current="page"` |
| `onSelect` | `(id: string) => void` | — | стринг, не PageId: Shell каства безопасно — `PAGES` (източникът на PageId) е flatMap на същите SECTIONS |
| `isAdmin` | `boolean` | — | филтър на `adminOnly` (Profiles) |
| `alarm` | `AnomalySummary \| null` | `null` | броячът; `null` (още без успешен poll) или `alarm === 0` → БЕЗ badge (не „0") |

Филтрите `adminOnly`/`hidden` са 1:1 от днешния App. Новото спрямо днес:
глиф (`.side-btn__icon`, фиксирана колона 20px → етикетите се подравняват),
етикет с ellipsis (`.side-btn__label`), тюркоазен 2px акцент-бар вътре в
активния (`.side-btn.active::before` — без сянка, без разместване),
`nav[aria-label="Главно меню"]` обвивка, danger badge `.side-badge`.

### Типове/константи (експорти от Shell.tsx)

```ts
export type Me = { id: string; username: string; role: string; default_password: boolean }
export interface ShellItem { id; label; icon?; adminOnly?; hidden?; badge?: 'alarm' }
export interface ShellSection { title: string; items: ShellItem[] }
export const SECTIONS: ShellSection[]   // 1:1 от App.tsx + badge:'alarm' на Мониторинг
export const PAGES = SECTIONS.flatMap(s => s.items)
export type PageId = (typeof PAGES)[number]['id']
```

`Me` се мести от App.tsx; App ре-експортира (`export type { Me }`), та
8-те страници с `import type { Me } from '../App'` остават непипнати
(grep 2026-10-27: Bridges, Integrations, Broker, Devices, Onboarding,
Notifications, System, RoutingRules).

## `useAnomalyCount` — броячът

```ts
const { summary, error, refresh } = useAnomalyCount({ hours = 24, intervalMs = 10_000, source = 'anomalies' })

interface AnomalySummary {
  hours: number
  alarm: number            // ЧИСЛОТО В БРОЯЧА = deadletter + notify_failed
  deadletter: number; notifyFailed: number          // ЛОШИТЕ, поотделно
  notifySent: number; rulePublish: number           // информационни
  byKind: Record<AnomalyKind, number>               // суровите бройки (tooltip/Т7)
  total: number
  lastAlarmTs: string | null; lastTs: string | null
  updatedAt: number        // Date.now() на последния УСПЕШЕН poll
}
```

- **Какво е „аларма"**: само `deadletter` + `notify_failed` (ЛОШИТЕ).
  `notify_sent` (известието тръгна) и `rule_publish` (админ публикува
  версия) са нормална работа — те НЕ вдигат брояча, но броят се в summary
  (tooltip-ът и Т7 превключвателят ги имат готови).
- **Източникът е превключваем**: `ADAPTERS: Record<AnomalySource,
  SourceFetcher>` — `'anomalies'` е реализиран (meta.py ред 254+;
  `api()` вече е свалил `{data:…}` обвивката); `'critical-events'`
  връща изрична грешка „включва се след Т7". След Т7: един нов fetcher в
  ADAPTERS + `alarmSource='critical-events'` в Shell — нищо друго.
- **Живот**: poll на 10s; скрит таб (visibilitychange) → НУЛА заявки
  (NOC табовете стоят отворени с часове), при връщане — веднага refresh;
  в полет → новият tick се пропуска (`inFlight` ref); грешка (вкл. 401) →
  ЗАДЪРЖА последния добър summary (badge-ът не мига/не изчезва) и вдига
  `error`; никога успешен poll → `summary = null` → без badge. Cleanup:
  clearInterval + removeEventListener + `disposed` срещу setState след
  unmount. `refresh()` — стабилен (useCallback) за консуматори (Т9: след
  ack/silence).
- **Непознат kind** (бъдещ бекенд): брои се в `total`, не чупи нищо.
- **Badge рендиране**: `0` или `null` → без badge; `> 99` → „99+";
  aria-label на бутона носи ПЪЛНИЯ разпад („аларми (24 ч): 7 — мъртви
  букви: 5, провалени известия: 2; последна: …"); title добавя
  „проверено в HH:MM:SS" (свежест без error-канал в UI).

### Защо без `aria-live` на badge-а

Полинг на 10s + NOC флууктуация → live region би дрънкал на всеки скок.
Достъпът е осигурен иначе: числото е текст в бутона, aria-label-ът носи
разпада, `aria-current="page"` маркира активния. Ако Т7/Т18 решат, че
новата аларма ТРЯБВА да се обявява — това е Toast (danger) с push от
консуматор, не live region на брояча.

## LIVE в топбара — първият постоянен WS консуматор

- `usePacketStream()` (Т3) се монтира в **Shell** — т.е. след login
  (Shell се рендерира само при `me != null`) и живее **цялата сесия**:
  смяната на страници НЕ къса сокета; backoff 1s→10s при срив; нула
  handler-и (`onDataBind` не се връзва) — ползваме само `state`/`pulsing`
  за `LiveIndicator compact`.
- **Състояния, които се виждат** (QA): `live` (зелен; пулс — разширяващ
  се ринг — САМО при пристигащи пакети), `reconnect` (жълт
  „СВЪРЗВАНЕ…" — спри api контейнера и го гледай). `idle` (куха точка)
  не се появява в топбара — топбарът никога не паузира потока си (паузата
  е екранно понятие, Т14 Explorer); компонентът го поддържа.
- **До Т14**: PacketExplorer държи свой WS ( ред 114 в него ) → на
  страницата Explorer има transient 2 сокета. Документиран компромис, не
  дефект: броят е малък, животът на втория е само докато сте на страницата.
- **След Т14**: потокът минава в общ `PacketStreamProvider` с refcount —
  Shell вече е ЕДИНСТВЕНОТО място, което държи потока и го предава надолу
  (Topbar взима само `{state, pulsing}` резен) → миграцията е локална в
  Shell, консуматорите не се пипат. Полето е подготвено.

## Икони (картата `GLYPHS` в Shell.tsx)

| id | глиф | | id | глиф |
| --- | --- | --- | --- | --- |
| overview | `▦` решетка | | routing | `◇` решение/условие |
| monitor | `∿` осцилограма | | notifications | `⚑` флаг |
| devices | `⬡` mesh възел | | integrations | `⧉` свързани квадрати |
| packets | `⇄` двупосочен поток | | system | `▣` ядро |
| map | `⌖` мерник | | profiles | `⊞` матрица |
| broker | `◉` хъб с център | | plan | `✓` план/тестове |

Критерий: кодови точки **без** свойство Emoji_Presentation (геометрия /
стрелки / математика / флаг U+2691) → монохромен текстов рендер на ВЯРКА
платформа — няма „emoji карнавал" (цветен ☁️/⚙️/✉️ под Android/iOS е точно
това). Проверено срещу покритието на Segoe UI Symbol (Windows) и DejaVu
Sans (Linux Docker/NOC); при липсващ глиф на екзотична ОС: fallback `•`.
Запасни кандидати при нужда: monitor `≋`, devices `⬢`, broker `◍`,
notifications `⚑` (задържа), system `◧`. Иконата наследява цвета на
бутона (muted/accent) → контрастът е този на етикета (таблицата долу).
Т33 (tablet, sidebar до икони): скриват се `.side-btn__label` +
`.side-title` с CSS — картата не се пипа.

## Миграционен план на App.tsx

Пълен diff (генериран с `diff -u` срещу днешния файл): **app-diff.md**.
Резюме ред по ред: добавят се 2 импорт-реда + ре-експорт на `Me` след
импортите; трият се редове 43–80 (коментар, SECTIONS, PAGES, PageId, Me —
преместени в Shell.tsx с новите полета), ред 114 (`isAdmin` — Shell го
има) и целият return JSX 116–193 се замества с `<Shell …>` (14-те реда
страници в PageBoundary остават буквално непипнати; модалите отиват в
проп `overlays`). PageBoundary и Login остават в App. Резултат:
**237 → 163 реда** (−74), като най-тлъстата част на App вече е списъкът
страници. DOM след миграцията е идентично на днешното (само нови
вътрешни възли в топбара/sidebar).

## Контраст (изчислен, WCAG 2.x relative luminance)

Метод като в notes на Т3: L = 0.2126R+0.7152G+0.0722B (линеен);
ratio = (L1+0.05)/(L2+0.05); AA за нормален текст ≥ 4.5:1, за не-текстови
UI елементи ≥ 3:1. L-та: accent #22D3D9 = 0.5194; text-muted #91A8BA =
0.3756; text-primary #E6F0F7 = 0.8588; danger #FF626C = 0.3108;
surface #0B1B2A = 0.0102; panel #102437 = 0.0165; canvas #07131F = 0.0061.

| Комбинация (елект) | Фон | Ratio | AA |
| --- | --- | --- | --- |
| **активен** side-btn: accent текст + accent бар 2px | panel | **8.56:1** | PASS (и 3:1 за бара) |
| **неактивен** side-btn: text-muted 13px | surface | **7.07:1** | PASS |
| side-btn hover: text-primary | panel | 13.67:1 | PASS |
| side-title (12px muted) | surface | 7.07:1 | PASS |
| **badge**: canvas текст 12px върху danger плочка | danger | **6.43:1** | PASS |
| badge плочка (danger) срещу бутона (panel) — не-текст | panel | 5.43:1 | PASS ≥ 3:1 |
| топбар LIVE: live(success) / reconnect(warning) / idle(muted) | surface | 9.17 / 10.27 / 7.07:1 | PASS |
| topbar-user 13px muted; pill (role) 12px muted | surface / panel | 7.07 / 6.40:1 | PASS |
| икона на item = цвета на етикета (muted/accent) | surface / panel | 7.07 / 8.56:1 | PASS |

Нищо под 12px (badge 12, икони 14, LIVE 12, side-title 12, потребител 13).

## Responsive

- **< 900px** (QA gate): тялото се колонизира от ЛЕГАСИ @media 900 блок
  (4.1) — sidebar става хоризонтална пелетна лента (wrap), side-title се
  скрива. Нашите flex item-и (икона+етикет+badge) работят в пелетите без
  намеса; акцент-бар остава; топбарът се смуква (gap 24→12, потребител
  max-width 140px с ellipsis). Подблокът е ПРЕДИ легаси media блока →
  неговите правила печелят (zero specificity трикове).
- **< 800px**: топбарът wrap-ва на 2 реда (легаси 4.10 @media 800,
  `height:auto` + статични panel heads от Т3). `.topbar-left` е едно цяло
  → LIVE остава до бранда; потребителският блок отива на втория ред и е
  изцяло видим — „LIVE състоянията се виждат" и на тесен екран.
- **< 640px** (бонус, извън gates): wordmark-ът се свива до символа
  (`display:none` — пренареждане, не смаляване); нищо под 12px не се
  въвежда; без хоризонтален скрол (етикетите имат ellipsis, sidebar-ът
  wrap-ва).
- Т33 ще добави „sidebar до икони" на tablet — готово: скриват се
  `.side-btn__label`/`.side-title`, картата GLYPHS остава.

## Тест-план на брояча (QA + жива проверка)

Предусловие: вход като admin; два прозореца — един `/?p=monitor` (лентата
на аномалиите там за кръстосана проверка), един произволен.

1. **Базова линия**: `curl -cu user:pass /api/v1/anomalies?hours=24` (или
   fetch в конзолата) → брой `kind: deadletter` + `kind: notify_failed` =
   числото, което badge-ът показва (при ≤ cap; вж. §Рискове 4). Tooltip =
  „мъртви букви: X, провалени известия: Y; последна: …".
2. **deadletter през bridge pipeline**: спри външния брокер, към който
   публикува мост/правило (или създай тестово правило към несъществуваща
   дестинация) → изпрати тестов пакет (демо възел или MQTT publish в
   mesh тема) → routed fail → пакетът влиза в `deadletter/…`. Очакване:
   ≤ 10s badge +1; на Monitor се появява червен маркер.
3. **notify_failed**: Notifications → канал с невалиден webhook URL →
   задействай правило с известие → `notification_log.status='failed'`.
   Очакване: badge +1 (разпадът в aria-label показва точно този компонент).
4. **0 → без badge**: изчисти тестовите записи (deadletter редове +
   тестовите notification_log) → ≤ 10s badge изчезва (никога „0").
5. **Обновяване/свежест**: tooltip „проверено в HH:MM:SS" се мени на ~10s;
   скрит таб → Network tab: НУЛА заявки към /v1/anomalies; върни се →
   веднага една.
6. **Срив на api**: спри api контейнера → badge стои (не мига), конзолата
   без unhandled rejection; пуни → обновява се.
7. **LIVE състояния**: жив поток → зелено LIVE с пулс при всеки пакет;
   спри api → жълто „СВЪРЗВАНЕ…" (backoff); върни → отново LIVE. Върху
   `prefers-reduced-motion` рингът е статичен, състоянието се чете от текста.
8. **Регресия обиколка**: всички `?p=` страници се отварят (вкл.
   `/?p=profiles` като admin, `/?p=ui` скрития полигон); дълбоки връзки
   (`/?p=packets`); Monitor си тегли собствените /v1/anomalies (30s) —
   непокътнат; Modal-ите (ChangePassword/Onboarding) се отварят от 🔑 и
   банера; Изход работи; при viewer Profiles липсва от менюто.
9. **tsc/vite**: чист `tsc -b && vite build` (хостът без Node — проверката
   е при внедряващия преглед).

## Self-check

- **0 hex** в shell.tsx / hooks.ts / shell.css (grep `#[0-9a-fA-F]{3,8}`) —
  всички цветове през токени; `99+`, глифовете и URL-ите не са hex.
- **0 размери под 12px**; **0 сенки** (акцент-барът е плътна плочка с
  absolute позициониране, divider-ът е 1px border-left); **radius** само
  4/8/12; **z-стълбата** не пипната (топбар z 5; нищо ново над нея).
- **0 нови npm пакети**: импорти са react (hooks.ts), '../api',
  './Brand', './ui' (Т3), '../hooks/useAnomalyCount'.
- **Strict TS**: без non-null assertion (двойна проверка `hasBadge &&
  alarm != null`); cast-ът `id as PageId` е аргументиран в кода; `inFlight`
  ref без състезания; `disposed` срещу setState след unmount; стрингови
  сравнения на ts през Date.parse (не лексикографски).
- **Cleanup матрица**: WS (в Т3 hook) — disposed+close; interval +
  visibilitychange listener — в cleanup на ефекта; нула таймери след
  демонтиране на Shell.

## Рискове и решения

1. **НАЙ-ГОЛЯМ — DOM регресия по страници, разчитащи на DOM на стария
   шел.** Митигация: (а) grep 2026-10-27: `.side-btn`/`.topbar`/
   `.sidebar`/`.shell` се ползват САМО в App.tsx (страниците — нула;
   `querySelector`/`closest` към шел DOM — нула); (б) Shell рендерира
   СЪЩИТЕ класове/йерархия (div.shell > banner? > header.topbar >
   div.body > aside.sidebar + main), модалите остават на същото място
   чрез `overlays`; (в) единствените нови възли са вътрешни за
   топбара/sidebar; (г) тест 8 по-горе е задължителна пълна `?p=` обиколка.
   Остатъчен риск: страница, чупеща се от `display:flex` на `.side-btn`
   (невъзможно — не го ползва) или тест (124-те CSS теста не пипат шел).
2. **Два WS до Т14** (топбар + Explorer). Transient, документиран;
   api-то издържа 2 връзки на потребител. След Т14: Provider с refcount —
   Shell е единственият купувач на потока днес, миграцията е локална.
3. **Глифово покритие на шрифтовете**: избрани codepoints без
   Emoji_Presentation; на екзотична ОС без глиф → fallback `•` (не tofu
   — винаги е в картата). Запасни кандидати — §Икони.
4. **Капациран отговор на /v1/anomalies** (200 deadletter + 200
   известия + 100 публикации): при повече събития badge-ът е „поне
   толкова", не точен брой. За индикатор „има проблем СЕГА" е достатъчно;
   точният брой идва с Т7 (critical-events) — превключвателят е 1 ред.
5. **Изтекла сесия (401)**: hook-ът вдига error на всеки 10s, badge-ът
   замръзва на последния добър (честно; не е „жив"). Глобален 401 handler
   е извън обхвата на Т6 — решение при Т7/Т9 (Interceptor в api.ts).
6. **StrictMode double-mount** (dev): `inFlight` guard може да пропусне
   първия immediate poll на втория монаж → interval-ът го наваксва до 10s.
   Само dev; production е чист.
7. **`--topbar-h` в 4.1 вместо §1**: подблокът е самодостатъчен (правило
   „CSS се ДОБАВЯ в 4.1"); при внедряване токенът може да се изкачи в
   §1 TOKENS без делта. `.mg-panel__head` (4.3) остава на raw 52px до
   еднократната препоръчана подмяна — вж. §Файлове.
8. **Потребителският блок се мести вдясно** (margin-left:auto): днес той
   стои до бранда — съзнателната промяна на спека („по-подреден десен
   блок"). Ако собственикът възрази: маха се едно правило в shell.css.
9. **Без aria-live на badge-а** — съзнателно (полинг-спам); обяснено в
   §useAnomalyCount; изходът при нужда е Toast, не live region.
