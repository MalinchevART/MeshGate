import { useEffect, useState } from 'react'
import { api, fmtTime } from '../api'
import { useNodeNames } from '../names'
import { MetricCard, Panel } from '../components/ui'
import { syncPageUrl } from '../components/Shell'
import TimeTab from './monitor/TimeTab'
import UtilityTab from './monitor/UtilityTab'

/* ============================================================================
 * MeshGate · Мониторинг (Т27 таб-шел): Обзор / Време / Полезност.
 * - Обзор: графиките + лентата на аномалиите в новия вид (Т3 Panel/MetricCard)
 * - Време: Водопад (Т28) + Ефир-часовник (Т29) — pages/monitor/TimeTab
 * - Полезност: Фунията (Т30) — pages/monitor/UtilityTab
 * Всеки таб е ?p= дълбока връзка (monitor / monitor-time / monitor-utility).
 * ========================================================================== */

type Bucket = { hour: string; count: number }
type Family = { family: string; count: number }
type Battery = { node: string; battery: number; ts: string }
type RuleStat = {
  name: string; enabled: boolean; matched: number; forwarded: number
  errors: number; last_fired_at: string | null
}
type Data = {
  buckets: Bucket[]; families: Family[]; batteries: Battery[]; rules: RuleStat[]
  mesh_deduped?: number
}
type FacetType = { type: string; count: number }
type Anomaly = { ts: string; kind: string; label: string }

export type MonitorTab = 'overview' | 'time' | 'utility'

const TABS: { id: MonitorTab; label: string; page: string }[] = [
  { id: 'overview', label: 'Обзор', page: 'monitor' },
  { id: 'time', label: 'Време', page: 'monitor-time' },
  { id: 'utility', label: 'Полезност', page: 'monitor-utility' },
]

const TYPE_LABEL: Record<string, string> = {
  'meshtastic-text': 'Текст',
  'meshtastic-telemetry': 'Телеметрия',
  'meshtastic-position': 'Позиция',
  'meshtastic-encrypted': 'Криптирано',
  'meshtastic-nodeinfo': 'Възел инфо',
  'meshtastic-neighbor': 'Съседи',
  'meshtastic-routing': 'Рутинг',
  'meshtastic-traceroute': 'Трейсрут',
  'meshtastic-map': 'Карта',
  binary: 'Бинарен',
  json: 'JSON',
  text: 'Текст (raw)',
}

/** Тон на маркера = клас от 4.11 DATA-VIZ (цветовете живеят в CSS токените) */
const KIND_CLS: Record<string, string> = {
  deadletter: 'mg-anom--danger',
  notify_sent: 'mg-anom--accent',
  notify_failed: 'mg-anom--danger',
  rule_publish: 'mg-anom--publish',
}

function Sparkline({ points, height = 120, anomalies = [], onMarker }: {
  points: number[]
  height?: number
  anomalies?: Anomaly[]
  onMarker?: (a: Anomaly) => void
}) {
  const w = 900, h = height, pad = 8
  const max = Math.max(1, ...points)
  const step = points.length > 1 ? (w - 2 * pad) / (points.length - 1) : 0
  const y = (v: number) => h - pad - (v / max) * (h - 2 * pad)
  const x = (i: number) => pad + i * step
  const path = points.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const area = `${path} L${(pad + (points.length - 1) * step).toFixed(1)},${h - pad} L${pad},${h - pad} Z`
  // всеки маркер попада в най-близката лява час-кофа на графиката
  const spanMs = points.length > 1 ? ((24 / (points.length - 1)) * 3600_000) : 24 * 3600_000
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ width: '100%', height }}>
      <defs>
        <linearGradient id="mgfill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" className="mg-spark-stop" stopOpacity="0.35" />
          <stop offset="100%" className="mg-spark-stop" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#mgfill)" />
      <path d={path} fill="none" className="mg-spark-line" strokeWidth="2" />
      {anomalies.map((a, i) => {
        const t = new Date(a.ts).getTime()
        const ageMs = Date.now() - t
        const idx = Math.round((1 - ageMs / (points.length * spanMs)) * (points.length - 1))
        if (idx < 0 || idx >= points.length) return null
        return (
          <line key={i} x1={x(idx)} y1={pad} x2={x(idx)} y2={h - pad}
            className={KIND_CLS[a.kind] ?? 'mg-anom--muted'} strokeWidth="1.5" strokeDasharray="3 3" opacity="0.8"
            style={{ cursor: onMarker ? 'pointer' : 'help' }}
            onClick={() => onMarker?.(a)}>
            <title>{`${new Date(a.ts).toLocaleString('bg-BG')} · ${a.label}`}</title>
          </line>
        )
      })}
    </svg>
  )
}

