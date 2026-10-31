import { useEffect, useState } from 'react'
import { api } from '../api'

type Profile = { id: string; name: string; description: string; current_version: number }
type Version = { version: number; spec: any; created_at: string }

type ApplyResult = {
  applied: string | false
  requires_confirmation?: boolean
  risky?: boolean
  diff?: Record<string, { before: any; after: any }>
}

export default function Profiles() {
  const [profiles, setProfiles] = useState<Profile[] | null>(null)
  const [selected, setSelected] = useState<Profile | null>(null)
  const [versions, setVersions] = useState<Version[] | null>(null)
  const [confirmApply, setConfirmApply] = useState<{ name: string; version: number; diff: any } | null>(null)
  const [msg, setMsg] = useState<string | null>(null)

  useEffect(() => { api('/v1/profiles').then(setProfiles).catch(() => setProfiles([])) }, [])

  async function open(p: Profile) {
    setSelected(p)
    setVersions(await api(`/v1/profiles/${p.name}/versions`).catch(() => []))
  }

  async function apply(name: string, version: number, confirmRisky = false) {
    setMsg(null)
    const res: ApplyResult = await api(`/v1/profiles/${name}/apply`, {
      method: 'POST',
      body: JSON.stringify({ version, confirm_risky: confirmRisky }),
    })
    if (res.requires_confirmation) {
      setConfirmApply({ name, version, diff: res.diff })
    } else {
      setMsg(`✓ приложен профил ${res.applied}`)
      setConfirmApply(null)
      if (selected) await open(selected)
    }
  }

  return (
    <div>
      {msg && <div className="ok-box panel">{msg}</div>}
      <div className="panel">
        <div className="kicker">ШАБЛОНИ</div>
      <h1 className="h-page">Шаблони</h1>
        {!profiles ? (
          <div className="empty">Зарежда се…</div>
        ) : (
          <table>
            <thead><tr><th>Профил</th><th>Описание</th><th>Версия</th><th></th></tr></thead>
            <tbody>
              {profiles.map((p) => (
                <tr key={p.id} className={selected?.id === p.id ? 'selected' : ''}>
                  <td className="mono">{p.name}</td>
                  <td>{p.description}</td>
                  <td>v{p.current_version}</td>
                  <td>
                    <button className="nav-btn" onClick={() => open(p)}>Версии</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selected && versions && (
        <div className="panel">
          <h2>Версии на {selected.name}</h2>
          <table>
            <thead><tr><th>Версия</th><th>Retention (суровини)</th><th>Retention (събития)</th><th>Изход. мостове</th><th></th></tr></thead>
            <tbody>
              {versions.map((v) => (
                <tr key={v.version}>
                  <td>v{v.version}</td>
                  <td>{v.spec.retention_packets_raw} д.</td>
                  <td>{v.spec.retention_events} д.</td>
                  <td>
                    <span className={v.spec.bridge_outbound_enabled ? 'tag bad' : 'tag ok'}>
                      {v.spec.bridge_outbound_enabled ? 'включени' : 'изключени'}
                    </span>
                  </td>
                  <td><button className="nav-btn" onClick={() => apply(selected.name, v.version)}>Приложи</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">
            Прилагането променя retention и дали изходящите мостове са позволени изобщо;
            всичко се записва в audit журнала с diff и може да се върне с прилагане на друга версия.
          </p>
        </div>
      )}

      {confirmApply && (
        <div className="modal-back">
          <div className="modal card">
            <h2>Потвърди рискова промяна</h2>
            <p>Профил <b>{confirmApply.name}</b> v{confirmApply.version} включва <b>изходящите мостове</b>.</p>
            <pre>{JSON.stringify(confirmApply.diff, null, 2)}</pre>
            <div className="form-row">
              <button className="ghost-btn" onClick={() => setConfirmApply(null)}>Отказ</button>
              <button onClick={() => apply(confirmApply.name, confirmApply.version, true)}>
                Приложи с риск
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
