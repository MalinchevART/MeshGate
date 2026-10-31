/* ============================================================================
 * MeshGate · Т6 „Топбар + sidebar + брояч аларми" — Вариант 2
 * „Шел като компоненти"
 * ----------------------------------------------------------------------------
 * Дестинация при внедряване:
 *   този файл → apps/web/src/components/Shell.tsx
 *   hooks.ts  → apps/web/src/hooks/useAnomalyCount.ts
 *   shell.css → подблок „Т6" в секция 4.1 SHELL на apps/web/src/styles.css
 *               (точното място на вмъкване е КРИТИЧНО за каскадата <900px —
 *               вмъква се ПРЕДИ легаси @media (max-width: 900px) блока;
 *               виж shell.css и notes.md)
 *
 * Стратегия В2: ИЗВЛИЧАНЕ на шел-а от App.tsx в компоненти, та следващите
 * точки (Т9 dashboard, Т13 devices, Т33 tablet) пипат компоненти, а не
 * 228-редов App:
 *   · Shell   — собственик на сесийните ресурси на шел-а:
 *               - постоянният WS поток (usePacketStream от Т3) — първият
 *                 НЕтранзиентен WS консуматор: монтира се след login
 *                 (Shell се рендерира само при me != null), живее цялата
 *                 сесия; до Т14 PacketExplorer държи свой WS → transient
 *                 2 сокета на страницата Explorer; след Т14 потокът минава
 *                 в общ Provider с refcount — полето е подготвено (Shell
 *                 вече държи потока на едно място и само го предава надолу);
 *               - броячът на аларми (useAnomalyCount: poll /v1/anomalies
 *                 на 10s, източникът превключваем към critical-events след Т7);
 *               - banner-ът за начална парола; <main> е слот children.
 *   · Topbar  — лого + приложен LIVE (LiveIndicator compact от Т3) +
 *               подреден десен потребителски блок: username + role pill +
 *               🔑 + Изход (както днес, но в блок с margin-left:auto).
 *   · Sidebar — SECTIONS с икона+текст, групи (side-section/side-title),
 *               тюркоазен акцент-бар на активния (+ aria-current="page"),
 *               danger badge с брояча на аларми на „Мониторинг".
 *   · SECTIONS/PAGES/PageId се местят ТУК (с новите полета icon/badge);
 *     App импортира PAGES за валидацията на ?p=.
 *   · Me се мести тук; App го ре-експортира (`export type { Me }`), та
 *     8-те легаси страници с `import type { Me } from '../App'` не се пипат.
 *
 * Навигацията остава ?p= (без router — docs/16 „Какво не влиза").
 * DOM: СЪЩИТЕ класове/йерархия като днешния App (div.shell > banner?,
 * header.topbar, div.body > aside.sidebar + main) + modals на същото място
 * (проп overlays) — страниците, разчитащи на шел DOM, не усещат разликата
 * (проверено с grep: нула консуматори на .side-btn/.topbar/.sidebar извън
 * App.tsx; вж. notes.md §Рискове).
 *
 * Правила (Т1): само токени, нищо под 12px, без сенки, radius 4/8/12,
 * z-стълбата не се пипа (топбарът остава sticky z 5). НУЛА нови npm
 * пакети; TypeScript strict + jsx: react-jsx (React типовете — глобални,
 * както в App.tsx / ui.tsx / Brand.tsx).
 * ========================================================================== */
import { api } from '../api'
import { BrandMark } from './Brand'
import { LiveIndicator, usePacketStream, type LiveState } from './ui'
import {
  useAnomalyCount,
  type AnomalySource,
  type AnomalySummary,
} from '../hooks/useAnomalyCount'

/* ============================================================================
 * 1. ОБЩИ ТИПОВЕ + SECTIONS (идват от App.tsx редове 43–80)
 * ========================================================================== */

/** Сесийният потребител — преместен от App.tsx. App.tsx го ре-експортира,
 *  за да останат непипнати 8-те страници с `import type { Me } from '../App'`. */
export type Me = { id: string; username: string; role: string; default_password: boolean }

export interface ShellItem {
  id: string
  label: string
  /** Собствен глиф, който бие картата GLYPHS по-долу (рядко нужно —
   *  резервно поле за екрани, добавяни след Т6). */
  icon?: string
  /** Само за admin (днес: Profiles) — филтрира се в Sidebar. */
  adminOnly?: boolean
  /** Скрит от менюто, но достъпен чрез ?p= (днес: регресионният полигон
   *  на Т3 — „Компоненти"). */
  hidden?: boolean
  /** Този item носи брояча на аларми (danger badge; днес: Мониторинг).
   *  Отделно поле, не id-проверка — след Т7 брояч може да оглави и друг
   *  екран (напр. Т9 панел „Критични събития"). */
  badge?: 'alarm'
}

