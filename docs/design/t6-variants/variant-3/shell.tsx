/* MeshGate — Т6 „Топбар + sidebar + брояч аларми" · Вариант 3 „NOC операторски фокус"
 * ============================================================================
 * Вариантен файл (преглед, НЕ е свързан в билда).
 * Дестинация при внедряване: apps/web/src/shell.tsx (нов файл).
 * Импортите по-долу са спрямо apps/web/src/ (където файлът ще живее):
 *   ./components/ui    ← LiveIndicator / StatusChip / usePacketStream (Т3)
 *   ./components/Brand ← BrandMark (Т2)
 *   ./hooks            ← AnomalyCountState (Т6, hooks.ts от този вариант)
 *
 * Какво предлага В3 (стратегия „операторът на NOC пост вижда ВСИЧКО важно
 * без да търси"):
 *   · TopBar  — лого + role pill + приложен LIVE (usePacketStream, пулс
 *               САМО при нови данни) отляво; вдясно ПРЕД потребителя —
 *               ALARM чип (danger при deadletter+notify_failed > 0,
 *               неутрален „без аларми" при 0 — НЕ изчезва: операторът
 *               трябва да ВИЖДА, че системата е чиста), клик → ?p=monitor;
 *   · SideNav — същите групи като днешния App.tsx (етикетите са 1:1),
 *               всеки бутон с монохромна SVG икона (currentColor →
 *               тюрказен акцент на активния), тънка акцентна черта на
 *               активния + МАЛЪК danger badge на „Мониторинг",
 *               синхронен с топбар чипа (същият AnomalyCountState);
 *   · syncPageUrl — навигацията си остава ?p= (без router); кликът вече
 *               синхронизира адреса през history.replaceState (дълбоката
 *               връзка не „замръзва" след първото зареждане).
 *
 * Правила (Т1): само токени (тук: нула цвят в TSX — всичко през класове),
 * нищо под 12px, без сенки, radius 4/8/12, z-стълбата не се пипа (топбар
 * е z 5; този файл не въвежда нито един z-index). НУЛА нови npm пакети.
 * ========================================================================== */
import { BrandMark } from './components/Brand'
import { LiveIndicator, StatusChip, usePacketStream, type Tone } from './components/ui'
import type { AnomalyCountState } from './hooks'

/* ============================================================================
 * 1. Навигационно дърво — 1:1 от днешния App.tsx (етикетите не се менят:
 *    мускулната памет на оператора е част от интерфейса). Иконите са нови.
 * ========================================================================== */

export interface NavItem {
  id: string
  label: string
  adminOnly?: boolean
  hidden?: boolean
}
export interface NavSection {
  title: string
  items: NavItem[]
}

/** Групите на sidebar-а (днес SECTIONS в App.tsx — мигрират тук). */
export const NAV_SECTIONS: NavSection[] = [
  { title: 'Dashboard', items: [{ id: 'overview', label: 'Overview' }] },
  {
    title: 'Monitoring',
    items: [
      { id: 'monitor', label: 'Мониторинг' },
      { id: 'devices', label: 'Устройства и мрежа' },
      { id: 'packets', label: 'Packet Explorer' },
      { id: 'map', label: 'Карта' },
    ],
  },
  { title: 'MQTT Brokers', items: [{ id: 'broker', label: 'Брокер' }] },
  { title: 'Bridges', items: [{ id: 'bridges', label: 'Мостове и маршрути' }] },
  { title: 'Routing Rules', items: [{ id: 'routing', label: 'Правила за рутиране' }] },
  { title: 'Automation', items: [{ id: 'notifications', label: 'Известия' }] },
  { title: 'Integrations', items: [{ id: 'integrations', label: 'Интеграции' }] },
  {
    title: 'Security & Settings',
    items: [
      { id: 'system', label: 'Система и сигурност' },
      { id: 'profiles', label: 'Profiles', adminOnly: true },
    ],
  },
  {
    title: '',
    items: [
      { id: 'plan', label: 'План & Тестове' },
      // скрит регресионен полигон на Т3 — само чрез ?p=ui, не се брои в менюто
      { id: 'ui', label: 'Компоненти', hidden: true },
    ],
  },
]

