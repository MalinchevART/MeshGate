import { useEffect, useMemo, useRef, useState } from 'react'
import { api, fmtTime } from '../api'
import { MetricCard, Panel, StatusChip, LiveIndicator, usePacketStream } from '../components/ui'
import { useAnomalyCount } from '../hooks/useAnomalyCount'
import { useNodeNames } from '../names'

/* ============================================================================
 * MeshGate · KPI Дашборд (Т9-предварителен срез върху готови API-та)
 * ----------------------------------------------------------------------------
 * „Мрежата сега" на един екран, без скрол: KPI ред → трафик → живи пакети.
 * Всичко от СЪЩЕСТВУВАЩИТЕ endpoint-и (нула нов бекенд):
 *   /v1/stats/overview?hours=  — кофи по час + семейства теми + батерии
 *   /v1/packets/facets?hours=  — активни възли + декодируемост
 *   /v1/devices/topology?hours — RF връзки (кой кого чу, SNR)
 *   /v1/anomalies (useAnomalyCount от Т6) — аларми
 *   WS /api/v1/packets/ws (usePacketStream от Т3) — „Последни пакети" живи
 * Пълният Т9 (критични събития с ack/silence, пончик) идва след Т7/Т8.
 * ========================================================================== */

type Battery = { node: string; battery: number; ts: string }

/** Т8: ЕДНОТО GET /v1/dashboard — източникът на KPI реда, трафика, пончика
 *  и изпратените (консистентност по конструкция с останалите endpoints). */
type Dashboard = {
  hours: number
  kpi: {
    windows: { nodes: number; rf: number; alarms: number; sent: number }
    nodes: { active: number; total: number }
    packets: { total: number; per_hour: number; last_hour: number }
    rf: { links: number; stable: number; stable_snr_db: number; nodes: number }
    alarms: { open: number }
  }
  traffic: { bucket: string; count: number }[]
  sent_24h: { bucket: string; sent: number; failed: number }[]
  channels: { name: string; count: number }[]
}

/** Само за „Слаби батерии" (dashboard не носи телеметрия по-design). */
type StatsOverview = { batteries: Battery[] }

type LivePacket = {
  id: string
  ts: string
  topic: string
  packet_type: string
  decode_status: string
}

const PERIODS = [
  { id: 6, label: '6 ч' },
  { id: 24, label: '24 ч' },
  { id: 168, label: '7 д' },
] as const
type PeriodId = (typeof PERIODS)[number]['id']

/** topic → канал/възел за живите редове (1:1 от PacketExplorer). */
function topicParts(topic: string): { channel: string | null; node: string | null } {
  const toks = topic.split('/')
  const node = toks.find((t) => t.startsWith('!')) ?? null
  let channel: string | null = null
  const i = toks.findIndex((t) => t === 'e' || t === 'c' || t === 'json')
  if (i >= 0 && toks[i + 1] && !toks[i + 1].startsWith('!')) channel = toks[i + 1]
  return { channel, node }
}

const TYPE_LABEL: Record<string, string> = {
  'meshtastic-text': 'текст',
  'meshtastic-telemetry': 'телеметрия',
  'meshtastic-position': 'позиция',
  'meshtastic-nodeinfo': 'възел инфо',
  'meshtastic-neighbor': 'съседи',
  'meshtastic-routing': 'рутинг',
  'meshtastic-encrypted': 'криптирано',  binary: 'бинарен',
  json: 'JSON',
  text: 'текст',
}

function fmtNum(n: number): string {
  return n.toLocaleString('bg-BG')
}

/* ============================================================================
 * Панел „Критични събития" (Т7 в UI): какво буди оператора СЕГА + действие
 * от реда (✓ потвърди / 🔇 заглуши 4 ч). Данни: /v1/critical-events (Т7).
 * ========================================================================== */
type CriticalEvent = {
  event_key: string
  kind: 'battery' | 'deadletter' | 'silence' | 'geofence'
  severity: 'important' | 'critical'
  status: string
  payload: { node?: string; rule?: string; battery?: number; silent_hours?: number; deadletter_24h?: number; zone?: string; distance_m?: number }
  last_seen_at: string
  occurrences: number
}

const CRIT_KIND: Record<CriticalEvent['kind'], { icon: string; label: string }> = {
  battery: { icon: '🔋', label: 'батерия' },
  deadletter: { icon: '✉', label: 'мъртви букви' },
  silence: { icon: '🔇', label: 'мълчание' },
  geofence: { icon: '📍', label: 'геозона' },
}

