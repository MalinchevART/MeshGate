import { useEffect, useState } from 'react'
import { api } from '../api'

type Phase = {
  id: string; title: string; status: 'done' | 'active' | 'next' | 'later'; when: string
  items: { title: string; status: string }[]
}
type Plan = { title: string; updated: string; phases: Phase[] }
type AutoCheck = { id: string; title: string; status: string; detail: string }
type ManualCheck = { id: string; title: string; steps: string; expected: string }

const STATUS_BG: Record<string, string> = {
  done: 'tag ok', active: 'tag', next: 'tag', later: 'tag',
}
const STATUS_LABEL: Record<string, string> = {
  done: '✅ готово', active: '▶ СЕГА', next: '⏭ следващо', later: '• по-късно',
}
const CHECK_BG: Record<string, string> = { ok: 'tag ok', warn: 'tag', fail: 'tag bad' }

/** Отметките на ръчния чеклист се пазят локално в браузъра (твой прогрес). */
function loadMarks(): Record<string, boolean> {
  try { return JSON.parse(localStorage.getItem('mg_manual_checks') || '{}') } catch { return {} }
}
function saveMarks(m: Record<string, boolean>) {
  localStorage.setItem('mg_manual_checks', JSON.stringify(m))
}

export default function PlanPage() {
  const [plan, setPlan] = useState<Plan | null>(null)
  const [auto, setAuto] = useState<AutoCheck[] | null>(null)
  const [manual, setManual] = useState<ManualCheck[]>([])
  const [marks, setMarks] = useState<Record<string, boolean>>(loadMarks)
  const [err, setErr] = useState<string | null>(null)
  const [openPhase, setOpenPhase] = useState<string | null>(null)

  async function runSelftest() {
    setAuto(null)
    try {
      const d = await api('/v1/selftest')
      setAuto(d.auto); setManual(d.manual)
    } catch (e: any) { setErr(e.message) }
  }

  useEffect(() => {
    api('/v1/plan').then(setPlan).catch((e: any) => setErr(e.message))
    runSelftest()
  }, [])

  function toggleMark(id: string) {
    const m = { ...marks, [id]: !marks[id] }
    setMarks(m); saveMarks(m)
  }

  const doneCount = manual.filter((m) => marks[m.id]).length

  return (
    <>
      <div className="toolbar">
        <div>
          <div className="kicker">ПЛАН</div>
          <h1 className="h-page" style={{ margin: 0 }}>План & Тестове</h1>
        </div>
        <button className="ghost-btn" onClick={runSelftest}>↻ пусни проверките отново</button>
        <span className="muted small">кое кога е готово + какво можеш да тестваш сам</span>
      </div>
      {err && <div className="error">{err}</div>}

      {/* --- автоматични проверки --- */}
      <div className="panel" style={{ marginBottom: 16 }}>
        <h2>Автоматични проверки на системата</h2>
        {!auto ? <div className="empty">проверявам…</div> : (
          <table>
            <thead><tr><th></th><th>Проверка</th><th>Резултат</th></tr></thead>
            <tbody>
              {auto.map((c) => (
                <tr key={c.id}>
                  <td><span className={CHECK_BG[c.status] || 'tag'}>{c.status === 'ok' ? '✓' : c.status === 'warn' ? '!' : '✗'}</span></td>
                  <td>{c.title}</td>
                  <td className="small muted">{c.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* --- ръчен чеклист за собственика --- */}
      <div className="panel" style={{ marginBottom: 16 }}>
        <h2>Ръчен чеклист — твоите тестове ({doneCount}/{manual.length || '…'} направени)</h2>
        {!manual.length ? <div className="empty">зарежда…</div> : manual.map((m) => (
          <div key={m.id} style={{ display: 'flex', gap: 12, padding: '10px 0', borderBottom: '1px solid var(--line)' }}>
            <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer', flex: 1 }}>
              <input type="checkbox" style={{ marginTop: 3, width: 18, height: 18 }}
                checked={!!marks[m.id]} onChange={() => toggleMark(m.id)} />
              <div>
                <strong style={{ textDecoration: marks[m.id] ? 'line-through' : 'none' }}>{m.title}</strong>
                <div className="small">🧪 {m.steps}</div>
                <div className="small muted">✔ очаквано: {m.expected}</div>
              </div>
            </label>
          </div>
        ))}
        {manual.length > 0 && (
          <button className="ghost-btn small" style={{ marginTop: 8 }}
            onClick={() => { if (confirm('Изчистване на всички отметки?')) { setMarks({}); saveMarks({}) } }}>
            изчисти отметките
          </button>
        )}
      </div>

      {/* --- план: дърво на функционалностите --- */}
      <div className="panel">
        <h2>План на функционалностите — кое кога</h2>
        {!plan ? <div className="empty">зарежда…</div> : (
          <>
            <p className="muted small">обновен: {plan.updated} · детайлният технически план: docs/09-routing-rules-plan.md и docs/07-roadmap.md</p>
            {plan.phases.map((p) => {
              const open = openPhase === p.id
              const doneItems = p.items.filter((i) => i.status === 'done').length
              return (
                <div key={p.id} style={{ borderBottom: '1px solid var(--line)', padding: '8px 0' }}>
                  <div style={{ display: 'flex', gap: 10, alignItems: 'center', cursor: 'pointer' }}
                    onClick={() => setOpenPhase(open ? null : p.id)}>
                    <span className={STATUS_BG[p.status]}>{STATUS_LABEL[p.status]}</span>
                    <strong>{p.title}</strong>
                    <span className="muted small">{p.when}</span>
                    <span style={{ flex: 1 }} />
                    <span className="muted small">{doneItems}/{p.items.length} елемента {open ? '▲' : '▼'}</span>
                  </div>
                  {open && (
                    <ul style={{ margin: '6px 0 4px 26px' }}>
                      {p.items.map((it, i) => (
                        <li key={i} className="small" style={{ padding: '2px 0', listStyle: 'none' }}>
                          <span className={STATUS_BG[it.status]} style={{ marginRight: 8 }}>
                            {it.status === 'done' ? '✓' : it.status === 'next' ? '⏭' : '•'}
                          </span>
                          {it.title}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )
            })}
          </>
        )}
      </div>
    </>
  )
}