const LAST_TOKEN: Record<string, string> = {
  up: 'телеметрия', pos: 'позиции', msg: 'съобщения', priv: 'частни',
}

function familyLabel(fam: string): string {
  const toks = fam.split('/')
  if (fam.startsWith('msh/')) {
    const chIdx = toks.findIndex((t) => t === 'e' || t === 'c' || t === 'json')
    const channel = chIdx >= 0 && toks[chIdx + 1] ? toks[chIdx + 1] : (toks[3] || '')
    return `Meshtastic ${toks[1] || ''} — ${channel}`
  }
  const net = toks.slice(0, 2).join('/')
  const kind = LAST_TOKEN[toks[toks.length - 1]] || toks[toks.length - 1]
  return `${net === 'mesh/emul' ? 'демо мрежа' : net} — ${kind}`
}

function batteryClass(b: number): string {
  return b < 20 ? 'tag bad' : b < 50 ? 'tag' : 'tag ok'
}

/* ============================================================================
 * Таб „Обзор" — същите данни (stats/overview + facets + topology + anomalies)
 * в новия вид: MetricCard ред (Т3) + Panel-и.
 * ========================================================================== */
function OverviewTab() {
  const nameOf = useNodeNames()
  const [data, setData] = useState<Data | null>(null)
  const [types, setTypes] = useState<FacetType[] | null>(null)
  const [topo, setTopo] = useState<{ edges: number; nodes: number } | null>(null)
  const [anoms, setAnoms] = useState<Anomaly[]>([])

  useEffect(() => {
    const load = () => {
      api('/v1/stats/overview?hours=24').then(setData).catch(() => {})
      api('/v1/packets/facets?hours=24').then((f: any) => setTypes(f.types)).catch(() => {})
      api('/v1/devices/topology?hours=24')
        .then((t: any) => setTopo({ edges: (t.edges ?? []).length, nodes: t.nodes }))
        .catch(() => {})
      api('/v1/anomalies?hours=24')
        .then((r: any) => setAnoms(r.events ?? []))
        .catch(() => {})
    }
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [])

  const total24 = (data?.buckets ?? []).reduce((s, b) => s + b.count, 0)
  const maxFam = Math.max(1, ...(data?.families ?? []).map((f) => f.count))

  return (
    <>
      {/* KPI ред (Т3 MetricCard) — същите числа, новият вид */}
      <div className="mg-card-grid">
        <MetricCard label="Съобщения · 24 ч" value={total24.toLocaleString('bg-BG')} icon="⇄"
                    context="пакети, стигнали платформата" />
        <MetricCard label="Активни канала" value={String(data?.families.length ?? '…')} tone="accent" icon="◍"
                    context="семейства теми с трафик" />
        <MetricCard label="Наблюдавани възли" value={String(data?.batteries.length ?? '…')} icon="◉"
                    context="с телеметрия за батерия" />
        <MetricCard label="Правила (включени)" icon="☰"
                    value={data ? `${data.rules.filter((r) => r.enabled).length} / ${data.rules.length}` : '…'}
                    context="активни от общо дефинирани" />
        <MetricCard label="Дедупликация (mesh)" icon="⧉"
                    value={((data?.mesh_deduped ?? 0) as number).toLocaleString('bg-BG')}
                    context="повторни копия, спестени на системата" />
        <MetricCard label="Връзки (24 ч)" icon="⇌"
                    tone={(topo?.edges ?? 0) === 0 ? 'neutral' : 'success'}
                    value={topo ? topo.edges.toLocaleString('bg-BG') : '…'}
                    context={topo ? `${topo.nodes} възела с връзки` : 'от NeighborInfo пакетите'} />
      </div>

      <Panel title="Трафик по часове" subtitle="последни 24 часа · обновява се на всеки 30 сек" className="dash-row__wide">
        <Sparkline points={(data?.buckets ?? []).map((b) => b.count)} anomalies={anoms}
          onMarker={(a) => {
            if (a.kind === 'deadletter') {
              sessionStorage.setItem('mg_pe_topic', 'deadletter/')
              location.href = '/?p=packets'
            }
          }} />
        {data && data.buckets.length > 0 && (
          <div style={{ display: 'flex', justifyContent: 'space-between' }} className="muted small">
            <span>{new Date(data.buckets[0]?.hour).toLocaleString('bg-BG')}</span>
            <span>сега</span>
          </div>
        )}
        {anoms.length > 0 && (
          <div className="muted small" style={{ marginTop: 4 }}>
            маркери: <span className="mg-tone--danger">▬ мъртви букви / провалени известия</span>{' '}
            · <span className="mg-tone--accent">▬ изпратени известия</span>{' '}
            · <span className="mg-tone--publish">▬ публикувани правила</span>{' '}
            — {anoms.length} събития (24 ч); клик върху червено → мъртвите букви в Explorer
          </div>
        )}
      </Panel>

      <div className="dash-row">
        <Panel title="Разпределение по вид съобщение" subtitle="24 ч" className="dash-row__wide">
          {!types || types.length === 0 ? (
            <div className="empty">Няма разпознати типове за периода.</div>
          ) : types.slice(0, 8).map((t) => {
            const pct = Math.round((t.count / (types[0].count || 1)) * 100)
            return (
              <div key={t.type} style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '4px 0' }}>
                <span style={{ width: 110 }} className="small">
                  {TYPE_LABEL[t.type] ?? t.type.replace(/^meshtastic-/, '')}
                </span>
                <div className="mg-bar-track">
                  <div className="mg-dist-bar" style={{ width: `${Math.max(pct, 2)}%` }} />
                </div>
                <span className="muted small" style={{ width: 70, textAlign: 'right' }}>
                  {t.count.toLocaleString('bg-BG')}
                </span>
              </div>
            )
          })}
        </Panel>

        <Panel title="Батерии на възлите" subtitle="най-изтощените (24 ч)" className="dash-row__side">
          {!data || !data.batteries.length ? (
            <div className="empty">Няма телеметрия с батерии (поле battery в payload).</div>
          ) : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {data.batteries.slice(0, 12).map((b) => (
                <span key={b.node} className={batteryClass(b.battery)} title={`последно: ${fmtTime(b.ts)}`}>
                  {nameOf(b.node).main}: {Math.round(b.battery)}%
                </span>
              ))}
            </div>
          )}
          <p className="muted small">червено &lt; 20% · жълто &lt; 50%</p>
        </Panel>
      </div>

      <div className="dash-row">
        <Panel title="Най-активни канали" subtitle="по семейства теми (24 ч)" className="dash-row__wide">
          {!data || !data.families.length ? (
            <div className="empty">Няма трафик в последните 24 часа.</div>
          ) : (
            data.families.slice(0, 10).map((f) => (
              <div key={f.family} style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '3px 0' }}>
                <span className="mono small" style={{ width: 320, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={f.family}>{familyLabel(f.family)}</span>
                <div className="mg-bar-track" style={{ overflow: 'hidden' }}>
                  <div className="mg-bar-fill" style={{ width: `${(f.count / maxFam) * 100}%` }} />
                </div>
                <span className="mono small" style={{ width: 70, textAlign: 'right' }}>{f.count.toLocaleString('bg-BG')}</span>
              </div>
            ))
          )}
        </Panel>
      </div>

      <div className="dash-row">
        <Panel title="Активност на правилата" subtitle="съвпадения и препращания (кумулативно)" className="dash-row__wide" padded={false}>
          {!data || !data.rules.length ? (
            <div className="empty">Няма правила — създай от Routing Rules.</div>
          ) : (
            <div className="table-scroll">
              <table>
                <thead><tr><th>Правило</th><th>Статус</th><th>Съвпадения</th><th>Препратени</th><th>Грешки</th><th>Последно</th></tr></thead>
                <tbody>
                  {data.rules.map((r) => (
                    <tr key={r.name}>
                      <td>{r.name}</td>
                      <td><span className={r.enabled ? 'tag ok' : 'tag bad'}>{r.enabled ? 'включено' : 'изключено'}</span></td>
                      <td className="mono">{r.matched}</td>
                      <td className="mono">{r.forwarded}</td>
                      <td className="mono">{r.errors || '·'}</td>
                      <td className="small muted">{r.last_fired_at ? fmtTime(r.last_fired_at) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </>
  )
}

/* ============================================================================
 * Самата страница: заглавие + mg-tabs (дълбоки връзки през onPage) + табове.
 * ========================================================================== */
export default function Monitor({ tab = 'overview', onPage }: {
  tab?: MonitorTab
  onPage?: (page: string) => void
}) {
  const switchTab = (t: (typeof TABS)[number]) => {
    // ?p= дълбока връзка до таба (QA Т27) — същият механизъм като шел-а
    if (onPage) {
      onPage(t.page)
      syncPageUrl(t.page)
    } else {
      location.href = `/?p=${t.page}`
    }
  }
  return (
    <div>
      <div className="kicker">МОНИТОРИНГ</div>
      <h1 className="h-page">Мониторинг</h1>
      <div className="mg-tabs" style={{ marginBottom: 14 }} role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id}
                  className={tab === t.id ? 'active' : ''}
                  onClick={() => switchTab(t)}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'overview' && <OverviewTab />}
      {tab === 'time' && <TimeTab />}
      {tab === 'utility' && <UtilityTab />}
    </div>
  )
}
