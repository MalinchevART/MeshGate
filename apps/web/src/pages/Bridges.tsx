import { useEffect, useState } from 'react'
import { api, fmtTime } from '../api'
import type { Me } from '../App'

type Rule = { kind: string; topic_pattern: string; priority: number; reason: string | null }
type Bridge = {
  id: string
  name: string
  enabled: boolean
  direction: string
  remote_host: string
  remote_port: number
  health: string
  last_error: string | null
  allow_internal: boolean
  rules: Rule[]
  counters?: Record<string, number>
}
type BridgeEvent = { ts: string; decision: string; topic: string; reason: string }

const emptyForm = {
  name: '', direction: 'outbound', remote_host: '', remote_port: 1883,
  remote_username: '', remote_password: '', allow_internal: false,
  rules: [
    { kind: 'deny', topic_pattern: 'mesh/*/priv', priority: 10, reason: 'лични съобщения' },
    { kind: 'allow', topic_pattern: 'mesh/+/up', priority: 100, reason: '' },
  ],
}

export default function Bridges({ me }: { me: Me }) {
  const [bridges, setBridges] = useState<Bridge[] | null>(null)
  const [events, setEvents] = useState<BridgeEvent[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [form, setForm] = useState(emptyForm)
  const [showForm, setShowForm] = useState(false)
  const [test, setTest] = useState<{ id: string; topic: string; payload: string } | null>(null)
  const [testOut, setTestOut] = useState<string | null>(null)
  const isAdmin = me.role === 'admin'

  async function load() {
    try {
      setBridges(await api('/v1/bridges'))
    } catch (e: any) {
      setError(e.message)
    }
  }
  useEffect(() => {
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    if (!selected) return setEvents([])
    const loadEv = () =>
      api(`/v1/bridges/${selected}/events?limit=30`).then(setEvents).catch(() => {})
    loadEv()
    const t = setInterval(loadEv, 3000)
    return () => clearInterval(t)
  }, [selected])

  async function toggle(b: Bridge) {
    try {
      if (b.enabled) {
        await api(`/v1/bridges/${b.id}/disable`, { method: 'POST' })
      } else if (b.direction !== 'outbound') {
        const why = b.direction === 'inbound'
          ? 'Входящ мост ВНАСЯ данни от външния брокер (с дедупликация и rate limit). Пускаш ли го?'
          : 'Двупосочен мост изнася И внася данни. Пускаш ли го?'
        if (!confirm(why)) return
        await api(`/v1/bridges/${b.id}/enable`, { method: 'POST', body: JSON.stringify({ confirm_risky: true }) })
      } else {
        await api(`/v1/bridges/${b.id}/enable`, { method: 'POST', body: '{}' })
      }
      load()
    } catch (e: any) { setError(e.message) }
  }

  async function remove(b: Bridge) {
    if (!confirm(`Изтриване на мост ${b.name}?`)) return
    await api(`/v1/bridges/${b.id}`, { method: 'DELETE' }).catch((e) => setError(e.message))
    load()
  }

  async function create(e: React.FormEvent) {
    e.preventDefault()
    setMsg(null)
    try {
      await api('/v1/bridges', { method: 'POST', body: JSON.stringify(form) })
      setMsg(`✓ мостът "${form.name}" е създаден (изключен по подразбиране — включи го изрично)`)
      setForm(emptyForm)
      setShowForm(false)
      load()
    } catch (err: any) { setMsg('✘ ' + err.message) }
  }

  async function runTest(e: React.FormEvent) {
    e.preventDefault()
    if (!test) return
    setTestOut(null)
    const res = await api(`/v1/bridges/${test.id}/test`, {
      method: 'POST',
      body: JSON.stringify({ topic: test.topic, payload: test.payload }),
    }).catch((err) => ({ action: 'error', reason: err.message }))
    setTestOut(`${res.action === 'forward' ? '✓ ЩЕ БЪДЕ препратен' : '✘ НЯМА да бъде препратен'} — ${res.reason}`)
  }

  return (
    <div>
      {error && <div className="error panel">{error}</div>}
      {msg && <div className={msg.startsWith('✓') ? 'ok-box panel' : 'error panel'}>{msg}</div>}

      <div className="panel toolbar">
        <div className="kicker">МОСТОВЕ</div>
      <h1 className="h-page">Мостове и маршрути</h1>
        {isAdmin && (
          <button className="ghost-btn" onClick={() => setShowForm(!showForm)}>
            {showForm ? 'Скрий формата' : '+ Нов мост'}
          </button>
        )}
      </div>

      {showForm && isAdmin && (
        <div className="panel">
          <h2>Създаване на мост (изключен по подразбиране)</h2>
          <form className="form-grid" onSubmit={create}>
            <input placeholder="име (латиница)" value={form.name}
                   onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <label>Посока
              <select value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value })}>
                <option value="outbound">изходящ — праща към външния</option>
                <option value="inbound">входящ — внася от външния (за публични Meshtastic брокери)</option>
                <option value="bidirectional">двупосочен — и двете (рисково)</option>
              </select>
            </label>
            {form.direction !== 'outbound' && (
              <p className="muted small" style={{ gridColumn: '1 / -1', margin: 0 }}>
                {form.direction === 'inbound'
                  ? 'Входящ: слушаме външните теми (topic_map: from_prefix) и ги публикуваме локално — системата ги разпознава и рутира автоматично; повторни копия се пропускат (дедупликация), ехо-съобщения се режат.'
                  : 'Двупосочен: изходящите правила важат за изхода; входящият поток е като при входящ мост.'}
              </p>
            )}
            <input placeholder="remote хост (публичен DNS)" className="mono" value={form.remote_host}
                   onChange={(e) => setForm({ ...form, remote_host: e.target.value })} />
            <input placeholder="потребител за външния брокер (публичният mqtt.meshtastic.org изисква)"
                   value={form.remote_username}
                   onChange={(e) => setForm({ ...form, remote_username: e.target.value })} />
            <input type="password" placeholder="парола за външния брокер" value={form.remote_password}
                   onChange={(e) => setForm({ ...form, remote_password: e.target.value })} />
            <input type="number" placeholder="порт" value={form.remote_port}
                   onChange={(e) => setForm({ ...form, remote_port: Number(e.target.value) })} />
            <label className="check">
              <input type="checkbox" checked={form.allow_internal}
                     onChange={(e) => setForm({ ...form, allow_internal: e.target.checked })} />
              позволи вътрешен адрес (само за тестови цели)
            </label>
          </form>
          <h3>Правила (първото по приоритет, което пасва, решава)</h3>
          {form.rules.map((r, i) => (
            <div className="form-grid rule-row" key={i}>
              <select value={r.kind}
                      onChange={(e) => setForm({ ...form, rules: form.rules.map((x, j) => j === i ? { ...x, kind: e.target.value } : x) })}>
                <option value="allow">allow</option>
                <option value="deny">deny</option>
              </select>
              <input className="mono" placeholder="тема/шаблон (напр. mesh/+/up)" value={r.topic_pattern}
                     onChange={(e) => setForm({ ...form, rules: form.rules.map((x, j) => j === i ? { ...x, topic_pattern: e.target.value } : x) })} />
              <input type="number" placeholder="приоритет" value={r.priority}
                     onChange={(e) => setForm({ ...form, rules: form.rules.map((x, j) => j === i ? { ...x, priority: Number(e.target.value) } : x) })} />
              <input placeholder="причина (вижда се в журнала)" value={r.reason ?? ''}
                     onChange={(e) => setForm({ ...form, rules: form.rules.map((x, j) => j === i ? { ...x, reason: e.target.value } : x) })} />
              <button type="button" className="nav-btn danger"
                      onClick={() => setForm({ ...form, rules: form.rules.filter((_, j) => j !== i) })}>✕</button>
            </div>
          ))}
          <div className="form-row">
            <button type="button" className="ghost-btn"
                    onClick={() => setForm({ ...form, rules: [...form.rules, { kind: 'allow', topic_pattern: '', priority: 100, reason: '' }] })}>
              + правило
            </button>
            <button onClick={create} disabled={!form.name || !form.remote_host}>Създай моста</button>
          </div>
        </div>
      )}

      <div className="panel">
        {!bridges ? (
          <div className="empty">Зарежда се…</div>
        ) : bridges.length === 0 ? (
          <div className="empty">
            Няма конфигурирани мостове. Изходящото препращане е изключено по подразбиране —
            създай мост с изрични allow правила.
          </div>
        ) : (
          <table>
            <thead>
              <tr><th>Име</th><th>Посока</th><th>Към</th><th>Правила</th><th>Статус</th><th>Броячи</th><th></th></tr>
            </thead>
            <tbody>
              {bridges.map((b) => (
                <tr key={b.id} className={selected === b.id ? 'selected' : ''}>
                  <td>{b.name}</td>
                  <td>{b.direction}</td>
                  <td className="mono">{b.remote_host}:{b.remote_port}</td>
                  <td>
                    {b.rules.map((r, i) => (
                      <div key={i} className={r.kind === 'deny' ? 'deny' : ''}>
                        {r.kind} {r.topic_pattern}
                      </div>
                    ))}
                  </td>
                  <td>
                    <span className={!b.enabled ? 'tag' : b.health === 'up' ? 'tag ok' : 'tag bad'}>
                      {b.enabled ? b.health : 'изключен'}
                    </span>
                    {b.last_error && <div className="muted small">{b.last_error}</div>}
                  </td>
                  <td className="small">
                    ↗{b.counters?.forwarded ?? 0} · ✕{b.counters?.rejected ?? 0} · ↻{b.counters?.loop_blocked ?? 0}
                  </td>
                  <td className="row-actions">
                    {isAdmin && <button className="nav-btn" onClick={() => toggle(b)}>{b.enabled ? 'Изключи' : 'Включи'}</button>}
                    {isAdmin && <button className="nav-btn" onClick={() => { setTest({ id: b.id, topic: 'mesh/x/up', payload: 'test' }); setTestOut(null) }}>Тест</button>}
                    <button className="nav-btn" onClick={() => setSelected(selected === b.id ? null : b.id)}>Журнал</button>
                    {isAdmin && <button className="nav-btn danger" onClick={() => remove(b)}>✕</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {test && (
        <div className="panel">
          <h2>Тест на правилата (dry-run, нищо не се препраща)</h2>
          <form className="form-grid" onSubmit={runTest}>
            <input className="mono" value={test.topic}
                   onChange={(e) => setTest({ ...test, topic: e.target.value })} placeholder="тема" />
            <input className="mono" value={test.payload}
                   onChange={(e) => setTest({ ...test, payload: e.target.value })} placeholder="payload" />
            <button>Провери</button>
            <button type="button" className="ghost-btn" onClick={() => { setTest(null); setTestOut(null) }}>Затвори</button>
          </form>
          {testOut && <div className={testOut.startsWith('✓') ? 'ok-box' : 'error'}>{testOut}</div>}
        </div>
      )}

      {selected && (
        <div className="panel">
          <h2>Журнал на решенията</h2>
          {events.length === 0 ? (
            <div className="empty">Още няма решения за този мост.</div>
          ) : (
            <table>
              <thead><tr><th>Час</th><th>Решение</th><th>Тема</th><th>Причина</th></tr></thead>
              <tbody>
                {events.map((e, i) => (
                  <tr key={i}>
                    <td>{fmtTime(e.ts)}</td>
                    <td><span className={e.decision === 'forward' ? 'tag ok' : 'tag bad'}>{e.decision}</span></td>
                    <td className="mono">{e.topic}</td>
                    <td>{e.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