/** Плосък списък (днес PAGES в App.tsx) — за валидация на ?p=. */
export const NAV_PAGES = NAV_SECTIONS.flatMap((s) => s.items)
export type PageId = (typeof NAV_PAGES)[number]['id']

/* ============================================================================
 * 2. Икони — монохромни SVG, 16×16, stroke currentColor (наследява цвета
 *    на бутона: muted → тюркоз при active). НУЛА emoji в навигацията:
 *    emoji-тата се рендерират цветни и недържим палитрата им; токен-цвят
 *    може да се сложи само на SVG с currentColor. Декоративни (aria-hidden)
 *    — смисълът го носи текстовият етикет до тях.
 * ========================================================================== */

const NAV_ICONS: Record<string, React.ReactNode> = {
  overview: (
    <>
      <rect x="2" y="2" width="5" height="5" rx="1" />
      <rect x="9" y="2" width="5" height="5" rx="1" />
      <rect x="2" y="9" width="5" height="5" rx="1" />
      <rect x="9" y="9" width="5" height="5" rx="1" />
    </>
  ),
  monitor: <path d="M1.5 8.5h3L6 4l3 8 1.5-3.5h4" />, // пулс-линия на мониторинг
  devices: (
    <>
      <rect x="4.5" y="4.5" width="7" height="7" rx="1" />
      <path d="M8 1.5v3M8 11.5v3M1.5 8h3M11.5 8h3" />
    </>
  ),
  packets: (
    <>
      <path d="M8 1.8l6.2 3.2L8 8.2 1.8 5z" />
      <path d="M1.8 8.4L8 11.6l6.2-3.2" />
      <path d="M1.8 11.4L8 14.6l6.2-3.2" />
    </>
  ),
  map: (
    <>
      <path d="M8 1.5c-2.9 0-5 2.2-5 4.9C3 10.2 8 14.5 8 14.5s5-4.3 5-8.1c0-2.7-2.1-4.9-5-4.9z" />
      <circle cx="8" cy="6.4" r="1.8" />
    </>
  ),
  broker: (
    <>
      <rect x="2.5" y="2" width="11" height="5" rx="1" />
      <rect x="2.5" y="9" width="11" height="5" rx="1" />
      <path d="M5 4.5h.01M5 11.5h.01" />
    </>
  ),
  bridges: (
    <>
      <circle cx="3.5" cy="8" r="2" />
      <circle cx="12.5" cy="8" r="2" />
      <path d="M5.5 8h5" />
    </>
  ),
  routing: (
    <>
      <path d="M3 14V8c0-3 2.2-4 5-4h2" />
      <path d="M8.5 1.8L11 4 8.5 6.2" />
    </>
  ),
  notifications: (
    <>
      <path d="M8 2a4.3 4.3 0 0 0-4.3 4.3c0 3.8-1.7 4.7-1.7 4.7h12s-1.7-.9-1.7-4.7A4.3 4.3 0 0 0 8 2z" />
      <path d="M6.5 13.5a1.6 1.6 0 0 0 3 0" />
    </>
  ),
  integrations: (
    <>
      <circle cx="3" cy="3.5" r="1.8" />
      <circle cx="3" cy="12.5" r="1.8" />
      <circle cx="13" cy="8" r="1.8" />
      <path d="M4.6 4.6l6.7 2.4M4.6 11.4l6.7-2.4" />
    </>
  ),
  system: (
    <>
      <path d="M8 1.5l5.5 2.2v3.8c0 3.8-2.9 5.7-5.5 7-2.6-1.3-5.5-3.2-5.5-7V3.7z" />
      <path d="M5.8 7.8l1.6 1.6 3-3.2" />
    </>
  ),
  profiles: (
    <>
      <circle cx="8" cy="5" r="2.8" />
      <path d="M2.8 14c.4-2.9 2.6-4.3 5.2-4.3s4.8 1.4 5.2 4.3" />
    </>
  ),
  plan: (
    <>
      <path d="M6 3.5h8M6 8h8M6 12.5h8" />
      <path d="M2 3.3l1 1 1.8-2M2 7.8l1 1 1.8-2M2 12.3l1 1 1.8-2" />
    </>
  ),
}

