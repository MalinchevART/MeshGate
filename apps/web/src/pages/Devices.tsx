import { memo, useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { api, fmtTime } from '../api'
import type { Me } from '../App'
import { Table, type Column } from '../components/Table'
import { useNodeNames } from '../names'

type Device = {
  id: string
  protocol: string
  external_id: string
  name: string
  long_name?: string | null
  short_name?: string | null
  status: string
  muted: boolean
  blocked: boolean
  last_seen_at: string
  events_count: number
}

type PulseBucket = { t: string; plain: number; encrypted: number; other: number; snr?: number | null }
type Pulse = {
  node: string
  hours: number
  daily?: boolean
  buckets: PulseBucket[]
  last: string | null
  /** за възел без msh кофи — колко е мълчал по devices.last_seen_at */
  fallbackLast?: string | null
}

const FILTERS: { key: string; label: string }[] = [
  { key: '', label: 'всички' },
  { key: 'active', label: 'активни' },
  { key: 'muted', label: 'заглушени' },
  { key: 'blocked', label: 'блокирани' },
]

/** Пулс-лента (docs/15 Вълна 1): 24 клетки по час; мълчанието е ЯВНО.
 *  Зелено = чуван чисто; лилаво-шарка = само криптирано; тюркоаз = само
 *  служебни пакети; сива празна = мълчание. Интензитет = log(брой).
 *  Клик на лентата → Packet Explorer филтриран по възела (drill-down).
 *  memo: пропсът е стабилна референция между 60s refresh-и — без него
 *  всеки 5s devices refresh пререндерва 140×24 клетки + tooltip низове. */
const PulseStrip = memo(function PulseStrip({ p }: { p: Pulse }) {
  const hours = Math.min(p.hours ?? 24, 168) // реален clamp срещу бъдещ параметри
  // дневен режим: hours=168 → 7 ДЕЛНИ кофи, не 168 (иначе лентата е 1.3k px)
  const units = p.daily ? Math.ceil(hours / 24) : hours
  const msPer = p.daily ? 86_400_000 : 3_600_000
  const bySlot = new Map<string, PulseBucket>()
  for (const b of p.buckets) {
    bySlot.set(p.daily ? b.t.slice(0, 10) : b.t.slice(0, 13), b)
  }
  const cells: (PulseBucket | null)[] = []
  const now = new Date()
  if (p.daily) {
    now.setUTCHours(0, 0, 0, 0)
  } else {
    now.setUTCMinutes(0, 0, 0) // трънк в UTC — ключовете са UTC (toISOString)
  }
  for (let i = units - 1; i >= 0; i--) {
    const d = new Date(now.getTime() - i * msPer)
    cells.push(bySlot.get(p.daily ? d.toISOString().slice(0, 10)
                                  : d.toISOString().slice(0, 13)) ?? null)
  }
  // мълчание: от последната кофа, а за напълно тих възел — от devices
  const lastActive = p.buckets.length
    ? new Date(p.buckets[p.buckets.length - 1].t).getTime()
    : (p.fallbackLast ? new Date(p.fallbackLast).getTime() : 0)
  const silentH = lastActive ? Math.floor((now.getTime() - lastActive) / 3600_000) : null
  const drill = () => {
    sessionStorage.setItem('mg_pe_topic', p.node)
    location.href = '/?p=packets'
  }
  // цветовете са КАТЕГОРИИ, не статуси (зелено/оранжево/червено остават
  // статуси в SNR/батерии): лилаво-шарка = криптирано, тюркоаз = служебни
  return (
    <span style={{ whiteSpace: 'nowrap' }}>
      <span
        style={{ display: 'inline-flex', gap: 1, verticalAlign: 'middle', cursor: 'pointer', padding: '5px 0' }}
        onClick={drill}
        title={`клик: пакетите на ${p.node} в Packet Explorer\n` + cells.map((c, i) => {
          const d = new Date(now.getTime() - (cells.length - 1 - i) * msPer)
          const lbl = p.daily
            ? d.toLocaleDateString('bg-BG', { timeZone: 'UTC' }) // кофата е UTC-полунощ
            : `${String(d.getHours()).padStart(2, '0')}:00`
          if (!c) return `${lbl} мълчи`
          const parts = [
            c.plain && `${c.plain} чисти`,
            c.encrypted && `${c.encrypted} криптирани`,
            c.other && `${c.other} служебни`,
          ].filter(Boolean)
          const snr = c.snr != null ? ` · SNR ${c.snr} dB` : ''
          return `${lbl} ${parts.join(', ') || '0 пакета'}${snr}`
        }).join('\n')}
      >
        {cells.map((c, i) => {
          // интензитетът е ЧИСЛО (процент); цветът+шарката живеят в 4.11 DATA-VIZ
          const total = c ? c.plain + c.encrypted + c.other : 0
          const pct = Math.round((0.45 + Math.min(0.55, Math.log10(total + 1) * 0.4)) * 100)
          let cls: string
          if (!c) cls = 'mg-pulse-cell mg-pulse-cell--silent'
          else if (c.plain > 0) cls = 'mg-pulse-cell mg-pulse-cell--clean'
          else if (c.encrypted > 0) cls = 'mg-pulse-cell mg-pulse-cell--encrypted'
          else cls = 'mg-pulse-cell mg-pulse-cell--service'
          return <span key={i} className={cls} style={c ? ({ '--a': pct } as CSSProperties) : undefined} />
        })}
      </span>
      {silentH != null && silentH >= 2 && (
        <span className="muted small"
          title={`мълчи от ${silentH} ч (без msh пакети, вкл. криптирани); „Статус"/„Последно" отчитат всеки трафик; мълчанието се мери по цели кофи (${p.daily ? '±1 ден' : '±1 ч'})`}
          style={{ marginLeft: 6 }}>
          мълчи {silentH} ч
        </span>
      )}
    </span>
  )
})

export default function Devices({ me }: { me: Me }) {
  const [devices, setDevices] = useState<Device[] | null>(null)
  const [pulse, setPulse] = useState<Map<string, Pulse> | null>(null)
  const [span, setSpan] = useState<'24h' | '7d'>('24h')
  const [filter, setFilter] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const isAdmin = me.role === 'admin'
  const nameOf = useNodeNames()

  useEffect(() => {
    const load = () =>
      api(filter ? `/v1/devices?filter=${filter}` : '/v1/devices')
        .then(setDevices)
        // transient грешка не бива да трие вече показаните данни
        .catch(() => setDevices((prev) => prev ?? []))
    const loadPulse = () =>
      api(span === '7d' ? '/v1/devices/pulse?hours=168&daily=1' : '/v1/devices/pulse?hours=24')
        .then((r: any) => setPulse(new Map(
          (r.nodes ?? []).map((p: any) => [p.node.toLowerCase(),
            { ...p, hours: r.hours, daily: r.daily } as Pulse]))))
        .catch(() => {}) // пази стария map при transient грешка
    load(); loadPulse()
    const t = setInterval(load, 5000)
    const tp = setInterval(loadPulse, 60000)
    return () => { clearInterval(t); clearInterval(tp) }
  }, [filter, span])

  async function act(d: Device, action: string, confirmText?: string) {
    if (confirmText && !confirm(confirmText)) return
    try {
      await api(`/v1/devices/${d.id}/${action}`, { method: 'POST' })
      setDevices(await api(filter ? `/v1/devices?filter=${filter}` : '/v1/devices'))
    } catch (e: any) {
      setErr(e.message)
      setTimeout(() => setErr(null), 4000)
    }
  }

  async function remove(d: Device, withPackets: boolean) {
    const what = withPackets
      ? `Изтрий ${nameOf(d.external_id).main} НАПЪЛНО — възел, събития И всички негови пакети?`
      : `Изтрий ${nameOf(d.external_id).main} (възел + събития, пакетите остават)?`
    if (!confirm(what)) return
    try {
      await api(`/v1/devices/${d.id}${withPackets ? '?packets=1' : ''}`, {
        method: 'DELETE',
      })
      setDevices(await api(filter ? `/v1/devices?filter=${filter}` : '/v1/devices'))
    } catch (e: any) {
      setErr(e.message)
      setTimeout(() => setErr(null), 4000)
    }
  }

  async function emulator(action: 'pause' | 'resume') {
    try {
      await api(`/v1/system/emulator/${action}`, { method: 'POST' })
    } catch (e: any) {
      setErr(e.message)
      setTimeout(() => setErr(null), 4000)
    }
  }

  // ---- Т13: колоните на новата таблица (Table от Т12) -------------------
  // пулс лентите остават (24h/7d toggle е в toolbar-а); действията само за
  // admin; приоритет-индикацията идва с Т24 на това място.
  const pulseOf = (d: Device): Pulse | null => {
    const p = pulse?.get(d.external_id.toLowerCase())
    return p ?? (d.protocol === 'meshtastic'
      ? {
          node: d.external_id.toLowerCase(),
          hours: span === '7d' ? 168 : 24,
          daily: span === '7d',
          buckets: [],
          last: null,
          fallbackLast: d.last_seen_at,
        }
      : null)
  }

  const columns: Column<Device>[] = [
    {
      id: 'external_id', label: 'Възел / източник',
      // ИМЕТО е главно (кратко → дълго), ID-то е второстепенно — сиво долу
      value: (d) => nameOf(d.external_id).main,
      render: (d) => {
        const n = nameOf(d.external_id)
        const isNode = d.protocol === 'meshtastic'
        return isNode && n.sub ? (
          <span title={n.tip}>
            <span style={{ fontWeight: 600 }}>{n.main}</span>
            <span className="small" style={{ display: 'block', color: 'var(--text-muted)' }}>{n.sub}</span>
          </span>
        ) : (
          <span className="mono">{d.external_id}</span>
        )
      },
    },
    {
      id: 'protocol', label: 'Протокол', defaultHidden: true,
      value: (d) => d.protocol,
    },
    {
      id: 'status', label: 'Статус',
      value: (d) => (d.blocked ? '0-блокиран' : d.muted ? '1-заглушен' : `2-${d.status}`),
      render: (d) => d.blocked ? (
        <span className="tag bad" title="блокиран за защита — пакетите му не се обработват">⛔ блокиран</span>
      ) : d.muted ? (
        <span className="tag" title="заглушен — пакетите му не се записват">🔇 заглушен</span>
      ) : (
        <span className={d.status === 'online' ? 'tag ok' : 'tag'}>{d.status}</span>
      ),
    },
    {
      id: 'pulse', label: 'Пулс',
      value: () => '',
      render: (d) => {
        const strip = pulseOf(d)
        return strip
          ? <PulseStrip p={strip} />
          : <span className="muted small" title="не е Meshtastic възел">—</span>
      },
    },
    {
      id: 'last_seen_at', label: 'Последно',
      value: (d) => d.last_seen_at,
      render: (d) => fmtTime(d.last_seen_at),
    },
    {
      id: 'events_count', label: 'Събития', align: 'right',
      value: (d) => d.events_count,
      render: (d) => d.events_count.toLocaleString('bg-BG'),
    },
    ...(isAdmin ? [{
      id: 'actions', label: 'Действия',
      value: () => '',
      render: (d: Device) => (
        <span style={{ whiteSpace: 'nowrap' as const }}>
          {d.blocked ? (
            <button className="ghost" title="отблокирай"
              onClick={() => act(d, 'unblock')}>🔓</button>
          ) : (
            <>
              {!d.muted && (
                <button className="ghost" title="заглуши — не записвай пакетите му (шум от тест)"
                  onClick={() => act(d, 'mute',
                    `Заглуши ${nameOf(d.external_id).main}? Пакетите му няма да се записват/рутират.`)}>🔇</button>
              )}
              {d.muted && (
                <button className="ghost" title="върни"
                  onClick={() => act(d, 'unmute')}>🔈</button>
              )}
              <button className="ghost" title="блокирай за защита"
                onClick={() => act(d, 'block',
                  `Блокирай ${nameOf(d.external_id).main} за защита? Пакетите му няма да се обработват.`)}>⛔</button>
            </>
          )}
          <button className="ghost" title="изтрий (възел + събития)"
            onClick={() => remove(d, false)}>🗑</button>
          <button className="ghost" title="изтрий НАПЪЛНО (вкл. пакетите)"
            onClick={() => remove(d, true)}>💀</button>
        </span>
      ),
    }] : []),
  ]

  if (!devices) return <div className="empty">Зарежда се…</div>

  return (
    <div className="panel">
      <div className="toolbar">
        <h2>Устройства и източници</h2>
        {FILTERS.map((f) => (
          <button
            key={f.key}
            className={filter === f.key ? 'nav-btn active' : 'nav-btn ghost'}
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
        {/* Т13 П3: 24h/7d превключвателят на пулс-лентите (span вече
            храни заявката — UI бутоните липсваха) */}
        <span className="muted small" style={{ marginLeft: 6 }}>пулс:</span>
        {([['24h', '24 часа'], ['7d', '7 дни']] as const).map(([k, label]) => (
          <button
            key={k}
            className={span === k ? 'nav-btn active' : 'nav-btn ghost'}
            title={`пулс-лентите показват ${label}`}
            onClick={() => setSpan(k)}
          >
            {k}
          </button>
        ))}
        {isAdmin && (
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
            <span className="muted small">демо възли:</span>
            <button
              className="ghost" title="спри публикуването на тестовите възли"
              onClick={() => emulator('pause')}
            >⏸ пауза</button>
            <button
              className="ghost" title="върни публикуването на тестовите възли"
              onClick={() => emulator('resume')}
            >▶ продължи</button>
          </span>
        )}
      </div>
      {err && <div className="error">{err}</div>}
      {devices.length === 0 ? (
        <div className="empty">
          Няма устройства{filter ? ' за този филтър' : ''}. Публикувай MQTT съобщение
          и то ще се появи тук.
        </div>
      ) : (
        <Table
          columns={columns}
          rows={devices}
          getKey={(d) => d.id}
          initialSort="external_id"
          filterable
          placeholder="търси възел / тема / протокол…"
          empty="никой не отговаря на филтъра"
        />
      )}
      <p className="muted small" style={{ marginTop: 8 }}>
        Пулс: <span className="mg-pulse-swatch mg-pulse-cell--clean" style={{ '--a': 100 } as CSSProperties} />{' '}
        чуван чисто · <span className="mg-pulse-swatch mg-pulse-cell--encrypted" style={{ '--a': 100 } as CSSProperties} />{' '}
        само криптирано · <span className="mg-pulse-swatch mg-pulse-cell--service" style={{ '--a': 60 } as CSSProperties} />{' '}
        служебни · <span className="mg-pulse-swatch mg-pulse-cell--silent" />{' '}
        мълчание (няма msh пакети; среден SNR — в tooltip на клетката). 🔇 заглушен / ⛔ блокиран → пакетите не се записват; 🗑 изтрий, 💀 с пакетите.
      </p>
    </div>
  )
}
