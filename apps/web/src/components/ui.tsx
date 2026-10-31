/* ============================================================================
 * MeshGate · Т3 „Базови компоненти" — Вариант 2
 * „Платформени примитиви с коректен жизнен цикъл"
 * ----------------------------------------------------------------------------
 * Дестинация при внедряване: apps/web/src/components/ui.tsx
 * Стилове:                          variant-2/ui.css → секции 4.2/4.3/4.5/
 *                                    4.7/4.8 на apps/web/src/styles.css
 *
 * Стратегия В2: пълноценна платформа, не сглобки за един случай —
 *   · StatusChip  — тон → (токен, глиф); цвят + икона + текст ВИНАГИ;
 *                   flat за плътни таблици; sm/md (и двата ≥ 12px);
 *   · MetricCard  — име/стойност/тон/контекст; еднаква височина в grid ред;
 *   · Panel       — заглавие + filters/actions слотове (ReactNode) + ⛶
 *                   цял екран (Esc изход);
 *   · Modal/Drawer — focus trap (Tab цикъл), aria-modal, Esc, scroll lock
 *                   на body, възстановяване на фокуса, стек от модали;
 *   · ToastProvider/useToast — push(tone, message, opts) → id; стек макс 5
 *                   с изтласкване; авто-dismiss 6s (danger 10s); pause на
 *                   hover; action бутон; aria-live region; без createPortal;
 *   · LiveIndicator + useLivePulse() — пулс САМО при свържи данни
 *                   (decay 1.5s); hook-ът не знае нищо за WebSocket;
 *   · usePacketStream() — готов WS живот за /api/v1/packets/ws:
 *                   { state, pulsing, paused, setPaused, onDataBind } —
 *                   миграцията на Т14 е с ~1 ред.
 *
 * Правила (Т1 система): само токени (нула hex), тинтове през
 * color-mix(in srgb, var(--…) N%, transparent), нищо под 12px, без сенки,
 * 1px граници var(--border-default), radius 4/8/12, .mono за ID/topic,
 * tabular-nums за числа. НУЛА нови npm пакети — само react/react-dom.
 *
 * TypeScript: strict (apps/web/tsconfig.json); jsx: react-jsx → нулев
 * JSX импорт; типовете на React идват глобално от @types/react (както в
 * App.tsx / components/Brand.tsx).
 * ========================================================================== */