function NavIcon({ id }: { id: string }) {
  return (
    <svg
      className="side-btn__glyph"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {NAV_ICONS[id] ?? null}
    </svg>
  )
}

/* ============================================================================
 * 3. ?p= синхронизация — навигацията ОСТАВА ?p= (без router, нула нови
 *    зависимости). replaceState не бута историята; резултатът: копираното
 *    от топбар чипа/менюто URL-адреси е дълбока връзка и след кликване.
 * ========================================================================== */

export function syncPageUrl(page: string): void {
  const q = new URLSearchParams(location.search)
  q.set('p', page)
  history.replaceState(null, '', `${location.pathname}?${q.toString()}`)
}

/* ============================================================================
 * 4. AlarmChip — алармата на топбара (стратегия В3: ТОПБАРът носи алармата).
 *    StatusChip (Т3) прави визалния вид; <button> прави взаимодействието.
 *    Двойните етикети (full/short) се превключват от CSS при <800px.
 * ========================================================================== */

function alarmWord(n: number): string {
  return n === 1 ? 'аларма' : 'аларми'
}

export interface AlarmChipProps {
  alarm: AnomalyCountState
  /** Клик → страницата с лентата на аномалиите (днес monitor). */
  onNavigate: (page: string) => void
}

export function AlarmChip({ alarm, onNavigate }: AlarmChipProps) {
  const n = alarm.total
  const display = n > 99 ? '99+' : String(n)
  // „неизвестно" = никога не сме чули успешно ИЛИ грешка при последно
  // известно 0 — нито едно от двете НЕ бива да се чете като „без аларми"
  const unknown = !alarm.loaded || (alarm.error != null && n === 0)
  const tone: Tone = !unknown && n > 0 ? 'danger' : 'neutral'
  const icon = unknown ? '•' : n > 0 ? '⚡' : '✓'
  const full = unknown
    ? alarm.error != null
      ? 'аларми: няма данни'
      : 'аларми: зареждане…'
    : n > 0
      ? `${display} ${alarmWord(n)} (${alarm.hours}ч)`
      : 'без аларми'
  const short = unknown ? '?' : display

  const parts: string[] = []
  if (!unknown && n > 0) {
    parts.push(
      `${display} за ${alarm.hours} ч: ${alarm.deadletter} мъртви букви + ` +
        `${alarm.notifyFailed} провалени известия`,
    )
    if (alarm.uniqueLabels > 0) parts.push(`${alarm.uniqueLabels} различни причини`)
    if (alarm.lastTs != null) parts.push(`последно събитие: ${alarm.lastTs}`)
  } else if (!unknown) {
    parts.push(`нито една мъртва буква или провалено известие в последните ${alarm.hours} ч`)
  }
  if (alarm.error != null) parts.push(`последната заявка грешка: ${alarm.error}`)
  parts.push('Клик → Мониторинг (лента на аномалиите)')

  return (
    <button
      type="button"
      className="mg-alarm"
      onClick={() => onNavigate('monitor')}
      title={parts.join(' · ')}
      aria-label={`Аларми: ${full}. Отвори Мониторинг`}
    >
      <StatusChip tone={tone} icon={icon}>
        <span className="mg-alarm__full">{full}</span>
        <span className="mg-alarm__short">{short}</span>
      </StatusChip>
    </button>
  )
}