export interface ShellSection {
  /** Празен титул → група без заглавие (долният блок „План & Тестове"). */
  title: string
  items: ShellItem[]
}

/* --- карта id→глиф -------------------------------------------------------
 * Единственото място с икони. Критерий за избор: КОДОВИ ТОЧКИ БЕЗ свойство
 * Emoji_Presentation (геометрични форми / стрелки / математика / флагове
 * U+2690–2691) → рендерират се монохромно като текст на ВЯРКА платформа,
 * няма „emoji карнавал" (инструментът/облакът/пликът като ЦВЕТНИ emoji
 * под Android/iOS са точно това, което избягваме).
 * Т33 (tablet, sidebar до икони): същите глифове остават — етикетите се
 * скриват с CSS, не с друга карта.
 * Фallback при липсващ глиф в шрифта на дадена ОС: '•' (винаги наличен);
 * запасни кандидати по item — в notes.md §Икони.
 * ------------------------------------------------------------------------ */
const GLYPHS: Record<string, string> = {
  overview: '▦', // решетка — обзор/KPI табло
  monitor: '∿', // осцилограма — мониторинг (носи и брояча аларми)
  devices: '⬡', // възел на mesh-а — устройства и мрежа
  packets: '⇄', // входящо/изходящ поток — Packet Explorer
  map: '⌖', // мерник/позиция — карта
  broker: '◉', // хъб с център — MQTT брокер
  bridges: '⇌', // двупосочна връзка — мостове
  routing: '◇', // решение/условие — правила за рутиране
  notifications: '⚑', // флаг — известия
  integrations: '⧉', // свързани квадратчета — интеграции
  system: '▣', // ядро с вдлъбнатина — система и сигурност
  profiles: '⊞', // профилна матрица — Profiles (admin)
  plan: '✓', // план & тестове
}

function glyphOf(item: ShellItem): string {
  return item.icon ?? GLYPHS[item.id] ?? '•'
}

