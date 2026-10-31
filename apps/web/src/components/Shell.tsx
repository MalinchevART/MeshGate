/* ============================================================================
 * MeshGate · Т6 „Топбар + sidebar + брояч аларми" — шелът като компонент
 * ----------------------------------------------------------------------------
 * Съчетание В2+В3 (решението е документирано в AGENTS.md · Статус „Т6"): структурата на В2
 * (Shell/Topbar/Sidebar; Shell е собственик на сесийните ресурси) + NOC
 * семантиката на В3 (алармата е в ТОПБАРА с честно „без аларми" състояние;
 * монохромни SVG икони с currentColor; ?p= синхронизация през replaceState).
 *
 *   · Shell   — постоянният WS поток (usePacketStream от Т3; първият
 *               нетранзиентен консуматор — живее цялата сесия след login;
 *               до Т14 PacketExplorer държи свой сокет → transient 2) +
 *               броячът на аларми (useAnomalyCount: poll /v1/anomalies на
 *               10s; източникът превключваем към critical-events след Т7) +
 *               банерът за начална парола; <main> е слот children.
 *   · Topbar  — лого + приложен LIVE + (дясно) ALARM чип + потребител.
 *   · Sidebar — групи с икона+текст, тюркоазен акцент-бар на активния
 *               (+ aria-current="page"), danger badge на „Мониторинг".
 *   · SECTIONS/PAGES/PageId/Me живеят ТУК; App ре-експортира Me, та
 *               легаси страниците с `import type { Me } from '../App'`
 *               остават непипнати.
 *
 * Навигацията остава ?p= (без router). DOM йерархията е същата като
 * днешния App (div.shell > banner?, header.topbar, div.body > aside+main,
 * модалите в края чрез проп overlays).
 * ========================================================================== */
import { api } from '../api'
import { BrandMark } from './Brand'
import { LiveIndicator, StatusChip, usePacketStream, type LiveState, type Tone } from './ui'
import {
  useAnomalyCount,
  type AnomalySource,
  type AnomalySummary,
} from '../hooks/useAnomalyCount'

/* ============================================================================
 * 1. ТИПОВЕ + SECTIONS (moved от App.tsx)
 * ========================================================================== */

/** Сесийният потребител — App.tsx го ре-експортира за легаси страниците. */
export type Me = { id: string; username: string; role: string; default_password: boolean }

export interface ShellItem {
  id: string
  label: string
  adminOnly?: boolean
  /** Скрит от менюто, но достъпен чрез ?p= (регресионният полигон на Т3). */
  hidden?: boolean
  /** Този item носи брояча на аларми (danger badge; днес: Мониторинг). */
  badge?: 'alarm'
}

export interface ShellSection {
  /** Празен титул → група без заглавие (долният блок „План & Тестове"). */
  title: string
  items: ShellItem[]
}

/* --- икони: монохромни SVG 16×16, stroke currentColor — наследяват цвета
   на бутона (muted → тюркоз на активния); нула emoji в навигацията (emoji
   се рендерират цветни и недържим палитрата им). Декоративни (aria-hidden)
   — смисълът го носи етикетът. Т33 (tablet, sidebar до икони) ги запазва. */
