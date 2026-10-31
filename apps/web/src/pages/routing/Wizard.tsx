import { Component, useEffect, useState } from 'react'
import { api, fmtTime } from '../../api'
import type { Me } from '../../App'
import Helper from '../Helper'
import RuleCanvas from '../RuleCanvas'
import TopicTokens, { TopicLegend } from '../TopicTokens'
import {
  OPS, normalizeDefinition, topicVerdict, suggestPattern, payloadPaths, familyOf,
} from '../RoutingRulesHelpers'
import type { Definition, Rule, Template, Bridge, Sample } from '../RoutingRulesHelpers'


/** Т19: Wizard (5-стъпковия редактор) + WizBoundary — извлечени 1:1 от
 *  RoutingRules.tsx; нула функционална промяна. */
const STEPS = ['Източник и тема', 'Payload условия', 'Трансформация', 'Дестинации', 'Тест & публикуване']

/** Никакъв черен екран: грешка в редактора се показва с изход, без фатален край. */
export class WizBoundary extends Component<{ onExit: () => void; children: React.ReactNode }, { err: string | null }> {
  state = { err: null as string | null }
  static getDerivedStateFromError(e: any) { return { err: String(e?.message || e) } }
  render() {
    if (this.state.err) {
      return (
        <div className="panel">
          <div className="error">
            Редакторът срещна грешка: {this.state.err}. Данните не са записани — опитай отново
            или избери друг шаблон.
          </div>
          <button className="ghost-btn" onClick={this.props.onExit}>Назад към списъка</button>
        </div>
      )
    }
    return this.props.children
  }
}

