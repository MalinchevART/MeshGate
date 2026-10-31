import { useEffect, useState } from 'react'
import { api, fmtTime } from '../api'
import type { Me } from '../App'

type User = { id: string; username: string; role: string; disabled: boolean }
type AuditRow = { ts: string; username: string; action: string; entity: string; entity_id: string | null; details: any }
type Thresholds = { battery_pct: number; deadletter_24h: number; silence_hours: number }

export default function SystemPage({ me, onChanged }: { me: Me; onChanged: () => void }) {
  const [users, setUsers] = useState<User[] | null>(null)
  const [audit, setAudit] = useState<AuditRow[]>([])
  const [actionFilter, setActionFilter] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [newUser, setNewUser] = useState({ username: '', password: '', role: 'viewer' })
  const [msg, setMsg] = useState<string | null>(null)
  const isAdmin = me.role === 'admin'
  const [thr, setThr] = useState<Thresholds | null>(null)

  async function load() {
    try {
      if (isAdmin) {
        setUsers(await api('/v1/users'))
        const q = actionFilter ? `?action=${encodeURIComponent(actionFilter)}&limit=50` : '?limit=50'
        setAudit(await api(`/v1/audit${q}`))
        const t = await api('/v1/critical-events/settings/thresholds')
        setThr(t.effective ?? t)
      }
    } catch (e: any) { setError(e.message) }
  }
  useEffect(() => { load() }, [actionFilter])

  async function saveThresholds(e: React.FormEvent) {
    e.preventDefault()
    if (!thr) return
    setMsg(null)
    try {
      await api('/v1/critical-events/settings/thresholds', {
        method: 'PUT',
        body: JSON.stringify({
          battery_pct: Number(thr.battery_pct),
          deadletter_24h: Number(thr.deadletter_24h),
          silence_hours: Number(thr.silence_hours),
        }),
      })
      setMsg('✓ праговете са записани (следващият цикъл на evaluator-а ги взима)')
    } catch (err: any) { setMsg('✘ ' + err.message) }
  }

  async function createUser(e: React.FormEvent) {
    e.preventDefault()
    setMsg(null)
    try {
      await api('/v1/users', { method: 'POST', body: JSON.stringify(newUser) })
      setMsg(`✓ създаден потребител ${newUser.username} (${newUser.role})`)
      setNewUser({ username: '', password: '', role: 'viewer' })
      load()
    } catch (err: any) { setMsg('✘ ' + err.message) }
  }

  async function resetPassword(u: User) {
    const p = prompt(`Нова парола за ${u.username} (мин. 8 знака):`)
    if (!p) return
    try {
      await api(`/v1/users/${u.id}/password`, { method: 'POST', body: JSON.stringify({ new_password: p }) })
      setMsg(`✓ паролата на ${u.username} е сменена`)
    } catch (err: any) { setMsg('✘ ' + err.message) }
  }

  async function deleteUser(u: User) {
    if (!confirm(`Изтриване на потребител ${u.username}?`)) return
    try {
      await api(`/v1/users/${u.id}`, { method: 'DELETE' })
      setMsg(`✓ ${u.username} е изтрит`)
      load()
    } catch (err: any) { setMsg('✘ ' + err.message) }
  }

  return (
    <div>
      {error && <div className="error panel">{error}</div>}
      {msg && <div className={msg.startsWith('✓') ? 'ok-box panel' : 'error panel'}>{msg}</div>}

      {isAdmin ? (
        <>
          <div className="panel">
            <div className="kicker">СИСТЕМА</div>
      <h1 className="h-page">Система</h1>
            <table>
              <thead><tr><th>Потребител</th><th>Роля</th><th></th></tr></thead>
              <tbody>
                {(users ?? []).map((u) => (
                  <tr key={u.id}>
                    <td>{u.username}</td>
                    <td><span className="tag">{u.role}</span></td>
                    <td className="row-actions">
                      <button className="nav-btn" onClick={() => resetPassword(u)}>Ресет парола</button>
                      <button className="nav-btn danger" onClick={() => deleteUser(u)}>Изтрий</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <form className="form-grid" onSubmit={createUser}>
              <input placeholder="потребителско име" value={newUser.username}
                     onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} />
              <input type="password" placeholder="парола (мин. 8)" value={newUser.password}
                     onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} />
              <select value={newUser.role} onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}>
                <option value="viewer">viewer (гледане)</option>
                <option value="operator">operator</option>
                <option value="admin">admin</option>
              </select>
              <button>Създай</button>
            </form>
          </div>

          <div className="panel">
            <h2>Критични събития — прагове (Т7)</h2>
            <p className="muted small">
              Броячът в топбара брои тези събития (батерии / мъртви букви / мълчания).
              Промяната действа от следващия цикъл на evaluator-а — без рестарт.
            </p>
            {thr ? (
              <form className="form-grid" onSubmit={saveThresholds}>
                <label className="small">батерия под (%)
                  <input type="number" min={0} max={100} value={thr.battery_pct}
                         onChange={(e) => setThr({ ...thr, battery_pct: Number(e.target.value) })} />
                </label>
                <label className="small">мъртви букви за 24 ч (поне)
                  <input type="number" min={1} max={1000} value={thr.deadletter_24h}
                         onChange={(e) => setThr({ ...thr, deadletter_24h: Number(e.target.value) })} />
                </label>
                <label className="small">мълчание след (часа)
                  <input type="number" min={0.5} max={720} step={0.5} value={thr.silence_hours}
                         onChange={(e) => setThr({ ...thr, silence_hours: Number(e.target.value) })} />
                </label>
                <button>Запиши</button>
              </form>
            ) : <div className="empty">…</div>}
          </div>

          <GeoPanel />

          <PskPanel />

          <div className="panel">
            <h2>Audit журнал</h2>
            <input placeholder="филтър по действие (напр. bridge.create)"
                   value={actionFilter} onChange={(e) => setActionFilter(e.target.value)} />
            <table>
              <thead><tr><th>Час</th><th>Потребител</th><th>Действие</th><th>Обект</th></tr></thead>
              <tbody>
                {audit.map((a, i) => (
                  <tr key={i}>
                    <td>{fmtTime(a.ts)}</td>
                    <td>{a.username ?? 'система'}</td>
                    <td className="mono">{a.action}</td>
                    <td>{a.entity}{a.entity_id ? ` / ${a.entity_id}` : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <div className="panel">
          <h2>Сигурност</h2>
          <p className="muted">
            Ролята ти е <b>{me.role}</b> — управлението на потребители и audit журналът
            са достъпни за администратори. Твоята парола сменяш с 🔑 в горния десен ъгъл.
          </p>
        </div>
      )}
    </div>
  )
}


/* ============================================================================
 * Т36 срез 2 (ADR-007): PSK ключове по канал — собственикът въвежда base64
 * PSK на всеки криптиран канал; стойностите НЕ се показват след запис.
 * AQ== (1 байт) = дефолтният LongFast ключ. Влизат в сила на живо.
 * ========================================================================== */
function PskPanel() {
  const [channels, setChannels] = useState<Record<string, { length: number; one_byte: boolean }> | null>(null)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [newCh, setNewCh] = useState('')
  const [newKey, setNewKey] = useState('')
  const [msg, setMsg] = useState<string | null>(null)

  const load = () =>
    api<{ channels: Record<string, { length: number; one_byte: boolean }> }>('/v1/system/psk')
      .then((r) => setChannels(r.channels ?? {}))
      .catch(() => setChannels({}))

  useEffect(() => { void load() }, [])

  async function save() {
    setMsg(null)
    try {
      const payload: Record<string, string | null> = {}
      for (const [ch, v] of Object.entries(drafts)) payload[ch] = v.trim() || null
      if (newCh.trim() && newKey.trim()) payload[newCh.trim()] = newKey.trim()
      if (Object.keys(payload).length === 0) { setMsg('Няма промени.'); return }
      await api('/v1/system/psk', { method: 'PUT', body: JSON.stringify({ channels: payload }) })
      setDrafts({}); setNewCh(''); setNewKey('')
      setMsg('✓ Ключовете са записани и вече действат (без рестарт).')
      await load()
    } catch (e: any) { setMsg('Грешка: ' + e.message) }
  }

  return (
    <div className="panel">
      <h2>PSK ключове на каналите (Т36)</h2>
      <p className="muted small">
        Декрипция на криптирани канали: въведи base64 PSK за всеки канал
        (от Meshtastic приложението на устройството). <code>AQ==</code> = дефолтният
        LongFast ключ. Ключовете не се показват след запис; без ключ каналът
        остава честно „криптирано“.
      </p>
      {channels && Object.keys(channels).length > 0 && (
        <table>
          <thead><tr><th>Канал</th><th>Ключ</th></tr></thead>
          <tbody>
            {Object.entries(channels).map(([ch, meta]) => (
              <tr key={ch}>
                <td className="mono">{ch}</td>
                <td className="muted small">
                  въведен · {meta.one_byte ? 'кратък (индекс)' : `${meta.length} байта base64`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="form-grid" style={{ marginTop: 8 }}>
        <label className="small">канал (напр. LongFast)
          <input value={newCh} onChange={(e) => setNewCh(e.target.value)} placeholder="LongFast" />
        </label>
        <label className="small">PSK (base64)
          <input value={newKey} onChange={(e) => setNewKey(e.target.value)} placeholder="AQ==" />
        </label>
        <label className="small">смени съществуващ
          <select value="" onChange={(e) => e.target.value && setDrafts({ ...drafts, [e.target.value]: drafts[e.target.value] ?? '' })}>
            <option value="">— избери канал —</option>
            {Object.keys(channels ?? {}).map((ch) => <option key={ch} value={ch}>{ch}</option>)}
          </select>
        </label>
        {Object.entries(drafts).map(([ch, v]) => (
          <label key={ch} className="small">нов PSK за {ch}
            <input value={v} onChange={(e) => setDrafts({ ...drafts, [ch]: e.target.value })} placeholder="празно = премахни" />
          </label>
        ))}
        <button onClick={() => void save()}>Запиши ключовете</button>
      </div>
      {msg && <div className={msg.startsWith('✓') ? 'ok-box' : 'error'}>{msg}</div>}
    </div>
  )
}


/* ============================================================================
 * Т35 (ADR-008): геозони — кръг с център/радиус; детекторът „напусна
 * зоната" минава през критичните събития (ack/silence/notify каквито са).
 * ========================================================================== */
type Zone = { name: string; node: string; lat: number; lng: number; radius_m: number }

function GeoPanel() {
  const [zones, setZones] = useState<Zone[] | null>(null)
  const [z, setZ] = useState<Zone>({ name: '', node: '*', lat: 42.6975, lng: 23.3242, radius_m: 1000 })
  const [msg, setMsg] = useState<string | null>(null)

  const load = () =>
    api<{ zones: Zone[] }>('/v1/system/geofence').then((r) => setZones(r.zones ?? [])).catch(() => setZones([]))

  useEffect(() => { void load() }, [])

  async function save(next: Zone[]) {
    setMsg(null)
    try {
      await api('/v1/system/geofence', { method: 'PUT', body: JSON.stringify({ zones: next }) })
      setMsg('✓ Зоните са записани — детекторът ги взема при следващия цикъл.')
      await load()
    } catch (e: any) { setMsg('Грешка: ' + e.message) }
  }

  return (
    <div className="panel">
      <h2>Геозони (Т35)</h2>
      <p className="muted small">
        Когато възел с позиция НАПУСНЕ зоната (беше вътре, стана извън) —
        критично събитие „геозона“: с ✓ потвърди / 🔇 заглуши и през известията.
        Кръговете се виждат на Картата (Гео режим).
      </p>
      {zones && zones.length > 0 && (
        <table>
          <thead><tr><th>Зона</th><th>Възел</th><th>Център</th><th>Радиус</th><th></th></tr></thead>
          <tbody>
            {zones.map((zz, i) => (
              <tr key={i}>
                <td>{zz.name}</td>
                <td className="mono small">{zz.node === '*' ? 'всички' : zz.node}</td>
                <td className="mono small">{zz.lat.toFixed(4)}, {zz.lng.toFixed(4)}</td>
                <td className="mono small">{zz.radius_m} м</td>
                <td>
                  <button className="nav-btn ghost" onClick={() => void save(zones.filter((_, j) => j !== i))}>✕</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="form-grid" style={{ marginTop: 8 }}>
        <label className="small">име
          <input value={z.name} onChange={(e) => setZ({ ...z, name: e.target.value })} placeholder="релеи-София" />
        </label>
        <label className="small">възел (* = всички)
          <input value={z.node} onChange={(e) => setZ({ ...z, node: e.target.value })} placeholder="*" />
        </label>
        <label className="small">lat
          <input type="number" step={0.0001} value={z.lat} onChange={(e) => setZ({ ...z, lat: Number(e.target.value) })} />
        </label>
        <label className="small">lng
          <input type="number" step={0.0001} value={z.lng} onChange={(e) => setZ({ ...z, lng: Number(e.target.value) })} />
        </label>
        <label className="small">радиус (м)
          <input type="number" min={10} value={z.radius_m} onChange={(e) => setZ({ ...z, radius_m: Number(e.target.value) })} />
        </label>
        <button disabled={!z.name} onClick={() => { void save([...(zones ?? []), z]); setZ({ ...z, name: '' }) }}>+ добави зона</button>
      </div>
      {msg && <div className={msg.startsWith('✓') ? 'ok-box' : 'error'}>{msg}</div>}
    </div>
  )
}
