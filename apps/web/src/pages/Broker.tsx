import { useEffect, useState } from 'react'
import { api, fmtTime } from '../api'
import type { Me } from '../App'

type Status = {
  connections: number
  topics: number
  subscriptions: number
  received_msg_rate: number
  sent_msg_rate: number
  retained_msg_count: number
  listeners: { id: string; running: boolean; bind: string; current_connections: number }[]
}
type Client = { client_id: string; username: string; ip: string; connected: boolean; connected_at: string; subscriptions_count: number }
type Sub = { client_id: string; topic: string; qos: number }

export default function Broker({ me }: { me: Me }) {
  const [status, setStatus] = useState<Status | null>(null)
  const [clients, setClients] = useState<Client[] | null>(null)
  const [subs, setSubs] = useState<Sub[] | null>(null)
  const [tab, setTab] = useState<'clients' | 'subs'>('clients')
  const [error, setError] = useState<string | null>(null)
  const [pub, setPub] = useState({ topic: 'mesh/test/up', payload: '{"hello":"meshgate"}' })
  const [pubMsg, setPubMsg] = useState<string | null>(null)

  const canOperate = me.role !== 'viewer'

  async function load() {
    try {
      setStatus(await api('/v1/broker/status'))
      setClients(await api('/v1/broker/clients'))
      setSubs(await api('/v1/broker/subscriptions'))
    } catch (e: any) {
      setError(e.message)
    }
  }
  useEffect(() => {
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [])

  async function kick(id: string) {
    if (!confirm(`Прекъсване на клиент ${id}?`)) return
    try {
      await api(`/v1/broker/clients/${id}`, { method: 'DELETE' })
      load()
    } catch (e: any) { setError(e.message) }
  }

  async function testPublish(e: React.FormEvent) {
    e.preventDefault()
    setPubMsg(null)
    try {
      await api('/v1/broker/test-publish', { method: 'POST', body: JSON.stringify({ ...pub, qos: 0 }) })
      setPubMsg('✓ публикувано — виж го в Packet Explorer')
    } catch (err: any) { setPubMsg('✘ ' + err.message) }
  }

  if (error) return <div className="panel"><div className="error">{error}</div></div>
  if (!status) return <div className="empty">Зарежда се…</div>

  return (
    <div>
      <div className="cards">
        <div className="card stat"><div className="stat-label">Връзки</div><div className="stat-value">{status.connections}</div></div>
        <div className="card stat"><div className="stat-label">Теми</div><div className="stat-value">{status.topics}</div></div>
        <div className="card stat"><div className="stat-label">Абонаменти</div><div className="stat-value">{status.subscriptions}</div></div>
        <div className="card stat ok">
          <div className="stat-label">Съобщения/сек (текущо)</div>
          <div className="stat-value">{status.received_msg_rate}</div>
          <div className="stat-sub">изпращани: {status.sent_msg_rate}/с · retained: {status.retained_msg_count}</div>
        </div>
      </div>

      <div className="panel">
        <div className="kicker">УПРАВЛЕНИЕ НА БРОКЕРА</div>
      <h1 className="h-page">Брокер</h1>
        <table>
          <thead><tr><th>Име</th><th>Адрес</th><th>Връзки</th><th>Статус</th></tr></thead>
          <tbody>
            {status.listeners.map((l) => (
              <tr key={l.id}>
                <td className="mono">{l.id}</td>
                <td className="mono">{l.bind}</td>
                <td>{l.current_connections}</td>
                <td><span className={l.running ? 'tag ok' : 'tag bad'}>{l.running ? 'работи' : 'спрян'}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel toolbar">
        <h2>Клиенти и абонаменти</h2>
        <button className={tab === 'clients' ? 'nav-btn active' : 'nav-btn'} onClick={() => setTab('clients')}>
          Клиенти ({clients?.length ?? 0})
        </button>
        <button className={tab === 'subs' ? 'nav-btn active' : 'nav-btn'} onClick={() => setTab('subs')}>
          Абонаменти ({subs?.length ?? 0})
        </button>
      </div>

      <div className="panel">
        {tab === 'clients' ? (
          !clients || clients.length === 0 ? <div className="empty">Няма клиенти.</div> : (
            <table>
              <thead><tr><th>Client ID</th><th>Потребител</th><th>IP</th><th>От</th><th>Абон.</th><th></th></tr></thead>
              <tbody>
                {clients.map((c) => (
                  <tr key={c.client_id}>
                    <td className="mono">{c.client_id}</td>
                    <td>{c.username ?? '—'}</td>
                    <td className="mono">{c.ip}</td>
                    <td>{c.connected_at ? fmtTime(c.connected_at) : '—'}</td>
                    <td>{c.subscriptions_count}</td>
                    <td>
                      {canOperate && (
                        <button className="nav-btn" onClick={() => kick(c.client_id)}>Прекъсни</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        ) : (
          !subs || subs.length === 0 ? <div className="empty">Няма абонаменти.</div> : (
            <table>
              <thead><tr><th>Client ID</th><th>Тема</th><th>QoS</th></tr></thead>
              <tbody>
                {subs.map((s, i) => (
                  <tr key={i}>
                    <td className="mono">{s.client_id}</td>
                    <td className="mono">{s.topic}</td>
                    <td>{s.qos}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
      </div>

      {canOperate && (
        <div className="panel">
          <h2>Тестова публикация</h2>
          <form className="form-grid" onSubmit={testPublish}>
            <input className="mono" value={pub.topic} onChange={(e) => setPub({ ...pub, topic: e.target.value })} placeholder="тема" />
            <input className="mono" value={pub.payload} onChange={(e) => setPub({ ...pub, payload: e.target.value })} placeholder="payload (текст/JSON)" />
            <button>Публикувай</button>
          </form>
          {pubMsg && <div className={pubMsg.startsWith('✓') ? 'ok-box' : 'error'}>{pubMsg}</div>}
        </div>
      )}
    </div>
  )
}
