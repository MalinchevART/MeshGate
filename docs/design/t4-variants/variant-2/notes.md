# Т4 „Почистване inline hex → var(), част 1" — Вариант 2: Семантични CSS класове

Дата: 2026-10-28 · Подетап 1 (варианти) по docs/16-design-and-functionality-plan.md, точка Т4.
Обхват: `apps/web/src/pages/Monitor.tsx` (13 hex), `Devices.tsx` (2 hex + 11 rgba), `MapPage.tsx` (18 hex + 1 rgba), `PacketExplorer.tsx` (0 hex — **верифицирано**: grep на `#[0-9a-fA-F]{3,8}` връща 0; страницата вече е изцяло върху CSS класове `.tag/.chip/.mono`).

## Идеята на В2 в едно изречение

Цветовете слизат от TSX в `styles.css` като **семантични класове с `mg-` префикс** (схемата на Т3/Т6/Т9: `mg-card`, `mg-chip`, `mg-bars`…); TSX подава само име на клас или чисто число; динамичните случаи минават през CSS custom property, зададено от JS (`--a: 62` за интензитет, индекс на канал за палитрата), а стойността е винаги токен или веднъж декларирана палитра в CSS.

---

## 1. Инвентар — всеки hex/rgba в трите файла

### 1.1 Monitor.tsx (13 hex)

| файл:ред | стойност | роля | какво го поема в В2 |
|---|---|---|---|
| Monitor:39 | `#e06c75` | `KIND_COLOR.deadletter` — константа → `stroke` на SVG маркер | `KIND_COLOR` става `KIND_CLS: Record<string,string>` с клас-имена; тук `mg-anom--danger` → `var(--status-danger)` |
| Monitor:40 | `#35c5d8` | `KIND_COLOR.notify_sent` | `mg-anom--accent` → `var(--accent-primary)` |
| Monitor:41 | `#e06c75` | `KIND_COLOR.notify_failed` | `mg-anom--danger` (същият като deadletter — днес и двата са червени) |
| Monitor:42 | `#c792ea` | `KIND_COLOR.rule_publish` | `mg-anom--publish` → `var(--viz-purple)` (категорен, вж. §3.1) |
| Monitor:63 | `#35c5d8` | SVG атрибут `stopColor` (топ стоп на градиента на площта) | клас `.mg-spark-stop { stop-color: var(--accent-primary) }`; `stopOpacity="0.35"` остава атрибут (число, не цвят) |
| Monitor:64 | `#35c5d8` | `stopColor` (долен стоп) | същият клас `.mg-spark-stop` (`stopOpacity="0.02"` остава) |
| Monitor:68 | `#35c5d8` | SVG атрибут `stroke` на линията | `.mg-spark-line { stroke: var(--accent-primary) }` |
| Monitor:74 | `#9aa5b1` | fallback цвят за непознат `a.kind` | `?? 'mg-anom--muted'` → `var(--text-muted)` |
| Monitor:193 | `#e06c75` | inline `style.color` — легенда под графиката | reuse на Т3 `.mg-tone--danger` (вече съществува в 4.2) |
| Monitor:194 | `#35c5d8` | легенда | reuse `.mg-tone--accent` (съществува) |
| Monitor:195 | `#c792ea` | легенда | нов `.mg-tone--publish` (лилавият няма тон в Т3) |
| Monitor:214 | `#35c5d8` | inline `linear-gradient` на лентата „Разпределение по вид" | `.mg-dist-bar { background: linear-gradient(90deg, var(--accent-primary), var(--status-info)) }` |
| Monitor:214 | `#4a8fe0` | втори цвят на същия градиент | в същия клас → `var(--status-info)` |

Бонус (не е hex, но слиза на същото място): Monitor:211 и 233–234 ползват легаси псевдонимите `var(--panel2)`/`var(--accent)` — В2 ги обира с `.mg-bar-track` / `.mg-bar-fill` (2 опционални класа; намалява брояча на секция 6 LEGACY ALIASES за Т32).

### 1.2 Devices.tsx (2 hex + 11 rgba — „пулс клетките" от Т4)