export default function Wizard({ wiz, setWiz, patchDef, bridges, recent, samples, isAdmin, onDone }: {
  wiz: { ruleId: string | null; step: number; def: Definition }
  setWiz: any; patchDef: any; bridges: Bridge[]; recent: { topic: string; count: number }[]
  samples: Sample[]; isAdmin: boolean; onDone: () => void
}) {
  const { def } = wiz
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [testTopic, setTestTopic] = useState(recent[0]?.topic || 'mesh/test/up')
  const [testPayload, setTestPayload] = useState('')
  const [trace, setTrace] = useState<any[] | null>(null)
  const [testTab, setTestTab] = useState<'trace' | 'preview' | 'validation'>('trace')
  const [validation, setValidation] = useState<{ errors: string[]; warnings: string[] } | null>(null)
  const canNext = def.name.trim().length >= 2 && def.conditions.topic.include.length > 0

  // Meshtastic семейства от живия трафик + добавяне на семантични шаблони
  const mshFamilies = (() => {
    const m = new Map<string, { count: number; region: string; channel: string; nodes: string[] }>()
    for (const r of recent) {
      if (!r.topic.startsWith('msh/')) continue
      const f = familyOf(r.topic)
      const toks = f.split('/')
      const chIdx = toks.findIndex((t) => t === 'e' || t === 'c' || t === 'json')
      if (chIdx < 0) continue
      const region = toks[1]
      const channel = toks[chIdx + 1] || '?'
      const node = r.topic.split('/').find((t) => t.startsWith('!'))
      const cur = m.get(f) || { count: 0, region, channel, nodes: [] as string[] }
      cur.count += r.count
      if (node && !cur.nodes.includes(node)) cur.nodes.push(node)
      m.set(f, cur)
    }
    return [...m.entries()].map(([pattern, v]) => ({ pattern, ...v })).sort((a, b) => b.count - a.count)
  })()

  function addInclude(pattern: string) {
    patchDef((d: any) => {
      if (!d.conditions.topic.include.includes(pattern)) d.conditions.topic.include.push(pattern)
    })
  }

  // реални съобщения, които минават през текущите филтри — за тест и подсказки
  const matching = samples.filter((s) => topicVerdict(def, s.topic).ok)
  const sampleDoc = (() => {
    for (const s of matching) {
      try { const d = JSON.parse(s.payload); if (d && typeof d === 'object') return d } catch { /* не JSON */ }
    }
    return null
  })()

  // при влизане в стъпка 5: ако тестовата тема не минава вече през филтрите,
  // подставяме реално съобщение (автоматизация — тест с истински данни)
  useEffect(() => {
    if (wiz.step === 5 && !topicVerdict(def, testTopic).ok && matching.length) {
      setTestTopic(matching[0].topic)
      setTestPayload(matching[0].payload)
    }
  }, [wiz.step])

  async function dryRun() {
    setBusy(true); setErr(null); setTrace(null)
    try {
      const out = await api('/v1/routing/dry-run', {
        method: 'POST',
        body: JSON.stringify({ definition: { ...def, enabled: true }, topic: testTopic, payload: testPayload }),
      })
      setTrace(out)
    } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }

  // Т21: валидация с човешки грешки (празни дестинации, липсващ мост, цикъл)
  async function runValidation() {
    setBusy(true); setErr(null); setValidation(null)
    try {
      const r = await api('/v1/routing/validate', {
        method: 'POST',
        body: JSON.stringify({ definition: { ...def, enabled: true }, topic: testTopic, payload: testPayload }),
      })
      setValidation(r)
    } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }

  async function save(publish: boolean) {
    setBusy(true); setErr(null)
    try {
      // Т21: валидация при save — блокер спира записа
      const v = await api('/v1/routing/validate', {
        method: 'POST',
        body: JSON.stringify({ definition: { ...def, enabled: true }, topic: testTopic, payload: testPayload }),
      })
      if (v.errors?.length) {
        setErr('Не може да се запише: ' + v.errors.join(' | '))
        setBusy(false)
        return
      }
      if (wiz.ruleId) {
        await api(`/v1/routing/${wiz.ruleId}`, { method: 'PATCH', body: JSON.stringify({ definition: def }) })
        if (publish) await api(`/v1/routing/${wiz.ruleId}/publish`, { method: 'POST', body: JSON.stringify({ note: 'от wizard' }) })
      } else {
        const created = await api('/v1/routing', { method: 'POST', body: JSON.stringify({ definition: def }) })
        if (publish) await api(`/v1/routing/${created.id}/publish`, { method: 'POST', body: JSON.stringify({ note: 'първо публикуване' }) })
      }
      onDone()
    } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }

  const setF = (fn: (d: Definition) => void) => patchDef(fn)
  const goStep = (n: number) => setWiz({ ...wiz, step: n })

  return (
    <>
      <div className="toolbar">
        <h2>{wiz.ruleId ? `Редакция: ${def.name}` : 'Създаване на правило'}</h2>
        <span className="muted small">
          стъпка {wiz.step}/5 — {STEPS[wiz.step - 1]}
        </span>
        <span style={{ flex: 1 }} />
        <button className="ghost-btn" onClick={onDone}>Отказ</button>
      </div>
      {err && <div className="error">{err}</div>}

      <div style={{ display: 'flex', gap: 6, margin: '10px 0' }}>
        {STEPS.map((s, i) => (
          <button key={s} className={wiz.step === i + 1 ? 'tag ok' : 'tag'}
            onClick={() => goStep(i + 1)}>{i + 1}. {s}</button>
        ))}
      </div>

      <div className="panel">
        {wiz.step === 1 && (
          <>
            <div className="form-grid">
              <label>Име <input value={def.name} onChange={(e) => setF((d) => { d.name = e.target.value })} /></label>
              <label>Описание <input value={def.description || ''} onChange={(e) => setF((d) => { d.description = e.target.value })} /></label>
              <label>Приоритет (по-малко = по-рано) <input type="number" value={def.priority}
                onChange={(e) => setF((d) => { d.priority = +e.target.value || 100 })} /></label>
              <label>Режим
                <select value={def.execution_mode} onChange={(e) => setF((d) => { d.execution_mode = e.target.value })}>
                  <option value="first_match">first_match — спи след първо съвпадение</option>
                  <option value="all_match">all_match — прилага всички правила</option>
                </select>
              </label>
            </div>
            <div className="form-grid">
              <label>Include шаблони (по един на ред; + и #)
                <textarea rows={3} className="mono" value={def.conditions.topic.include.join('\n')}
                  onChange={(e) => setF((d) => { d.conditions.topic.include = e.target.value.split('\n').map((x) => x.trim()).filter(Boolean) })} />
              </label>
              <label>Exclude шаблони (имат приоритет)
                <textarea rows={3} className="mono" value={def.conditions.topic.exclude.join('\n')}
                  onChange={(e) => setF((d) => { d.conditions.topic.exclude = e.target.value.split('\n').map((x) => x.trim()).filter(Boolean) })} />
              </label>
            </div>
            {mshFamilies.length > 0 && (
              <div style={{ border: '1px solid var(--line)', borderRadius: 8, padding: 12, marginTop: 12 }}>
                <h3 style={{ margin: '0 0 6px' }}>🛰 Meshtastic селектор — мачни по регион / канал / устройство</h3>
                <TopicLegend />
                <div style={{ marginTop: 8 }}>
                  {mshFamilies.map((f) => (
                    <div key={f.pattern} style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '6px 0', flexWrap: 'wrap', borderBottom: '1px solid var(--line)' }}>
                      <TopicTokens value={f.pattern.replace(/\*/g, '+')} />
                      <span className="muted small">{f.count.toLocaleString('bg-BG')} съобщения</span>
                      <span style={{ flex: 1 }} />
                      <button className="ghost-btn small" title={`всички канали в регион ${f.region}`}
                        onClick={() => addInclude(`msh/${f.region}/#`)}>по регион</button>
                      <button className="ghost-btn small" title={`каналът ${f.channel} в който и да е регион`}
                        onClick={() => addInclude(`msh/+/2/e/${f.channel}/#`)}>по канал</button>
                      {f.nodes[0] && (
                        <select className="small" title="конкретно устройство"
                          onChange={(e) => e.target.value && addInclude(`msh/+/2/e/+/${e.target.value}`)}
                          value="">
                          <option value="">по устройство…</option>
                          {f.nodes.map((n) => <option key={n} value={n}>{n}</option>)}
                        </select>
                      )}
                    </div>
                  ))}
                </div>
                <p className="muted small" style={{ margin: '6px 0 0' }}>
                  ⚠ През обществен брокер съобщенията често са шифровани (бинарни) — тогава
                  условия по payload няма как да сработят; хващай по регион/канал/устройство (по тема).
                </p>
              </div>
            )}
            <h3>Проверка срещу реалните теми — ⇢ добавя тема като шаблон</h3>
            <div className="small" style={{ maxHeight: 180, overflowY: 'auto' }}>
              {!recent.length && <div className="empty">Няма трафик — проверката срещу живи теми ще се появи, щом потекат съобщения.</div>}
              {recent.map((r) => {
                const v = topicVerdict(def, r.topic)
                const sug = suggestPattern(r.topic)
                const added = def.conditions.topic.include.includes(sug)
                return (
                  <div key={r.topic} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <span className={v.ok ? 'tag ok' : 'tag'}>{v.ok ? '✓' : '✗'}</span>
                    <span className="mono">{r.topic}</span>
                    <span className="muted small">{v.why}</span>
                    <span style={{ flex: 1 }} />
                    {!added && (
                      <button className="ghost-btn small" title={`добави ${sug} в include`}
                        onClick={() => setF((d) => { d.conditions.topic.include.push(sug) })}>
                        ⇢ {sug}
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          </>
        )}

        {wiz.step === 2 && (
          <>
            <div className="form-grid">
              <label>Логика
                <select title="при непарсебъл payload (не-JSON): пропускай условието или пасвай по тема"
                        value={def.conditions.payload.on_unparseable ?? 'no_match'}
                        onChange={(e) => setF((d) => { d.conditions.payload.on_unparseable = e.target.value })}>
                  <option value="no_match">не-JSON: не пасва</option>
                  <option value="match">не-JSON: пасва (по тема)</option>
                </select>
                <select value={def.conditions.payload.mode} onChange={(e) => setF((d) => { d.conditions.payload.mode = e.target.value })}>
                  <option value="all">all — всички условия</option>
                  <option value="any">any — поне едно</option>
                </select>
              </label>
            </div>
            {def.conditions.payload.terms.map((t: any, i: number) => (
              <TermNode key={i} node={t} depth={0} onChange={(n: any) => setF((d) => { d.conditions.payload.terms[i] = n })}
                        onRemove={() => setF((d) => { d.conditions.payload.terms.splice(i, 1) })} />
            ))}
            <button className="ghost-btn" onClick={() => setF((d) => { d.conditions.payload.terms.push({ path: '$.', op: 'exists', value: null }) })}>
              + условие
            </button>
            {sampleDoc && (
              <>
                <h3>Полетата на реално съобщение, което минава през филтъра — клик добавя условие</h3>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {payloadPaths(sampleDoc).slice(0, 14).map((p) => {
                    const val = p.split('.').slice(1).reduce((acc: any, seg) => {
                      const m = seg.match(/^(.*)\[0\]$/)
                      return m ? (acc?.[m[1]]?.[0] ?? acc?.[m[1]]) : acc?.[seg]
                    }, sampleDoc)
                    return (
                      <button key={p} className="tag mono" title={`стойност сега: ${JSON.stringify(val)}`}
                        onClick={() => setF((d) => { d.conditions.payload.terms.push({ path: p, op: 'exists', value: null }) })}>
                        {p}
                      </button>
                    )
                  })}
                </div>
                <pre className="mono small" style={{ opacity: 0.7, maxHeight: 120, overflow: 'auto' }}>
                  {JSON.stringify(sampleDoc, null, 1)}
                </pre>
              </>
            )}
            <p className="muted small">Работи върху JSON payload ($.поле.поле, $.масив[0]); текстови/бинарни съобщения не минават през тези условия.</p>
          </>
        )}

        {wiz.step === 3 && (
          <>
            <div className="form-grid">
              <label>Нова тема (шаблон)
                <input className="mono" placeholder="alerts/battery/{payload.node} — празно = без промяна"
                  value={def.transform.topic_template || ''}
                  onChange={(e) => setF((d) => { d.transform.topic_template = e.target.value || null })} />
              </label>
            </div>
            <h3>Полета</h3>
            {Object.entries(def.transform.set_fields).map(([k, v]) => (
              <div key={k} className="form-grid" style={{ gridTemplateColumns: '1fr 2fr auto' }}>
                <input className="mono" value={k} onChange={(e) => setF((d) => {
                  delete d.transform.set_fields[k]; d.transform.set_fields[e.target.value] = v
                })} />
                <input className="mono" value={typeof v === 'object' ? JSON.stringify(v) : String(v)} onChange={(e) => {
                  let val: any = e.target.value
                  try { val = JSON.parse(e.target.value) } catch { /* текст е */ }
                  setF((d) => { d.transform.set_fields[k] = val })
                }} />
                <button className="ghost-btn" onClick={() => setF((d) => { delete d.transform.set_fields[k] })}>✕</button>
              </div>
            ))}
            <button className="ghost-btn" onClick={() => setF((d) => { d.transform.set_fields['ново_поле'] = 'стойност' })}>+ поле</button>
            <div className="form-grid">
              <label>Премахни полета (разделени със запетая)
                <input className="mono" value={def.transform.remove_fields.join(', ')}
                  onChange={(e) => setF((d) => { d.transform.remove_fields = e.target.value.split(',').map((x) => x.trim()).filter(Boolean) })} />
              </label>
              <label style={{ alignSelf: 'end' }}>
                <input type="checkbox" checked={def.transform.add_envelope}
                  onChange={(e) => setF((d) => { d.transform.add_envelope = e.target.checked })} />{' '}
                обвий оригинала в envelope.payload
              </label>
            </div>
            <p className="muted small">
              Шаблони: {'{topic}'} · {'{topic_tokens[2]}'} · {'{topic_suffix[3]}'} · {'{payload.node}'} · {'{payload.telemetry.battery}'}
            </p>
          </>
        )}

        {wiz.step === 4 && (
          <>
            {def.destinations.map((dst, i) => (
              <div key={i} className="form-grid" style={{ gridTemplateColumns: dst.type === 'http' ? '1fr 3fr auto' : '2fr 2fr auto auto auto' }}>
                <select value={dst.type} onChange={(e) => setF((d) => {
                  if (e.target.value === 'http') {
                    d.destinations[i] = { type: 'http', target: 'http', topic_template: '{topic}', qos: 0, retain: false, url: 'https://' }
                  } else {
                    d.destinations[i] = { type: 'mqtt', target: 'local', topic_template: d.destinations[i].topic_template, qos: 0, retain: false }
                  }
                })}>
                  <option value="mqtt">MQTT</option>
                  <option value="http">HTTP POST</option>
                </select>
                {dst.type === 'http' ? (
                  <input className="mono" placeholder="https://ntfy.sh/моят-канал или n8n webhook"
                    value={dst.url || ''} onChange={(e) => setF((d) => { d.destinations[i].url = e.target.value })} />
                ) : (
                  <>
                    <select value={dst.target} onChange={(e) => setF((d) => { d.destinations[i].target = e.target.value })}>
                      <option value="local">локален брокер</option>
                      {bridges.map((b) => (
                        <option key={b.id} value={`bridge:${b.id}`}>
                          bridge: {b.name} {b.enabled ? '' : '(изключен!)'}
                        </option>
                      ))}
                      {!['local', ...bridges.map((b) => `bridge:${b.id}`)].includes(dst.target) && (
                        <option value={dst.target}>{dst.target} — замени с реална цел!</option>
                      )}
                    </select>
                    <input className="mono" value={dst.topic_template}
                      onChange={(e) => setF((d) => { d.destinations[i].topic_template = e.target.value })} />
                    <select value={dst.qos} onChange={(e) => setF((d) => { d.destinations[i].qos = +e.target.value })}>
                      <option value={0}>QoS 0</option><option value={1}>QoS 1</option><option value={2}>QoS 2</option>
                    </select>
                    <label className="small">
                      <input type="checkbox" checked={dst.retain}
                        onChange={(e) => setF((d) => { d.destinations[i].retain = e.target.checked })} /> retain
                    </label>
                  </>
                )}
                {def.destinations.length > 1 && (
                  <>
                    <button className="ghost-btn" title="своя грешкова политика за този клон (Т22)"
                            onClick={() => setF((d) => {
                              (d.destinations[i] as any).error_policy = (d.destinations[i] as any).error_policy || {
                                on_destination_failure: 'continue',
                                retry: { max: 0, backoff_ms: 1000 },
                                dead_letter: false,
                              }
                              // принудителен рендер: три/върни същата стойност
                              d.destinations = [...d.destinations]
                            })}>⚙</button>
                    <button className="ghost-btn" onClick={() => setF((d) => { d.destinations.splice(i, 1) })}>✕</button>
                  </>
                )}
              </div>
            ))}
            <button className="ghost-btn" onClick={() => setF((d) => {
              d.destinations.push({ type: 'mqtt', target: 'local', topic_template: '{topic}', qos: 0, retain: false })
            })}>+ дестинация</button>
            {def.destinations.length > 1 && (
              <p className="small" style={{ marginTop: 6 }}>
                ⇄ Разклонение: над 1 дестинация — всяка може със <b>своя грешкова политика</b> (Т22):
                разтяни „политика на клона“ под нея. Празно = важи политиката на правилото.
              </p>
            )}
            {def.destinations.map((dst, i) => (dst as any).error_policy && (
              <div key={`pol-${i}`} className="form-grid" style={{ gridTemplateColumns: 'auto auto auto auto', marginTop: -8 }}>
                <span className="muted small" style={{ alignSelf: 'center' }}>политика на клон {i + 1}:</span>
                <select value={(dst as any).error_policy.on_destination_failure}
                        onChange={(e) => setF((d) => { (d.destinations[i] as any).error_policy.on_destination_failure = e.target.value })}>
                  <option value="continue">при грешка: продължи към следващите</option>
                  <option value="halt">при грешка: спри останалите клонове</option>
                </select>
                <label className="small">опити: <input type="number" min={0} max={10} style={{ width: 50 }}
                      value={(dst as any).error_policy.retry?.max ?? 0}
                      onChange={(e) => setF((d) => { (d.destinations[i] as any).error_policy.retry.max = +e.target.value })} /></label>
                <label className="small">
                  <input type="checkbox" checked={!!(dst as any).error_policy.dead_letter}
                         onChange={(e) => setF((d) => { (d.destinations[i] as any).error_policy.dead_letter = e.target.checked })} /> dead-letter
                </label>
              </div>
            ))}
            <p className="muted small">
              HTTP POST праща съдържанието на съобщението като тяло (JSON → application/json,
              текст → text/plain — ntfy.go разбира и двете). Вътрешни адреси не се допускат.
            </p>
            {!bridges.length && (
              <p className="muted small">Няма създадени мостове — дестинация „bridge" се появява, когато добавиш такъв от Bridges &amp; Routes.</p>
            )}
          </>
        )}

        {wiz.step === 5 && (
          <>
            <div className="form-grid">
              <label>Тестова тема
                <input className="mono" value={testTopic} onChange={(e) => setTestTopic(e.target.value)} />
              </label>
              <label>Тестов payload (JSON)
                <textarea rows={4} className="mono" value={testPayload} onChange={(e) => setTestPayload(e.target.value)} />
              </label>
            </div>
            {matching.length > 0 && (
              <>
                <h3>Реални съобщения, които минават през филтъра — тест с истински данни</h3>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
                  {matching.slice(0, 8).map((s, i) => (
                    <button key={i} className="tag mono"
                      onClick={() => { setTestTopic(s.topic); setTestPayload(s.payload) }}>
                      {s.topic}
                    </button>
                  ))}
                </div>
              </>
            )}
            <button onClick={dryRun} disabled={busy || !canNext}>{busy ? '…' : '▶ Dry-run (без публикуване)'}</button>{' '}
            <span className="muted small">същият engine, същите стъпки — нищо не се изпраща</span>
            <div className="mg-tabs" style={{ marginTop: 10 }}>
              {([['trace', 'Trace'], ['preview', 'Preview (преди/след)'], ['validation', 'Валидация']] as const).map(([id, label]) => (
                <button key={id} role="tab" aria-selected={testTab === id}
                        className={testTab === id ? 'active' : ''}
                        onClick={() => { setTestTab(id); if (id === 'validation' && !validation) void runValidation() }}>
                  {label}
                </button>
              ))}
            </div>
            {testTab === 'trace' && trace && trace.map((t: any, i: number) => (
              <div key={i} className="ok-box" style={{ marginTop: 10 }}>
                <strong className={t.decision === 'match_forward' ? '' : 'deny'}>{t.decision}</strong>{' '}
                <span className="mono small">{t.input_topic}</span>
                {t.error && <div className="deny small">{t.error}</div>}
                <div className="small">
                  {t.steps.map((s: any, j: number) => <div key={j}>· {s.step}</div>)}
                </div>
                {t.outputs?.map((o: any, j: number) => (
                  <div key={j} className="mono small" style={{ marginTop: 4 }}>
                    → {o.target} : {o.topic} (qos {o.qos}{o.retain ? ', retain' : ''})
                  </div>
                ))}
              </div>
            ))}
            {testTab === 'trace' && trace && !trace.length && (
              <div className="ok-box small">Съобщението не мина през правилото (no_match) — върни се на стъпка 1–2 и виж причините в live проверката.</div>
            )}
            {testTab === 'preview' && (
              (() => {
                const withPv = (trace ?? []).find((t: any) => t.preview)
                if (!trace) return <div className="empty small">Пусни Dry-run — преди/след от трансформацията.</div>
                if (!withPv) return <div className="empty small">Няма трансформация с промяна за този payload.</div>
                const pv = withPv.preview
                return (
                  <div className="ok-box small" style={{ marginTop: 10 }}>
                    <div><b>Тема:</b> <span className="mono">{pv.topic_before}</span>{pv.changed && <> → <span className="mono" style={{ color: 'var(--accent-primary)' }}>{pv.topic_after}</span></>}</div>
                    <div style={{ marginTop: 6 }}><b>Payload преди:</b></div>
                    <pre className="mono" style={{ fontSize: 12, maxHeight: 180, overflow: 'auto' }}>{typeof pv.payload_before === 'string' ? pv.payload_before : JSON.stringify(pv.payload_before, null, 2)}</pre>
                    <div><b>Payload след:</b></div>
                    <pre className="mono" style={{ fontSize: 12, maxHeight: 180, overflow: 'auto', color: pv.changed ? 'var(--accent-primary)' : undefined }}>{typeof pv.payload_after === 'string' ? pv.payload_after : JSON.stringify(pv.payload_after, null, 2)}</pre>
                  </div>
                )
              })()
            )}
            {testTab === 'validation' && (
              validation ? (
                <div style={{ marginTop: 10 }}>
                  {validation.errors.length === 0 && validation.warnings.length === 0 && (
                    <div className="ok-box small">✓ Няма блокери и предупреждения — готово за запис.</div>
                  )}
                  {validation.errors.map((e, i) => <div key={i} className="error" style={{ marginTop: 4 }}>✘ {e}</div>)}
                  {validation.warnings.map((w, i) => <div key={i} className="ok-box small" style={{ marginTop: 4 }}>⚠ {w}</div>)}
                </div>
              ) : (
                <div className="empty small">Пусни Dry-run или изчакай проверката…</div>
              )
            )}
          </>
        )}
      </div>

      <div className="toolbar" style={{ marginTop: 14 }}>
        <button className="ghost-btn" disabled={wiz.step === 1 || busy}
          onClick={() => goStep(wiz.step - 1)}>← Назад</button>
        {wiz.step < 5 ? (
          <button disabled={!canNext || busy} onClick={() => goStep(wiz.step + 1)}>Напред →</button>
        ) : (
          <>
            {isAdmin && <button disabled={busy || !canNext} onClick={() => save(false)}>
              {wiz.ruleId ? 'Запази чернова' : 'Запази (изключено)'}
            </button>}
            {isAdmin && <button disabled={busy || !canNext} onClick={() => save(true)}>Публикувай версия</button>}
            <span className="muted small">новите правила се създават ИЗКЛЮЧЕНИ — включваш ги от списъка</span>
          </>
        )}
      </div>
    </>
  )
}


// ---------- R3.1: правилото като блок-диаграма (визията от MeshGate.docx) ----------

/** Т20: рекурсивен редактор на термин/група (дълбочина ≤ 3). Групата има
 *  режим all/any + свои термини; „→ група" обгръща термин, „разформи" го
 *  връща към термин. Мутациите са на място (същият стил като Wizard-а). */
function TermNode({ node, depth, onChange, onRemove }: {
  node: any; depth: number; onChange: (n: any) => void; onRemove: () => void
}) {  // локален any — рекурсивната форма идва от API-то
  if (node && typeof node === 'object' && Array.isArray(node.terms)) {
    return (
      <div style={{ marginLeft: depth * 16, borderLeft: '2px solid var(--border-default)', paddingLeft: 8, marginTop: 4 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <select value={node.mode} onChange={(e) => onChange({ ...node, mode: e.target.value })}>
            <option value="all">ВСИЧКИ (AND)</option>
            <option value="any">ПОНЕ ЕДИН (OR)</option>
          </select>
          <button className="ghost-btn" onClick={() => onChange({ ...node, terms: [...node.terms, { path: '$.', op: 'exists', value: null }] })}>+ условие</button>
          {depth < 2 && <button className="ghost-btn" onClick={() => onChange({ ...node, terms: [...node.terms, { mode: 'all', terms: [] }] })}>+ подгрупа</button>}
          <button className="ghost-btn" title="трие групата ЗАЕДНО с термините в нея (поддръжка: конфигурираните условия се губят)"
                  onClick={() => onRemove()}>✕ група</button>
        </div>
        {node.terms.map((t: any, i: number) => (
          <TermNode key={i} node={t} depth={depth + 1}
                    onChange={(n) => onChange({ ...node, terms: node.terms.map((x: any, j: number) => j === i ? n : x) })}
                    onRemove={() => onChange({ ...node, terms: node.terms.filter((_: any, j: number) => j !== i) })} />
        ))}
      </div>
    )
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: depth * 16, marginTop: 4 }}>
      <input value={node.path ?? ''} onChange={(e) => onChange({ ...node, path: e.target.value })} />
      <select value={node.op} onChange={(e) => onChange({ ...node, op: e.target.value })}>
        {OPS.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
      <input value={node.value ?? ''} onChange={(e) => {
        const raw = e.target.value
        const val = raw !== '' && !isNaN(Number(raw)) ? Number(raw) : raw
        onChange({ ...node, value: val })
      }} />
      <button className="ghost-btn" title="обгърни в група (Т20)" disabled={depth >= 3}
              onClick={() => onChange({ mode: 'any', terms: [node] })}>→ група</button>
      <button className="ghost-btn" onClick={onRemove}>✕</button>
    </div>
  )
}
