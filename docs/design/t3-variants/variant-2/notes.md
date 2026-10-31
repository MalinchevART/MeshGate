# Т3 „Базови компоненти" — Вариант 2: „Платформени примитиви с коректен жизнен цикъл"

Дата: 2026-10-25. Стратегия: пълноценна платформа с коректен живот на всички
ресурси (таймери, listeners, WS, фокус) и вградена достъпност — не еднократни
сглобки. Всичко е в рамките на съществуващата система от Т1 (само токени,
color-mix тинтове, нищо под 12px, без сенки, 1px граници, radius 4/8/12) и на
съществуващите зависимости (само react/react-dom — нула нови npm пакети).

## Файлове

| Файл (вариант) | Дестинация при внедряване |
| --- | --- |
| `ui.tsx` | `apps/web/src/components/ui.tsx` (нов; до Т6/Т9/Т14 живее редом до `Brand.tsx`) |
| `ui.css` | петте блока се вмъкват КАТО ПОДБЛОЦИ „Т3" в съществуващите секции на `apps/web/src/styles.css`: 4.2 CARDS ← `.mg-card*`; 4.3 PANEL ← `.mg-panel*`/`.mg-icon-btn`; 4.5 TAGS & CHIPS ← `.mg-chip*`; 4.7 MODAL/DRAWER ← `.mg-modal*`/`.mg-drawer*`/`.mg-dialog__*`; 4.8 FEEDBACK ← `.mg-toasts`/`.mg-toast*`/`.mg-live*` |
| `notes.md` | този файл — не се внедрява |

Префиксът `mg-` е съзнателен: компонентните класове живеят редовно до легаси
`.card/.panel/.chip/.modal` по време на поетапната миграция (Т6→Т32) — нула
конфликти при вмъкване в `styles.css`.

Монтаж (едно място): `ToastProvider` се слага ВЕДНЪЖ около шел-а —
в `App.tsx`: `<ToastProvider><div className="shell">…</div></ToastProvider>`
или в `main.tsx` около `<App/>`. Рендерира собствен фиксиран контейнер
`.mg-toasts` в края на subtree-то — без `createPortal`.

## API

### StatusChip — статус винаги с цвят + глиф + текст

| Проп | Тип | Default | Значение |
| --- | --- | --- | --- |
| `tone` | `'success'\|'warning'\|'danger'\|'info'\|'accent'\|'neutral'` | `'neutral'` | статусния токен (цвят на текст + граница + 8% тинт) |
| `icon` | `ReactNode` | глиф по тон | собствен глиф/икона вместо `✓ ⚠ ✕ ℹ ◆ •` |
| `flat` | `boolean` | `false` | без тинт-фон, неутрална граница — за плътни таблици (Т13: 60–140 реда); цветът на текста остава носещ |
| `size` | `'sm'\|'md'` | `'md'` | sm = без вертикален padding за клетки; и двата са 12px текст |
| `mono` | `boolean` | `false` | JetBrains Mono + tabular-nums (Node ID / topic / packet id) |
| `title` | `string` | — | tooltip |
| `children` | `ReactNode` | — | текстът |

Не е интерактивен (`<span>`) — фасет чиповете на Т14 остават
`<button className="chip">`; StatusChip е за статуси. Тонът никога не се носи
само от цвята (глиф + текст винаги присъстват, WCAG 1.4.1).

### MetricCard (експортът `Metric` е alias) — KPI карта

| Проп | Тип | Default | Значение |
| --- | --- | --- | --- |
| `label` | `ReactNode` | — | `.metric-label` (12px uppercase muted, Т1 §3.6) |
| `value` | `ReactNode` | — | `.metric-value` (24px/600, tabular-nums, Т1 §3.5) |
| `tone` | `Tone` | `'neutral'` | оцветява СТОЙНОСТТА и иконата |
| `context` | `ReactNode` | — | 12px muted ред, закован долу (`margin-top:auto`) → в grid ред всички карти са еднакво високи |
| `icon` | `ReactNode` | — | декоративна икона до името (aria-hidden) |
| `align` | `'left'\|'center'` | `'left'` | |
| `mono` | `boolean` | `false` | стойност с фиксирана ширина → mono на 24px |
| `className` | `string` | `''` | |

