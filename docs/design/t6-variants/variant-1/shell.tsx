/* MeshGate — Т6 „Топбар + sidebar + брояч аларми" — Вариант 1
 * „Консервативен рестил на Shel-а"
 * ============================================================================
 * Дестинация при внедряване: apps/web/src/App.tsx — секции A–D по-долу са
 * готови декларации (copy-paste на едно място), E–F са ДВЕ точни кръпки в
 * вече съществуващия JSX. Пътищата в import-ите предполагат крайното
 * местоположение App.tsx (както е конвенцията от t3-variants).
 * Стилове: variant-1/shell.css → подблок „Т6" в секция 4.1 SHELL на
 * apps/web/src/styles.css.
 *
 * Стратегия В1: DOM структурата на App.tsx се ЗАПАЗВА 1:1 (топбар: brand →
 * topbar-right; sidebar: side-section > side-title + side-btn; ?p= навигация
 * непипана). Промените са само три:
 *   (а) икона-глиф пред всеки sidebar item — SIDE_ICON const с МОНОХРОМНИ
 *       unicode символи с консистентна оптическа тежест (не emoji пазар);
 *       цветът следва текста (inherit) → неутрален=muted, активен=акцент;
 *   (б) LIVE индикатор в топбара, вдясно от лого-блока — TopbarLive
 *       (LiveIndicator compact + usePacketStream);
 *   (в) БРОЯЧ аларми като badge върху „Мониторинг" — AlarmBadge +
 *       useAnomalyCount (polling на /v1/anomalies?hours=24 на 10 s).
 *
 * КЛЮЧОВО решение: никой нов hook не стои в тялото на App(). App() има
 * early return-и (loading / Login) — hook там би polling-вал и би отварял
 * WS още на екрана за вход. Затова и WS потокът, и броячът живеят в малки
 * компоненти (TopbarLive / AlarmBadge), които се монтират ЧАК с логнатия
 * шел и се демонтират при изход (WS се затваря от cleanup-а на хука).
 *
 * ЖИВ ПОТОК — 2 сокета (transient, по план): топбарът е ПЪРВИЯТ ПОСТОЯНЕН
 * консуматор на /api/v1/packets/ws. PacketExplorer държи СВОЯ WS до Т14 —
 * на ?p=packets има 2 отворени сокета едновременно (безобидно: сървърът
 * мултиплексира; данните не се споделят). След Т13/Т14 се вдига общ
 * PacketStreamProvider на контекст с refcount (виж коментара в
 * components/ui.tsx §7) и топбарът минава под него с ~1 ред.
 *
 * Правила (Т1 система), спазени тук: само токени (0 нови hex), нищо под
 * 12px, без сенки, 1px граници, radius 4/8/12, z-стълбата непипана
 * (топбар 5 < панел-fs 8 < модал 10 < toast 20). НУЛА нови npm пакети.
 */

/* ============================================================================
 * §A. import-и, които се ДОБАВЯТ в App.tsx (останалите ги има)
 * ============================================================================
 * В App.tsx вече има: `import { Component, useEffect, useState } from 'react'`
 * и `import { api, Unauthorized } from './api'`. Новите редове са:
 *
 *   import { LiveIndicator, usePacketStream } from './components/ui'
 *
 * (Т3 платформата — apps/web/src/components/ui.tsx — е готова и в дървото.)
 * Секциите B–D по-долу носят собствените си `useEffect`/`useState`/`api`
 * употреби; при сливане в App.tsx import-ите се обединяват.
 */
import { useEffect, useState } from 'react'
import { api } from './api'
import { LiveIndicator, usePacketStream } from './components/ui'

/* ============================================================================
 * §B. SIDE_ICON — монохромни глифове за sidebar-а (Т6 а)
 * ============================================================================
 * Изборът е от блокове с текстова (не-emoji) презентация: Geometric Shapes,
 * Arrows, Misc Technical, Math Operators. Двата символа от Misc Symbols
 * (⚑ ⚙) носят U+FE0E (VARIATION SELECTOR-15), за да не се рендерират като
 * цветни emoji на мобилни платформи. Фиксираната ширина (20px в CSS) изравнява
 * колоната на етикетите; размерът е 13px — над подовата граница 12px.
 * Смяна на глиф = 1 ред тук, нула CSS (затова е const, не hardcoded JSX).
 */