import {
  useCallback,
  createContext,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from 'react'

/* ============================================================================
 * 0. ОБЩИ ТИПОВЕ + рецеппи
 * ========================================================================== */

/** Семантичен тон — един списък за чипове, карти и Live състояния.
 *  „neutral" е неутралният (text-muted), останалите са статусните токени. */
export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'accent' | 'neutral'

/** Състояние на жив поток: жив / спрял (пауза или затворен) / свързва се. */
export type LiveState = 'live' | 'idle' | 'reconnect'

/** Глиф по подразбиране за всеки тон — чипът винаги има икона + цвят + текст,
 *  така че тонът не се носи само от цвета (WCAG 1.4.1). */
const TONE_GLYPH: Record<Tone, string> = {
  success: '✓',
  warning: '⚠',
  danger: '✕',
  info: 'ℹ',
  accent: '◆',
  neutral: '•',
}

/* ============================================================================
 * 1. StatusChip — тон → (токен, глиф); винаги цвят + икона + текст
 * ========================================================================== */

export interface StatusChipProps {
  /** Тон: статусните токени от Т1 + accent + neutral (default). */
  tone?: Tone
  /** Собствен глиф/икона вместо този по подразбиране. */
  icon?: React.ReactNode
  /** Плосък вариант за плътни таблици: без тинт-фон, неутрална граница —
   *  цветът остава носещ (виж .mg-chip--flat). */
  flat?: boolean
  /** sm — плътно за клетки; md — стандартно. И двата са 12px текст
   *  (подовата граница на системата); разликата е в уплътняването. */
  size?: 'sm' | 'md'
  /** Съдържанието е Node ID / topic / packet id → JetBrains Mono. */
  mono?: boolean
  /** Tooltip (напр. „филтрирай по този канал"). */
  title?: string
  children: React.ReactNode
}

export function StatusChip({
  tone = 'neutral',
  icon,
  flat = false,
  size = 'md',
  mono = false,
  title,
  children,
}: StatusChipProps) {
  const cls = [
    'mg-chip',
    `mg-chip--${tone}`,
    flat ? 'mg-chip--flat' : '',
    size === 'sm' ? 'mg-chip--sm' : '',
    mono ? 'mg-chip--mono' : '',
  ]
    .filter(Boolean)
    .join(' ')
  return (
    <span className={cls} title={title}>
      <span className="mg-chip__icon" aria-hidden="true">
        {icon ?? TONE_GLYPH[tone]}
      </span>
      <span className="mg-chip__text">{children}</span>
    </span>
  )
}

/* ============================================================================
 * 2. MetricCard (alias: Metric) — KPI карта с еднаква височина в grid ред
 * ========================================================================== */

export interface MetricCardProps {
  /** Име на метриката — .metric-label (12px uppercase muted, Т1 §3.6). */
  label: React.ReactNode
  /** Стойност — .metric-value (24px/600, tabular-nums, Т1 §3.5). */
  value: React.ReactNode
  /** Тон оцветява СТОЙНОСТТА (и иконата); neutral = text-primary. */
  tone?: Tone
  /** Контекст ред — 12px muted, закован долу (margin-top: auto) → всички
   *  карти в един grid ред са с еднаква височина, контекстът се изравнява. */
  context?: React.ReactNode
  /** Декоративна икона до името (aria-hidden). */
  icon?: React.ReactNode
  align?: 'left' | 'center'
  /** Стойността е ID/текст с фиксирана ширина → mono на 24px. */
  mono?: boolean
  className?: string
}

export function MetricCard({
  label,
  value,
  tone = 'neutral',
  context,
  icon,
  align = 'left',
  mono = false,
  className = '',
}: MetricCardProps) {
  const rootCls = ['mg-card', `mg-card--${align}`, className].filter(Boolean).join(' ')
  const valueCls = [
    'mg-card__value',
    'metric-value',
    tone !== 'neutral' ? `mg-tone--${tone}` : '',
    mono ? 'mg-card__value--mono' : '',
  ]
    .filter(Boolean)
    .join(' ')
  return (
    <div className={rootCls}>
      <div className="mg-card__head">
        {icon != null && (
          <span className={`mg-card__icon${tone !== 'neutral' ? ` mg-tone--${tone}` : ''}`} aria-hidden="true">
            {icon}
          </span>
        )}
        <span className="mg-card__label metric-label">{label}</span>
      </div>
      <div className={valueCls}>{value}</div>
      {context != null && <div className="mg-card__context">{context}</div>}
    </div>
  )
}

/** Кратко име за KPI редовете на Т9. */
export { MetricCard as Metric }

/* ============================================================================
 * 3. Panel — заглавие + filters/actions слотове + цял екран (⛶ / Esc)
 * ========================================================================== */

export interface PanelProps {
  title: React.ReactNode
  /** Подзаглавие под главното (12px muted) — напр. „последни 24 ч". */
  subtitle?: React.ReactNode
  /** Слот за филтър/период-селектор — ReactNode. */
  filters?: React.ReactNode
  /** Слот за допълнителни действия (бутони) — ReactNode. */
  actions?: React.ReactNode
  /** Показва бутон ⛶ за цял екран (default true). При цял екран: fixed
   *  inset 0, z-index НАД топбара (топбар е z 5, модалите са z 10),
   *  Esc излиза. */
  fullscreen?: boolean
  children: React.ReactNode
  /** Изключва padding-а на тялото (напр. edge-to-edge таблици). */
  padded?: boolean
  className?: string
}

export function Panel({
  title,
  subtitle,
  filters,
  actions,
  fullscreen = true,
  children,
  padded = true,
  className = '',
}: PanelProps) {
  const [isFull, setFull] = useState(false)
  const bodyId = useId()

  // Esc изход от цял екран. Модал/дравер над панела ще спре разпростране-
  // нието по-рано (document capture + stopPropagation) → тук не се достига.
  useEffect(() => {
    if (!isFull) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setFull(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [isFull])

  const rootCls = [
    'mg-panel',
    isFull ? 'mg-panel--fs' : '',
    padded ? '' : 'mg-panel--flush',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  const hasTools = filters != null || actions != null || fullscreen

  return (
    <section className={rootCls} id={bodyId}>
      <header className="mg-panel__head">
        <div className="mg-panel__heading">
          <h2 className="mg-panel__title panel-title">{title}</h2>
          {subtitle != null && <div className="mg-panel__subtitle">{subtitle}</div>}
        </div>
        {hasTools && (
          <div className="mg-panel__tools">
            {filters != null && <div className="mg-panel__filters">{filters}</div>}
            {actions != null && <div className="mg-panel__actions">{actions}</div>}
            {fullscreen && (
              <button
                type="button"
                className="mg-icon-btn"
                aria-expanded={isFull}
                aria-controls={bodyId}
                title={isFull ? 'Изход от цял екран (Esc)' : 'Цял екран'}
                onClick={() => setFull((v) => !v)}
              >
                {isFull ? '✕' : '⛶'}
              </button>
            )}
          </div>
        )}
      </header>
      <div className="mg-panel__body">{children}</div>
    </section>
  )
}

/* ============================================================================
 * 4. Modal / Drawer — focus trap + aria-modal + Esc + scroll lock + стек
 * ========================================================================== */

/** Селектор за фокусируеми елементи (фокус-капана и началният фокус). */
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), [contenteditable]:not([contenteditable="false"]), ' +
  '[tabindex]:not([tabindex="-1"])'

/** Видими (рендерирани) фокусируеми елементи в контейнера. */
function focusableIn(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (el) => el.getClientRects().length > 0,
  )
}

/** Стек на отворените диалози (module scope): Esc го обработва САМО
 *  най-горният — вложен модал/дравер не затваря този под себе си.
 *  Легаси .modal-back модалите (ChangePassword/Onboarding/Profiles/
 *  PacketExplorer детайл) още не влизат в стека — Едно Esc би затворило
 *  долния <Modal> под тях; недостижимо днес (бекдрапът блокира), решава
 *  се с миграцията им в Т11/Т14. */
const OPEN_DIALOG_STACK: symbol[] = []

/** Скрол-ключ на body: ПЪРВИЯТ отворен диалог записва pristine
 *  стойностите, ПОСЛЕДНИЯТ затворен ги възстановява — коректно при
 *  всякакъв ред на отваряне/затваряне (не само LIFO). */
const SCROLL_LOCK_SAVED: { overflow: string; padRight: string } = { overflow: '', padRight: '' }
let scrollLockSaved = false

export interface ModalProps {
  open: boolean
  onClose: () => void
  title?: React.ReactNode
  children: React.ReactNode
  /** Футър — слот за бутони (Подаване/Отказ). */
  footer?: React.ReactNode
  /** 'modal' (центриран, default) | 'drawer' (страничен панел). */
  variant?: 'modal' | 'drawer'
  /** Страна на drawer-а (само при variant='drawer'); default 'right'.
   *  Под 900px drawer-ът е на цял екран (виж ui.css). */
  side?: 'left' | 'right'
  /** CSS ширина (число → px). Default: modal 720px, drawer 480px. */
  width?: number | string
  /** Затваряне при клик на фона (default true). */
  closeOnBackdrop?: boolean
  className?: string
}

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  variant = 'modal',
  side = 'right',
  width,
  closeOnBackdrop = true,
  className = '',
}: ModalProps) {
  const dlgRef = useRef<HTMLDivElement | null>(null)
  const titleId = useId()

  // onClose често е inline стрелка в консуматора — държим я в ref, за да
  // НЕ рестартираме ефекта (фокус, scroll lock) при всеки рендер на родителя.
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  const resolvedWidth = width == null ? undefined : typeof width === 'number' ? `${width}px` : width

  useEffect(() => {
    if (!open) return
    const dlg = dlgRef.current
    if (!dlg) return

    // 1) запомняме предишния фокус → възстановяваме при затваряне
    const prevFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null

    // 2) scroll lock на body + компенсация на изчезналия скролбар.
    //    Pristine стойностите се записват от ПЪРВИЯ диалог (виж
    //    SCROLL_LOCK_SAVED горе) — вложени/паралелни диалогове в
    //    произволен ред не се късат.
    const body = document.body
    if (!scrollLockSaved) {
      SCROLL_LOCK_SAVED.overflow = body.style.overflow
      SCROLL_LOCK_SAVED.padRight = body.style.paddingRight
      scrollLockSaved = true
    }
    const scrollbarW = window.innerWidth - document.documentElement.clientWidth
    body.style.overflow = 'hidden'
    if (scrollbarW > 0) body.style.paddingRight = `${scrollbarW}px`

    // 3) регистрираме се в стека на отворените диалози
    const key = Symbol('mg-dialog')
    OPEN_DIALOG_STACK.push(key)

    // 4) Esc + Tab — listeners на document в CAPTURE фаза: хващат се преди
    //    всички bubble хендлъри (напр. Esc-изхода на панел в цял екран) и
    //    преди останалите диалози; stopPropagation гаси по-нататъшната
    //    обработка. Tab е тук, а не на контейнера, защото фокусът може да
    //    е избягал на body (програмен blur) — тогава keydown не минава
    //    през диалога и капанът трябва да го върне отвън.
    const onKey = (e: KeyboardEvent) => {
      if (OPEN_DIALOG_STACK[OPEN_DIALOG_STACK.length - 1] !== key) return
      if (e.key === 'Escape') {
        e.stopPropagation()
        onCloseRef.current()
        return
      }
      if (e.key !== 'Tab') return
      const focusables = focusableIn(dlg)
      if (focusables.length === 0) {
        e.preventDefault()
        dlg.focus()
        return
      }
      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      const active = document.activeElement
      const outside = active instanceof Node && !dlg.contains(active)
      if (!e.shiftKey && (active === last || outside)) {
        e.preventDefault()
        first.focus()
      } else if (e.shiftKey && (active === first || outside)) {
        e.preventDefault()
        last.focus()
      }
    }
    document.addEventListener('keydown', onKey, true)

    // 5) начален фокус: [data-autofocus] (ако е ВИДИМ/активен) → първият
    //    фокусируем → самият диалог (tabIndex -1), та Tab-капанът винаги
    //    има изход вътре. Минава през focusableIn — скрит/disabled autofocus
    //    не бива да оставя фокуса извън диалога.
    const focusables = focusableIn(dlg)
    const auto = focusables.find((el) => el.hasAttribute('data-autofocus'))
    ;(auto ?? focusables[0] ?? dlg).focus()

    return () => {
      document.removeEventListener('keydown', onKey, true)
      const idx = OPEN_DIALOG_STACK.indexOf(key)
      if (idx >= 0) OPEN_DIALOG_STACK.splice(idx, 1) // -1 би режал последния
      if (OPEN_DIALOG_STACK.length === 0 && scrollLockSaved) {
        body.style.overflow = SCROLL_LOCK_SAVED.overflow
        body.style.paddingRight = SCROLL_LOCK_SAVED.padRight
        scrollLockSaved = false
      }
      if (prevFocus != null && document.contains(prevFocus)) prevFocus.focus()
    }
  }, [open])

  // Tab-капанът живее в ефекта по-горе (document capture) — виж бележката
  // там защо не на контейнера.

  // drag-селекция в диалога не бива да затваря: click-ът се fire-ва на
  // общия ancestor (бекдрапа) при mousedown вътре + mouseup вън — затваряме
  // само ако И двете събития са тръгнали от самия бекдрап
  const downOnBackdrop = useRef(false)

  if (!open) return null

  const isDrawer = variant === 'drawer'
  const backCls = isDrawer ? `mg-drawer-back mg-drawer-back--${side}` : 'mg-modal-back'
  const boxCls = [isDrawer ? 'mg-drawer' : 'mg-modal', isDrawer ? `mg-drawer--${side}` : '', className]
    .filter(Boolean)
    .join(' ')

  return (
    <div
      className={backCls}
      onMouseDown={(e) => {
        downOnBackdrop.current = e.target === e.currentTarget
      }}
      onClick={(e) => {
        if (closeOnBackdrop && downOnBackdrop.current && e.target === e.currentTarget) {
          onCloseRef.current()
        }
      }}
    >
      <div
        ref={dlgRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title != null ? titleId : undefined}
        className={boxCls}
        style={resolvedWidth != null ? { width: resolvedWidth } : undefined}
        tabIndex={-1}
      >
        <div className="mg-dialog__head">
          {title != null && (
            <h2 id={titleId} className="mg-dialog__title panel-title">
              {title}
            </h2>
          )}
          <button
            type="button"
            className="mg-icon-btn"
            aria-label="Затвори диалога"
            onClick={() => onCloseRef.current()}
          >
            ✕
          </button>
        </div>
        <div className="mg-dialog__body">{children}</div>
        {footer != null && <div className="mg-dialog__foot">{footer}</div>}
      </div>
    </div>
  )
}