Grid-редът: `<div className="mg-card-grid">` (auto-fit, minmax 220px —
дефиниран в CSS блока, Т9 не зависи от легаси `.cards`). Минимална височина
104px + flex колона → еднаква височина дори без контекст.

### Panel — заглавие + слотове + цял екран

| Проп | Тип | Default | Значение |
| --- | --- | --- | --- |
| `title` | `ReactNode` | — | `.panel-title` (15px/500) |
| `subtitle` | `ReactNode` | — | 12px muted под заглавието |
| `filters` | `ReactNode` | — | слот филтър/период-селектор (лизва се от `.mg-panel__filters input/select` 180px) |
| `actions` | `ReactNode` | — | слот бутони |
| `fullscreen` | `boolean` | `true` | показва ⛶; цял екран = `fixed inset 0`, z-index 8 (НАД топбар 5, ПОД модал 10), Esc изход, тялото скролва, head стои закрепен |
| `padded` | `boolean` | `true` | `false` → тяло без padding (edge-to-edge таблици за Т12) |
| `children` | `ReactNode` | — | |

Head-ът е `position:sticky; top:52px` (височината на топбара от Т1 §4.1) —
залепя се при скрол на страницата.

### Modal / Drawer (експортът `Drawer` е alias с `variant='drawer'`)

| Проп | Тип | Default | Значение |
| --- | --- | --- | --- |
| `open` | `boolean` | — | рендерира се само при `true` |
| `onClose` | `() => void` | — | Esc / ⛊ / клик на фона (държана в ref → inline стрелка в консуматора НЕ рестартира ефекта) |
| `title` | `ReactNode` | — | когато липсва, няма header лента (и `aria-labelledby`) |
| `footer` | `ReactNode` | — | слот бутони (Подаване/Отказ) |
| `variant` | `'modal'\|'drawer'` | `'modal'` | drawer = страничен панел |
| `side` | `'left'\|'right'` | `'right'` | само за drawer; под 900px drawer-ът е на цял екран |
| `width` | `number\|string` | модал 720px / drawer 480px | число → px |
| `closeOnBackdrop` | `boolean` | `true` | клик на завесата затваря |
| `className` | `string` | `''` | |

Жизнен цикъл и достъпност на диалога:
- focus trap — Tab/Shift+Tab цикъл вътре в диалога; начален фокус:
  `[data-autofocus]` → първият видим фокусируем → самият диалог (`tabIndex=-1`);
- `role="dialog"` + `aria-modal="true"` + `aria-labelledby` (useId);
- Esc — listener на `document` в CAPTURE фаза + модул-стек
  `OPEN_DIALOG_STACK`: само НАЙ-ГОРНИЯТ диалог се затваря; `stopPropagation`
  гаси и Esc-изхода на панел в цял екран под него;
- scroll lock на `body` (+ компенсация на изчезналия скролбар през
  `padding-right`), с запазени предишни inline стойности → вложените модали
  се отключват в обратен ред;
- възстановяване на фокуса при затваряне (ако елементът още е в DOM);
- видимост за фокуса = `getClientRects().length > 0` (елементи в скрит таб
  коректно се прескачат).

### Toast — ToastProvider (context) + useToast()

```ts
type ToastTone = 'success' | 'info' | 'warning' | 'danger'
interface ToastApi {
  push(tone: ToastTone, message: string, opts?: ToastOptions): number  // връща id
  dismiss(id: number): void                                            // idempotent
}
interface ToastOptions {
  title?: string               // 12px uppercase тонално заглавие
  action?: { label: string; onClick: () => void }  // след клик → затваря
  duration?: number            // ms; default 6000, danger 10000; 0 = без авто-dismiss
}
```

Поведение: стек макс 5 с изтласкване на най-стария; авто-dismiss с
pause-on-hover (таймерите живеят в ref, не в state → hover-ът НЕ предизвиква
re-render); контейнер `position:fixed` долу вдясно, z-index 20 (над модал
10); `role="log" aria-live="polite"`; action + ✕ бутон с aria-label;
пълцен тинт `color-mix(in srgb, тон 8%, var(--bg-surface))` — контрастът не
зависи от това какво свети отдолу. `useToast()` хвърля ясна грешка без
`<ToastProvider>`. Cleanup: при демонтиране на provider-а се изчистват всички
таймери; изтласканият toast има още жив таймер — `dismiss` по липсващо id е
no-op за състоянието (документиран риск по-долу).

