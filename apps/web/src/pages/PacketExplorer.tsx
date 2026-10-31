import { useEffect, useMemo, useRef, useState } from 'react'
import { useNodeNames } from '../names'
import { LiveIndicator, usePacketStream, useToast } from '../components/ui'
import { Table, Column } from '../components/Table'
import { api, fmtTime } from '../api'

type Packet = {
  id: string
  ts: string
  topic: string
  packet_type: string
  decode_status: string
  payload_size: number
  origin: string
  channel?: string | null
  node?: string | null
}

type MeshInfo = {
  packet_type: string | null
  node_id: string | null
  text: string | null
  battery: number | null
  lat: number | null
  lng: number | null
  snr: number | null
  rssi: number | null
  packet_id: number | null
  neighbors: { node: string; snr: number | null }[] | null
  route: string[] | null
}

type Detail = Packet & {
  payload_text: string | null
  payload_hex: string | null
  decode_error: string | null
  decoder_id: string | null
  mesh?: MeshInfo | null
  trace: { ts: string; decision: string; reason: string }[]
}

type Facets = {
  hours: number
  total: number
  types: { type: string; count: number }[]
  channels: { channel: string; count: number; types: string[] }[]
  nodes: { node: string; count: number }[]
}

/** msh/<регион>/2/e|json/<канал>/!<възел> → канал/възел (за live редовете). */
function topicParts(topic: string): { channel: string | null; node: string | null } {
  const toks = topic.split('/')
  const node = toks.find((t) => t.startsWith('!')) ?? null
  let channel: string | null = null
  const i = toks.findIndex((t) => t === 'e' || t === 'c' || t === 'json')
  if (i >= 0 && toks[i + 1] && !toks[i + 1].startsWith('!')) channel = toks[i + 1]
  return { channel, node }
}

const TYPE_META: Record<string, { label: string; cls: string; icon: string }> = {
  'meshtastic-text': { label: 'Текст', cls: 'tag ok', icon: '💬' },
  'meshtastic-telemetry': { label: 'Телеметрия', cls: 'tag', icon: '🔋' },
  'meshtastic-position': { label: 'Позиция', cls: 'tag', icon: '📍' },
  'meshtastic-encrypted': { label: 'Криптирано', cls: 'tag', icon: '🔒' },
  'meshtastic-nodeinfo': { label: 'Възел инфо', cls: 'tag', icon: '🏷' },
  'meshtastic-neighbor': { label: 'Съседи', cls: 'tag', icon: '🔗' },
  'meshtastic-routing': { label: 'Рутинг', cls: 'tag', icon: '🧭' },
  'meshtastic-traceroute': { label: 'Трейсрут', cls: 'tag', icon: '🛰' },
  'meshtastic-map': { label: 'Карта', cls: 'tag', icon: '🗺' },
  binary: { label: 'Бинарен', cls: 'tag', icon: '📦' },
  json: { label: 'JSON', cls: 'tag', icon: '{ }' },
  text: { label: 'Текст (raw)', cls: 'tag', icon: '📄' },
}

function typeMeta(t: string) {
  return TYPE_META[t] ?? { label: t.replace(/^meshtastic-/, ''), cls: 'tag', icon: '•' }
}

