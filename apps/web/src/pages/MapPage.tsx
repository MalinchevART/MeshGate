import { useEffect, useMemo, useRef, useState } from 'react'
import { api, fmtTime } from '../api'
import { useNodeNames } from '../names'

type MapNode = {
  node: string
  lat: number
  lng: number
  position_ts: string
  channel: string | null
  battery: number | null
  packets: number
  last_seen: string
  short_name?: string | null
  long_name?: string | null
  id?: string | null
  routing_priority?: string
}

type TopoEdge = {
  from: string
  to: string
  snr_avg: number | null
  snr_max: number | null
  packets: number
  last: string
}

/** Канал → клас-индекс от палитрата в 4.11 DATA-VIZ (--chan-0…9);
 *  хешът е същият като преди — визуалният ред на каналите не се мени. */
function channelCls(ch: string | null): string {
  if (!ch) return 'mg-chan-none'
  let h = 0
  for (let i = 0; i < ch.length; i++) h = (h * 31 + ch.charCodeAt(i)) >>> 0
  return `mg-chan-${h % 10}`
}

/** години от последно виждане → свежест на точката */
function freshness(ts: string): number {
  const mins = (Date.now() - new Date(ts).getTime()) / 60000
  if (mins < 15) return 1
  if (mins < 60) return 0.75
  if (mins < 6 * 60) return 0.5
  return 0.3
}

/** SNR (dB) → тон на връзката (4.11; праговете идват ОТ SETTINGS през
 *  /v1/devices/map/thresholds — Т10: „праговете от settings", не тук);
 *  замыкание върху state-а на MapPage ( Hooks преди early returns) */
function snrTone(snr: number | null, thr: { good: number; fair: number }): string {
  if (snr == null) return 'none'
  if (snr >= thr.good) return 'good'
  if (snr >= thr.fair) return 'mid'
  return 'bad'
}