/** Drawer = Modal с variant='drawer' (дясно/ляво, width проп, мобилно full). */
export { Modal as Drawer }

/* ============================================================================
 * 5. Toast — ToastProvider (context) + useToast(); без createPortal
 * ========================================================================== */

export type ToastTone = 'success' | 'info' | 'warning' | 'danger'

export interface ToastAction {
  label: string
  onClick: () => void
}

export interface ToastOptions {
  /** Кратко заглавие (12px uppercase, тонален цвят). */
  title?: string
  /** Action бутон (напр. „Виж"); след клик известието се затваря. */
  action?: ToastAction
  /** Авто-dismiss в ms. Default 6000; danger 10000. 0 = без авто-dismiss. */
  duration?: number
}

export interface ToastApi {
  /** Добавя известието, връща id (за dismiss). Над 5 → изтласква най-стария. */
  push: (tone: ToastTone, message: string, opts?: ToastOptions) => number
  /** Затваря по id (idempotent). */
  dismiss: (id: number) => void
}

interface ToastItem {
  id: number
  tone: ToastTone
  message: string
  title?: string
  action?: ToastAction
  duration: number
}

/** Таймер с пауза: remaining се презаписва при всяко (ре)стартиране. */
interface TimerRec {
  timeout: ReturnType<typeof setTimeout> | null
  remaining: number
  startedAt: number
}