function critDetail(e: CriticalEvent, nameOf: ReturnType<typeof useNodeNames>): string {
  if (e.kind === 'battery') return `${nameOf(e.payload.node).main} — ${Math.round(e.payload.battery ?? 0)}%`
  if (e.kind === 'deadletter') return `${e.payload.rule ?? '?'} — ${e.payload.deadletter_24h ?? '?'} за 24 ч`
  if (e.kind === 'geofence') return `${nameOf(e.payload.node).main} — напусна „${e.payload.zone ?? '?'}“ (${e.payload.distance_m ?? '?'} м от зоната)`
  return `${nameOf(e.payload.node).main} — мълчи ${e.payload.silent_hours ?? '?'} ч`
}

function CriticalPanel({ onChanged }: { onChanged?: () => void }) {
  const nameOf = useNodeNames()
  const [events, setEvents] = useState<CriticalEvent[] | null>(null)
  const [count, setCount] = useState(0)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const load = async () => {
    try {
      const r = await api<{ counts?: { open?: number }; events?: CriticalEvent[] }>(
        '/v1/critical-events?status=open&limit=8&hours=24',
      )
      setEvents(r.events ?? [])
      setCount(r.counts?.open ?? 0)
      setErr(null)
    } catch (e: any) { setErr(e.message) }
  }
  useEffect(() => {
    void load()
    const t = setInterval(() => { if (!document.hidden) void load() }, 10_000)
    return () => clearInterval(t)
  }, [])

  const act = async (key: string, action: 'ack' | 'silence') => {
    setBusy(key)
    try {
      await api(`/v1/critical-events/${encodeURIComponent(key)}/${action}`, {
        method: 'POST',
        body: action === 'silence' ? JSON.stringify({ hours: 4 }) : undefined,
      })
      await load()
      onChanged?.()
    } catch (e: any) { setErr(e.message) } finally { setBusy(null) }
  }

  return (
    <Panel
      title="Критични събития"
      subtitle={count > 8 ? `най-силните ${count} общо — потвърди или заглуши от реда` : 'потвърди или заглуши от реда'}
      className="dash-row__wide"
    >
      {err && <div className="empty">грешка: {err}</div>}
      {!events ? (
        <div className="empty">…</div>
      ) : events.length === 0 ? (
        <div className="empty">Няма критични събития — мрежата е спокойна. ✓</div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>Вид</th><th>Обект</th><th>Път</th><th>Сила</th><th></th></tr>
            </thead>
            <tbody>
              {events.map((e) => {
                const k = CRIT_KIND[e.kind] ?? { icon: '•', label: e.kind }
                return (
                  <tr key={e.event_key}>
                    <td>{k.icon} {k.label}</td>
                    <td className="small">{critDetail(e, nameOf)}</td>
                    <td className="mono small muted">{fmtTime(e.last_seen_at)}</td>
                    <td>
                      <StatusChip size="sm" tone={e.severity === 'critical' ? 'danger' : 'warning'}>
                        {e.severity === 'critical' ? 'критично' : 'важно'}
                      </StatusChip>
                    </td>
                    <td className="row-actions">
                      <button className="nav-btn" disabled={busy === e.event_key}
                              onClick={() => act(e.event_key, 'ack')}>✓ Потвърди</button>
                      <button className="nav-btn" disabled={busy === e.event_key}
                              onClick={() => act(e.event_key, 'silence')}>🔇 4 ч</button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}

export default function Overview() {
  const nameOfO = useNodeNames()
  const [period, setPeriod] = useState<PeriodId>(24)
  const [dash, setDash] = useState<Dashboard | null>(null)
  const [stats, setStats] = useState<StatsOverview | null>(null)
  const [error, setError] = useState<string | null>(null)

  // жив поток за „Последни пакети" (втори консуматор след шел-а; transient
  // до общия Provider с refcount в Т14)
  const stream = usePacketStream()
  const [live, setLive] = useState<LivePacket[]>([])
  const [seed, setSeed] = useState<LivePacket[] | null>(null)

  const { summary: alarm } = useAnomalyCount({ hours: 24, intervalMs: 10_000 })

  // stale-гвард: бавен отговор за стар период НЕ бива да презаписва по-нов
  // (7-дневната агрегация е тежка и пристига след по-бърката 6-часова)
  const loadSeq = useRef(0)

  useEffect(() => {
    const load = async () => {
      const my = ++loadSeq.current
      try {
        // Т9: ЕДНОТО GET на Т8 носи KPI/трафик/пончик/изпратени;
        // stats/overview остава само за „Слаби батерии" (телеметрия)
        const [d, s] = await Promise.all([
          api<Dashboard>(`/v1/dashboard?hours=${period}`),
          api<StatsOverview>(`/v1/stats/overview?hours=24`),
        ])
        if (loadSeq.current !== my) return
        setDash(d)
        setStats(s)
        setError(null)
      } catch (e: any) {
        if (loadSeq.current === my) setError(e.message)
      }
    }
    void load()
    const timer = setInterval(() => {
      if (!document.hidden) void load()
    }, 10_000)
    return () => clearInterval(timer)
  }, [period])

  // семена от историята + живият поток отгоре (пауза не къса сокета)
  useEffect(() => {
    api<LivePacket[]>('/v1/packets?limit=12')
      .then((r) => setSeed(Array.isArray(r) ? r : []))
      .catch(() => setSeed([]))
  }, [])

  useEffect(() => {
    // onDataBind НЕ връща unsubscribe — връзането се чисти с изричен null
    // (важно за Т14, когато сокетът ще е споделен и ще надживее страницата)
    const bind = (msg: unknown) => {
      const m = msg as { type?: string; data?: LivePacket } | null
      if (!m || m.type !== 'packet' || !m.data) return
      setLive((prev) => [m.data as LivePacket, ...prev].slice(0, 12))
    }
    stream.onDataBind(bind)
    return () => stream.onDataBind(null)
  }, [stream.onDataBind])

  // ---- производни числа (от dash — авторитетният източник на Т9) --------
  const derived = useMemo(() => {
    if (!dash || !stats) return null
    const weakBatt = stats.batteries.filter((b) => b.battery < 20)
    return {
      weakBatt,
      channels: dash.channels.filter((c) => c.count > 0),
      sent: dash.sent_24h,
    }
  }, [dash, stats])

  // кофи за графиката: 7д → 7 дневни колони, иначе часови
  const bars = useMemo(() => {
    if (!dash) return []
    if (period <= 24) {
      return dash.traffic.map((b) => ({
        label: new Date(b.bucket).toLocaleTimeString('bg-BG', { hour: '2-digit' }),
        value: b.count,
        title: `${new Date(b.bucket).toLocaleString('bg-BG')} · ${fmtNum(b.count)} пакета`,
        last: false,
      }))
    }
    const days = new Map<string, number>()
    for (const b of dash.traffic) {
      const d = new Date(b.bucket).toLocaleDateString('bg-BG', { weekday: 'short' })
      days.set(d, (days.get(d) ?? 0) + b.count)
    }
    return [...days.entries()].map(([label, value]) => ({
      label,
      value,
      title: `${label} · ${fmtNum(value)} пакета`,
      last: false,
    }))
  }, [dash, period])

  const maxBar = bars.length > 0 ? Math.max(...bars.map((b) => b.value)) : 1

  // пончик: порции на каналите (цвят от 4.11 палитрата по индекс)
  const donut = useMemo(() => {
    const list = derived?.channels ?? []
    const total = list.reduce((a, c) => a + c.count, 0)
    const R = 52
    const C = 2 * Math.PI * R
    let offset = 0
    const segs = list.slice(0, 10).map((c, i) => {
      const frac = total > 0 ? c.count / total : 0
      const seg = {
        ...c,
        cls: `mg-chan-${i % 10}`,
        len: frac * C,
        gap: C - frac * C,
        rot: (offset / C) * 360 - 90,
        pct: Math.round(frac * 100),
      }
      offset += c.count
      return seg
    })
    return { segs, total, R, C }
  }, [derived])

  if (error) return <div className="empty">Грешка: {error}</div>

  const rows = live.length > 0 ? live : (seed ?? [])

  return (
    <div>
      <div className="kicker">МРЕЖАТА СЕГА</div>
      <h1 className="h-page">Дашборд</h1>

      {/* ---- KPI ред: проблемът се вижда без скрол ------------------------ */}
      <div className="mg-card-grid">
        <MetricCard
          label={`Пакети · ${PERIODS.find((p) => p.id === period)?.label}`}
          value={dash ? fmtNum(dash.kpi.packets.total) : '…'}
          context={dash ? `последният час: ${fmtNum(dash.kpi.packets.last_hour)} · ${fmtNum(dash.kpi.packets.per_hour)}/ч средно` : '—'}
          icon="⇄"
        />
        <MetricCard
          label={`Активни възли${dash && dash.kpi.windows.nodes !== period ? ` · ${dash.kpi.windows.nodes} ч` : ''}`}
          value={dash ? fmtNum(dash.kpi.nodes.active) : '…'}
          tone="accent"
          icon="◉"
          context={dash ? `от ${fmtNum(dash.kpi.nodes.total)} известени на платформата` : '—'}
        />
        <MetricCard
          label={`RF връзки${dash && dash.kpi.windows.rf !== period ? ` · ${dash.kpi.windows.rf} ч` : ''}`}
          value={dash ? fmtNum(dash.kpi.rf.links) : '…'}
          tone={(dash?.kpi.rf.links ?? 0) === 0 ? 'neutral' : 'success'}
          icon="⇌"
          context={dash ? `${dash.kpi.rf.stable} стабилни (SNR ≥ ${dash.kpi.rf.stable_snr_db} dB)` : '—'}
        />
        <MetricCard
          label="Аларми · 24 ч"
          value={alarm ? fmtNum(alarm.alarm) : '…'}
          tone={(alarm?.alarm ?? 0) > 0 ? 'danger' : 'neutral'}
          icon="⚑"
          context={
            alarm
              ? alarm.alarm > 0
                ? `${alarm.byKind.battery} батерии · ${alarm.byKind.deadletter} мъртви букви · ${alarm.byKind.silence} мълчания`
                : 'нито едно критично събитие — мрежата е спокойна'
              : '—'
          }
        />
      </div>

      {/* ---- Критични събития (Т7): статус/аларми ПРЕДИ трафика по спецификацията на Т9 ---- */}
      <CriticalPanel />

      {/* ---- Трафик във времето + Изпратени 24ч ---------------------------- */}
      <div className="dash-row">
        <Panel
          title="Трафик във времето"
          subtitle="пакети по час от приемника"
          className="dash-row__wide"
          filters={
            <select value={period} onChange={(e) => setPeriod(Number(e.target.value) as PeriodId)}>
              {PERIODS.map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </select>
          }
          actions={<span className="text-muted-sm mono">{dash ? `∑ ${fmtNum(dash.kpi.packets.total)}` : ''}</span>}
        >
          {bars.length === 0 ? (
            <div className="empty">Няма данни за периода.</div>
          ) : (
            <div className="mg-bars" role="img" aria-label="Колона на всеки час; височината е броят пакети">
              {bars.map((b, i) => (
                <div
                  key={i}
                  className="mg-bars__col"
                  title={b.title}
                  style={{ flexGrow: 1 }}
                >
                  <div
                    className={`mg-bars__bar${i === bars.length - 1 ? ' mg-bars__bar--last' : ''}`}
                    style={{ height: `${Math.max(4, Math.round((b.value / maxBar) * 140))}px` }}
                  />
                  {(bars.length <= 12 || i % Math.ceil(bars.length / 12) === 0) && (
                    <span className="mg-bars__label">{b.label}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Изпратени последните 24 ч" subtitle="препращания от правилата + мъртви букви (кофи по 3 ч)" className="dash-row__side">
          {!derived ? (
            <div className="empty">…</div>
          ) : derived.sent.every((b) => b.sent === 0 && b.failed === 0) ? (
            <div className="empty">Никакви изпращания от правилата за 24 ч.</div>
          ) : (
            <div className="mg-sent" role="img" aria-label="Изпратени и провалени препращания по 3-часови кофи">
              {derived.sent.map((b, i) => {
                const max = Math.max(1, ...derived.sent.map((x) => x.sent + x.failed))
                const h = Math.max(4, Math.round(((b.sent + b.failed) / max) * 110))
                const fh = b.failed > 0 ? Math.max(3, Math.round((b.failed / (b.sent + b.failed)) * h)) : 0
                const hh = new Date(b.bucket).getHours()
                return (
                  <div key={i} className="mg-sent__col" title={`${new Date(b.bucket).toLocaleString('bg-BG')} · ${b.sent} изпратени${b.failed ? ` · ${b.failed} мъртви букви` : ''}`}>
                    <div className="mg-sent__stack" style={{ height: `${h}px` }}>
                      {b.failed > 0 && <div className="mg-sent__fail" style={{ height: `${fh}px` }} />}
                      <div className="mg-sent__ok" style={{ height: `${h - fh}px` }} />
                    </div>
                    <span className="mg-sent__label">{String(hh).padStart(2, '0')}</span>
                  </div>
                )
              })}
            </div>
          )}
        </Panel>
      </div>

      {/* ---- Пончик каналите + Слаби батерии -------------------------------- */}
      <div className="dash-row">
        <Panel title="Канали" subtitle="разпределение на трафика (Meshtastic канали)" className="dash-row__wide">
          {donut.segs.length === 0 ? (
            <div className="empty">Няма msh трафик в периода.</div>
          ) : (
            <div className="mg-donut">
              <svg viewBox="0 0 140 140" className="mg-donut__svg" role="img" aria-label="Пончик: дял на всеки канал">
                <circle cx="70" cy="70" r={donut.R} className="mg-donut__track" />
                {donut.segs.map((s) => (
                  <circle key={s.name} cx="70" cy="70" r={donut.R}
                    className={`mg-donut__seg ${s.cls}`}
                    strokeDasharray={`${s.len} ${s.gap}`}
                    pathLength={donut.C}
                    transform={`rotate(${s.rot} 70 70)`}>
                    <title>{`${s.name}: ${fmtNum(s.count)} пакета (${s.pct}%)`}</title>
                  </circle>
                ))}
                <text x="70" y="66" textAnchor="middle" className="mg-donut__num">{fmtNum(donut.total)}</text>
                <text x="70" y="80" textAnchor="middle" className="mg-donut__cap">пакета</text>
              </svg>
              <div className="mg-donut__legend">
                {donut.segs.map((s) => (
                  <div key={s.name} className="mg-donut__row">
                    <span className={`mg-chan-dot ${s.cls}`} />
                    <span className="mono small mg-donut__name" title={s.name}>{s.name}</span>
                    <span className="text-muted-sm mono">{fmtNum(s.count)} · {s.pct}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Panel>

        <Panel title="Слаби батерии" subtitle="най-изтощените възли (24 ч)" className="dash-row__side">
          {!stats ? (
            <div className="empty">…</div>
          ) : derived && derived.weakBatt.length === 0 ? (
            <div className="empty">Няма възел под 20% батерия.</div>
          ) : (
            <table>
              <tbody>
                {stats.batteries.slice(0, 5).map((b) => (
                  <tr key={b.node}>
                    <td className="small" title={b.node}>{nameOfO(b.node).main}</td>
                    <td style={{ textAlign: 'right' }}>
                      <StatusChip size="sm" tone={b.battery < 10 ? 'danger' : 'warning'}>
                        {Math.round(b.battery)}%
                      </StatusChip>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>

      {/* ---- Последни пакети (живи) — цял ред -------------------------------- */}
      <div className="dash-row">
        <Panel
          title="Последни пакети"
          subtitle="жив поток от приемника — без презареждане"
          className="dash-row__wide"
          actions={<LiveIndicator state={stream.state} pulsing={stream.pulsing} compact />}
          padded={false}
        >
          {rows.length === 0 ? (
            <div className="empty">Очакват се пакети…</div>
          ) : (
            <div className="table-scroll">
            <table>
              <thead>
                <tr><th>Час</th><th>Канал</th><th>Възел</th><th>Тип</th><th>Декод</th></tr>
              </thead>
              <tbody>
                {rows.map((p) => {
                  const parts = topicParts(p.topic)
                  const t = TYPE_LABEL[p.packet_type] ?? p.packet_type.replace(/^meshtastic-/, '')
                  return (
                    <tr key={p.id}>
                      <td className="mono small">{fmtTime(p.ts)}</td>
                      <td>{parts.channel ? <span className="tag ch">{parts.channel}</span> : <span className="muted">—</span>}</td>
                      <td className="small" title={parts.node ?? ''}>{parts.node ? nameOfO(parts.node).main : '—'}</td>
                      <td><span className="tag">{t}</span></td>
                      <td>
                        <StatusChip
                          size="sm"
                          flat
                          tone={p.decode_status === 'decoded' ? 'success' : p.decode_status === 'failed' ? 'danger' : 'neutral'}
                        >
                          {p.decode_status === 'decoded' ? 'декод.' : p.decode_status === 'failed' ? 'грешка' : p.decode_status}
                        </StatusChip>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}
