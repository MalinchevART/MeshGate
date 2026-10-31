import { useEffect, useState } from 'react'
import { api } from '../../api'
import { Panel } from '../../components/ui'

/* ============================================================================
 * MeshGate · Таб „Полезност" (Т30): Фунията.
 * Ефир → Декодируеми → Хванати → Доставени → Deadletter — кофи + проценти,
 * всяко ниво кликва до своя trace. Нулите са видими (no-data е състояние).
 * ========================================================================== */

type Funnel = {
  hours: number
  air: number
  decoded: number
  captured: number
  delivered: number
  deadletter: number
}

const LEVELS: { key: keyof Omit<Funnel, 'hours'>; label: string; hint: string; drill: () => void }[] = [
  { key: 'air', label: 'Ефир', hint: 'всичко, стигнало платформата', drill: () => { sessionStorage.removeItem('mg_pe_topic'); location.href = '/?p=packets' } },
  { key: 'decoded', label: 'Декодируеми', hint: 'разпознати от декодерите', drill: () => { sessionStorage.setItem('mg_pe_topic', 'msh/'); location.href = '/?p=packets' } },
  { key: 'captured', label: 'Хванати', hint: 'match_forward решения на правилата', drill: () => { location.href = '/?p=routing' } },
  { key: 'delivered', label: 'Доставени', hint: 'публикувани от правилата (вкл. мостове)', drill: () => { location.href = '/?p=routing' } },
  { key: 'deadletter', label: 'Deadletter', hint: 'мъртви букви — неуспешни доставки', drill: () => { sessionStorage.setItem('mg_pe_topic', 'deadletter/'); location.href = '/?p=packets' } },
]

const PERIODS = [
  { id: 24, label: '24 ч' },
  { id: 168, label: '7 д' },
  { id: 720, label: '30 д' },
] as const

export default function UtilityTab() {
  const [period, setPeriod] = useState<(typeof PERIODS)[number]['id']>(24)
  const [f, setF] = useState<Funnel | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let gone = false
    api(`/v1/stats/funnel?hours=${period}`)
      .then((r: any) => { if (!gone) { setF(r); setErr(null) } })
      .catch((e: any) => { if (!gone) setErr(e.message) })
    return () => { gone = true }
  }, [period])

  const max = Math.max(1, f?.air ?? 1)
  let prev = 0

  return (
    <Panel
      title="Фунията"
      subtitle="колко от ефира стига до полезен край — всяко ниво кликва до своя trace"
      className="dash-row__wide"
      filters={
        <select value={period} onChange={(e) => setPeriod(Number(e.target.value) as 24 | 168 | 720)}>
          {PERIODS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>
      }
    >
      {err && <div className="empty">грешка: {err}</div>}
      {!f && !err ? (
        <div className="empty">…</div>
      ) : (
        <div className="mg-fun">
          {LEVELS.map(({ key, label, hint, drill }) => {
            const n = f?.[key] ?? 0
            const shareOfAir = Math.round((n / max) * 100)
            const shareOfPrev = prev > 0 ? Math.round((n / prev) * 100) : null
            prev = n
            return (
              <button key={key} className="mg-fun__row" title={hint} onClick={drill}>
                <span className="mg-fun__label">{label}</span>
                <span className="mg-fun__track">
                  <span className={`mg-fun__bar${key === 'deadletter' && n > 0 ? ' mg-fun__bar--bad' : ''}`}
                        style={{ width: `${Math.max(shareOfAir, n > 0 ? 2 : 0)}%` }} />
                </span>
                <span className="mg-fun__num mono">{n.toLocaleString('bg-BG')}</span>
                <span className="mg-fun__pct muted small">
                  {shareOfAir}%{shareOfPrev != null ? ` · ${shareOfPrev}% от предх.` : ''}
                </span>
              </button>
            )
          })}
        </div>
      )}
      <p className="muted small">
        Ефир = всичко в базата за периода; Декодируеми = decode_status „decoded";
        Хванати = правила с решение match_forward; Доставени = публикации с
        routing произход; Deadletter = неуспешни доставки по политиката.
        Нулите са нормално състояние — фунията не скрива празни нива.
      </p>
    </Panel>
  )
}
