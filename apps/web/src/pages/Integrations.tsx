import { useEffect, useState } from 'react'
import { api } from '../api'
import { Panel, StatusChip } from '../components/ui'
import type { Me } from '../App'

type Facets = {
  total: number
  types: { type: string; count: number }[]
  channels: { channel: string; count: number; types: string[] }[]
  nodes: { node: string; count: number }[]
}
type Bridge = {
  id: string; name: string; remote_host: string; remote_port: number
  direction: string; enabled: boolean
  health?: string; counters?: Record<string, number>; last_error?: string | null
}
type Channel = { id: string; name: string; kind: string; topic_pattern: string; enabled: boolean }
type Status = { data: { broker?: any; packets_total: number; devices_total: number } }
type HAStatus = {
  enabled: boolean; nodes: number; entities: number; published: number
  node_list: { node: string; entities: string[] }[]
}

export default function Integrations({ me }: { me: Me }) {
  const [facets, setFacets] = useState<Facets | null>(null)
  const [bridges, setBridges] = useState<Bridge[] | null>(null)
  const [channels, setChannels] = useState<Channel[] | null>(null)
  const [status, setStatus] = useState<Status | null>(null)
  const [ha, setHa] = useState<HAStatus | null>(null)
  const [haUser, setHaUser] = useState<{ username: string; password: string } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [showChannels, setShowChannels] = useState(25)
  const [gws, setGws] = useState<{ gateway_id: string; kind: string; name?: string | null; packets: number; channels: { channel: string; packets: number }[] }[] | null>(null)

  const isAdmin = me.role === 'admin'

  useEffect(() => {
    const load = () => {
      api('/v1/packets/facets?hours=24').then(setFacets).catch(() => {})
      api('/v1/bridges').then(setBridges).catch(() => setBridges([]))
      api('/v1/notifications').then(setChannels).catch(() => setChannels([]))
      api('/v1/system/status').then(setStatus).catch(() => {})
      api('/v1/home-assistant').then((r: any) => setHa(r)).catch(() => setHa(null))
      api('/v1/gateways?hours=168').then((r: any) => setGws(r.gateways ?? [])).catch(() => setGws([]))
    }
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [])

  async function haToggle(on: boolean) {
    try {
      const r = await api(`/v1/home-assistant/${on ? 'enable' : 'disable'}`, { method: 'POST' })
      setHa({ ...r, node_list: r.node_list ?? [] })  // защитено: без пълен статус старата стойност чупеше страницата
    } catch (e: any) { setErr(e.message); setTimeout(() => setErr(null), 4000) }
  }

  async function haTest() {
    try {
      const r = await api('/v1/home-assistant/test', { method: 'POST' })
      setHa((h) => h && { ...h, nodes: h.nodes + 1 })
      alert(`Тестов възел ${r.test_node} е публикуван — ще се появи в Home Assistant след секунда.`)
    } catch (e: any) { alert('Неуспех: ' + e.message) }
  }

  async function createHaUser() {
    try {
      const r = await api('/v1/broker/credentials', {
        method: 'POST',
        body: JSON.stringify({
          username: 'home-assistant',
          topics: ['homeassistant/#', 'meshgate/#'],
        }),
      })
      setHaUser({ username: r.username, password: r.password })
    } catch (e: any) { alert('Неуспех: ' + e.message) }
  }

  if (err) return <div className="error">{err}</div>
  const meshTypes = (facets?.types ?? []).filter((t) => t.type.startsWith('meshtastic-'))
  const meshTotal = meshTypes.reduce((s, t) => s + t.count, 0)

  return (
    <>
      <div className="kicker">ИНТЕГРАЦИИ</div>
      <h1 className="h-page">Интеграции</h1>
      <div className="toolbar">
        <span className="muted small">свързаните мрежи и услуги — статус на живо</span>
      </div>

      <div className="cards">
        <div className="card stat">
          <div className="stat-label">Meshtastic адаптер</div>
          <div className="stat-value" style={{ color: meshTotal > 0 ? 'var(--ok)' : 'var(--muted)' }}>
            {meshTotal > 0 ? 'жив' : 'без данни'}
          </div>
          <div className="stat-sub">
            {meshTotal.toLocaleString('bg-BG')} разпознати пакета (24 ч) ·{' '}
            {facets?.channels.length ?? 0} канала · {facets?.nodes.length ?? 0}+ възела
          </div>
        </div>
        <div className="card stat">
          <div className="stat-label">Външни брокери (мостове)</div>
          <div className="stat-value">{bridges?.length ?? '…'}</div>
          <div className="stat-sub">
            {(bridges ?? []).filter((b) => b.health === 'up' || (b.enabled && b.health !== 'down')).length} активни
          </div>
        </div>
        <div className="card stat">
          <div className="stat-label">Канали за известия</div>
          <div className="stat-value">{channels?.length ?? '…'}</div>
          <div className="stat-sub">
            {(channels ?? []).filter((c) => c.enabled).length} включени ·{' '}
            {(channels ?? []).map((c) => c.kind).filter((v, i, a) => a.indexOf(v) === i).join(', ') || '—'}
          </div>
        </div>
        <div className="card stat">
          <div className="stat-label">Локален брокер (EMQX)</div>
          <div className="stat-value" style={{ color: status?.data?.broker ? 'var(--ok)' : 'var(--muted)' }}>
            {status?.data?.broker ? 'жив' : '…'}
          </div>
          <div className="stat-sub">
            {status?.data?.broker?.connections != null
              ? `${status.data.broker.connections} връзки` : ''}
          </div>
        </div>
      </div>

      <Panel title="Meshtastic канали на живо (24 ч)"
             subtitle={facets && facets.channels.length > showChannels ? `първите ${showChannels} от ${facets.channels.length}` : 'кой канал колко излъчва'} padded={false}>
        {!facets?.channels.length ? (
          <div className="empty">Още няма Meshtastic трафик — включи входящ мост от Bridges.</div>
        ) : (
          <>
            <table>
              <thead>
                <tr><th>Канал</th><th>Пакети</th><th>Разпознати видове</th></tr>
              </thead>
              <tbody>
                {facets.channels.slice(0, showChannels).map((c) => (
                  <tr key={c.channel}>
                    <td><span className="tag ch">{c.channel}</span></td>
                    <td>{c.count.toLocaleString('bg-BG')}</td>
                    <td className="small muted">{c.types.join(', ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {facets.channels.length > showChannels && (
              <button className="nav-btn" style={{ marginTop: 8 }}
                      onClick={() => setShowChannels(facets.channels.length)}>
                покажи всички ({facets.channels.length})
              </button>
            )}
          </>
        )}
      </Panel>

      <Panel title="MQTT гейтове на живо (7 д)" subtitle={gws && gws.length ? `${gws.length} гейта — кой канал кой излъчва` : 'пакетите носят gateway_id от ServiceEnvelope'} padded={false}>
        {!gws?.length ? (
          <div className="empty">Няма гейтове с последни 7 д — пакетите носят gateway_id от ServiceEnvelope.</div>
        ) : (
          <table>
            <thead>
              <tr><th>Гейт</th><th>Пакети</th><th>Канали, които излъчва</th></tr>
            </thead>
            <tbody>
              {gws.slice(0, 20).map((g) => (
                <tr key={g.gateway_id}>
                  <td>
                    <span style={{ fontWeight: 600 }}>{g.name ?? g.gateway_id}</span>
                    {g.name && <span className="mono small" style={{ display: 'block', color: 'var(--text-muted)' }}>{g.gateway_id}</span>}
                  </td>
                  <td>{g.packets.toLocaleString('bg-BG')}</td>
                  <td className="small">
                    {g.channels.slice(0, 6).map((c) => (
                      <span key={c.channel} className="tag ch" style={{ marginRight: 4 }} title={`${c.channel}: ${c.packets} пакета`}>
                        {c.channel} {c.packets > 99 ? '·99+' : c.packets > 0 && c.packets < 100 ? c.packets : ''}
                      </span>
                    ))}
                    {g.channels.length > 6 && <span className="muted">+{g.channels.length - 6}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="Външни брокери" subtitle="входящи/изходящи мостове към други MQTT брокери" padded={false}>
        {!bridges?.length ? (
          <div className="empty">Няма мостове. Създай входящ мост (напр. към публичен Meshtastic брокер) от „Мостове и маршрути“.</div>
        ) : (
          <table>
            <thead>
              <tr><th>Име</th><th>Хост</th><th>Посока</th><th>Здраве</th><th>Броячи</th></tr>
            </thead>
            <tbody>
              {bridges.map((b) => (
                <tr key={b.id}>
                  <td>{b.name}</td>
                  <td className="mono small">{b.remote_host}:{b.remote_port}</td>
                  <td>{b.direction}</td>
                  <td>
                    <StatusChip size="sm" flat tone={b.health === 'down' ? 'danger' : b.health === 'up' ? 'success' : 'neutral'}>
                      {b.health ?? '—'}{!b.enabled ? ' (изключен)' : ''}
                    </StatusChip>
                  </td>
                  <td className="small muted">
                    {b.counters
                      ? Object.entries(b.counters).map(([k, v]) => `${k}: ${v}`).join(' · ')
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="🏠 Home Assistant (MQTT Discovery)" subtitle="възлите като устройства със сензори в HA">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <StatusChip size="sm" flat tone={ha?.enabled ? 'success' : 'neutral'}>
            {ha?.enabled ? 'включен' : 'изключен'}
          </StatusChip>
          {ha && (
            <span className="muted small">
              {ha.nodes} възела · {ha.entities} сензора · {ha.published} публикации
            </span>
          )}
          <span style={{ flex: 1 }} />
          {isAdmin && (
            <>
              <button className="ghost-btn" onClick={() => haToggle(!ha?.enabled)}>
                {ha?.enabled ? 'Изключи' : 'Включи'}
              </button>
              <button className="ghost-btn" onClick={haTest} disabled={!ha?.enabled}>
                ⚡ Тестов възел
              </button>
              <button className="ghost-btn" onClick={createHaUser}>
                + MQTT потребител за HA
              </button>
            </>
          )}
        </div>
        {haUser && (
          <div className="ok-box" style={{ marginTop: 10 }}>
            <strong>Готов потребител за Home Assistant:</strong>
            <div className="mono small">
              хост: &lt;IP-то на този компютър&gt; · порт: 1883<br />
              потребител: <strong>{haUser.username}</strong><br />
              парола: <strong>{haUser.password}</strong>
            </div>
            <p className="muted small">
              Паролата се показва само веднъж — запиши я. В HA: Настройки → Устройства и
              услуги → Добавяне → MQTT, въведи хоста и тези данни. Възлите се появяват
              като устройства със сензори „Батерия“, „SNR“ и „Последно съобщение“.
            </p>
          </div>
        )}
        {ha?.enabled && (ha.node_list?.length ?? 0) > 0 && (
          <table style={{ marginTop: 8 }}>
            <thead><tr><th>Възел</th><th>Сензори в HA</th></tr></thead>
            <tbody>
              {ha.node_list.slice(0, 10).map((n) => (
                <tr key={n.node}>
                  <td className="mono">{n.node}</td>
                  <td className="small">{n.entities.join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted small" style={{ marginBottom: 0 }}>
          Когато е включен, всеки Meshtastic възел с батерия/SNR/съобщение се публикува
          като устройство в Home Assistant (discovery теми homeassistant/…, състояния
          meshgate/&lt;възел&gt;/…, обновяване на всеки ~20 сек).
        </p>
      </Panel>

      <Panel title="Предстоящи връзки" subtitle="следващите интеграции от каталога">
        <p className="muted small" style={{ margin: 0 }}>
          Zigbee2MQTT, Node-RED/n8n, ntfy push и Grafana/InfluxDB се включват тук
          (вж. docs/13-integrations-catalog.md). Webhook каналът от „Известия“ вече е
          врата към n8n/Node-RED днес.
        </p>
      </Panel>
    </>
  )
}