const SIDE_ICON: Record<string, string> = {
  overview: '⌂', // Диаграма/начало — Misc Technical
  monitor: '◉', // „радарът" на системата — наблюдение
  devices: '⬡', // hexagon = mesh възел
  packets: '▤', // редове данни — потокът/таблицата на Explorer
  map: '⌖', // position indicator — картата
  broker: '▣', // „сервъра" — брокер/регистър
  bridges: '⇄', // двупосочен обмен — мостове
  routing: '⇉', // препращане по веригата — правила
  notifications: '⚑\uFE0E', // флаг = внимание/аларма (+ текстова презентация)
  integrations: '⊕', // „разширяване" — вклинюване навън
  system: '⚙\uFE0E', // системата/зъбното колело (+ текстова презентация)
  profiles: '⊙', // идентитет/потребител
  plan: '▦', // тестова решетка — план & тестове
  ui: '⌗', // скритият полигон на Т3 (виж SECTIONS.hidden; несменяемо)
}

/* ============================================================================
 * §C. useAnomalyCount — броячът на аларми (Т6 в)
 * ============================================================================
 * Източник: GET /v1/anomalies?hours=24 (готов, RBAC viewer; apps/api/app/
 * routes/meta.py ред 254+). Отговор: {hours, events:[{ts, kind, label}]} —
 * api() в apps/web/src/api.ts вече развързва body.data.
 *
 * КОИ kind-ове се броят (и защо) — само ЛОШИТЕ:
 *   · deadletter     — пакет, изгубен от рутирането: реална оперативна тревога;
 *   · notify_failed  — известието трябваше да алармира оператора и НЕ успя —
 *                      провалът му иначе е невидим (точно затова е в брояча).
 * НЕ се броят: notify_sent (успех — обратна връзка, не тревога) и
 * rule_publish (нормално административно действие — audit следа, не аларма).
 *
 * СЛЕД Т7 (превключвател по спека): източникът се сменя на
 * GET /v1/critical-events (евтин, оценен от бекенда: батерия/dead-letter/
 * мълчание + ack/silence състояние) — интерфейсът на хука {count,
 * deadletter, notifyFailed, title} остава, ALARM_KINDS филтърът се маха,
 * щом събитието носи ack-статус. Точката на смяна е бележката по-долу.
 */
type AnomalyEvent = { ts: string; kind: string; label: string }

/** Само „лошите" kind-ове (виж коментара на блока). СЛЕД Т7: махни филтъра. */
const ALARM_KINDS: ReadonlySet<string> = new Set(['deadletter', 'notify_failed'])

/** Polling период — 10 s по спека на Т6. */
const ALARM_POLL_MS = 10_000

/** Брояч аларми за шел-а. Монтиран само в логнатия шел (AlarmBadge по-долу),
 *  затова не polling-ва на Login екрана. При грешка запазва последната
 *  стойност (flapping мрежа не кара badge-а да мига); докато не е заредено
 *  никога — count=0 → badge скрит („скрит при 0" по спека). */
function useAnomalyCount() {
  const [events, setEvents] = useState<AnomalyEvent[] | null>(null)

  useEffect(() => {
    let dead = false
    const load = async () => {
      // фонов таб: пропускаме заявката (NOC таб в background не товари API);
      // при връщане на фокус данните се обновяват на следващия тик (≤10 s)
      if (document.hidden) return
      try {
        const r = await api<{ hours: number; events: AnomalyEvent[] }>(
          '/v1/anomalies?hours=24',
        )
        if (!dead) setEvents(r.events ?? [])
      } catch {
        /* 401/мрежа: шел-ът не умира от временен отказ; пазим старата стойност */
      }
    }
    load()
    const t = setInterval(load, ALARM_POLL_MS)
    return () => {
      dead = true
      clearInterval(t)
    }
  }, [])

  const deadletter = events?.filter((e) => e.kind === 'deadletter').length ?? 0
  const notifyFailed = events?.filter((e) => e.kind === 'notify_failed').length ?? 0
  const count = deadletter + notifyFailed
  const title =
    count > 0
      ? `Аномалии (24 ч): ${deadletter} мъртви букви · ${notifyFailed} провалени известия — клик за Мониторинг`
      : 'Няма аларми в последните 24 часа'
  return { count, deadletter, notifyFailed, title, loaded: events != null }
}