### LiveIndicator + useLivePulse()

```tsx
<LiveIndicator state={s} pulsing={p} label? compact? title? />
// state: 'live' | 'idle' | 'reconnect'  →  LIVE / СПРЯН / СВЪРЗВАНЕ…
// цвят: success / muted / warning; idle = КУХА точка
// пулс: .mg-live__dot--pulse — разширяващ се ринг (border + transform/opacity,
//       БЕЗ сянка), слага се САМО при pulsing && state==='live'

const { pulsing, onData } = useLivePulse(decayMs = 1500)
```

- `onData()` — извиквай при ВСЯКА нова единица данни (WS рамка, poll
  отговор); рестартира decay-таймер 1.5s; стабилна референция (useCallback);
  `setPulsing(true)` при вече-true не re-render-ва (React bail-out).
- Hook-ът НЕ знае нищо за WebSocket — консуматорът решава кое е „нова данна".
- Спрян поток НЕ пулсира (QA изискване); `prefers-reduced-motion` спира
  анимациите, състоянието се чете от текста.
- cleanup: decay-таймерът се изчиства при демонтиране.

### usePacketStream() — готовият WS живот за Т14

```ts
function usePacketStream(url?: string): PacketStream  // default: ws(s)://<host>/api/v1/packets/ws
interface PacketStream {
  state: LiveState          // live | idle (пауза) | reconnect (вкл. първо свързване)
  pulsing: boolean          // само при реално пристигнали данни в НЕ-паузиран поток
  paused: boolean
  setPaused(p: boolean)     // пауза на ПОТНОКА през ref — НЕ къса WS връзката
  onDataBind(h: ((msg: unknown) => void) | null)  // стабилна; JSON-parse-н обект
                             // (при непарсебъл — суровият низ); null отписва
}
```

Живот: отваря при монтиране; exponential backoff при прекъсване
1s → 2s → 4s → … max 10s (нулира се при успешно отваряне); `onerror` →
`close()` → backoff логиката е на едно място; демонтиране: `disposed` флаг +
`clearTimeout(retry)` + `ws.close()` (късните `onclose` не правят нищо).
Паузата и handler-ът са през refs → смяна на филтър/пауза НЕ преинсталира
сокета (днешният PacketExplorer преинсталира WS при всяка смяна на филтъра —
тук това изчезва). Пауза = рамките се пропускат изцяло → без пулс, без данни.

## Примери за консуматорите

### Т6 — LIVE в топбара (App.tsx)

```tsx
import { LiveIndicator, useLivePulse, ToastProvider } from './components/ui'

// в компонента на топбара; onData се вика от който и да е жив поток/полинг
const live = useLivePulse()
// ws.onmessage = () => { live.onData(); … }   (или usePacketStream().pulsing)

<span className="topbar-right">
  <LiveIndicator state={connected ? 'live' : 'reconnect'} pulsing={live.pulsing} compact />
</span>
```

### Т9 — KPI ред с Card/Metric (Overview → KPI Dashboard)

```tsx
import { MetricCard } from './components/ui'

<div className="mg-card-grid">
  <MetricCard label="Активни възли" value={142} tone="success"
              context="от 168 известни" />
  <MetricCard label="Пакети / час" value="1 284" icon="📦"
              context="последните 60 мин" />
  <MetricCard label="Аларми" value={7} tone="danger" context="3 с ack" />
  <MetricCard label="RF връзки" value="41 / 57" tone="warning"
              context="72% стабилни" />
</div>
```

Контекстът е закован долу → четирите карти са с еднаква височина независимо
кой има контекст.

### Т14 — Packet Explorer: Live + чипове + Toast