| файл:ред | стойност | роля | какво го поема в В2 |
|---|---|---|---|
| Devices:304 | `#7bd88f` | легенда: квадратче „чуван чисто" | `.mg-pulse-swatch .mg-pulse-cell--clean` → `var(--status-success)` |
| Devices:305 | `#c792ea` (+ `rgba(199,146,234,.25)`) | легенда: шарка „само криптирано" | `.mg-pulse-swatch .mg-pulse-cell--encrypted` → `var(--viz-purple)` + color-mix |
| Devices:306 | `rgba(53,197,216,.6)` | легенда: „служебни" | `--service` с `--a: 60` |
| Devices:307 | `rgba(122,132,144,.2)` и `rgba(122,132,144,.3)` | легенда: „мълчание" (фон + outline) | `--silent` (приравнени на .16/.25 от клетката — разминаването днес е невидимо, вж. §5) |
| Devices:97 | `rgba(122,132,144,0.16)` | bg на мълчаща клетка (fallback клон) | `.mg-pulse-cell--silent` → `color-mix(var(--text-muted) 16%, transparent)` |
| Devices:98 | `rgba(123,216,143,${alpha})` | чисто; **динамичен интензитет** | `.mg-pulse-cell--clean` + `style={{ '--a': pct }}`; CSS: `color-mix(in srgb, var(--status-success) calc(var(--a,45) * 1%), transparent)` |
| Devices:99 | `rgba(199,146,234,${alpha})` ×2 | криптирана шарка; динамичен интензитет | `.mg-pulse-cell--encrypted`; целият `repeating-linear-gradient` слиза в CSS с `--a` и `--a*0.3` |
| Devices:100 | `rgba(53,197,216,${alpha})` | служебни; динамичен интензитет | `.mg-pulse-cell--service` + `--a` |
| Devices:104 | `rgba(122,132,144,0.25)` | outline на мълчаща клетка | в `.mg-pulse-cell--silent` |

Ключов механизъм: JS смята само числото `alpha = 0.45 + min(0.55, log10(total+1)*0.4)` и подава `--a` като процент (45–100); нито един rgba низ не се конкатенира вече в рендера на 140×24 клетки.

### 1.3 MapPage.tsx (18 hex + 1 rgba)

| файл:ред | стойност | роля | какво го поема в В2 |
|---|---|---|---|
| MapPage:25–26 | 10 hex: `#35c5d8 #e0a13a #7bd88f #c792ea #e06c75 #98c379 #61afef #e5c07b #d16d6d #56b6c2` | `CHANNEL_COLORS` — палитра, хеширана по име на канал | палитрата се декларира ВЕДНЪЖ в CSS като `--chan-0…9`; класове `.mg-chan-0…9` носят `color: var(--chan-N)`; формите пият `currentColor`; JS пада само индекс `h % 10` (вж. §3.2) |
| MapPage:29 | `#9aa5b1` | `channelColor(null)` — възел без канал | `.mg-chan-none` → `var(--text-muted)` |
| MapPage:46 | `#7d8590` | `snrQuality(null)` — SNR неизвестен | `.mg-snr--none` → `var(--text-muted)`, `--edge-w: 1` |
| MapPage:47 | `#7bd88f` | SNR силна (≥ −8 dB) | `.mg-snr--good` → `var(--status-success)`, `--edge-w: 2.5` |
| MapPage:48 | `#e0a13a` | SNR средна (≥ −15 dB) | `.mg-snr--mid` → `var(--status-warning)`, `--edge-w: 1.8` |
| MapPage:49 | `#e06c75` | SNR слаба (< −15 dB) | `.mg-snr--bad` → `var(--status-danger)`, `--edge-w: 1.2` |
| MapPage:247 | `#7bd88f` | легенда SNR „силна" | `.mg-snr-bar .mg-snr--good` (легендата и ребрата споделят класа — не могат да се разминат) |
| MapPage:247 | `#e0a13a` | легенда „средна" | `.mg-snr-bar .mg-snr--mid` |
| MapPage:247 | `#e06c75` | легенда „слаба" | `.mg-snr-bar .mg-snr--bad` |
| MapPage:138 | `rgba(53,197,216,0.10)` | SVG `stroke` на координатната мрежа | `.mg-map-grid` → `color-mix(in srgb, var(--accent-primary) 10%, transparent)` |