export default function PacketExplorer() {
  const nameOf = useNodeNames()
  const [delivery, setDelivery] = useState<{ sent: boolean; status: string; ack_by?: string | null; ack_at?: string | null; ack_error?: string | null } | null>(null)
  const stream = usePacketStream()
  const [live, setLive] = useState<Packet[]>([])
  const [paused, setPaused] = useState(false)
  const [filter, setFilter] = useState('')
  const [typeSel, setTypeSel] = useState<string | null>(null)
  const [channelSel, setChannelSel] = useState<string | null>(null)
  const [nodeSel, setNodeSel] = useState<string | null>(null)
  const [dedupe, setDedupe] = useState(false)
  const [facets, setFacets] = useState<Facets | null>(null)
  const [history, setHistory] = useState<Packet[] | null>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const pausedRef = useRef(false)
  pausedRef.current = paused
  // Т14 П3: ЕДИН споделен WS (usePacketStream); филтрите живеят в ref —
  // binding-ът не се преинсталира на всяка клавишна стъпка (двоен WS беше
  // разход №1: нов сокет на всяка буква в полето за търсене)
  const toast = useToast()
  const liveFilter = useRef({ filter, typeSel, channelSel, nodeSel })
  liveFilter.current = { filter, typeSel, channelSel, nodeSel }

  // Т12 таблицата (fixed header, сортиране, филтър, колони) носи списъка;
  // клетъчните чипове спират row-click-а сами (фасетно филтриране).
  // useMemo ПРЕДИ какъвто и да е ранен return (урокът React #310)
  const COLUMNS = useMemo<Column<Packet>[]>(() => [
    { id: 'ts', label: 'Час', value: (p) => p.ts, render: (p) => fmtTime(p.ts) },
    { id: 'channel', label: 'Канал', value: (p) => p.channel ?? '',
      render: (p) => (p.channel
        ? <span className="tag ch" onClick={(e) => { e.stopPropagation(); setChannelSel(p.channel!) }} title="филтрирай по този канал">{p.channel}</span>
        : <span className="muted">—</span>) },
    { id: 'node', label: 'Възел', value: (p) => p.node ?? '',
      render: (p) => (p.node
        ? <span className="rowlink" onClick={(e) => { e.stopPropagation(); setNodeSel(p.node!) }} title={nameOf(p.node).tip}>{nameOf(p.node).main}</span>
        : <span className="muted">—</span>) },
    { id: 'type', label: 'Тип', value: (p) => p.packet_type,
      render: (p) => { const m = typeMeta(p.packet_type); return <span className={m.cls}>{m.icon} {m.label}</span> } },
    { id: 'decode', label: 'Декод', value: (p) => p.decode_status,
      render: (p) => (
        <span className={
          p.decode_status === 'decoded' ? 'tag ok' :
          p.decode_status === 'failed' ? 'tag bad' : 'tag'
        }>{p.decode_status}</span>) },
    { id: 'topic', label: 'Тема', value: (p) => p.topic,
      render: (p) => <span className="mono small">{p.topic}</span> },
    { id: 'origin', label: 'Проход', value: (p) => p.origin,
      render: (p) => (
        <span className="muted">{p.origin}{(p as any).dup_count > 1 && (
          <span className="tag" title="еднакви съобщения, групирани"> ×{(p as any).dup_count}</span>
        )}</span>) },
  ], [nameOf])

  async function loadFacets() {
    try {
      setFacets(await api('/v1/packets/facets?hours=24'))
    } catch (e: any) { /* фасетите не са критични */ }
  }

  useEffect(() => {
    loadFacets()
    const t = setInterval(loadFacets, 20000)
    return () => clearInterval(t)
  }, [])

  // drill-down от Пулс-лентата в Devices: филтрирай направо по възела
  useEffect(() => {
    const pre = sessionStorage.getItem('mg_pe_topic')
    if (pre) {
      sessionStorage.removeItem('mg_pe_topic')
      setFilter(pre)
    }
  }, [])

  useEffect(() => {
    const bind = (msg: unknown) => {
      const m = msg as { type?: string; data?: any } | null
      if (!m || m.type !== 'packet' || !m.data || pausedRef.current) return
      const p = { ...m.data, ...topicParts(m.data.topic as string) }
      const f = liveFilter.current
      if (f.filter && !p.topic.toLowerCase().includes(f.filter.toLowerCase())) return
      if (f.typeSel && p.packet_type !== f.typeSel) return
      if (f.channelSel && p.channel !== f.channelSel) return
      if (f.nodeSel && p.node !== f.nodeSel) return
      setLive((prev) => [p, ...prev].slice(0, 300))
    }
    // onDataBind НЕ връща unsubscribe — чисти се с изричен null
    stream.onDataBind(bind)
    return () => stream.onDataBind(null)
  }, [stream.onDataBind])

  // при смяна на филтър старият буфер на живия поток вече не пасва —
  // редовете, които не отговарят на новия филтър, се изчистват
  useEffect(() => {
    setLive((prev) => prev.filter((p) =>
      (!filter || p.topic.toLowerCase().includes(filter.toLowerCase())) &&
      (!typeSel || p.packet_type === typeSel) &&
      (!channelSel || p.channel === channelSel) &&
      (!nodeSel || p.node === nodeSel)))
  }, [filter, typeSel, channelSel, nodeSel])

  // dedupe се подава изрично (stale closure: state-ът още не е рендерен
  // при setTimeout(loadHistory, 0) — П3 Т14)
  async function loadHistory(dedupeNow: boolean = dedupe) {
    try {
      const q = new URLSearchParams()
      if (dedupeNow) q.set('dedupe', '1')
      if (typeSel) q.set('packet_type', typeSel)
      if (channelSel) q.set('channel', channelSel)
      if (nodeSel) q.set('node', nodeSel)
      if (filter) q.set('topic', filter)
      const r = await api(`/v1/packets?limit=100&${q.toString()}`)
      setHistory(r)
    } catch (e: any) { toast.push('danger', `Историята не се зареди: ${e.message}`) }
  }

  async function openDetail(p: Packet) {
    setDelivery(null)
    try {
      setDetail(await api(`/v1/packets/${p.id}`))
    } catch (e: any) {
      toast.push('danger', `Детайлът не се отвори: ${e.message}`)
      return
    }
    api(`/v1/packets/${p.id}/delivery`).then(setDelivery).catch(() => setDelivery(null))
  }

  // Т14: експортът ползва готовия POST /v1/packets/export (JSON attach)
  async function exportJson() {
    try {
      const r = await fetch('/api/v1/packets/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ limit: 1000, format: 'json' }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const blob = await r.blob()
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `packets-export-${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(a.href)
      toast.push('success', 'Експортът е изтеглен (последните 1000 пакета).')
    } catch (e: any) { toast.push('danger', `Експортът се провали: ${e.message}`) }
  }

  const rows = live.length > 0 ? live : (history ?? [])
  const hasFilters = !!(typeSel || channelSel || nodeSel || filter)

  return (
    <div>
      <div className="panel toolbar">
        <h2>Packet Explorer</h2>
        <input
          placeholder="филтър по тема/текст…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <label className="small" title="повтарящите се съобщения (еднаква тема+съдържание) се групират в една линия с брой">
          <input type="checkbox" checked={dedupe}
            onChange={(e) => { setDedupe(e.target.checked); void loadHistory(e.target.checked) }} />{' '}
          групирай повторения
        </label>
        <span className="topbar-live" title="LIVE при отворена връзка; пулс — само при нови данни; пауза спира рендера, не сокета">
          <LiveIndicator state={paused ? 'idle' : stream.state} pulsing={!paused && stream.pulsing} compact />
        </span>
        <button onClick={() => setPaused(!paused)}>{paused ? '▶ Продължи' : '⏸ Пауза'}</button>
        <button onClick={() => void loadHistory()}>История (100)</button>
        <button className="ghost" onClick={() => void exportJson()}
                title="изтегля последните 1000 пакета като JSON">⤓ Експорт</button>
        {hasFilters && (
          <button className="ghost" onClick={() => {
            setTypeSel(null); setChannelSel(null); setNodeSel(null); setFilter('')
          }}>Изчисти филтрите</button>
        )}
      </div>

      {/* Фасети: тип съобщение + логически канал + възел — подредени по брой */}
      <div className="panel">
        <div className="muted small" style={{ marginBottom: 6 }}>
          Последни 24 ч{facets ? ` · ${facets.total.toLocaleString('bg-BG')} пакета` : ''} —
          кликни за филтриране
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
          {(facets?.types ?? []).map((t) => {
            const m = typeMeta(t.type)
            const active = typeSel === t.type
            return (
              <button
                key={t.type}
                className={active ? 'chip active' : 'chip'}
                title={`тип ${t.type} — ${t.count} пакета`}
                onClick={() => setTypeSel(active ? null : t.type)}
              >
                <span>{m.icon}</span> {m.label} <b>{t.count.toLocaleString('bg-BG')}</b>
              </button>
            )
          })}
        </div>
        {/* канали/възли също като чипове (Status Chip стил, Т14) — най-активните
            8 видими, останалите в „още…“ (632 възела = чип за всеки е шум) */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginBottom: 6 }}>
          <span className="muted small">Канал:</span>
          {(facets?.channels ?? []).slice(0, 8).map((c) => {
            const active = channelSel === c.channel
            return (
              <button key={c.channel} className={active ? 'chip active' : 'chip'}
                      title={`канал ${c.channel} — ${c.count} пакета`}
                      onClick={() => setChannelSel(active ? null : c.channel)}>
                {c.channel} <b>{c.count.toLocaleString('bg-BG')}</b>
              </button>
            )
          })}
          {(facets?.channels?.length ?? 0) > 8 && (
            <select value="" aria-label="още канали"
                    onChange={(e) => setChannelSel(e.target.value || null)}>
              <option value="">още… ({(facets?.channels?.length ?? 0) - 8})</option>
              {(facets?.channels ?? []).slice(8).map((c) => (
                <option key={c.channel} value={c.channel}>{c.channel} ({c.count})</option>
              ))}
            </select>
          )}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
          <span className="muted small">Възел:</span>
          {(facets?.nodes ?? []).slice(0, 8).map((n) => {
            const active = nodeSel === n.node
            return (
              <button key={n.node} className={active ? 'chip active' : 'chip'}
                      title={`${n.node} — ${n.count} пакета`}
                      onClick={() => setNodeSel(active ? null : n.node)}>
                {nameOf(n.node).main} <b>{n.count.toLocaleString('bg-BG')}</b>
              </button>
            )
          })}
          {(facets?.nodes?.length ?? 0) > 8 && (
            <select value="" aria-label="още възли"
                    onChange={(e) => setNodeSel(e.target.value || null)}>
              <option value="">още… ({(facets?.nodes?.length ?? 0) - 8})</option>
              {(facets?.nodes ?? []).slice(8).map((n) => (
                <option key={n.node} value={n.node}>{nameOf(n.node).main} ({n.count})</option>
              ))}
            </select>
          )}
          {channelSel && (
            <button
              className="ghost"
              title="отвори Помощника за рутиране с този канал вече избран (аларма, копие в друг канал, препращане към брокер)"
              onClick={() => {
                sessionStorage.setItem(
                  'mg_route_family',
                  `msh/*/2/e/${channelSel}/*`,
                )
                location.href = '/?p=routing'
              }}
            >
              → Рутирай „{channelSel}“
            </button>
          )}
        </div>
      </div>

      <div className="panel">
        <Table<Packet>
          columns={COLUMNS}
          rows={rows}
          getKey={(p) => p.id}
          initialSort="ts"
          dense
          onRowClick={(p) => void openDetail(p)}
          empty={
            <div className="empty">
              Няма пакети{hasFilters ? ' за тези филтри' : ''}. Публикувай MQTT съобщение —
              ще се появи тук без презареждане.
            </div>
          }
        />
      </div>

      {detail && (
        <div className="modal-back" onClick={() => setDetail(null)}>
          <div className="modal card" onClick={(e) => e.stopPropagation()}>
            <h2 className="mono">{detail.topic}</h2>
            <p className="muted">{new Date(detail.ts).toLocaleString('bg-BG')} · {detail.decoder_id ?? 'без декодер'}</p>
            {detail.decode_error && <div className="error">{detail.decode_error}</div>}
            {delivery && delivery.sent && (
                <div style={{ marginBottom: 10 }}>
                  <span className={delivery.status === 'acked' ? 'tag ok' : delivery.status.startsWith('ack_error') ? 'tag bad' : 'tag'}
                        title={delivery.ack_by ? `ACK от ${delivery.ack_by} · ${delivery.ack_at ?? ''}` : 'качено в msh/ — чака ACK от мрежата'}>
                    📮 Доставка: {delivery.status.startsWith('ack_error') ? `грешка (${delivery.status.split(':')[1]})` : delivery.status === 'acked' ? 'потвърдено от мрежата' : 'качено — чака ACK'}
                    {delivery.ack_by ? ` · ${nameOf(delivery.ack_by).main}` : ''}
                  </span>
                </div>
              )}
            {detail.mesh?.packet_id != null && (
                <HeardPanel pid={detail.mesh.packet_id} />
              )}
            {detail.mesh && (
              <>
                <h3>Разпознати полета</h3>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
                  {detail.mesh.node_id && <span className="tag ch" title={nameOf(detail.mesh.node_id).tip}>{nameOf(detail.mesh.node_id).main}</span>}
                  {detail.mesh.text && <span className="tag ok">„{detail.mesh.text.slice(0, 60)}“</span>}
                  {detail.mesh.battery != null && <span className="tag">🔋 {Math.round(detail.mesh.battery)}%</span>}
                  {detail.mesh.lat != null && detail.mesh.lng != null && (
                    <span className="tag">📍 {detail.mesh.lat.toFixed(4)}, {detail.mesh.lng.toFixed(4)}</span>
                  )}
                  {detail.mesh.snr != null && <span className="tag">SNR {detail.mesh.snr} dB</span>}
                  {detail.mesh.rssi != null && <span className="tag">RSSI {detail.mesh.rssi}</span>}
                  {detail.mesh.neighbors?.map((nb) => (
                    <span key={nb.node} className="tag ch" title="чут съсед (NeighborInfo)">
                      🔗 {nameOf(nb.node).main} {nb.snr != null ? `${nb.snr} dB` : ''}
                    </span>
                  ))}
                  {detail.mesh.route && (
                    <span className="tag ch" title="маршрут от Routing/traceroute">
                      ➜ {detail.mesh.route.join(' → ')}
                    </span>
                  )}
                </div>
              </>
            )}
            {detail.topic.startsWith('deadletter/') && (
              <div style={{ marginBottom: 10, display: 'flex', gap: 8, alignItems: 'center' }}>
                <button
                  title="изпрати оригиналното съобщение наново към целта му"
                  onClick={async () => {
                    try {
                      const r = await api('/v1/routing/deadletter/resend', {
                        method: 'POST',
                        body: JSON.stringify({ packet_id: detail.id }),
                      })
                      alert(`Изпратено наново: ${r.topic} → ${r.target}`)
                    } catch (e: any) { alert('Неуспех: ' + e.message) }
                  }}
                >
                  ↻ Изпрати повторно
                </button>
                <span className="muted small">мъртва буква — оригиналът отива към целта си</span>
              </div>
            )}
            <h3>Decoded / Text</h3>
            <pre>{detail.payload_text ?? '—'}</pre>
            <h3>Hex (първите 512 байта)</h3>
            <pre className="hex">{detail.payload_hex?.slice(0, 1024) ?? '—'}</pre>
            <h3>Обработка (trace)</h3>
            {detail.trace.length === 0 ? (
              <p className="muted">Няма bridge решения за тази тема.</p>
            ) : (
              <table>
                <tbody>
                  {detail.trace.map((t, i) => (
                    <tr key={i}>
                      <td>{fmtTime(t.ts)}</td>
                      <td><span className={t.decision === 'forwarded' ? 'tag ok' : 'tag bad'}>{t.decision}</span></td>
                      <td>{t.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function HeardPanel({ pid }: { pid: number }) {
  const [data, setData] = useState<{ node: string; name?: string | null; copies: number; first_ts: string }[] | null>(null)
  useEffect(() => {
    let gone = false
    api<{ heard_by: { node: string; name?: string | null; copies: number; first_ts: string }[] }>(
      `/v1/packets/${pid}/heard`,
    ).then((r) => { if (!gone) setData(r.heard_by ?? []) })
     .catch(() => { if (!gone) setData([]) })
    return () => { gone = true }
  }, [pid])
  if (!data) return null
  return (
    <>
      <h3>Двете уши — кой чу ({data.length})</h3>
      {data.length === 0 ? (
        <div className="empty">Никой друг не е чуъл този пакет — ако очакваш повече приемници, провери средата/ретранслатора.</div>
      ) : (
        <div className="small" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
          {data.map((h) => (
            <span key={h.node} className={h.name ? 'tag ok' : 'tag'}
                  title={`${h.node} · ${h.copies} копия · първо ${new Date(h.first_ts).toLocaleTimeString('bg-BG')}`}>
              👂 {h.name ?? h.node} · {h.copies}пр.
            </span>
          ))}
        </div>
      )}
    </>
  )
}