```tsx
import { LiveIndicator, StatusChip, usePacketStream, useToast, Modal } from './components/ui'

const toast = useToast()
const stream = usePacketStream()          // WS + backoff + пауза без късане
useEffect(() => {
  stream.onDataBind((msg) => {            // старата onmessage логика — тук
    if ((msg as any)?.type !== 'packet') return
    // … съществуващите филтри и setLive([p, ...prev].slice(0, 300))
  })
}, [stream])

// лентата на панела:
<LiveIndicator state={stream.state} pulsing={stream.pulsing} />
<button onClick={() => stream.setPaused(!stream.paused)}>
  {stream.paused ? '▶ Продължи' : '⏸ Пауза'}
</button>

// статус на декода в реда (плоско за плътната таблица):
<StatusChip flat size="sm"
  tone={p.decode_status === 'decoded' ? 'success'
      : p.decode_status === 'failed' ? 'danger' : 'neutral'}>
  {p.decode_status}
</StatusChip>

// alert() → Toast (deadletter resend):
try {
  const r = await api('/v1/routing/deadletter/resend', { method: 'POST', body: … })
  toast.push('success', `Изпратено наново: ${r.topic} → ${r.target}`)
} catch (e: any) {
  toast.push('danger', `Неуспех: ${e.message}`, { title: 'Deadletter', duration: 10_000 })
}

// детайлът става <Modal open={!!detail} onClose={() => setDetail(null)} title={<span className="mono">{detail.topic}</span>}>
```

## Контраст (изчислен, WCAG 2.x relative luminance)

Метод: `color-mix(in srgb, X 8%, Y)` миксва в гама-кодирания sRGB →
8-bit резултат = `0.08·X + 0.92·Y` на канал (закръглено); L = 0.2126R +
0.7152G + 0.0722B (линеен), ratio = (L1+0.05)/(L2+0.05). Изискване AA за
нормален текст: ≥ 4.5:1 (най-малкият ни текст е 12px → нормален).

**Статусен текст върху 8% тинт на същия статус върху `--bg-surface` #0B1B2A**
(рецептата на `.mg-chip--*` и `.mg-toast--*` заглавията/иконите):

| Тон | Токен | Тинт фон (8%) | L фон | L текст | Ratio | AA |
| --- | --- | --- | --- | --- | --- | --- |
| success | #35D49A | rgb(14,42,51) | 0.0199 | 0.5018 | **7.89:1** | PASS |
| warning | #F5BE4F | rgb(30,40,45) | 0.0199 | 0.5681 | **8.84:1** | PASS |
| danger | #FF626C | rgb(31,33,47) | 0.0158 | 0.3108 | **5.48:1** | PASS |
| info | #63A9FF | rgb(18,38,59) | 0.0183 | 0.3825 | **6.33:1** | PASS |
| accent | #22D3D9 | rgb(13,42,56) | 0.0203 | 0.5194 | **8.10:1** | PASS |

**Flat вариант и LiveIndicator (тон върху чисти фонове)** — `--bg-surface`
(L=0.0102) и `--bg-panel` #102437 (L=0.0165):

| Комбинация | Фон | Ratio | AA |
| --- | --- | --- | --- |
| success / warning / danger / info / accent върху `--bg-surface` | surface | 9.17 / 10.27 / 5.99 / 7.18 / **9.46:1** | PASS |
| `--text-muted` #91A8BA върху `--bg-panel` (неутрален чип, sm) | panel | **6.40:1** | PASS |
| `--text-muted` върху `--bg-surface` (idle Live, субтитри) | surface | **7.07:1** | PASS |
| `--accent-primary` като текст върху `--bg-surface` (л branding, чип ch) | surface | **9.46:1** | PASS |
| LiveIndicator: live(success) / reconnect(warning) / idle(muted) в топбара | surface | 9.17 / 10.27 / **7.07:1** | PASS |
| `--text-primary` #E6F0F7 върху най-тъмния toast тинт (8% danger/surface) | тинт | **13.81:1** | PASS |

Границите на статусните чипове са самите токени върху същия тинт → същите
ratio като текста (≥ 5.48:1) — покриват и 3:1 за не-текстови UI елементи.

## Self-check

- **0 hex** в `ui.css` и `ui.tsx`: `grep -En '#[0-9a-fA-F]{3,8}'` → 0
  съвпадения в двата файла (всички цветове през токени; тинтовете през
  `color-mix(in srgb, var(--…) N%, …)`).
- **0 шрифтови размери под 12px**: нула raw `font-size: Npx`; всички през
  `--fs-12…24` (12 е подовата граница; `2px` margin в `.mg-toast__title` и
  `padding: 2px` в чипа са spacing, не типография).
- **0 сенки**: нула `box-shadow`/`drop-shadow`; пулсът на Live е ринг от
  `border` + `transform`/`opacity`; разделението модал/фон — завеса + 1px
  граница.
- **0 нови зависимости**: imports са само от `'react'` (7 хука); нула
  `createPortal`, нула DOM извън React извън документираните scroll-lock/
  фокус операции в Modal.