/* ============================================================================
 * 5. TopBar — лого + role pill + LIVE отляво; ALARM чип + потребител вдясно.
 *    LIVE е ПРИЛОЖНИЯТ поток (usePacketStream към /api/v1/packets/ws):
 *    пулсира само при нови данни, състоянията жив/спрял/свързва се се
 *    виждат (QA на Т6). Един WS за целия шел — виж notes.md §Рискове за
 *    временно два сокета на ?p=packets до миграцията на Explorer в Т14.
 * ========================================================================== */

export interface TopBarProps {
  me: { username: string; role: string }
  /** Състоянието от useAnomalyCount() — ЕДНО на App, споделено със SideNav. */
  alarm: AnomalyCountState
  onNavigate: (page: string) => void
  onOpenPassword: () => void
  onLogout: () => void
}

export function TopBar({ me, alarm, onNavigate, onOpenPassword, onLogout }: TopBarProps) {
  const stream = usePacketStream()
  return (
    <header className="topbar">
      <div className="brand">
        <BrandMark size={22} />
        <span className="brand-word">
          Mesh<span className="brand-word-gate">Gate</span>
        </span>
        <span className="pill">{me.role}</span>
      </div>
      <div
        className="topbar-live"
        title="Поток на пакети (приложен) — пулсира само при нови данни"
      >
        <LiveIndicator state={stream.state} pulsing={stream.pulsing} compact />
      </div>
      <div className="topbar-right">
        <AlarmChip alarm={alarm} onNavigate={onNavigate} />
        <span className="muted">{me.username}</span>
        <button className="nav-btn ghost" title="Смяна на парола" onClick={onOpenPassword}>
          🔑
        </button>
        <button className="nav-btn" onClick={onLogout}>
          Изход
        </button>
      </div>
    </header>
  )
}

/* ============================================================================
 * 6. SideNav — групите на App.tsx + икона+текст + danger badge на Мониторинг.
 *    Badge-ът е ВТОРИЧНИЯТ магнит (погледът вече е в менюто, където се
 *    клика за детайла); НЕ носи „чисто" състояние — при 0 се скрива, защото
 *    неутралният топбар чип вече твърди „без аларми" (две места с едно и
 *    също твърдение = шум; badge с „0" = трепереща нула без информация).
 * ========================================================================== */

export function AlarmBadge({ count }: { count: number }) {
  if (count <= 0) return null
  return (
    <span className="mg-side-badge" aria-hidden="true">
      {count > 99 ? '99+' : count}
    </span>
  )
}

export interface SideNavProps {
  page: string
  isAdmin: boolean
  /** Същият AnomalyCountState като на топбара — синхронни по конструкция. */
  alarm: AnomalyCountState
  onNavigate: (page: string) => void
}

export function SideNav({ page, isAdmin, alarm, onNavigate }: SideNavProps) {
  return (
    <aside className="sidebar">
      {NAV_SECTIONS.map((s, i) => (
        <div key={i} className="side-section">
          {s.title && <div className="side-title">{s.title}</div>}
          {s.items
            .filter((p) => (!p.adminOnly || isAdmin) && !p.hidden)
            .map((p) => {
              const isMonitor = p.id === 'monitor'
              const badge = isMonitor && alarm.total > 0
              const title = badge
                ? `${alarm.total} аларми (${alarm.hours} ч) — лентата на аномалиите`
                : p.label
              return (
                <button
                  key={p.id}
                  type="button"
                  className={page === p.id ? 'side-btn active' : 'side-btn'}
                  onClick={() => onNavigate(p.id)}
                  title={title}
                >
                  <NavIcon id={p.id} />
                  <span className="side-btn__label">{p.label}</span>
                  {isMonitor && <AlarmBadge count={alarm.total} />}
                </button>
              )
            })}
        </div>
      ))}
    </aside>
  )
}