const TOAST_MAX = 5

const ToastCtx = createContext<ToastApi | null>(null)

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const nextId = useRef(0)
  const timers = useRef(new Map<number, TimerRec>())

  const clearTimer = (id: number) => {
    const rec = timers.current.get(id)
    if (rec != null && rec.timeout != null) {
      clearTimeout(rec.timeout)
      rec.timeout = null
    }
  }

  const dismiss = useCallback((id: number) => {
    clearTimer(id)
    timers.current.delete(id)
    // идempotent: липсващ id не праща нов масив → без излишен re-render
    setToasts((prev) => (prev.some((t) => t.id === id) ? prev.filter((t) => t.id !== id) : prev))
  }, [])

  const arm = useCallback(
    (id: number, remaining: number) => {
      const rec = timers.current.get(id)
      if (rec == null) return
      if (rec.timeout != null) clearTimeout(rec.timeout) // защита от двоен арм
      rec.remaining = remaining
      rec.startedAt = Date.now()
      rec.timeout = setTimeout(() => dismiss(id), remaining)
    },
    [dismiss],
  )

  const push = useCallback(
    (tone: ToastTone, message: string, opts?: ToastOptions): number => {
      const id = ++nextId.current
      const duration = opts?.duration ?? (tone === 'danger' ? 10_000 : 6_000)
      const item: ToastItem = {
        id,
        tone,
        message,
        title: opts?.title,
        action: opts?.action,
        duration,
      }
      // стек макс 5 с изтласкване на най-стария; чисто обновяване на
      // състоянието (StrictMode-безопасно) — таймерът на изтласкания се
      // изчиства idempotentно, когато изтече (dismiss по стара id е no-op
      // за състоянието и чисти Map-а).
      setToasts((prev) => {
        const base = prev.length >= TOAST_MAX ? prev.slice(prev.length - (TOAST_MAX - 1)) : prev.slice()
        base.push(item)
        return base
      })
      timers.current.set(id, { timeout: null, remaining: duration, startedAt: 0 })
      if (duration > 0) arm(id, duration)
      return id
    },
    [arm],
  )

  // пауза на hover — директно върху таймерите, без state → без re-render
  const pause = useCallback((id: number) => {
    const rec = timers.current.get(id)
    if (rec == null || rec.timeout == null) return // не е активен → нищо
    clearTimeout(rec.timeout)
    rec.timeout = null
    rec.remaining = Math.max(0, rec.remaining - (Date.now() - rec.startedAt))
  }, [])

  const resume = useCallback(
    (id: number) => {
      const rec = timers.current.get(id)
      if (rec == null || rec.timeout != null) return // не е на пауза → нищо
      if (rec.startedAt === 0) return // никога не е бил въоръжен (duration 0 / evicted)
      if (rec.remaining <= 0) {
        dismiss(id)
        return
      }
      arm(id, rec.remaining)
    },
    [arm, dismiss],
  )

  // изтласканите от стека (макс 5) чистят таймер-записа си тук — Map-ът
  // не расте при спам (особено с duration: 0, чиито записи иначе остават)
  useEffect(() => {
    for (const id of [...timers.current.keys()]) {
      if (!toasts.some((t) => t.id === id)) {
        clearTimer(id)
        timers.current.delete(id)
      }
    }
  }, [toasts])

  // cleanup на всички таймери при демонтиране на provider-а
  useEffect(() => {
    const map = timers.current
    return () => {
      for (const rec of map.values()) {
        if (rec.timeout != null) clearTimeout(rec.timeout)
      }
      map.clear()
    }
  }, [])

  const api = useMemo<ToastApi>(() => ({ push, dismiss }), [push, dismiss])

  return (
    <ToastCtx.Provider value={api}>
      {children}
      {/* „портал-подобен" контейнер: position fixed → мястото в дървото не
          влияе; стои в края на shell-а, над модалите (z 20 > 10) */}
      <div className="mg-toasts" role="log" aria-live="polite" aria-label="Системни известия">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`mg-toast mg-toast--${t.tone}`}
            onMouseEnter={() => pause(t.id)}
            onMouseLeave={() => resume(t.id)}
            onFocus={() => pause(t.id)}
            onBlur={() => resume(t.id)}
          >
            <span className="mg-toast__icon" aria-hidden="true">
              {TONE_GLYPH[t.tone]}
            </span>
            <div className="mg-toast__content">
              {t.title != null && <div className="mg-toast__title">{t.title}</div>}
              <div className="mg-toast__msg">{t.message}</div>
            </div>
            {t.action != null && (
              <button
                type="button"
                className="mg-toast__action"
                onClick={() => {
                  t.action?.onClick()
                  dismiss(t.id)
                }}
              >
                {t.action.label}
              </button>
            )}
            <button
              type="button"
              className="mg-toast__close"
              aria-label="Затвори известието"
              onClick={() => dismiss(t.id)}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

