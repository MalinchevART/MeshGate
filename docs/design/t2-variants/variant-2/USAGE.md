# Т2 „Лого + favicon" — Вариант 2 „React компонент + файл favicon"

Символът „Mesh Triangle" живее в **един TS компонент** (`Brand.tsx`) като
inline SVG с цветове през токена `--accent-primary`, а **favicon-ът е
отделен статичен SVG файл** — браузърът го иска от `/favicon.svg` още преди
React да е зареден, така че той не може (и не бива) да зависи от компонента.
Wordmark-ът „MeshGate" и таглайнът са **HTML текст**, не SVG `<text>`.

## Файлова карта (къде отива какво при внедряване)

| Файл тук | Дестинация | Бележка |
| --- | --- | --- |
| `Brand.tsx` | `apps/web/src/components/Brand.tsx` | нула импорти, нула нови пакети (само react-jsx runtime от tsconfig) |
| `favicon.svg` | `apps/web/public/favicon.svg` | Vite сервира `public/` от корена → `/favicon.svg` |
| `index-head.html` | фрагмент в `<head>` на `apps/web/index.html`, след `<title>` | 2 реда + по избор PNG резерв |

## Интеграция в App.tsx — замяна на текущия `◈` глиф

Отгоре в `apps/web/src/App.tsx` се добавя един импорт:

```tsx
import { BrandMark, BrandLockup } from './components/Brand'
```

### 1. Топбар (App.tsx, блокът `.brand` — днес L116–119)

ПРЕДИ:

```tsx
<div className="brand">
  <span className="brand-mark">◈</span> MeshGate
  <span className="pill">{me.role}</span>
</div>
```

СЛЕД (Lockup — „Gate" в акцент, както в мастър логото):

```tsx
<div className="brand">
  <BrandLockup size={22} />
  <span className="pill">{me.role}</span>
</div>
```

Алтернативно — само символа, ако топбарът трябва да си остане плътно бял текст
(тогава `.brand-word-gate` не се консумира тук):

```tsx
<div className="brand">
  <BrandMark size={22} /> MeshGate
  <span className="pill">{me.role}</span>
</div>
```

`size={22}`: символът е с пропорции 194:143 → видимата му височина е ~16px,
колкото 16px текста на `.brand` — визуално се изравняват, а щрихът от 12
единици се рендира ~1.4px (над прага на изчезване).

### 2. Login (App.tsx, блока `.login` — днес L211–212)

ПРЕДИ:

```tsx
<h1><span className="brand-mark">◈</span> MeshGate</h1>
<p className="muted">MQTT Gateway & Management</p>
```

СЛЕД:

```tsx
<h1><BrandLockup size={30} showTagline /></h1>
<p className="muted">MQTT Gateway & Management</p>
```

- `size={30}` — по-голям hero-мащаб за login картата; теглото/размерът на
  текста идват наготово от `.login h1` (20px / 600 — в диапазона 600–700 от
  мастър спецификацията).
- `showTagline` — „MONITOR / MANAGE / CONNECT" се реджа под wordmark-а,
  подравнен с началото на „MeshGate" (grid, виж CSS-а). По плана за Т2
  таглайнът е **само на Login**; топбарът го изключва.
- Редът „MQTT Gateway & Management" може да остане — той е описание, а
  таглайнът е бренд ритъм; ако е твърде шумно, той е първият за съкращаване.

## CSS фрагмент — предложение за styles.css (НЕ е добавян в живия файл)

Слага се като нов подблок в секция **4 COMPONENTS** (напр. „4.0 BRAND"),
точно преди SHELL. Консумира се само от `Brand.tsx`; нула нови цветове —
само съществуващи токени + едно ново letter-spacing число:

```css
/* -- 4.0 BRAND LOCKUP (Т2 · вариант 2) — консумира се от components/Brand.tsx;
      wordmark-ът е HTML текст → fs/weight наследява от контекста (.brand / .login h1) -- */
.brand-lockup {
  display: inline-grid;
  grid-template-columns: auto auto; /* кол. 1 = символ, кол. 2 = текст */
  column-gap: var(--space-2);       /* 8px — същото като .brand gap */
  row-gap: 2px;
  align-items: center;
}
/* символът временно заема и двата реда — таглайнът (ако го има) застава
   в колона 2, ред 2 → подравнен с началото на „MeshGate", без magic числа */
.brand-lockup .brand-mark { grid-row: 1 / span 2; }

.brand-word { color: var(--text-primary); }        /* „Mesh" */
.brand-word-gate { color: var(--accent-primary); } /* „Gate“ в акцент */

.brand-tagline {
  font-family: var(--font-mono);
  font-size: var(--fs-12);        /* нищо под 12px — правилото на системата */
  color: var(--text-muted);
  letter-spacing: 2.2px;
  white-space: nowrap;
}
```

Съответствия с мастър спецификацията (осъзнати отстояния от нея в името на
единния източник на токени):

- „Mesh" `#F3F7FA` → `var(--text-primary)` = `#E6F0F7` — почти идентични;
  печели се тематичен токен вместо втори бял.
- Таглайн `#D9E8F1` → `var(--text-muted)` = `#91A8BA` — контраст ~7:1 върху
  `--bg-surface` (AA на 12px с запас); ако ревюто иска по-светло, сменя се
  на `var(--text-primary)` на едно място.
- Съществуващият клас `.brand-mark { color: var(--accent-primary) }` вече
  се „попада" от SVG-а (`className="brand-mark"`) и остава безвреден.

## Защо HTML текст > SVG `<text>` за wordmark-а

1. **Шрифтът е зареден само в HTML каскадата.** IBM Plex Sans е self-hosted
   `@font-face` в styles.css; inline `<text>` би го взел, но всеки опит да се
   изнесе логото като самостоятелен SVG (експорт, docs, favicon) губи шрифта
   и моли за outline на буквите = тежък файл с вдигната поддръжка.
2. **Един източник на токените.** Цвят, тегло, размер на текста идват от
   същите CSS токени (`--text-primary`, `--accent-primary`, `.brand`/`.login h1`)
   — смяна на тема/типография минава на нула места в компонента. В SVG
   `<text>` същите стойности се дублират като атрибути.
3. **Реален текст = реален достъпност/търсене/превод** — избира се, чете се
   от четеци, копира се; SVG текстът е графика с по-слаба a11y поддръжка.
4. **Фокус на файла:**BrandMark остана чист вектор „символ-само" — той се
   преизползва 1:1 и като favicon, без думи в пътя.

## QA чеклист (по критериите на Т2)

- [ ] `tsc -b && vite build` чисто (компонентът е нула-импортен, strict-ready;
      цветове през inline `style`, защото `var()` в SVG presentation
      атрибути не е надеждно поддържан от браузърите).
- [ ] Символът е 1:1 от мастъра: пътища/радиуси/deбелини непокътнати; само
      цветът минава през `var(--accent-primary, #22D3D9)` с fallback.
- [ ] Четимост на 24px: щрих 12 → ~1.5px, възлите видими; връзките от 4
      (~0.5px на 24px, ~0.33px на favicon 16px) са съзнателна текстура —
      разпознаваемостта носят двата триъгълника и възлите.
- [ ] Favicon се появява в таб (твърд refresh — браузърите кешират агресивно);
      theme-color оцветява мобилната рамка в `#07131F`.
- [ ] Топбар: вертикално изравняване на символа с 16px текста; Login:
      таглайнът подравнен с „MeshGate", `showTagline` изключен в топбара.
