import { useEffect, useState } from 'react'
import { api } from '../api'
import { OPS, normalizeDefinition, topicVerdict } from './RoutingRulesHelpers'
import type { Definition, Bridge, Sample, Rule } from './RoutingRulesHelpers'

/**
 * R3.2 — Интерактивен канвас на правилото (docs/11 §2).
 * Същият pipeline като R3.1 диаграмата, но всеки блок се избира и редактира
 * тук; компилира се до СЪЩИЯ RuleDefinition JSON (единствен източник на
 * истината остава API-то — wizard/Помощникът са бързият път).
 * Без нови зависимости: чист SVG + панел със свойства.
 */

type Sel =
  | { kind: 'src' }
  | { kind: 'topic' }
  | { kind: 'payload' }
  | { kind: 'transform' }
  | { kind: 'dst'; idx: number }

export default function RuleCanvas({ rule, bridges, samples, onDone }: {
  rule: Rule; bridges: Bridge[]; samples: Sample[]; onDone: () => void
}) {
  const [def, setDef] = useState<Definition>(() =>
    normalizeDefinition(rule.draft ?? rule.definition))
  const [sel, setSel] = useState<Sel>({ kind: 'src' })
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [testTopic, setTestTopic] = useState(samples[0]?.topic || 'mesh/test/up')
  const [testPayload, setTestPayload] = useState('')
  const [trace, setTrace] = useState<any[] | null>(null)

  const patch = (fn: (d: Definition) => void) => {
    setDef((prev) => {
      const d = JSON.parse(JSON.stringify(prev))
      fn(d)
      return normalizeDefinition(d)
    })
    setDirty(true)
  }

  const matching = samples.filter((s) => topicVerdict(def, s.topic).ok)

  async function dryRun() {
    setBusy(true); setErr(null); setTrace(null)
    try {
      const out = await api('/v1/routing/dry-run', {
        method: 'POST',
        body: JSON.stringify({
          definition: { ...def, enabled: true },
          topic: testTopic, payload: testPayload,
        }),
      })
      setTrace(out)
    } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }

  async function save(publish: boolean) {
    setBusy(true); setErr(null)
    try {
      await api(`/v1/routing/${rule.id}`, {
        method: 'PATCH', body: JSON.stringify({ definition: def }),
      })
      if (publish) {
        await api(`/v1/routing/${rule.id}/publish`, {
          method: 'POST', body: JSON.stringify({ note: 'от канваса' }),
        })
      }
      setDirty(false)
      if (publish) onDone()
    } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }

  // ---------- канвас блокове (като R3.1, но с id за избор) ----------

  const hasTopic = def.conditions.topic.include.length > 0 || def.conditions.topic.exclude.length > 0
  const hasPayload = def.conditions.payload.terms.length > 0
  const tr = def.transform
  const hasTransform = !!(tr.topic_template || Object.keys(tr.set_fields).length
    || tr.remove_fields.length || tr.add_envelope)

  const blocks: { id: Sel; title: string; lines: string[]; tone: 'src' | 'cond' | 'transform' | 'dst' }[] = []
  blocks.push({ id: { kind: 'src' }, title: '📡 Източник', lines: [def.source.topic_filter], tone: 'src' })
  if (hasTopic) {
    const inc = def.conditions.topic.include
    const exc = def.conditions.topic.exclude
    blocks.push({
      id: { kind: 'topic' }, title: '⚑ Тема', tone: 'cond',
      lines: [
        ...(inc.length ? [`include: ${inc[0]}${inc.length > 1 ? ` +${inc.length - 1}` : ''}`] : []),
        ...(exc.length ? [`exclude: ${exc[0]}${exc.length > 1 ? ` +${exc.length - 1}` : ''}`] : []),
      ],
    })
  }
  if (hasPayload) {
    blocks.push({
      id: { kind: 'payload' }, title: '🔎 Payload', tone: 'cond',
      lines: def.conditions.payload.terms.slice(0, 2).map((t: any) =>
        Array.isArray(t?.terms)
          ? `[група ${t.mode}: ${t.terms.length}]`
          : `${t.path.replace('$.', '')} ${t.op} ${t.value ?? ''}`),
    })
  }
  if (hasTransform) {
    blocks.push({
      id: { kind: 'transform' }, title: '⚙ Трансформация', tone: 'transform',
      lines: [
        ...(tr.topic_template ? [tr.topic_template] : []),
        ...(Object.keys(tr.set_fields).length ? [`+${Object.keys(tr.set_fields).length} поле(та)`] : []),
        ...(tr.add_envelope ? ['envelope'] : []),
        ...(tr.remove_fields.length ? [`−${tr.remove_fields.length}`] : []),
      ],
    })
  }
  def.destinations.forEach((d, i) => {
    if (d.type === "http") {
      blocks.push({
        id: { kind: "dst", idx: i },
        title: "🌐 HTTP POST",
        tone: "dst",
        lines: [d.url || "(без url)", "тялото = съобщението"],
      })
      return
    }
    const bid = d.target.startsWith("bridge:") ? d.target.slice(7) : null
    blocks.push({
      id: { kind: "dst", idx: i },
      title: bid ? `🌉 ${bridges.find((b) => b.id === bid)?.name || "Мост"}` : "🎯 Локален",
      tone: "dst",
      lines: [d.topic_template, `qos ${d.qos}${d.retain ? " · retain" : ""}`],
    })
  })

  const isSel = (id: Sel) =>
    id.kind === sel.kind && (id.kind !== 'dst' || (sel as any).idx === id.idx)

  const W = 170, H = 96, GAP = 34
  const width = blocks.length * W + (blocks.length - 1) * GAP

  return (
    <>
      <div className="toolbar">
        <h2>🎨 Канвас: {def.name}</h2>
        <span className="muted small">
          {dirty ? 'незапазени промени' : rule.draft ? 'чернова' : `v${rule.current_version}`} —
          кликни блок, за да го редактираш
        </span>
        <span style={{ flex: 1 }} />
        <button className="ghost-btn" onClick={onDone}>← Към правилата</button>
      </div>
      {err && <div className="error">{err}</div>}

      <div className="panel" style={{ overflowX: 'auto' }}>
        <svg viewBox={`0 0 ${Math.max(width, 400)} ${H}`}
          style={{ width: '100%', maxWidth: width * 1.6, height: 'auto', minHeight: 90, display: 'block' }}>
          {blocks.map((b, i) => {
            const x = i * (W + GAP)
            const on = isSel(b.id)
            return (
              <g key={i} className={`mg-flow mg-kind-${b.tone}`} style={{ cursor: 'pointer' }} onClick={() => setSel(b.id)}>
                <rect x={x} y={4} width={W} height={H - 8} rx={9} className="mg-flow-box-rect"
                  strokeWidth={on ? 2.5 : 1.5}
                  strokeDasharray={on ? '6 3' : undefined} />
                <text x={x + 11} y={25} fontSize={11} fontWeight={600} className="mg-flow-title">{b.title}</text>
                {b.lines.slice(0, 4).map((l, j) => (
                  <text key={j} x={x + 11} y={44 + j * 14} fontSize={10} className="mg-flow-text">
                    {l.length > 24 ? l.slice(0, 23) + '…' : l}
                  </text>
                ))}
                {i < blocks.length - 1 && (
                  <>
                    <line x1={x + W} y1={H / 2} x2={x + W + GAP - 9} y2={H / 2}
                      strokeWidth={1.5} className="mg-flow-link-line" />
                    <polygon
                      points={`${x + W + GAP - 9},${H / 2 - 4} ${x + W + GAP - 9},${H / 2 + 4} ${x + W + GAP - 2},${H / 2}`}
                      className="mg-flow-link-arrow" />
                  </>
                )}
              </g>
            )
          })}
        </svg>

        {/* палитра: добави блок */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
          {!hasTopic && (
            <button className="ghost-btn" onClick={() => patch((d) => {
              d.conditions.topic.include.push('msh/+/2/e/+/+')
            })}>+ ⚑ Тема</button>
          )}
          {!hasPayload && (
            <button className="ghost-btn" onClick={() => patch((d) => {
              d.conditions.payload.terms.push({ path: '$.battery', op: 'exists', value: null })
            })}>+ 🔎 Payload</button>
          )}
          {!hasTransform && (
            <button className="ghost-btn" onClick={() => patch((d) => {
              d.transform.topic_template = '{topic}'
            })}>+ ⚙ Трансформация</button>
          )}
          <button className="ghost-btn" onClick={() => patch((d) => {
            d.destinations.push({ type: "mqtt", target: "local", topic_template: "{topic}", qos: 0, retain: false })
          })}>+ 🎯 Дестинация (локален)</button>
          <button className="ghost-btn" onClick={() => patch((d) => {
            d.destinations.push({ type: "http", target: "http", topic_template: "{topic}", qos: 0, retain: false, url: "https://" })
          })}>+ 🌐 HTTP POST (n8n/ntfy)</button>
          {bridges.map((b) => (
            <button key={b.id} className="ghost-btn" onClick={() => patch((d) => {
              d.destinations.push({ type: 'mqtt', target: `bridge:${b.id}`, topic_template: '{topic}', qos: 0, retain: false })
            })}>+ 🌉 {b.name}</button>
          ))}
        </div>
      </div>

      {/* поведение при грешка в дестинация (R2: retry/halt/dead-letter) */}
      <div className="panel">
        <h3>Грешки при доставка</h3>
        <div className="form-grid" style={{ gridTemplateColumns: '2fr 1fr 1fr auto' }}>
          <label>При провалена дестинация
            <select value={def.error_policy.on_destination_failure}
              onChange={(e) => patch((d) => { d.error_policy.on_destination_failure = e.target.value })}>
              <option value="continue">continue — продължи другите</option>
              <option value="halt">halt — спри следващите</option>
            </select>
          </label>
          <label>Retry опита
            <input type="number" min={0} max={10} value={def.error_policy.retry.max}
              onChange={(e) => patch((d) => { d.error_policy.retry.max = Math.max(0, Math.min(10, +e.target.value || 0)) })} />
          </label>
          <label>Пауза (ms)
            <input type="number" min={100} max={60000} step={100} value={def.error_policy.retry.backoff_ms}
              onChange={(e) => patch((d) => { d.error_policy.retry.backoff_ms = Math.max(100, Math.min(60000, +e.target.value || 1000)) })} />
          </label>
          <label style={{ alignSelf: 'end' }}>
            <input type="checkbox" checked={def.error_policy.dead_letter}
              onChange={(e) => patch((d) => { d.error_policy.dead_letter = e.target.checked })} />{' '}
            dead-letter
          </label>
        </div>
        <p className="muted small">
          При изчерпани retry-та съобщението отива в <code>deadletter/{def.name}</code> (retain) —
          вижда се в Packet Explorer и може да се изпрати повторно от детайла му.
        </p>
      </div>

      {/* свойства на избрания блок */}
      <div className="panel">
        <h3>Свойства на блока</h3>
        {sel.kind === 'src' && (
          <div className="form-grid">
            <label>Абонамент (topic_filter)
              <input className="mono" value={def.source.topic_filter}
                onChange={(e) => patch((d) => { d.source.topic_filter = e.target.value || '#' })} />
            </label>
          </div>
        )}
        {sel.kind === 'topic' && (
          <div className="form-grid">
            <label>Include (по един на ред; + и #)
              <textarea rows={3} className="mono" value={def.conditions.topic.include.join('\n')}
                onChange={(e) => patch((d) => {
                  d.conditions.topic.include = e.target.value.split('\n').map((x) => x.trim()).filter(Boolean)
                })} />
            </label>
            <label>Exclude (имат приоритет)
              <textarea rows={3} className="mono" value={def.conditions.topic.exclude.join('\n')}
                onChange={(e) => patch((d) => {
                  d.conditions.topic.exclude = e.target.value.split('\n').map((x) => x.trim()).filter(Boolean)
                })} />
            </label>
          </div>
        )}
        {sel.kind === 'payload' && (
          <>
            <div className="form-grid">
              <label>Логика
                <select value={def.conditions.payload.mode}
                  onChange={(e) => patch((d) => { d.conditions.payload.mode = e.target.value })}>
                  <option value="all">all — всички условия</option>
                  <option value="any">any — поне едно</option>
                </select>
              </label>
            </div>
            {def.conditions.payload.terms.map((t: any, i) => Array.isArray(t?.terms) ? (
              <div key={i} className="form-grid" style={{ gridTemplateColumns: '1fr' }}>
                <span className="muted small">[група {t.mode}: {t.terms.length} елемента — редакция в Wizard-а]</span>
              </div>
            ) : (
              <div key={i} className="form-grid" style={{ gridTemplateColumns: '2fr 1fr 2fr auto' }}>
                <input className="mono" placeholder="$.battery" value={(t as any).path}
                  onChange={(e) => patch((d) => { (d.conditions.payload.terms[i] as any).path = e.target.value })} />
                <select value={(t as any).op}
                  onChange={(e) => patch((d) => { (d.conditions.payload.terms[i] as any).op = e.target.value })}>
                  {OPS.map((o) => <option key={o}>{o}</option>)}
                </select>
                <input className="mono" placeholder="20" value={typeof (t as any).value === 'object' ? JSON.stringify((t as any).value) : String((t as any).value ?? '')}
                  onChange={(e) => {
                    const raw = e.target.value
                    let val: any = raw
                    if (raw !== '' && !isNaN(+raw)) val = +raw
                    patch((d) => { (d.conditions.payload.terms[i] as any).value = val })
                  }} />
                <button className="ghost-btn"
                  onClick={() => patch((d) => { d.conditions.payload.terms.splice(i, 1) })}>✕</button>
              </div>
            ))}
            <button className="ghost-btn" onClick={() => patch((d) => {
              d.conditions.payload.terms.push({ path: '$.', op: 'exists', value: null })
            })}>+ условие</button>
            <p className="muted small">Работи върху JSON payload ($.поле); шифровани/бинарни съобщения не минават.</p>
          </>
        )}
        {sel.kind === 'transform' && (
          <>
            <div className="form-grid">
              <label>Нова тема (шаблон)
                <input className="mono" placeholder="alerts/battery/{payload.node} — празно = без промяна"
                  value={def.transform.topic_template || ''}
                  onChange={(e) => patch((d) => { d.transform.topic_template = e.target.value || null })} />
              </label>
            </div>
            {Object.entries(def.transform.set_fields).map(([k, v]) => (
              <div key={k} className="form-grid" style={{ gridTemplateColumns: '1fr 2fr auto' }}>
                <input className="mono" value={k} onChange={(e) => patch((d) => {
                  delete d.transform.set_fields[k]
                  d.transform.set_fields[e.target.value] = v
                })} />
                <input className="mono" value={typeof v === 'object' ? JSON.stringify(v) : String(v)}
                  onChange={(e) => {
                    let val: any = e.target.value
                    try { val = JSON.parse(e.target.value) } catch { /* текст */ }
                    patch((d) => { d.transform.set_fields[k] = val })
                  }} />
                <button className="ghost-btn" onClick={() => patch((d) => { delete d.transform.set_fields[k] })}>✕</button>
              </div>
            ))}
            <button className="ghost-btn" onClick={() => patch((d) => { d.transform.set_fields['ново_поле'] = 'стойност' })}>+ поле</button>
            <p className="muted small">
              Шаблони: {'{topic}'} · {'{topic_tokens[2]}'} · {'{payload.node}'} — и махни блока с празна тема + без полета.
            </p>
          </>
        )}
        {sel.kind === 'dst' && (
          <>
            {def.destinations[sel.idx].type === 'http' ? (
              <div className="form-grid" style={{ gridTemplateColumns: '3fr auto' }}>
                <label>URL (POST)
                  <input className="mono" placeholder="https://ntfy.sh/my-topic"
                    value={def.destinations[sel.idx].url || ''}
                    onChange={(e) => patch((d) => { d.destinations[sel.idx].url = e.target.value })} />
                </label>
                {def.destinations.length > 1 && (
                  <button className="ghost-btn" title="премахни дестинацията"
                    onClick={() => { patch((d) => { d.destinations.splice(sel.idx, 1) }); setSel({ kind: 'src' }) }}>✕</button>
                )}
              </div>
            ) : (
              <>
                <div className="form-grid" style={{ gridTemplateColumns: '2fr 2fr auto auto auto' }}>
                  <select value={def.destinations[sel.idx].target}
                    onChange={(e) => patch((d) => { d.destinations[sel.idx].target = e.target.value })}>
                    <option value="local">локален брокер</option>
                    {bridges.map((b) => (
                      <option key={b.id} value={`bridge:${b.id}`}>bridge: {b.name}{b.enabled ? '' : ' (изключен!)'}</option>
                    ))}
                  </select>
                  <input className="mono" value={def.destinations[sel.idx].topic_template}
                    onChange={(e) => patch((d) => { d.destinations[sel.idx].topic_template = e.target.value })} />
                  <select value={def.destinations[sel.idx].qos}
                    onChange={(e) => patch((d) => { d.destinations[sel.idx].qos = +e.target.value })}>
                    <option value={0}>QoS 0</option><option value={1}>QoS 1</option><option value={2}>QoS 2</option>
                  </select>
                  <label className="small">
                    <input type="checkbox" checked={def.destinations[sel.idx].retain}
                      onChange={(e) => patch((d) => { d.destinations[sel.idx].retain = e.target.checked })} /> retain
                  </label>
                  {def.destinations.length > 1 && (
                    <button className="ghost-btn" title="премахни дестинацията"
                      onClick={() => { patch((d) => { d.destinations.splice(sel.idx, 1) }); setSel({ kind: 'src' }) }}>✕</button>
                  )}
                </div>
                <p className="muted small">Целева тема е шаблон: {'{topic}'} остава същата, {'{topic_suffix[3]}'} е частта след N-тия токен.</p>
              </>
            )}
          </>
        )}
      </div>

      {/* тест панел (dry-run) */}
      <div className="panel">
        <h3>Тест с реално съобщение (dry-run — нищо не се изпраща)</h3>
        <div className="form-grid">
          <label>Тема
            <input className="mono" value={testTopic} onChange={(e) => setTestTopic(e.target.value)} />
          </label>
          <label>Payload (JSON)
            <textarea rows={3} className="mono" value={testPayload} onChange={(e) => setTestPayload(e.target.value)} />
          </label>
        </div>
        {matching.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '6px 0' }}>
            {matching.slice(0, 8).map((s, i) => (
              <button key={i} className="tag mono"
                onClick={() => { setTestTopic(s.topic); setTestPayload(s.payload) }}>
                {s.topic}
              </button>
            ))}
          </div>
        )}
        <button onClick={dryRun} disabled={busy}>{busy ? '…' : '▶ Dry-run'}</button>
        {trace && trace.map((t: any, i: number) => (
          <div key={i} className="ok-box" style={{ marginTop: 10 }}>
            <strong className={t.decision === 'match_forward' ? '' : 'deny'}>{t.decision}</strong>{' '}
            <span className="mono small">{t.input_topic}</span>
            {t.error && <div className="deny small">{t.error}</div>}
            <div className="small">
              {t.steps?.map((s: any, j: number) => <div key={j}>· {s.step}</div>)}
            </div>
            {t.outputs?.map((o: any, j: number) => (
              <div key={j} className="mono small" style={{ marginTop: 4 }}>
                → {o.target} : {o.topic} (qos {o.qos}{o.retain ? ', retain' : ''})
              </div>
            ))}
          </div>
        ))}
      </div>

      <div className="toolbar">
        <button disabled={busy || !dirty} onClick={() => save(false)}>Запази чернова</button>{' '}
        <button disabled={busy} onClick={() => save(true)}>Публикувай версия</button>{' '}
        <span className="muted small">редакцията отива в чернова; влиза в сила с публикуване</span>
      </div>
    </>
  )
}