/** Достъп до Toast стека; хвърля ясна грешка без <ToastProvider>. */
export function useToast(): ToastApi {
  const ctx = useContext(ToastCtx)
  if (ctx == null) {
    throw new Error('useToast() изисква <ToastProvider> около шел-а (App.tsx / main.tsx).')
  }
  return ctx
}

/* ============================================================================
 * 6. LiveIndicator + useLivePulse — пулс САМО при свържи данни
 * ========================================================================== */

/** Decay прозорец на пулса: onData() → pulsing=true за 1.5s. */
export const LIVE_DECAY_MS = 1500

/** Състояние → (клас, етикет по подразбиране). */
const LIVE_DEFAULTS: Record<LiveState, { cls: string; label: string }> = {
  live: { cls: 'live', label: 'LIVE' },
  idle: { cls: 'idle', label: 'СПРЯН' },
  reconnect: { cls: 'reconnect', label: 'СВЪРЗВАНЕ…' },
}

export interface LiveIndicatorProps {
  /** live = връзката е отворена; idle = спрял/на пауза; reconnect = свързва се. */
  state: LiveState
  /** true само когато useLivePulse вижда свържи данни. Модификаторът
   *  .mg-live__dot--pulse се слага САМО при pulsing && state==='live' —
   *  спрян поток не пулсира (правило №9 на docs/16). */
  pulsing?: boolean
  /** Празен → етикет по подразбиране от state (LIVE / СПРЯН / СВЪРЗВАНЕ…). */
  label?: string
  /** Компактен вариант за топбара. */
  compact?: boolean
  title?: string
}