const NAV_ICONS: Record<string, React.ReactNode> = {
  overview: (
    <>
      <rect x="2" y="2" width="5" height="5" rx="1" />
      <rect x="9" y="2" width="5" height="5" rx="1" />
      <rect x="2" y="9" width="5" height="5" rx="1" />
      <rect x="9" y="9" width="5" height="5" rx="1" />
    </>
  ),
  monitor: <path d="M1.5 8.5h3L6 4l3 8 1.5-3.5h4" />,
  'monitor-time': (
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="M8 4.5V8l2.5 1.5" />
    </>
  ),
  'monitor-utility': (
    <>
      <path d="M2.5 3.5h11v2h-11z" />
      <path d="M4.5 7.5h7v2h-7z" />
      <path d="M6.5 11.5h3v2h-3z" />
    </>
  ),
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
      className="side-btn__icon"
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

// дървото от визията (docs/11-ui-vision-plan.md §1): секция се показва само
// когато зад нея има реален екран — етикетите са 1:1 от стария App.tsx
export const SECTIONS: ShellSection[] = [
  { title: 'Dashboard', items: [{ id: 'overview', label: 'Overview' }] },
  {
    title: 'Monitoring',
    items: [
      // Т27: Мониторинг = табов Обзор/Време/Полезност (всеки таб е ?p=
      // дълбока връзка; аларменият бадж остава на Обзор)
      { id: 'monitor', label: 'Обзор', badge: 'alarm' },
      { id: 'monitor-time', label: 'Време' },
      { id: 'monitor-utility', label: 'Полезност' },
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
      // скрит регресионен полигон на Т3 — само чрез ?p=ui
      { id: 'ui', label: 'Компоненти', hidden: true },
    ],
  },
]

/** Всички страници (за валидацията на ?p= в App). */
export const PAGES = SECTIONS.flatMap((s) => s.items)

export type PageId = (typeof PAGES)[number]['id']

/** Синхронизира ?p= в адреса (replaceState — без история-скокове): копирано
 *  URL след клик в менюто е дълбока връзка. Без router. */
export function syncPageUrl(page: string): void {
  const q = new URLSearchParams(location.search)
  q.set('p', page)
  history.replaceState(null, '', `${location.pathname}?${q.toString()}`)
}

/* ============================================================================
 * 2. AlarmChip — алармата на топбара (NOC: постоянна видимост на ВСЕКИ
 *    страница). При 0 стои неутрален „без аларми" (операторът различава
 *    „чисто" от „умрял брояч"); зеленият е резервиран за потвърдени ОК
 *    състояния (LIVE), не за „лиса на проблем".
 * ========================================================================== */

function alarmWord(n: number): string {
  return n === 1 ? 'аларма' : 'аларми'
}

export interface AlarmChipProps {
  /** null → още няма успешен poll. */
  summary: AnomalySummary | null
  /** Грешка от последния poll (summary остава последният добър). */
  error: string | null
  /** Клик → страницата с лентата на аномалиите. */
  onNavigate: (page: string) => void
  /** Т7: източникът решава семантиката на tooltip текста. */
  critical?: boolean
}

export function AlarmChip({ summary, error, onNavigate, critical = false }: AlarmChipProps) {
  const n = summary?.alarm ?? 0
  const display = n > 99 ? '99+' : String(n)
  // „неизвестно" = още без успешен poll ИЛИ грешка при последно известно 0 —
  // нито едното не бива да се чете като „без аларми"
  const unknown = summary == null || (error != null && n === 0)
  const tone: Tone = !unknown && n > 0 ? 'danger' : 'neutral'
  const icon = unknown ? '•' : n > 0 ? '⚡' : '✓'
  const full = unknown
    ? summary == null
      ? 'аларми: зареждане…'
      : 'аларми: няма данни'
    : n > 0
      ? `${display} ${alarmWord(n)} (${summary.hours} ч)`
      : 'без аларми'
  const short = unknown ? '?' : display

  const parts: string[] = []
  if (!unknown && summary != null && n > 0) {
    if (critical) {
      const b = summary.byKind
      parts.push(
        `${display} критични за ${summary.hours} ч: ` +
          `${b.battery} батерии + ${b.deadletter} мъртви букви + ${b.silence} мълчания`,
      )
    } else {
      parts.push(
        `${display} за ${summary.hours} ч: ${summary.deadletter} мъртви букви + ` +
          `${summary.notifyFailed} провалени известия`,
      )
    }
    if (summary.lastAlarmTs != null) {
      parts.push(`последна: ${new Date(summary.lastAlarmTs).toLocaleString('bg-BG')}`)
    }
  } else if (!unknown && summary != null) {
    parts.push(critical
      ? `нито едно критично събитие в последните ${summary.hours} ч`
      : `нито една мъртва буква или провалено известие в последните ${summary.hours} ч`)
  }
  if (error) parts.push(`последната заявка гръмна: ${error}`)
  if (summary != null) {
    parts.push(`проверено в ${new Date(summary.updatedAt).toLocaleTimeString('bg-BG')}`)
  }
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
 * 3. Topbar — лого + приложен LIVE (ляво); ALARM чип + потребител (дясно)
 * ========================================================================== */

export interface TopbarProps {
  me: Me
  /** Живият поток на сесията (usePacketStream, монтиран в Shell). */
  live: { state: LiveState; pulsing: boolean }
  alarm: AnomalySummary | null
  alarmError: string | null
  /** Т7: семантика на алармения чип (critical-events след Т7). */
  alarmCritical: boolean
  onNavigate: (page: string) => void
  onPassword: () => void
}

export function Topbar({ me, live, alarm, alarmError, alarmCritical, onNavigate, onPassword }: TopbarProps) {
  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className="brand">
          <BrandMark size={22} />
          <span className="brand-word">
            Mesh<span className="brand-word-gate">Gate</span>
          </span>
          <span className="pill" title={`роля: ${me.role}`}>
            {me.role}
          </span>
        </div>
        {/* приложен LIVE: живот/пулс на ЦЯЛАТА мрежа от постоянния WS на
            шел-а; пулс — само при нови данни; reconnect се вижда при срив */}
        <div
          className="topbar-live"
          title="Жив поток от приемника (WS): LIVE при отворена връзка; пулс — само при нови данни"
        >
          <LiveIndicator state={live.state} pulsing={live.pulsing} compact />
        </div>
      </div>
      <div className="topbar-right">
        <AlarmChip summary={alarm} error={alarmError} onNavigate={onNavigate} critical={alarmCritical} />
        <span className="topbar-user" title={`влезан като ${me.username} (роля: ${me.role})`}>
          {me.username}
        </span>
        <button className="nav-btn ghost" title="Смяна на парола" onClick={onPassword}>
          🔑
        </button>
        <button
          className="nav-btn"
          onClick={async () => {
            await api('/v1/auth/logout', { method: 'POST' })
            location.reload()
          }}
        >
          Изход
        </button>
      </div>
    </header>
  )
}

/* ============================================================================
 * 4. Sidebar — групи, икона+текст, акцент на активния, danger badge
 * ========================================================================== */

export interface SidebarProps {
  sections?: ShellSection[]
  active: string
  onSelect: (id: string) => void
  isAdmin: boolean
  alarm?: AnomalySummary | null
}

/** Над 99 → „99+" (кратко, бутонът не се пръска). */
function badgeText(n: number): string {
  return n > 99 ? '99+' : String(n)
}

export function Sidebar({
  sections = SECTIONS,
  active,
  onSelect,
  isAdmin,
  alarm = null,
}: SidebarProps) {
  const alarmCount = alarm?.alarm ?? 0

  return (
    <aside className="sidebar">
      <nav aria-label="Главно меню">
        {sections.map((s, i) => (
          <div key={s.title || i} className="side-section">
            {s.title && <div className="side-title">{s.title}</div>}
            {s.items
              .filter((p) => (!p.adminOnly || isAdmin) && !p.hidden)
              .map((p) => {
                const isActive = active === p.id
                const hasBadge = p.badge === 'alarm' && alarm != null && alarmCount > 0
                // достъпно име = ЕТИКЕТЪТ + пълният разпад (не само числото);
                // aria-label заменя съдържанието за SR → без етикета бутонът
                // остава анонимен; без aria-live — 10s полингът би дрънкал
                const ariaAlarm =
                  hasBadge && alarm != null
                    ? `${p.label}: аларми (${alarm.hours} ч) ${alarmCount} — мъртви букви: ` +
                      `${alarm.deadletter}, провалени известия: ${alarm.notifyFailed}` +
                      (alarm.lastAlarmTs != null
                        ? `; последна: ${new Date(alarm.lastAlarmTs).toLocaleString('bg-BG')}`
                        : '')
                    : null
                const titleAlarm =
                  hasBadge && alarm != null
                    ? `${ariaAlarm} · проверено в ${new Date(alarm.updatedAt).toLocaleTimeString('bg-BG')}`
                    : null
                return (
                  <button
                    key={p.id}
                    type="button"
                    className={isActive ? 'side-btn active' : 'side-btn'}
                    aria-current={isActive ? 'page' : undefined}
                    aria-label={ariaAlarm ?? undefined}
                    title={titleAlarm ?? undefined}
                    onClick={() => onSelect(p.id)}
                  >
                    <NavIcon id={p.id} />
                    <span className="side-btn__label">{p.label}</span>
                    {hasBadge && <span className="side-badge">{badgeText(alarmCount)}</span>}
                  </button>
                )
              })}
          </div>
        ))}
      </nav>
    </aside>
  )
}

/* ============================================================================
 * 5. Shell — собственикът на сесийните ресурси на шел-а
 * ========================================================================== */

export interface ShellProps {
  me: Me
  page: PageId
  onPage: (p: PageId) => void
  onPassword: () => void
  /** Модалите на App (ChangePassword, Onboarding) — на същото DOM място. */
  overlays?: React.ReactNode
  /** 'anomalies' (днес) | 'critical-events' (след Т7 — пропът е превключвателят). */
  alarmSource?: AnomalySource
  children: React.ReactNode
}

export function Shell({
  me,
  page,
  onPage,
  onPassword,
  overlays,
  alarmSource = 'critical-events',
  children,
}: ShellProps) {
  // ПЪРВИЯТ постоянен WS консуматор (Т3): отваря при login, живее сесията,
  // backoff при срив, не се влияе от смяната на страниците. Handler не се
  // връзва — ползваме само state/pulsing за LiveIndicator. До Т14 на
  // страницата Packet Explorer има 2 сокета (нейният си е неин) — transient;
  // след Т14 общ Provider с refcount (полето е подготвено: потокът е тук).
  const live = usePacketStream()

  // Броячът на аларми: poll 10s, пауза в скрит таб, грешка не мига badge-а
  const { summary: alarm, error: alarmError } = useAnomalyCount({
    hours: 24,
    intervalMs: 10_000,
    source: alarmSource,
  })

  const go = (id: string) => {
    onPage(id as PageId)
    syncPageUrl(id)
  }

  return (
    <div className="shell">
      {me.default_password && (
        <div className="banner">
          ⚠ Използваш НАЧАЛНАТА парола на системата. Смени я сега:
          <button onClick={onPassword}>Смяна на парола</button>
        </div>
      )}
      <Topbar
        me={me}
        live={live}
        alarm={alarm}
        alarmError={alarmError}
        alarmCritical={alarmSource === 'critical-events'}
        onNavigate={go}
        onPassword={onPassword}
      />
      <div className="body">
        {/* cast-ът е безопасен по конструкция: PAGES (източникът на PageId)
            е flatMap на същите SECTIONS, от които идват тези id */}
        <Sidebar active={page} onSelect={go} isAdmin={me.role === 'admin'} alarm={alarm} />
        <main>{children}</main>
      </div>
      {overlays}
    </div>
  )
}
