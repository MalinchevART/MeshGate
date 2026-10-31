import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api'
import { useNodeNames } from '../../names'
import { Panel } from '../../components/ui'

/* ============================================================================
 * MeshGate · Таб „Време" (Т28 + Т29):
 * - Водопад: матрица връзки×време, цвят = SNR; криптираните кофи — ЩРИХОВКА
 *   („известна неизвестност", не тишина).
 * - Ефир-часовник: 7×24 решетка с медианен SNR от собствената история +
 *   текстов извод „изпрати сега / по-добре в HH:00" (измерено, не предсказано).
 * ========================================================================== */

type WfCell = { t: string; n: number; snr: number | null; encrypted_only?: boolean }
type WfEdge = { from: string; to: string; packets: number; cells: WfCell[] }
type Waterfall = { hours: number; grain: 'hour' | 'day'; edges: WfEdge[] }
type AirClock = {
  hours: number
  cells: { dow: number; h: number; med_snr: number | null; n: number }[]
  days_covered: number
  verdict: { action: string; text: string; note?: string }
}

const PERIODS = [
  { id: 24, label: '24 ч' },
  { id: 168, label: '7 д' },
] as const

const DOW_BG = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд']

/** SNR → тон (праговете от settings — същият endpoint като Картата, Т10). */
function useSnrTone() {
  const [thr, setThr] = useState({ good: -8, fair: -15 })
  useEffect(() => {
    api('/v1/devices/map/thresholds')
      .then((r: any) => setThr({ good: r.effective.good_db, fair: r.effective.fair_db }))
      .catch(() => {})
  }, [])
  return (snr: number | null) =>
    snr == null ? 'none' : snr >= thr.good ? 'good' : snr >= thr.fair ? 'mid' : 'bad'
}

/** Пълната ос от кофи (часови или дневни) — и празните (мълчанието е ЯВНО). */
function bucketAxis(hours: number, grain: 'hour' | 'day'): string[] {
  const out: string[] = []
  const now = new Date()
  if (grain === 'hour') {
    now.setUTCMinutes(0, 0, 0)
    for (let i = hours - 1; i >= 0; i--) {
      out.push(new Date(now.getTime() - i * 3600_000).toISOString().slice(0, 13))
    }
  } else {
    now.setUTCHours(0, 0, 0, 0)
    const days = Math.ceil(hours / 24)
    for (let i = days - 1; i >= 0; i--) {
      out.push(new Date(now.getTime() - i * 86_400_000).toISOString().slice(0, 10))
    }
  }
  return out
}