export function LiveIndicator({
  state,
  pulsing = false,
  label,
  compact = false,
  title,
}: LiveIndicatorProps) {
  const d = LIVE_DEFAULTS[state]
  const text = label ?? d.label
  const isPulsing = pulsing && state === 'live'
  const cls = ['mg-live', `mg-live--${d.cls}`, compact ? 'mg-live--compact' : ''].filter(Boolean).join(' ')
  return (
    <span className={cls} role="status" title={title ?? text}>
      <span className={isPulsing ? 'mg-live__dot mg-live__dot--pulse' : 'mg-live__dot'} aria-hidden="true" />
      <span className="mg-live__label">{text}</span>
    </span>
  )
}

export interface LivePulse {
  /** true през decay-прозореца след последната единица данни. */
  pulsing: boolean
  /** Извиквай при ВСЯКА нова единица данни (WS рамка, poll отговор…).
   *  Стабилна референция (useCallback) — безопасна за deps на ефекти. */
  onData: () => void
}

/** Пулс-декоратор за жив поток. НЕ знае нищо за WebSocket — консуматорът
 *  решава кое е „нова данна" и вика onData(). Примери:
 *    · WS:   ws.onmessage = () => { pulse.onData(); … }      (или usePacketStream)
 *    · poll: setInterval(async () => { await load(); pulse.onData() }, 5000)
 *  setPulsing(true) при вече-true не предизвиква re-render (React bail-out). */