- **Strict TS**: null checks навсякере (`??`, `?.`, `!= null`), event
  типовете изрични (`KeyboardEvent`, `MessageEvent`,
  `React.KeyboardEvent<HTMLDivElement>`), `setTimeout` през
  `ReturnType<typeof setTimeout>`; поправен пропуск от черновата —
  `createContext` сега е импортиран (без него файлът не компилира).
- **Cleanup матрица** (всички ресурси имат `useEffect` return):

| Ресурс | Къде | Cleanup |
| --- | --- | --- |
| decay `setTimeout` | `useLivePulse` | изчиства се при unmount |
| WS + retry `setTimeout` | `usePacketStream` | `disposed` + `clearTimeout` + `ws.close()`; късен `onclose` е no-op |
| toast таймери (`Map`) | `ToastProvider` | unmount → изчистват се всички |
| `document` keydown Esc (capture) | `Modal` | `removeEventListener` + стек pop |
| `body` overflow/padding-right | `Modal` | възстановяват се запазените inline стойности (вложени модали OK) |
| предишен фокус | `Modal` | `prevFocus.focus()` ако още е в DOM |
| `document` keydown Esc | `Panel` (цял екран) | `removeEventListener` |

- **Нула re-render цикли**: `onClose`/`onDataBind`/`setPaused`/`push`/
  `dismiss`/`pause`/`resume`/`onData` са `useCallback`; паузата на toast-а
  работи изключително върху refs; WS ефектът зависи само от `[url, feedPulse]`
  (и двата стабилни); `pulsing` при вече-true не re-render-ва.
- **Overflow защита на стека**: toast макс 5 с изтласкване; live буферът
  остава отговорност на консуматора (Т14 държи `.slice(0, 300)`).

## Рискове и решения

1. **`color-mix(in srgb)`** изисква Chrome 111+ / Firefox 113+ / Safari 16.2+.
   Т1 вече разчита на него (`tr:hover`, `.tag.ok`, `.modal-back`) → не е нов
   риск за проекта, но го записваме като обща системна изискване.
2. **Drawer на мобилно** (<900px) побеждава inline `width` пропа с
   `width:100vw !important` — единственото `!important` в блока. Ако стане
   проблем: width да се подава като CSS var (`--mg-drawer-w`).
3. **`top: 52px`** в `.mg-panel__head` хардкод-ва височината на топбара от
   Т1 §4.1. Ако Т6 я смени — промяна на едно място; препоръка: при Т6 да стане
   токен (`--topbar-h`).
4. **Модул-стекът `OPEN_DIALOG_STACK`** е per-bundle: при HMR в dev може да
   останат стари symbol-и (без функционална последица — най-горният е
   винаги живият); в production е чисто.
5. **Изтласкан toast**: таймерът му изтича по-късно и вика `dismiss` по
   липсващ id — no-op за състоянието, но `Map` записът живее до тогава (≤10s).
   Съзнателен компромис за StrictMode-безопасен `push`.
6. **Без портал**: `.mg-toasts` е fixed в subtree-то на provider-а. Днешният
   шел няма `transform`/`filter`/`contain` на предшествениците (които биха
   преоразмерили fixed координатите); ако се появят — контейнерът се мести
   в края на `<body>` през createPortal (последна мярка).
7. **StatusChip е `<span>`** — не носи фокус; интерактивните фасет-чипове на
   Т14 остават `<button className="chip">` (классът от Т1) с anger focus-ring
   от базовия слой.
8. **`usePacketStream` паузата** бута `state` на `idle` синхронно с
   реалната връзка (`openRef`), не с предположение; при пауза + прекъсване
   показаният state е `reconnect` (честно: връзката СЕ свързва наново), а
   пристигащите рамки по време на пауза не пулсират (QA правило).
9. **Focus trap-ът** смята видимост през `getClientRects` — коректно за
   скрити табове, но focusable елемент в `display:none` би бил пропуснат
   (желано поведение). Ако диалогът зарежда съдържание асинхронно, началният
   фокус вече е поставен — първият Tab продължава от него.
10. **Z-стълба** (документирана в ui.css): топбар 5 < панел цял екран 8 <
    модал/дравер 10 < toast 20. Т6/Т14 не трябва да измислят нови номера —
    слотовете са заети.