export default function TimeTab() {
  const nameOf = useNodeNames()
  const tone = useSnrTone()
  const [period, setPeriod] = useState<(typeof PERIODS)[number]['id']>(168)
  const [wf, setWf] = useState<Waterfall | null>(null)
  const [clock, setClock] = useState<AirClock | null>(null)

  useEffect(() => {
    let gone = false
    api(`/v1/devices/waterfall?hours=${period}`)
      .then((r: any) => { if (!gone) setWf(r) })
      .catch(() => { if (!gone) setWf({ hours: period, grain: period <= 24 ? 'hour' : 'day', edges: [] }) })
    return () => { gone = true }
  }, [period])

  useEffect(() => {
    api('/v1/devices/air-clock?hours=168')
      .then((r: any) => setClock(r))
      .catch(() => {})
  }, [])

  const axis = useMemo(
    () => bucketAxis(wf?.hours ?? 168, wf?.grain ?? 'day'), [wf?.hours, wf?.grain])
  const cellsBy = useMemo(() => {
    const m = new Map<string, WfCell>()
    for (const e of wf?.edges ?? []) for (const c of e.cells) m.set(`${e.from}>${e.to}@${c.t}`, c)
    return m
  }, [wf])

  const drill = (node: string) => {
    sessionStorage.setItem('mg_pe_topic', node)
    location.href = '/?p=packets'
  }

  return (
    <>
      <Panel
        title="Водопад"
        subtitle="връзки × време — цветът е SNR, плътта е трафик; щрихованото = криптирано (известна неизвестност)"
        className="dash-row__wide"
        filters={
          <select value={period} onChange={(e) => setPeriod(Number(e.target.value) as 24 | 168)}>
            {PERIODS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        }
      >
        {!wf ? (
          <div className="empty">…</div>
        ) : wf.edges.length === 0 ? (
          <div className="empty">
            Няма NeighborInfo връзки за периода — водопадът се учи от пакетите
            „кой кого чу“ (виж Картата → Схема).
          </div>
        ) : (
          <>
            <div className="mg-wf" role="img" aria-label="Матрица връзки по време; цветът е SNR">
              <div className="mg-wf__row mg-wf__row--head">
                <span className="mg-wf__label" />
                {axis.map((t) => (
                  <span key={t} className="mg-wf__colhead"
                        title={new Date(t.length === 10 ? `${t}T00:00:00Z` : `${t}:00:00Z`).toLocaleString('bg-BG')}>
                    {grainLabel(t, wf.grain)}
                  </span>
                ))}
              </div>
              {wf.edges.map((e) => (
                <div key={`${e.from}>${e.to}`} className="mg-wf__row">
                  <span className="mg-wf__label" title={`${e.from} → ${e.to}`}>
                    {nameOf(e.from).main} <span className="muted">→</span> {nameOf(e.to).main}
                  </span>
                  {axis.map((t) => {
                    const c = cellsBy.get(`${e.from}>${e.to}@${t}`)
                    const cls = c
                      ? (c.encrypted_only ? 'mg-wf__cell--enc'
                         : `mg-wf__cell mg-snr--${tone(c.snr)}${c.snr == null ? ' mg-wf__cell--nosnr' : ''}`)
                      : 'mg-wf__cell mg-wf__cell--empty'
                    const tip = c
                      ? `${new Date(c.t.length === 10 ? `${c.t}T00:00:00Z` : `${c.t}:00:00Z`).toLocaleString('bg-BG')} · ${c.n} пак.` +
                        (c.snr != null ? ` · SNR ${c.snr} dB` : '') +
                        (c.encrypted_only ? ' · само криптирано' : '')
                      : `${new Date(t.length === 10 ? `${t}T00:00:00Z` : `${t}:00:00Z`).toLocaleString('bg-BG')} · мълчание`
                    return (
                      <span key={t} className={cls} title={tip} style={{ '--a': c ? Math.min(1, 0.35 + Math.log2(1 + c.n) / 6) : 0.15 } as React.CSSProperties}
                            onClick={() => drill(e.from)} />
                    )
                  })}
                </div>
              ))}
            </div>
            <div className="muted small" style={{ marginTop: 6 }}>
              легенда: <span className={`mg-snr--good`}>▬ силна</span> ·{' '}
              <span className={`mg-snr--mid`}>▬ средна</span> ·{' '}
              <span className={`mg-snr--bad`}>▬ слаба</span> ·{' '}
              <span className="mg-wf__cell--enc mg-wf__demo">▨ криптирано</span> ·{' '}
              празно = мълчание · клик върху клетка → Explorer по подателя
            </div>
          </>
        )}
      </Panel>

      <Panel
        title="Ефир-часовник"
        subtitle="медианен SNR по ден и час от собствената история (7 седмични дни)"
        className="dash-row__wide"
      >
        {!clock ? (
          <div className="empty">…</div>
        ) : (
          <>
            <div className={`mg-verdict${clock.verdict.action === 'send_now' ? ' mg-verdict--go' : ''}`}>
              {clock.verdict.text}
              {clock.verdict.note && (
                <div className="muted small">{clock.verdict.note}</div>
              )}
            </div>
            {clock.cells.length === 0 ? (
              <div className="empty">Няма измервания с SNR за изграждане на часовника.</div>
            ) : (
              <div className="mg-afx" role="img" aria-label="Седмица по часове: медианен SNR">
                {DOW_BG.map((lbl, i) => {
                  const dow = i + 1
                  return (
                    <div key={dow} className="mg-afx__row">
                      <span className="mg-afx__dow">{lbl}</span>
                      {Array.from({ length: 24 }, (_, h) => {
                        const c = clock.cells.find((x) => x.dow === dow && x.h === h)
                        return (
                          <span key={h}
                                className={`mg-afx__cell${c ? ` mg-snr--${tone(c.med_snr)}` : ' mg-wf__cell--empty'}`}
                                style={{ '--a': c ? Math.min(1, 0.3 + (c.n ?? 0) / 200) : 0.12 } as React.CSSProperties}
                                title={c
                                  ? `${lbl} ${String(h).padStart(2, '0')}:00 · медианен SNR ${c.med_snr?.toFixed(1)} dB · ${c.n} измервания`
                                  : `${lbl} ${String(h).padStart(2, '0')}:00 · без данни`}>
                            {h % 3 === 0 && <span className="mg-afx__hh">{h}</span>}
                          </span>
                        )
                      })}
                    </div>
                  )
                })}
              </div>
            )}
            <div className="muted small" style={{ marginTop: 6 }}>
              легенда: <span className="mg-snr--good">▬ силна</span> ·{' '}
              <span className="mg-snr--mid">▬ средна</span> ·{' '}
              <span className="mg-snr--bad">▬ слаба</span> — медиана на часа;
              изводът е ИЗМЕРЕН от историята, не прогноза
            </div>
          </>
        )}
      </Panel>
    </>
  )
}

function grainLabel(t: string, grain: 'hour' | 'day'): string {
  if (grain === 'day') {
    return new Date(`${t}T00:00:00Z`).toLocaleDateString('bg-BG', { weekday: 'short' })
  }
  return t.slice(11, 13) || t
}