export function useLivePulse(decayMs: number = LIVE_DECAY_MS): LivePulse {
  const [pulsing, setPulsing] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // дедлайн на пулса: при непрекъснат поток НЕ реармваме таймер на всяка
  // рамка (clearTimeout+setTimeout × N/сек) — местваме само дедлайна;
  // вече въоръженият таймер сам преизчислява остатъка при изтичане
  const deadline = useRef(0)

  const onData = useCallback(() => {
    deadline.current = Date.now() + decayMs
    setPulsing(true)
    if (timer.current != null) return
    const tick = () => {
      const left = deadline.current - Date.now()
      if (left > 0) {
        timer.current = setTimeout(tick, left)
        return
      }
      timer.current = null
      setPulsing(false)
    }
    timer.current = setTimeout(tick, decayMs)
  }, [decayMs])

  // cleanup при демонтиране — нулев таймер след unmount
  useEffect(() => {
    const t = timer
    return () => {
      if (t.current != null) clearTimeout(t.current)
    }
  }, [])

  return { pulsing, onData }
}

/* ============================================================================
 * 7. usePacketStream — готов WS живот за /api/v1/packets/ws (за Т14)
 * ========================================================================== */

export interface PacketStream {
  /** live | idle (на пауза) | reconnect (включително първото свързване). */
  state: LiveState
  /** Пулс само при реално пристигнали данни при НЕ-паузиран поток. */
  pulsing: boolean
  paused: boolean
  /** Пауза на ПОТНОКА (данните се пропускат), без късане на WS връзката —
   *  за разлика от днешния PacketExplorer, който преинсталира сокета при
   *  всяка смяна на филтъ/пауза. */
  setPaused: (p: boolean) => void
  /** Регистрира handler за всяка нова WS рамка (JSON-parse-нат обект;
   *  при непарсебъл — суровият низ). null отписва. Стабилна референция. */
  onDataBind: (handler: ((msg: unknown) => void) | null) => void
}