Небоядисани остатъци от цвета в MapPage, които В2 също обира (не са hex, затова QA не ги изисква, но са същият механизъм): `stroke={q.color}` (L162) → `class="mg-edge mg-snr--N"`; `fill={color}` на хало + точка (L181/183) → `.mg-map-node__halo`/`.mg-map-node` в `<g class="mg-chan-N">`; `fill={active ? color : 'var(--muted)'}` (L187) → `.mg-map-node-label(--active)`; `style={{color: snrQuality().color}}` (L216) → `.mg-snr--N`; `fill="var(--muted)"` (L144/147) → `.mg-map-label` — това премахва и 3 употреби на легаси псевдонима `--muted`.

Числа, които ОСТАВАТ в TSX (не са цветове): `fillOpacity={0.4 + 0.6*fresh}`, `opacity` на ребрата (0.55/0.95/0.15), `r`, координати, `--a`.

### 1.4 PacketExplorer.tsx — 0 hex (верифициран)

Единствените „цветни" неща са клас-низове (`'tag ok'`, `'tag bad'`, `'tag ch'`, `'chip active'`) — вече върху токени от Т1. Няма какво да се прави; В2 не го пипа.

---

## 2. Карта на заместване старо → токен

| стар hex/rgba | ново | бележка |
|---|---|---|
| `#35c5d8` (стар акцент) | `var(--accent-primary)` #22D3D9 | допустима палитрена смяна (QA: „промяна само в палитрата") |
| `#e06c75` | `var(--status-danger)` #FF626C | |
| `#7bd88f` | `var(--status-success)` #35D49A | |
| `#e0a13a` | `var(--status-warning)` #F5BE4F | точно правилото на Т1/риски №7: SNR е 3-цветна статусна скала, без нови цветови токени |
| `#4a8fe0` | `var(--status-info)` #63A9FF | |
| `#9aa5b1`, `#7d8590`, `rgba(122,132,144,…)` | `var(--text-muted)` #91A8BA + color-mix | трите сиви се уеднакватяват в един токен |
| `rgba(53,197,216,…)` | `var(--accent-primary)` + color-mix | |
| `#c792ea` | `var(--viz-purple)` #c792ea — категорен, НЕ статусен | вж. §3.1 |
| 10-цветната канална палитра | `--chan-0…9` — категорни | вж. §3.2 |

---

## 3. Дизайн на новите класове

### 3.1 Категорни цветове — единственият компромис