// дървото от визията (docs/11-ui-vision-plan.md §1): секция се показва само
// когато зад нея има реален екран — дефиницията е 1:1 от App.tsx (Т6 В2
// я мести тук), с новите полета icon (чрез GLYPHS) и badge.
export const SECTIONS: ShellSection[] = [
  { title: 'Dashboard', items: [{ id: 'overview', label: 'Overview' }] },
  {
    title: 'Monitoring',
    items: [
      { id: 'monitor', label: 'Мониторинг', badge: 'alarm' },
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

/** Всички страници (за валидация на ?p= в App — 1:1 от App.tsx). */
export const PAGES = SECTIONS.flatMap((s) => s.items)

/** Легитимните стойности на ?p= — изведен от PAGES, както в App.tsx. */
export type PageId = (typeof PAGES)[number]['id']

/* ============================================================================
 * 2. Topbar — лого + приложен LIVE + потребител
 * ========================================================================== */

export interface TopbarProps {
  me: Me
  /** Живият поток на сесията (usePacketStream, монтиран в Shell) —
   *  структурно съвместим резен: { state, pulsing }. PacketStream минава
   *  директно; за прегледност Topbar вижда само екрана на LiveIndicator. */
  live: { state: LiveState; pulsing: boolean }
  /** Отваря ChangePassword (от 🔑). Банерът за начална парола също сочи
   *  натам (в Shell). */
  onPassword: () => void
}

export function Topbar({ me, live, onPassword }: TopbarProps) {
  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className="brand">
          <BrandMark size={22} />
          <span className="brand-word">
            Mesh<span className="brand-word-gate">Gate</span>
          </span>
        </div>
        {/* приложен LIVE: живот/пулс на ЦЯЛАТА мрежа от постоянния WS на
            шел-а; idle не се вижда тук (топбарът никога не паузира потока —
            паузата е екранно понятие, Т14); reconnect се вижда при срив */}
        <div
          className="topbar-live"
          title="Жив поток от приемника (WS): LIVE при получаване на пакети; пулс — само при нови данни"
        >
          <LiveIndicator state={live.state} pulsing={live.pulsing} compact />
        </div>
      </div>
      {/* по-подреден десен блок (спек Т6): username + роля + 🔑 + Изход.
          margin-left:auto (shell.css Т6.1) го избутва надясно — днес блокът
          стоеше до бранда; това е единственото съзнателно разместване. */}
      <div className="topbar-right">
        <span className="topbar-user" title={`влезан като ${me.username} (роля: ${me.role})`}>
          {me.username}
        </span>
        <span className="pill" title={`роля: ${me.role}`}>
          {me.role}
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
 * 3. Sidebar — сегменти с икона+текст, групи, акцент на активния, брояч
 * ========================================================================== */

export interface SidebarProps {
  /** По подразбиране SECTIONS (експортиран за тестове/Т9). */
  sections?: ShellSection[]
  /** id на активната страница — акцент-бар + aria-current="page". */
  active: string
  /** Избира страница. Стринг, не PageId: Sidebar не знае типа на App;
   *  Shell каства безопасно (PAGES е flatMap на същите SECTIONS). */
  onSelect: (id: string) => void
  /** Филтрира adminOnly елементите (днес: Profiles). */
  isAdmin: boolean
  /** Броячът от useAnomalyCount; null → още без успешен poll → без badge;
   *  alarm === 0 → без badge (не „0" — спек Т6). */
  alarm?: AnomalySummary | null
}

/** Броя в badge: над 99 → „99+" (кратко, не се пръска бутонът). */
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
                // достъпно име с ПЪЛНИЯ разпад (не само числото) — чете се с
                // Tab/ VoiceOver; виж notes.md §Брояч защо без aria-live
                const ariaAlarm =
                  hasBadge && alarm != null
                    ? `аларми (${alarm.hours} ч): ${alarmCount} — мъртви букви: ` +
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
                    className={isActive ? 'side-btn active' : 'side-btn'}
                    aria-current={isActive ? 'page' : undefined}
                    aria-label={ariaAlarm ?? undefined}
                    title={titleAlarm ?? undefined}
                    onClick={() => onSelect(p.id)}
                  >
                    <span className="side-btn__icon" aria-hidden="true">
                      {glyphOf(p)}
                    </span>
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
 * 4. Shell — собственикът на сесийните ресурси + складът на шел-а
 * ========================================================================== */

export interface ShellProps {
  me: Me
  /** Активната страница (state-ът остава в App — ?p= логиката е там). */
  page: PageId
  /** Смяна на страницата (пряко SetStateAction на App). */
  onPage: (p: PageId) => void
  /** Отваря ChangePassword — от 🔑 в Topbar И от банера за начална парола. */
  onPassword: () => void
  /** Модалите на App (ChangePassword, Onboarding): рендерират се в края
   *  на div.shell — ТОЧНО както днес → нула DOM разместване спрямо стария
   *  шел (те са .modal-back с position:fixed, но не мъркаме и с инч). */
  overlays?: React.ReactNode
  /** Източник на брояча: 'anomalies' (днес) | 'critical-events' (след Т7 —
   *  превключвателят от спека е ТОЗИ проп, нищо друго не се меня). */
  alarmSource?: AnomalySource
  /** Съдържанието на <main> — <PageBoundary> + страниците от App. */
  children: React.ReactNode
}

export function Shell({
  me,
  page,
  onPage,
  onPassword,
  overlays,
  alarmSource = 'anomalies',
  children,
}: ShellProps) {
  // ПЪРВИЯТ постоянен WS консуматор (Т3 usePacketStream): Socketът се
  // отваря при монтиране на Shell (след login), живее цялата сесия с
  // exponential backoff при срив и НЕ се влияе от смяната на страниците.
  // Handler не се връзва (onDataBind не се вика) — ползваме само
  // state/pulsing за LiveIndicator; пулсът се храни от всяка WS рамка.
  // До Т14: на страницата Packet Explorer има 2 сокета (нейният си е неин)
  // — transient, документирано; след Т14: общ Provider с refcount, Shell
  // остава единственото място, което държи потока (полето е подготвено).
  const live = usePacketStream()

  // Броячът на аларми: poll на 10s, пауза в скрит таб, грешка не мига
  // badge-а. summary отива в Sidebar; error сега не се показва (console /
  // notes.md §Рискове за решението), refresh е изложен за консуматори.
  const { summary: alarm } = useAnomalyCount({ hours: 24, intervalMs: 10_000, source: alarmSource })

  return (
    <div className="shell">
      {me.default_password && (
        <div className="banner">
          ⚠ Използваш НАЧАЛНАТА парола на системата. Смени я сега:
          <button onClick={onPassword}>Смяна на парола</button>
        </div>
      )}
      <Topbar me={me} live={live} onPassword={onPassword} />
      <div className="body">
        {/* cast-ът в onSelect е безопасен по конструкция: PAGES (източникът
            на PageId) е flatMap на същите SECTIONS, от които идват тези id */}
        <Sidebar
          active={page}
          onSelect={(id) => onPage(id as PageId)}
          isAdmin={me.role === 'admin'}
          alarm={alarm}
        />
        <main>{children}</main>
      </div>
      {overlays}
    </div>
  )
}