/** Адресът на живия поток — 1:1 от днешния PacketExplorer. */
function defaultWsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/api/v1/packets/ws`
}

/** Живот на WS връзката: отваря при монтиране, exponential backoff при
 *  прекъсване (1s → 2s → 4s → … max 10s), затваря при демонтиране.
 *  Паузата е през ref → НЕ прекъсва връзката и НЕ преинсталира ефекта.
 *
 *  1 консуматор = 1 сокет (съзнателно). Днес страниците са взаимоизклю-
 *  чващи се; ако Т9 (Dashboard) и Т14 (Explorer) изискват едновременен
 *  поток → вдигни PacketStreamProvider на контекст с refcount ПРЕДИ това.
 *  ВНИМАНИЕ за deps на ефекти: обектът е нов всеки рендер — карай по
 *  стабилните onDataBind (useCallback), не по целия резултат. */
export function usePacketStream(url: string = defaultWsUrl()): PacketStream {
  const [paused, setPausedState] = useState(false)
  const [state, setState] = useState<LiveState>('reconnect')
  const { pulsing, onData: feedPulse } = useLivePulse()

  const pausedRef = useRef(false)
  useEffect(() => {
    pausedRef.current = paused
  }, [paused])

  const openRef = useRef(false)

  const handlerRef = useRef<((msg: unknown) => void) | null>(null)
  const onDataBind = useCallback((handler: ((msg: unknown) => void) | null) => {
    handlerRef.current = handler
  }, [])

  const setPaused = useCallback((p: boolean) => {
    setPausedState(p)
  }, [])

  useEffect(() => {
    let ws: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | null = null
    let attempts = 0
    let disposed = false

    const connect = () => {
      ws = new WebSocket(url)
      ws.onopen = () => {
        attempts = 0
        openRef.current = true
        setState(pausedRef.current ? 'idle' : 'live')
      }
      ws.onmessage = (ev: MessageEvent) => {
        if (pausedRef.current) return // спрян поток: без пулс, без данни
        let msg: unknown = ev.data
        if (typeof ev.data === 'string') {
          try {
            msg = JSON.parse(ev.data)
          } catch {
            /* непарсебъл → суровият низ отива на handler-а */
          }
        }
        // heartbeat (packets.py, на всеки 15s) НЕ пулсира — Т14 QA:
        // „пулс само при нови данни“ (тиха мрежа = тиха точка)
        const kind = (msg as { type?: string } | null)?.type
        if (kind !== 'heartbeat') feedPulse()
        const h = handlerRef.current
        if (h != null) h(msg)
      }
      ws.onclose = () => {
        openRef.current = false
        if (disposed) return
        setState('reconnect')
        const delay = Math.min(1000 * 2 ** attempts, 10_000)
        attempts += 1
        retry = setTimeout(connect, delay)
      }
      ws.onerror = () => {
        try {
          ws?.close() // onclose следва → backoff логиката е на едно място
        } catch {
          /* вече затворен */
        }
      }
    }

    connect()
    return () => {
      disposed = true
      if (retry != null) clearTimeout(retry)
      openRef.current = false
      try {
        ws?.close()
      } catch {
        /* вече затворен */
      }
    }
  }, [url, feedPulse])

  // паузата синхронизира състоянието с РЕАЛНАТА връзка (не с предположение)
  useEffect(() => {
    setState(paused ? 'idle' : openRef.current ? 'live' : 'reconnect')
  }, [paused])

  return { state, pulsing, paused, setPaused, onDataBind }
}