`#c792ea` (лилаво: криптирано в пулса + „публикувано правило" маркер) и 10-цветната канална палитра **нямат статусни токени и не могат да имат** — rule 7 забранява нови статусни токени, а палитра от 10 различими цвята не се извежда от 5-те токена със `color-mix`. В2 ги декларира като **категорни (data-viz) custom properties в самия блок 4.11**, НЕ в секция 1 TOKENS, с изричен коментар, че издигането им в TOKENS е решение на собственика (извън Т4). Така: TSX е 100% без hex (QA минава), hex стойностите в проекта остават само в styles.css, а статусните скали (SNR, батерии, deadletter) ползват САМО статусни токени — правилото на Т1 е честно спазено.

### 3.2 Каналната палитра (MapPage): клас + currentColor, не `--chan-color` от JS

Две алтернативи бяха разискани:
- (а) JS задава `style={{ '--chan-color': '#…' }}` — отхвърлено: връща hex обратно в TSX (QA гърми) или изисква JS да референцира `var(--chan-3)` като низ (крехко, тества се трудно);
- (б) **прието**: JS запазва хеша, но връща **индекс** (`channelColor → channelIdx`); класът `.mg-chan-N` носи `color: var(--chan-N)`; всички консуматори (SVG `fill`, `stroke`, HTML `background`) пият `currentColor`.

Така едната декларация обслужва: точка + хало + активен етикет на картата, легендата на каналите (`mg-chan-dot`), и е готова за Т11 (детайлен панел) без нови цветове.

### 3.3 SNR скалата (MapPage + бъдещи)

`.mg-snr--good/--mid/--bad/--none` задават `color` + `--edge-w` (дебелината на реброто върви с тона — днес са двойка от `snrQuality`). SVG реброто: `.mg-edge { stroke: currentColor; stroke-width: var(--edge-w, 1) }`, избраният възел добавя `.mg-edge--hot { stroke-width: calc(var(--edge-w,1) + 1.2) }`. Същите клас работят като цвят на текст в HTML (детайлният списък „Чута връзка") — нулева дублирация между легенда, ребра и текст.

### 3.4 Пълният списък нови класове (скица на декларациите)

Мястото: **нов подблок „4.11 DATA-VIZ · Т4" в края на секция 4 COMPONENTS** — след „4.10 LOGIN" (свършва ~ред 1384), преди секция 5 UTILITIES. Секциите на styles.css са подредени 4.0…4.10; Т4 append-ва 4.11, без да пипа съществуващ ред — точно правилото „следващите фази ДОБАВЯТ, не пренаписват" от шапката на файла.

```css
/* ====== 4.11 DATA-VIZ · Т4 (В2) ==========================================
   Цветовете на мониторинговите екрани (Monitor/Devices/MapPage) слизат
   от TSX тук. Статусните скали ползват САМО статусни токени (docs/16,
   правило 7). --chan-*/--viz-purple са КАТЕГОРНИ (визуализация), не
   статусни: живеят тук, докато собственикът не ги издигне в §1 TOKENS. */
:root {
  --viz-purple: #c792ea;                 /* криптирано / публикувано правило */
  --chan-0: #35c5d8; --chan-1: #e0a13a; --chan-2: #7bd88f; --chan-3: #c792ea;
  --chan-4: #e06c75; --chan-5: #98c379; --chan-6: #61afef; --chan-7: #e5c07b;
  --chan-8: #d16d6d; --chan-9: #56b6c2;
}

/* -- спарклайн (Monitor) -- */
.mg-spark-stop { stop-color: var(--accent-primary); }
.mg-spark-line { stroke: var(--accent-primary); }

/* -- маркери на аномалии (Monitor): KIND_CLS подава само тона -- */
.mg-anom--danger  { stroke: var(--status-danger); }
.mg-anom--accent  { stroke: var(--accent-primary); }
.mg-anom--publish { stroke: var(--viz-purple); }
.mg-anom--muted   { stroke: var(--text-muted); }
.mg-tone--publish { color:  var(--viz-purple); }   /* легендата до графиката */

/* -- лента „Разпределение по вид" (Monitor) -- */
.mg-dist-bar { background: linear-gradient(90deg,
  var(--accent-primary), var(--status-info)); }

/* -- пулс клетки (Devices): геометрия в базите, цвят в модификаторите;
     интензитетът е ЧИСЛО от JS: style={{ '--a': 62 }} (процент) -- */
.mg-pulse-cell   { display: inline-block; width: 7px;  height: 14px; border-radius: 2px; }
.mg-pulse-swatch { display: inline-block; width: 8px;  height: 10px; border-radius: 2px; }
.mg-pulse-cell--clean {
  background: color-mix(in srgb, var(--status-success) calc(var(--a, 45) * 1%), transparent); }
.mg-pulse-cell--encrypted {
  background: repeating-linear-gradient(45deg,
    color-mix(in srgb, var(--viz-purple) calc(var(--a, 45) * 1%), transparent) 0 2px,
    color-mix(in srgb, var(--viz-purple) calc(var(--a, 45) * 0.3 * 1%), transparent) 2px 4px); }
.mg-pulse-cell--service {
  background: color-mix(in srgb, var(--accent-primary) calc(var(--a, 45) * 1%), transparent); }
.mg-pulse-cell--silent {
  background: color-mix(in srgb, var(--text-muted) 16%, transparent);
  outline: 1px solid color-mix(in srgb, var(--text-muted) 25%, transparent);
  outline-offset: -1px; }

/* -- SNR тоналност (MapPage: ребра, легенда, текст; 3-цветна по правило 7) -- */
.mg-snr--good { color: var(--status-success); --edge-w: 2.5; }
.mg-snr--mid  { color: var(--status-warning); --edge-w: 1.8; }
.mg-snr--bad  { color: var(--status-danger);  --edge-w: 1.2; }
.mg-snr--none { color: var(--text-muted);     --edge-w: 1;   }

/* -- карта (MapPage): каналът е клас, формите пият currentColor -- */
.mg-chan-0 { color: var(--chan-0); } /* … ×10 … */ .mg-chan-9 { color: var(--chan-9); }
.mg-chan-none { color: var(--text-muted); }

.mg-map-grid  { stroke: color-mix(in srgb, var(--accent-primary) 10%, transparent); }
.mg-map-label { fill: var(--text-muted); }

.mg-edge      { stroke: currentColor; stroke-width: var(--edge-w, 1); }
.mg-edge--hot { stroke-width: calc(var(--edge-w, 1) + 1.2); }
.mg-snr-bar   { display: inline-block; width: 14px; height: 3px;  border-radius: 2px; background: currentColor; }
.mg-chan-dot  { display: inline-block; width: 10px; height: 10px; border-radius: 5px; background: currentColor; }

.mg-map-node               { fill: currentColor; }
.mg-map-node__halo         { fill: currentColor; fill-opacity: 0.18; }
.mg-map-node-label         { fill: var(--text-muted); }
.mg-map-node-label--active { fill: currentColor; }
```

Пример за TSX страната (устройът се запазва, цветовете изчезват):

```tsx
// Monitor: KIND_COLOR → KIND_CLS (низове, не цветове)
const KIND_CLS: Record<string, string> = {
  deadletter: 'mg-anom--danger', notify_sent: 'mg-anom--accent',
  notify_failed: 'mg-anom--danger', rule_publish: 'mg-anom--publish',
}
<line className={KIND_CLS[a.kind] ?? 'mg-anom--muted'} strokeWidth="1.5" … />

// Devices: клетка = клас + число
const pct = Math.round((0.45 + Math.min(0.55, Math.log10(total + 1) * 0.4)) * 100)
<span className={cls} style={{ '--a': pct }} />

// MapPage: канал = индекс, SNR = тон
<g className={`mg-chan-${channelIdx(n.channel)}`}>
  <circle className="mg-map-node__halo" …
<line className={`mg-edge mg-snr--${snrTone(e.snr_avg)}${hot ? ' mg-edge--hot' : ''}`} …
```

### 3.5 Бройка

- **Нови класове: 39 задължителни** (+2 опционални `.mg-bar-track`/`.mg-bar-fill` за легаси `--panel2`/`--accent` в Monitor):
  - Monitor 8: `mg-spark-stop`, `mg-spark-line`, `mg-anom--danger/--accent/--publish/--muted`, `mg-tone--publish`, `mg-dist-bar`;
  - Devices 6: `mg-pulse-cell`, `mg-pulse-swatch`, `--clean/--encrypted/--service/--silent`;
  - MapPage 25: `mg-chan-0…9` (10), `mg-chan-none`, `mg-snr--good/--mid/--bad/--none` (4), `mg-map-grid`, `mg-map-label`, `mg-edge`, `mg-edge--hot`, `mg-snr-bar`, `mg-chan-dot`, `mg-map-node`, `mg-map-node__halo`, `mg-map-node-label`, `mg-map-node-label--active`.
- **Нови custom properties: 11** (`--chan-0…9`, `--viz-purple`) + 2 служебни за дебелина (`--edge-w` се задава от `.mg-snr--*`, не от JS).

---

## 4. Къде В2 печели и къде губи спрямо В1 (директна замяна hex → var())

**Печели:**
1. **SVG атрибутите стават надеждни.** CSS декларация бие presentation attribute (`fill=`, `stroke=`, `stop-color=`) по спецификация — стабилно във всички браузъри; при В1 атрибутът остава атрибут и всяка бъдеща промяна изисква пипане на TSX отново.
2. **Легендите не могат да се разминат с данните.** Днес легендата на Devices е ръчно дублирана (клетка `.16/.25` vs легенда `.2/.3`; шарка `α` vs `.25`) — при В2 легендата е същите класове с фиксирано `--a`. Същото за SNR легендата на картата (`.mg-snr-bar` + `.mg-snr--N` = точният тон на реброто).
3. **Динамиката става число.** Интензитетът на пулса и хешът на канала остават чисти числа/индекси (`--a: 62`, `mg-chan-3`); нито един rgba низ не се шаблонизира в рендера на 140×24 клетки — по-малко GC натоварване и никакъв шанс за правописна грешка в цвят.
4. **По-малко повторения.** `snrQuality` връща тон-низ вместо `{color, w}` двойка; `KIND_COLOR` става клас-мап; `CHANNEL_COLORS` масив изчезва от TSX изобщо.
5. **Надграждане:** `.mg-snr--*` е готова за Т11 (детайлен панел) и Т28/Т29 (водопад/ефир — SNR оцветяване); `.mg-chan-*` — за Т9 пончика и Т11. В1 би оставил всяка следваща фаза да копира var() низове.
6.color-mix извежда всички полупрозрачности от токени — „нула дублирани hex стойности" е изпълнено и за rgba-та (не само за hex).

**Губи:**
1. **Повече CSS:** ~110 реда в styles.css (39 класа + палитра) срещу 0 при В1.
2. **По-голям diff в TSX:** не се заменят стойности, а се пренаписват елементи (махат се цели inline стилове и атрибути) — по-висок риск от регресия при „механичната" цел на Т4; изисква по-внимателна жива обиколка.
3. **Имената стават API:** 39 нови публични класа се поддържат завинаги; преименуване = синхронен търсен в TSX.
4. **Категорните цветове не изчезват**, а се местят (палитра + лилаво остават 11 hex стойности в styles.css). В1 с тях би се справил още по-зле — или щеше да ги остави в TSX (QA гърми), или да нанесе произволни статусни токени върху 10-цветна палитра (неразличими канали).

## 5. Взаимодействия

- **Легаси CSS/specificity:** новите имена са уникални (`mg-pulse-*`, `mg-chan-*`, `mg-snr-*`, `mg-map-*`, `mg-anom-*`, `mg-spark-*` — никое не се среща в styles.css към 2026-10-28); не се засичат с `.tag/.chip/.card/.panel/.muted/.small/.mono` нито с глобалните `button`/`input` стилове (легендите са span/g/line). `.mono` върху SVG `<text>` задава само шрифт — безопасно с `fill` от клас. Нито един селектор в styles.css не таргетира `line/circle/stop` глобално.
- **currentColor веригата** (`g.mg-chan-N → circle/line/text`) е единственият чувствителен момент: ако някой предците зададе `color`, той печели; проверено — картата няма наследник с `color` освен body (`--text-primary`), а `g` класът е най-близкият.
- **Приравнявания на стойности (видими само под лупа):** легенда-мълчание `.2/.3` → `.16/.25`; шарка в легендата `α=.25` → `α*0.3`; трите сиви (`#9aa5b1/#7d8590/#7a8490`) → `--text-muted`. Всички в границите на „промяна само в палитрата".
- **Тестове:** всички тестове в repo-то са Python (16 файла, backend) — grep за `styles.css|className|PulseStrip|KIND_COLOR|channelColor|snrQuality` в тестовете връща 0 попадения. Т4/В2 е тестово неутрален; QA остава `tsc -b && vite build` + жива обиколка + „hex в четирите TSX = 0".
- **Легаси псевдоними (секция 6):** В2 допълнително маха ≥5 употреби на `--muted`/`--panel2`/`--accent` (MapPage 3× `var(--muted)`, Monitor 2× `--panel2`/1× `--accent` при опционалните класове) — броячът за Т32 намалява.

## 6. Присъда

В2 е **препоръчваният вариант за Т4**. Обхватът на Т4 не е случайна колекция от hex-и, а три екрана, в които цветът е семантика (категория трафик, SNR качество, канал) и където легенда + данни днес се дублират ръчно — точно това В2 премахва структурно, докато В1 (директна замяна) оставя дублирането и би изисквал същите класове отново при Т11/Т13/Т14. Цената (~110 реда CSS, 39 класа, по-дълъг TSX diff) се плаща веднъж и се амортизира в етапи 3–7. Двете изрични бележки към собственика: (1) категорната палитра `--chan-0…9` + `--viz-purple` живее в 4.11, НЕ в секция 1 TOKENS — издигането ѝ е решение извън Т4; (2) търпи се микро-приравняване на легендарните алфи и сивите нюанси (§5). Риск за „механичност": среден (по-дълбок TSX diff от В1) — затова подетап 2 трябва да мине файл по файл с жива обиколка на трите екрана.
