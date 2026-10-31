/* MeshGate — Т2 „Лого + favicon": бренд компоненти (съчетание В2+В1).
 * =====================================================================
 * НУЛА импорти: tsx-runtime е „react-jsx" (apps/web/tsconfig.json),
 * типовете на React идват глобално от @types/react.
 *
 * Символът „Mesh Triangle" е преписан 1:1 от мастър логото — пътищата,
 * радиусите и дебелините са непокътнати; цветът минава през токена
 * --accent-primary (с literal fallback #22D3D9 за контекст без CSS каскада).
 *
 * ВАЖНО (технически детайл): var() в SVG presentation attributes
 * (напр. stroke="var(--x)") не се поддържа надеждно от браузърите —
 * затова цветът се задава през inline style (CSSOM), а не през атрибут.
 */

/** Цвят на целия символ (щрихи + възли) — едно място, нула дублирани стойности. */
const ACCENT = 'var(--accent-primary, #22D3D9)'

/** viewBox, изчислен върху реалните граници на щрихите на символа
 * (miter-ъглите и square-капсите стърчат извън пътя с до ~12 единици,
 * възлите с радиуса си): x 24.6–212.7, y 35.9–173 + ~3 ед. поле.
 * Съотношение 194:143 — на 24px щрихът от 12 става ~1.5px (четимо),
 * а връзките от 4 оставят ~0.5px текстура (не са носещи линии). */
const SYMBOL_VIEWBOX = '22 33 194 143'

export interface BrandMarkProps {
  /** Рендерирани размери в px (квадратно поле; символът се побира в него
   * с letterbox, защото е по-широк от висок). По подразбиране 24. */
  size?: number
  /** Достъпно име на изображението; без него символът е декоративен
   * (aria-hidden) — така е редно до текстов wordmark. */
  title?: string
}

/** Само символът „Mesh Triangle" като inline SVG — за топбар и бъдещи
 * употреби. Класът .brand-mark е наследен от стария текстов глиф ◈
 * ( color: var(--accent-primary) в styles.css ) — безвреден е тук. */
export function BrandMark({ size = 24, title }: BrandMarkProps) {
  return (
    <svg
      className="brand-mark"
      width={size}
      height={size}
      viewBox={SYMBOL_VIEWBOX}
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      {title && <title>{title}</title>}
      {/* два припокриващи се триъгълника — stroke 12, square caps, fill none */}
      <g
        fill="none"
        strokeWidth={12}
        strokeLinecap="square"
        style={{ stroke: ACCENT }}
      >
        <path d="M35 166 L102 48 L170 166" />
        <path d="M73 166 L137 58 L202 166" />
      </g>
      {/* връзки от централния възел надолу — stroke 4 (текстура, не носеща линия) */}
      <path
        d="M73 119 L48 166 M73 119 L102 166"
        fill="none"
        strokeWidth={4}
        style={{ stroke: ACCENT }}
      />
      {/* възли (кръгове), плътни — периферията на mesh-а */}
      <g style={{ fill: ACCENT }}>
        <circle cx="102" cy="48" r="8" />
        <circle cx="137" cy="58" r="7" />
        <circle cx="73" cy="119" r="10" />        <circle cx="170" cy="166" r="7" />
        <circle cx="202" cy="166" r="7" />
      </g>
    </svg>
  )
}

export interface BrandLockupProps {
  /** Размер на BrandMark в px. Текстът НЕ мащабира оттук — наследява
   * fs/weight от контекста (.brand → 16/600 в топбара, .login h1 → 20/600),
   * та типографията да има един източник. По подразбиране 22 (топбар). */
  size?: number
  /** Долен ред „MONITOR / MANAGE / CONNECT" — по плана за Т2 само на Login. */
  showTagline?: boolean
}

/** Символ + HTML-text wordmark (+ незадължителен таглайн).
 * Wordmark-ът е HTML <span>, не SVG <text>: IBM Plex Sans е self-hosted
 * @font-face в HTML каскадата, а цветовете/теглото идват от същите
 * токени като навсякъде. */
export function BrandLockup({ size = 22, showTagline = false }: BrandLockupProps) {
  return (
    <span className="brand-lockup">
      <span className="brand-lockup-row">
        <BrandMark size={size} />
        <span className="brand-word">
          Mesh<span className="brand-word-gate">Gate</span>
        </span>
      </span>
      {showTagline && (
        <span className="brand-tagline">MONITOR / MANAGE / CONNECT</span>
      )}
    </span>
  )
}