/* ============================================================================
 * §D. Двете малки компоненти-потребители (монтират се чак с логнатия шел)
 * ============================================================================ */

/** (б) LIVE в топбара — ПЪРВИЯТ постоянен консуматор на живия поток.
 *  Compact вариант (LiveIndicator compact), без интеракция: състоянието се
 *  ЧЕТЕ (live=зелена плътна точка / idle=куха точка+„СПРЯН" / reconnect=
 *  жълто+„СВЪРЗВАНЕ…"); пулс-рингът идва САМО при реално пристигнали данни
 *  (useLivePulse в сърцето на usePacketStream) — правило №9 на docs/16.
 *  Пауза не се предлага на ниво шел (топбарът е винаги-жив монитор). */
function TopbarLive() {
  const live = usePacketStream()
  return (
    <div className="topbar-live">
      <LiveIndicator
        state={live.state}
        pulsing={live.pulsing}
        compact
        title="Жив поток от приемника (WS /api/v1/packets/ws)"
      />
    </div>
  )
}

/** (в) Badge върху „Мониторинг": danger при >0, скрит при 0 (връща null).
 *  Носи целия polling (§C); title tooltip-ът дава разпада
 *  мъртви букви / провалени известия. Клик → самият sidebar бутон вече
 *  води към Мониторинг (badge-ът не е отделен линк — 1 фокус, 1 target). */
function AlarmBadge() {
  const a = useAnomalyCount()
  if (a.count <= 0) return null
  return (
    <span className="side-badge" title={a.title}>
      {a.count}
    </span>
  )
}

/* ============================================================================
 * §E. КРЪПКА 1 — топбарът на App.tsx (подравняване + LIVE)
 * ============================================================================
 * МЯСТО: в `<header className="topbar">`, МЕЖДУ затварящия `</div>` на
 * блока `.brand` (този с BrandMark + wordmark + role pill — pill остава
 * вътре в лого-блока по спека) и отварящия `<div className="topbar-right">`.
 * Едновремено: .topbar-right получава margin-left:auto (виж shell.css,
 * корекция К2) → потребителският клъстер отива в дясния ръб (днес стои
 * до лого-блока — това е „подравняването" от спека).
 *
 *   <header className="topbar">
 *     <div className="brand">
 *       <BrandMark size={22} />
 *       <span className="brand-word">Mesh<span className="brand-word-gate">Gate</span></span>
 *       <span className="pill">{me.role}</span>
 *     </div>
 *     <TopbarLive />                                    ← + НОВО (този ред)
 *     <div className="topbar-right">                    (несменено долу)
 *       …
 */

/* ============================================================================
 * §F. КРЪПКА 2 — sidebar бутонът на App.tsx (икона + текст + badge)
 * ============================================================================
 * МЯСТО: в `<aside className="sidebar">`, вътрешността на map-натия
 * `<button className={page === p.id ? 'side-btn active' : 'side-btn'} …>`.
 * СЕГА (App.tsx ред ~154–160):        СТАВА:
 *
 *   <button                            <button
 *     key={p.id}                         key={p.id}
 *     className={page === p.id           className={page === p.id
 *       ? 'side-btn active'                ? 'side-btn active'
 *       : 'side-btn'}                      : 'side-btn'}
 *     onClick={() => setPage(p.id)}      onClick={() => setPage(p.id)}
 *   >                                  >
 *     {p.label}                          <span className="side-ico" aria-hidden="true">
 *                                        {SIDE_ICON[p.id] ?? '•'}
 *                                      </span>
 *                                      <span className="side-label">{p.label}</span>
 *                                      {p.id === 'monitor' && <AlarmBadge />}
 *                                    </button>
 *
 * Нищо друго в sidebar-а не се пипа: side-section/side-title групите,
 * филтърът adminOnly/hidden и ?p= навигацията остават 1:1. Активният
 * акцент идва от готовото .side-btn.active (тюркоаз + semibold) — иконата
 * и етикетът наследяват цвета му (контраст: виж notes.md §Контраст).
 */