export default function MapPage() {
  const [nodes, setNodes] = useState<MapNode[] | null>(null)
  const [topo, setTopo] = useState<TopoEdge[]>([])
  const [showTopo, setShowTopo] = useState(true)
  const [sel, setSel] = useState<MapNode | null>(null)
  const [err, setErr] = useState<string | null>(null)
  // Т10: дуален режим — гео (реални координати) | схема (топология без GPS)
  const [mode, setMode] = useState<'geo' | 'schema'>('geo')
  // Т10: SNR праговете на легендата идват от settings (fallback: 4.11)
  const [thr, setThr] = useState({ good: -8, fair: -15 })
  useEffect(() => {
    api('/v1/devices/map/thresholds')
      .then((r: any) => setThr({ good: r.effective.good_db, fair: r.effective.fair_db }))
      .catch(() => {})
  }, [])
  // Т34: мъгла (клетъчна плътност) + Т35: плейбек и геозони
  const [fogOn, setFogOn] = useState(false)
  const [fog, setFog] = useState<{ step: number; cells: { lat: number; lng: number; n: number; last: string; nodes: number }[] } | null>(null)
  useEffect(() => {
    if (!fogOn) { setFog(null); return }
    api('/v1/devices/fog?hours=168')
      .then((r: any) => setFog(r))
      .catch(() => setFog(null))
  }, [fogOn])
  const [playOn, setPlayOn] = useState(false)
  const [positions, setPositions] = useState<{ node: string; lat: number; lng: number; ts: string }[] | null>(null)
  const [playIdx, setPlayIdx] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [zones, setZones] = useState<{ name: string; node: string; lat: number; lng: number; radius_m: number }[]>([])
  useEffect(() => {
    api('/v1/system/geofence').then((r: any) => setZones(r.zones ?? [])).catch(() => {})
  }, [])
  useEffect(() => {
    if (!playOn) { setPositions(null); setPlaying(false); return }
    let gone = false  // QA-1 F10
    api('/v1/devices/positions?hours=24')
      .then((r: any) => {
        if (gone) return
        setPositions(r.positions ?? [])
        setPlayIdx((r.positions ?? []).length ? (r.positions ?? []).length - 1 : 0)
      })
      .catch(() => { if (!gone) setPositions(null) })
    return () => { gone = true }
  }, [playOn])
  useEffect(() => {
    if (!playing || !positions || !positions.length) return
    const t = setInterval(() => {
      setPlayIdx((i) => Math.min(i + 1, positions.length - 1))
    }, 350)
    return () => clearInterval(t)
    // QA-1 F8: стопът е отделен ефект (updater-ите са чисти)
  }, [playing, positions])
  useEffect(() => {
    if (positions && positions.length && playIdx >= positions.length - 1) setPlaying(false)
  }, [playIdx, positions])
  const nameOf = useNodeNames()
  const [nodePriority, setNodePriority] = useState<string | null>(null)
  const [prBusy, setPrBusy] = useState(false)
  const [nodePriorityErr, setNodePriorityErr] = useState<string | null>(null)

  useEffect(() => {
    // селекцията сменя възела → синхронизирай приоритета от данните на възела
    setNodePriority(sel?.routing_priority ?? 'normal')
    setNodePriorityErr(null)
  }, [sel?.node])
  // възел без devices ред (phantom от NeighborInfo) няма id → без PATCH
  const canSetPriority = Boolean(sel?.id)
  const selRef = useRef(sel)
  selRef.current = sel
  useEffect(() => {
    const target = sel
    if (!target || !canSetPriority || nodePriority == null
        || nodePriority === (target.routing_priority ?? 'normal')) return
    setPrBusy(true)
    api(`/v1/devices/${target.id}/priority`, { method: 'POST', body: JSON.stringify({ routing_priority: nodePriority }) })
      .then(() => { if (selRef.current?.node === target.node) setNodePriorityErr(null) })
      .catch((e: any) => {
        // QA-1 F3: revert само ако потребителят е ОЩЕ на същия възел
        if (selRef.current?.node === target.node) {
          setNodePriorityErr(e.message)
          setNodePriority(target.routing_priority ?? 'normal')
        }
      })
      .finally(() => setPrBusy(false))
  }, [nodePriority])
  const [minPk, setMinPk] = useState(0)

  useEffect(() => {
    const load = () =>
      Promise.all([
        api('/v1/devices/map?hours=24'),
        api('/v1/devices/topology?hours=24'),
      ])
        .then(([m, t]: any[]) => {
          setNodes(m.nodes)
          setTopo(t.edges ?? [])
          setErr(null)  // QA-1 F1: transient грешка не убива страницата завинаги
        })
        .catch((e: any) => setErr(e.message))
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [])

  // ---- Т10 схематична топология: кръгово подреждане по свързаност -------
  // возлите от ребрата (+ тези без GPS позиция от данните), сортирани по
  // брой връзки — най-свързаните отгоре; детайлите търсим в nodes[].
  const schemaNodes = useMemo(() => {
    if (!nodes) return []
    const deg = new Map<string, number>()
    for (const e of topo) {
      deg.set(e.from, (deg.get(e.from) ?? 0) + 1)
      deg.set(e.to, (deg.get(e.to) ?? 0) + 1)
    }
    const ids = [...deg.entries()].sort((a, b) => b[1] - a[1]).map(([id]) => id)
    // същите геометрични константи като SVG канваса (самодостатъчни тук —
    // useMemo живее ПРЕДИ тях в рендер обхвата)
    const W = 900, H = 560, PAD = 40
    const cx = W / 2, cy = H / 2, rx = W / 2 - PAD - 30, ry = H / 2 - PAD - 10
    const out: { node: MapNode | null; id: string; degree: number; x: number; y: number }[] = []
    ids.forEach((id, i) => {
      const ang = (i / Math.max(1, ids.length)) * 2 * Math.PI - Math.PI / 2
      out.push({
        id,
        node: nodes.find((n) => n.node === id) ?? null,
        degree: deg.get(id) ?? 0,
        x: cx + rx * Math.cos(ang),
        y: cy + ry * Math.sin(ang),
      })
    })
    return out
  }, [topo, nodes])
  // ---- Т11 детайлен панел: табове Пакети/История/Съседи ------------------
  // hooks ПРЕДИ ранните return-и (урокът от Т10: React #310)
  const [tab, setTab] = useState<'neighbors' | 'packets' | 'history'>('neighbors')
  const [selPackets, setSelPackets] = useState<{ ts: string; topic: string; packet_type: string; decode_status: string }[] | null>(null)
  const [selPulse, setSelPulse] = useState<{ cells: ({ plain: number; encrypted: number; other: number; snr: number | null } | null)[] } | null>(null)
  // Т36 срез 2: история на преименуванията на избрания възел
  const [selNames, setSelNames] = useState<{ current: { long_name: string | null; short_name: string | null }; history: { long_name: string | null; short_name: string | null; valid_from: string; valid_to: string | null }[] } | null>(null)

  useEffect(() => {
    if (!sel) { setSelPackets(null); setSelPulse(null); setSelNames(null); return }
    setSelPackets(null); setSelPulse(null); setSelNames(null)  // QA-1 F4
    let gone = false
    const load = () => {
      api(`/v1/packets?node=${encodeURIComponent(sel.node)}&limit=15`)
        .then((r: any) => { if (!gone) setSelPackets(Array.isArray(r) ? r : r.items ?? []) })
        .catch(() => { if (!gone) setSelPackets([]) })
      api(`/v1/names/history?node=${encodeURIComponent(sel.node)}`)
        .then((r: any) => { if (!gone) setSelNames(r) })
        .catch(() => { if (!gone) setSelNames(null) })
      api(`/v1/devices/pulse?hours=24`)
        .then((r: any) => {
          if (gone) return
          const mine = (r.nodes ?? []).find((n: any) => String(n.node).toLowerCase() === sel.node.toLowerCase())
          // buckets са САМО непразните часове → 24 слота (null = мълчание);
          // слот = един и същи час ОТСТЪПВАЙКИ назад (24h прозорецът стига
          // до вчера — час-от-деня мачка вчерашните кофи: П3 Т11)
          const bySlot = new Map<string, any>()
          for (const b of (mine?.buckets ?? [])) bySlot.set(String(b.t).slice(0, 13), b)
          const top = new Date()
          top.setUTCMinutes(0, 0, 0)
          const cells = Array.from({ length: 24 }, (_, i) => {
            const d = new Date(top.getTime() - (23 - i) * 3600_000)
            return bySlot.get(d.toISOString().slice(0, 13)) ?? null
          })
          setSelPulse({ cells })
        })
        .catch(() => { if (!gone) setSelPulse({ cells: [] }) })
    }
    load()
    const t = setInterval(load, 30000)
    return () => { gone = true; clearInterval(t) }
  }, [sel?.node])

  // Т34: фантоми — възли, чути от други (NeighborInfo), но без собствена
  // позиция; честно се показват САМО в Схема режим (Т10), тук само бройка.
  // useMemo ПРЕДИ ранните return-и (React #310 — урокът от Т10, наранен от Т34!)
  const phantoms = useMemo(() => {
    const withPos = new Set((nodes ?? []).map((n) => n.node))
    const s = new Set<string>()
    for (const e of topo ?? []) {
      if (!withPos.has(e.from)) s.add(e.from)
      if (!withPos.has(e.to)) s.add(e.to)
    }
    return [...s]
  }, [nodes, topo])

  if (err) return <div className="error">{err}</div>
  if (!nodes) return <div className="center muted">Картата се зарежда…</div>

  const W = 900
  const H = 560
  const PAD = 40

  //among nodes with positions — bounds with padding; единична точка →
  // центрираме и даваме "зоум" около нея
  let minLat = Math.min(...nodes.map((n) => n.lat))
  let maxLat = Math.max(...nodes.map((n) => n.lat))
  let minLng = Math.min(...nodes.map((n) => n.lng))
  let maxLng = Math.max(...nodes.map((n) => n.lng))
  if (minLat === maxLat) { minLat -= 0.02; maxLat += 0.02 }
  if (minLng === maxLng) { minLng -= 0.03; maxLng += 0.03 }
  const x = (lng: number) =>
    PAD + ((lng - minLng) / (maxLng - minLng)) * (W - 2 * PAD)
  const y = (lat: number) =>
    H - PAD - ((lat - minLat) / (maxLat - minLat)) * (H - 2 * PAD)

  const pos = new Map(nodes.map((n) => [n.node, { x: x(n.lng), y: y(n.lat) }]))

  const schemaPos = new Map(schemaNodes.map((s) => [s.id, { x: s.x, y: s.y }]))
  const allPos = mode === 'geo' ? pos : schemaPos

  // филтър на ребрата по минимален брой пакети + stale маркер (>6 ч)
  const edges = topo.filter(
    (e) => allPos.has(e.from) && allPos.has(e.to) && e.packets >= minPk)
  const stale = (e: TopoEdge) =>
    Date.now() - new Date(e.last).getTime() > 6 * 3600_000
  const selEdges = sel
    ? edges.filter((e) => e.from === sel.node || e.to === sel.node)
    : []

  const channels = Array.from(
    new Set(nodes.map((n) => n.channel).filter(Boolean) as string[]))

  return (
    <>
      <div className="toolbar">
        <h2 style={{ flex: '0 0 auto', whiteSpace: 'nowrap' }}>Карта на възлите</h2>
        <div className="mg-map-mode" role="tablist" aria-label="Режим на картата">
          <button role="tab" aria-selected={mode === 'geo'}
            className={mode === 'geo' ? 'active' : ''}
            onClick={() => setMode('geo')}>Гео</button>
          <button role="tab" aria-selected={mode === 'schema'}
            className={mode === 'schema' ? 'active' : ''}
            onClick={() => setMode('schema')}>Схема</button>
        </div>
        <span className="muted small" style={{ minWidth: 0 }}>
          {mode === 'geo'
            ? `${nodes.length} възела с позиция (24 ч)`
            : `${schemaNodes.length} възела от NeighborInfo`} · 30 сек
        </span>
        {/* Т34/Т35: мъгла + плейбек (само в Гео режим) */}
        {mode === 'geo' && (
          <label className="small" style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
            <input type="checkbox" checked={fogOn} onChange={(ev) => setFogOn(ev.target.checked)} />
            мъгла
          </label>
        )}
        {mode === 'geo' && (
          <label className="small" style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
            <input type="checkbox" checked={playOn} onChange={(ev) => setPlayOn(ev.target.checked)} />
            плейбек 24 ч
          </label>
        )}
        {mode === 'geo' && playOn && positions && positions.length > 0 && (
          <span style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%' }}>
            <button className="nav-btn ghost" onClick={() => setPlaying(!playing)}>
              {playing ? '⏸' : '▶'}
            </button>
            <input type="range" min={0} max={positions.length - 1} value={Math.min(playIdx, positions.length - 1)}
                   style={{ flex: 1 }} aria-label="Време на плейбека"
                   onChange={(e) => { setPlaying(false); setPlayIdx(Number(e.target.value)) }} />
            <span className="mono small muted" style={{ minWidth: 150 }}>
              {new Date(positions[Math.min(playIdx, positions.length - 1)].ts).toLocaleString('bg-BG')}
            </span>
          </span>
        )}
        {topo.length > 0 && (
          <label className="small" style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 'auto', cursor: 'pointer' }}>
            <input type="checkbox" checked={showTopo}
              onChange={(ev) => setShowTopo(ev.target.checked)} />
            връзки ({edges.length})
            <select value={minPk} onChange={(e) => setMinPk(Number(e.target.value))}
              style={{ marginLeft: 4 }} aria-label="Минимум пакети по връзка">
              <option value={0}>всички</option>
              <option value={5}>≥5</option>
              <option value={20}>≥20</option>
            </select>
          </label>
        )}
      </div>

      {!nodes.length ? (
        <div className="panel">
          <div className="empty">
            Още няма декодирани позиции. Позиционните пакети идват от канали
            без шифроване (или с публичен ключ) — вкл. входящ мост, ако още
            няма. Демо емулаторът също публикува позиции.
          </div>
        </div>
      ) : (
        <>
          <div className="mg-map-layout">
          <div className="panel mg-map-main">
            {mode === 'schema' && (
              <div className="muted small" style={{ marginBottom: 6 }}>
                Схематична топология — позициите не са географски (подредени
                по свързаност); пунктираните линии са stale (над 6 ч).
              </div>
            )}
            {mode === 'schema' && schemaNodes.length === 0 ? (
              <div className="empty">
                Няма NeighborInfo данни за 24 ч — схематичната топология се пълни
                от пакети „съседи“ (NeighborInfo); криптираните канали не ги
                носят. Демо емулаторът ги публикува.
              </div>
            ) : (
            <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }}>
              {/* мрежа + етикети (само в гео режим) */}
              {mode === 'geo' && Array.from({ length: 5 }, (_, i) => {
                const lng = minLng + ((maxLng - minLng) * (i + 1)) / 6
                const lat = minLat + ((maxLat - minLat) * (i + 1)) / 6
                return (
                  <g key={i} className="mg-map-grid" strokeWidth="1">
                    <line x1={x(lng)} y1={PAD} x2={x(lng)} y2={H - PAD} />
                    <line x1={PAD} y1={y(lat)} x2={W - PAD} y2={y(lat)} />
                  </g>
                )
              })}
              {mode === 'geo' && (<>
                <text x={PAD} y={PAD - 10} className="mono mg-map-label" fontSize="10">
                  {minLat.toFixed(3)}°, {minLng.toFixed(3)}°
                </text>
                <text x={W - PAD} y={PAD - 10} textAnchor="end" className="mg-map-label" fontSize="10">
                  {maxLat.toFixed(3)}°, {maxLng.toFixed(3)}°
                </text>
              </>)}

              {/* Т34: мъгла — черен фон (никога не чувано) + осветени клетки */}
              {mode === 'geo' && fogOn && fog && fog.cells.length > 0 && (
                <g>
                  <rect x={0} y={0} width={W} height={H} className="mg-fog__base" />
                  {fog.cells.map((c, i) => {
                    const fresh = Date.now() - new Date(c.last).getTime() < 3600_000
                    const half = fog.step / 2
                    const x0 = x(c.lng - half), x1 = x(c.lng + half)
                    const y0 = y(c.lat + half), y1 = y(c.lat - half)
                    if (!isFinite(x0) || !isFinite(y0)) return null
                    return (
                      <rect key={i} x={x0} y={y0} width={Math.max(2, x1 - x0)} height={Math.max(2, y1 - y0)}
                            className={`mg-fog__cell ${fresh ? 'mg-fog__cell--live' : 'mg-fog__cell--memory'}`}
                            style={{ '--a': Math.min(1, 0.25 + Math.log2(1 + c.n) / 8) } as React.CSSProperties}>
                        <title>{`клетка ${c.lat}/${c.lng}: ${c.n} пакета · ${c.nodes} възела · последно ${new Date(c.last).toLocaleString('bg-BG')}`}</title>
                      </rect>
                    )
                  })}
                </g>
              )}

              {/* Т35: геозони (кръгове; радиусът в метри → градуси haversine-приблизително) */}
              {mode === 'geo' && zones.map((z, i) => {
                const dLat = z.radius_m / 111_320
                const dLng = z.radius_m / (111_320 * Math.max(0.2, Math.cos((z.lat * Math.PI) / 180)))
                const cx = x(z.lng), cy = y(z.lat)
                const rx = Math.abs(x(z.lng + dLng) - cx), ry = Math.abs(y(z.lat - dLat) - cy)
                if (!isFinite(cx) || !isFinite(cy) || !isFinite(rx)) return null
                return (
                  <g key={i}>
                    <ellipse cx={cx} cy={cy} rx={rx} ry={ry} className="mg-zone" />
                    <text x={cx} y={cy - ry - 4} textAnchor="middle" className="mg-map-label" fontSize="10">
                      ⛨ {z.name}{z.node !== '*' ? ` · ${nameOf(z.node).main}` : ''}
                    </text>
                  </g>
                )
              })}

              {/* топология: кой кого чува (NeighborInfo) — координатите от
                  АКТИВНИЯ режим (гео точки или схемна елипса; схемата може
                  да включва и възли без GPS, които в pos ги няма) */}
              {showTopo && edges.map((e) => {
                const a = allPos.get(e.from)!
                const b = allPos.get(e.to)!
                const tone = snrTone(e.snr_avg, thr)
                const hot = sel
                  ? e.from === sel.node || e.to === sel.node
                  : false
                return (
                  <line key={`${e.from}>${e.to}`}
                    x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                    className={`mg-edge mg-snr--${tone}${hot ? ' mg-edge--hot' : ''}${stale(e) ? ' mg-edge--stale' : ''}`}
                    opacity={sel ? (hot ? 0.95 : 0.15) : 0.55}
                    strokeLinecap="round">
                    <title>
                      {`${nameOf(e.from).main} → ${nameOf(e.to).main}  SNR ${e.snr_avg ?? '?'} dB (макс ${e.snr_max ?? '?'}) · ${e.packets} пакета · ${fmtTime(e.last)}`}
                    </title>
                  </line>
                )
              })}

              {/* Т35: при плейбек възелът стои на последната позиция <= T;
                  възел без позиция до момента Т е ЧЕСТНО скрит */}
              {mode === 'geo' && playOn && positions && positions.length > 0 && (() => {
                const tIso = positions[Math.min(playIdx, positions.length - 1)].ts
                const latest = new Map<string, any>()
                for (const p of positions) {
                  if (p.ts <= tIso) latest.set(p.node.toLowerCase(), p)
                }
                return nodes.map((n) => {
                  const pos = latest.get(n.node.toLowerCase())
                  if (!pos) return null
                  const cx = x(pos.lng), cy = y(pos.lat)
                  if (!isFinite(cx) || !isFinite(cy)) return null
                  return (
                    <g key={`pb-${n.node}`}>
                      <circle cx={cx} cy={cy} r={6} className="mg-play__dot">
                        <title>{`${nameOf(n.node).main} · ${new Date(pos.ts).toLocaleString('bg-BG')}`}</title>
                      </circle>
                      <text x={cx + 8} y={cy + 3} fontSize="10" className="mg-map-label">{nameOf(n.node).main}</text>
                    </g>
                  )
                })
              })()}
              {mode === 'geo' && (!playOn || !positions || positions.length === 0) ? nodes.map((n) => {
                const fresh = freshness(n.last_seen)
                const chanCls = channelCls(n.channel)
                const r = 4 + Math.min(6, Math.log10(n.packets + 1) * 2.5)
                const active = sel?.node === n.node
                return (
                  <g key={n.node} className={chanCls}
                    style={{ cursor: 'pointer' }}
                    onClick={() => setSel(active ? null : n)}>
                    <circle cx={x(n.lng)} cy={y(n.lat)} r={r + (active ? 5 : 3)}
                      className="mg-map-node__halo" />
                    <circle cx={x(n.lng)} cy={y(n.lat)} r={r}
                      className="mg-map-node" opacity={0.4 + 0.6 * fresh} />
                    {(active || n.packets > nodes[0].packets / 5) && (
                      <text x={x(n.lng) + r + 4} y={y(n.lat) + 3}
                        fontSize="10"
                        className={`mg-map-node-label${active ? '--active' : ''}`}>
                        {nameOf(n.node).main}
                      </text>
                    )}
                  </g>
                )
              }) : mode === 'schema' ? schemaNodes.map((s) => {
                const r = 4 + Math.min(6, s.degree * 0.9)
                const active = sel?.node === s.id
                return (
                  <g key={s.id} className={s.node ? channelCls(s.node.channel) : 'mg-chan-none'}
                    style={{ cursor: 'pointer' }}
                    onClick={() => s.node && setSel(active ? null : s.node)}>
                    <circle cx={s.x} cy={s.y} r={r + (active ? 5 : 3)}
                      className="mg-map-node__halo" />
                    <circle cx={s.x} cy={s.y} r={r} className="mg-map-node" />
                    <text x={s.x + r + 4} y={s.y + 3} fontSize="10"
                      className={`mg-map-node-label${active ? '--active' : ''}`}>
                      {nameOf(s.id).main}
                    </text>
                  </g>
                )
              }) : null}
            </svg>
            )}
          </div>

          {/* Т11: детайлен панел на възел — ДО картата (не я закрива на
              десктоп; под 1000px става плъзгащ се drawer) */}
          {sel && (
            <aside className="mg-drawer panel" aria-label="Детайли на възела">
              <div className="mg-drawer__head">
                <h3 style={{ margin: 0 }} title={nameOf(sel.node).tip}>
                  {nameOf(sel.node).main}
                  {nameOf(sel.node).sub && (
                    <span className="mono small" style={{ display: 'block', fontWeight: 400, color: 'var(--text-muted)' }}>
                      {nameOf(sel.node).sub}
                    </span>
                  )}
                </h3>
                <button className="nav-btn" aria-label="Затвори детайла"
                        onClick={() => setSel(null)}>✕</button>
              </div>
              <p className="small" style={{ margin: '6px 0' }}>
                канал <span className="tag ch">{sel.channel ?? '—'}</span>{' '}
                {sel.battery != null && <>· батерия <span className={sel.battery < 20 ? 'deny' : ''}>{Math.round(sel.battery)}%</span></>}{' '}
                · {sel.packets.toLocaleString('bg-BG')} пакета (24 ч)
              </p>
              <p className="muted small" style={{ margin: 0 }}>
                видян {fmtTime(sel.last_seen)}
                {mode === 'geo' && <> · {sel.lat.toFixed(4)}, {sel.lng.toFixed(4)}</>}
              </p>

              <div className="mg-tabs" role="tablist">
                {([['neighbors', `Съседи (${selEdges.length})`], ['packets', 'Пакети'], ['history', 'История']] as const).map(([id, label]) => (
                  <button key={id} role="tab" aria-selected={tab === id}
                          className={tab === id ? 'active' : ''}
                          onClick={() => setTab(id)}>{label}</button>
                ))}
              </div>

              {tab === 'neighbors' && (
                selEdges.length === 0 ? (
                  <div className="empty">Няма чути връзки за 24 ч (NeighborInfo).</div>
                ) : selEdges.map((e) => (
                  <div key={e.from + e.to} className="mg-drawer__row">
                    <span className={`small mg-snr--${snrTone(e.snr_avg, thr)}`}>
                      {e.from === sel.node ? '→ ' : '← '}
                      {nameOf(e.from === sel.node ? e.to : e.from).main}
                    </span>
                    <span className="muted small">
                      SNR {e.snr_avg ?? '?'} dB · {e.packets} пр. · {fmtTime(e.last)}
                    </span>
                  </div>
                ))
              )}

              {tab === 'packets' && (
                !selPackets ? (
                  <div className="empty">…</div>
                ) : selPackets.length === 0 ? (
                  <div className="empty">Няма записани пакети за 24 ч.</div>
                ) : (
                  <div className="table-scroll">
                    <table>
                      <tbody>
                        {selPackets.map((pk, i) => (
                          <tr key={i}>
                            <td className="mono small">{fmtTime(pk.ts)}</td>
                            <td className="small">{pk.packet_type.replace(/^meshtastic-/, '')}</td>
                            <td className={pk.decode_status === 'decoded' ? 'small' : 'small muted'}>
                              {pk.decode_status === 'decoded' ? '✓' : pk.decode_status}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )
              )}

              {tab === 'history' && (
                !selPulse ? (
                  <div className="empty">…</div>
                ) : (
                  <div className="small" style={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
                    {selPulse.cells.map((c, i) => {
                      const total = c ? c.plain + c.encrypted + c.other : 0
                      const pct = Math.round((0.45 + Math.min(0.55, Math.log10(total + 1) * 0.4)) * 100)
                      const cls = !c ? 'mg-pulse-cell mg-pulse-cell--silent'
                        : c.plain > 0 ? 'mg-pulse-cell mg-pulse-cell--clean'
                        : c.encrypted > 0 ? 'mg-pulse-cell mg-pulse-cell--encrypted'
                        : 'mg-pulse-cell mg-pulse-cell--service'
                      return <span key={i} className={cls}
                        style={c ? ({ '--a': pct } as React.CSSProperties) : undefined}
                        title={`кофа ${i}: ${c ? `${c.plain} чисти / ${c.encrypted} криптирани / ${c.other} служебни${c.snr != null ? ' · SNR ' + c.snr + ' dB' : ''}` : 'мълчи'}`} />
                    })}
                    <span className="muted small" style={{ marginLeft: 6 }}>24 ч по час</span>
                  </div>
                )
              )}
              {selNames && selNames.history.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <div className="small" style={{ marginBottom: 4 }}>Хронология на имената (Т36):</div>
                  <table>
                    <tbody>
                      {selNames.history.map((h, i) => (
                        <tr key={i}>
                          <td className="small">{h.long_name || h.short_name}</td>
                          <td className="muted small mono">
                            {new Date(h.valid_from).toLocaleDateString('bg-BG')} – {h.valid_to ? new Date(h.valid_to).toLocaleDateString('bg-BG') : '…'}
                          </td>
                        </tr>
                      ))}
                      {selNames.current.long_name && (
                        <tr>
                          <td className="small">{selNames.current.long_name}</td>
                          <td className="muted small mono">сега</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Т24: приоритетно рутиране на възела */}
              <div className="mg-drawer__reserved">
                <div className="small" style={{ marginBottom: 4 }}>Приоритет на възела:</div>
                {(['normal', 'urgent', 'critical', 'auto'] as const).map((pr) => (
                  <button key={pr}
                    className={`tag${(nodePriority ?? 'normal') === pr ? ' ok' : ''}`}
                    style={{ marginRight: 4, cursor: 'pointer', opacity: (nodePriority ?? 'normal') === pr ? 1 : 0.75 }}
                    disabled={prBusy || !canSetPriority}
                    title={pr === 'auto' ? 'приоритет, изведен от съдържанието (severity=critical)' :
                           pr === 'critical' ? 'критично — изпреварва всичко в изходящата опашка' :
                           pr === 'urgent' ? 'спешно — изпреварва нормалните' : 'обикновено'}
                    onClick={() => setNodePriority(pr)}>
                    {pr}
                  </button>
                ))}
                {!canSetPriority && <div className="muted small">възелът още няма запис — приоритетът се задава след първия му пакет</div>}
                {nodePriorityErr && <div className="deny small">{nodePriorityErr}</div>}
              </div>
            </aside>
          )}
          </div>

          <div className="cards">
            <div className="card" style={{ flex: 2 }}>
              <p className="muted small" style={{ margin: 0 }}>
                {phantoms.length > 0 && (
                  <span className="mg-fog-note">
                    👻 Фантоми без GPS: {phantoms.length} — виждат се честно само в{' '}
                    <b>Схема</b> режим ({phantoms.slice(0, 4).map((n) => nameOf(n).main).join(', ')}
                    {phantoms.length > 4 ? '…' : ''}).<br />
                  </span>
                )}
                Кликни върху възел за детайлен панел (съседи / пакети / история).
                Размерът = трафик, прозрачността = свежест, цветовете = канали,
                линиите = кой кого чува.
              </p>
            </div>
            <div className="card" style={{ flex: 1 }}>
              <h3 style={{ margin: '0 0 6px' }}>Канали</h3>
              {channels.slice(0, 10).map((c) => (
                <div key={c} className="small" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span className={`mg-chan-dot ${channelCls(c)}`} />
                  {c} ({nodes.filter((n) => n.channel === c).length})
                </div>
              ))}
              {edges.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <h3 style={{ margin: '0 0 6px' }}>Връзки по SNR</h3>
                  {([['good', `силна ≥ ${thr.good} dB`], ['mid', `средна ≥ ${thr.fair} dB`], ['bad', `слаба < ${thr.fair} dB`]]).map(([tone, label]) => (
                    <div key={label} className="small" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span className={`mg-snr-bar mg-snr--${tone}`} />
                      {label}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </>
  )
}
