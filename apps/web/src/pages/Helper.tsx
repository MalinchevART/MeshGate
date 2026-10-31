import { useEffect, useState } from 'react'
import { api } from '../api'
import { emptyDefinition, mqttMatch, payloadPaths, familyOf, familyLabel } from './RoutingRulesHelpers'
import TopicTokens, { TopicLegend } from './TopicTokens'

type Goal = 'alarm' | 'forward' | 'remap' | 'archive'
type Bridge = { id: string; name: string; enabled: boolean; health: string }
type Sample = { topic: string; payload: string; ts: string }
type Definition = ReturnType<typeof emptyDefinition>

const GOALS: { id: Goal; icon: string; title: string; desc: string }[] = [
  { id: 'alarm', icon: '🔔', title: 'Аларма при проблем', desc: 'напр. „изпрати аларма, когато батерията на възел падне под 20%“' },
  { id: 'forward', icon: '📤', title: 'Препращай канал към външен брокер', desc: 'съобщенията от избран канал отиват към друг MQTT сървър (нужен е мост)' },
  { id: 'remap', icon: '🔀', title: 'Копирай канал в друг канал', desc: 'съобщенията се публикуват и под ново име на канала' },
  { id: 'archive', icon: '🗄', title: 'Архивирай съобщения', desc: 'всичко от избрания канал се пази под archive/…' },
]

const FIELD_LABELS: Record<string, string> = {
  battery: 'батерия (%)', temp: 'температура (°C)', hum: 'влажност (%)',
  rssi: 'RSSI (dBm)', snr: 'SNR', node: 'възел', text: 'текст',
}

const OP_LABELS: Record<string, string> = {
  lt: 'е под', gt: 'е над', lte: 'е под или равно на', gte: 'е над или равно на',
  eq: 'е равно на', ne: 'е различно от', contains: 'съдържа', exists: 'съществува',
}

function fieldLabel(path: string): string {
  const key = path.split('.').pop() || path
  return FIELD_LABELS[key] || key
}

export default function Helper({ recent, samples, bridges, onDone, prefillFamily }: {
  recent: { topic: string; count: number }[]; samples: Sample[]
  bridges: Bridge[]; onDone: () => void
  prefillFamily?: string | null
}) {
  const [step, setStep] = useState(1)
  const [goal, setGoal] = useState<Goal | null>(null)
  const [family, setFamily] = useState<string | null>(prefillFamily ?? null)
  const [noCond, setNoCond] = useState(false)
  const [field, setField] = useState('$.battery')
  const [fieldTouched, setFieldTouched] = useState(false)
  const [op, setOp] = useState('lt')
  const [value, setValue] = useState('20')
  const [bridgeId, setBridgeId] = useState(bridges[0]?.id || '')
  const [newChannel, setNewChannel] = useState('kopie')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [trace, setTrace] = useState<any[] | null>(null)
  const [created, setCreated] = useState<{ id: string; name: string } | null>(null)

  // каналите от живия трафик, групирани човешки
  const families = (() => {
    const m = new Map<string, { count: number; sample: string }>()
    for (const r of recent) {
      const f = familyOf(r.topic)
      const cur = m.get(f)
      m.set(f, { count: (cur?.count || 0) + r.count, sample: cur?.sample || r.topic })
    }
    return [...m.entries()]
      .map(([pattern, v]) => ({ pattern, ...v }))
      .sort((a, b) => b.count - a.count)
  })()

  const famSample = (pat: string) =>
    samples.find((s) => familyOf(s.topic) === pat) || samples.find((s) => mqttMatch(pat.replace(/\*/g, '+'), s.topic))

  // полетата се събират от последните НЯКОЛКО пакета на канала — така има
  // и батерията, когато поне един пакет е телеметрия
  const fields = (() => {
    const src = family && family !== '#'
      ? samples.filter((sm) => familyOf(sm.topic) === family || mqttMatch(family.replace(/\*/g, '+'), sm.topic))
      : samples.slice(0, 1)
    const out: string[] = []
    for (const sm of src.slice(0, 5)) {
      try {
        const d = JSON.parse(sm.payload)
        if (d && typeof d === 'object') {
          for (const p of payloadPaths(d)) if (!out.includes(p)) out.push(p)
        }
      } catch { /* не JSON */ }
    }
    return out.slice(0, 16)
  })()

  function condText(): string {
    if (goal !== 'alarm' || noCond || !field) return 'на всяко съобщение'
    if (op === 'exists') return `когато полето ${fieldLabel(field)} съществува`
    return `когато ${fieldLabel(field)} ${OP_LABELS[op] || op} ${value}`
  }

  function destText(): string {
    if (goal === 'forward') {
      const b = bridges.find((x) => x.id === bridgeId)
      return `външния брокер „${b?.name || '?'}“`
    }
    if (goal === 'remap') return `канал „${newChannel}“ (локално)`
    if (goal === 'archive') return 'архива (archive/…)'
    return 'алармената тема (alerts/…)'
  }

  function autoName(): string {
    const fam = family === '#' ? 'всичко' : familyLabel(family || '')
    if (goal === 'alarm') return noCond ? `Аларма: ${fam}` : `Аларма: ${fieldLabel(field)} ${OP_LABELS[op] || op} ${value}`
    if (goal === 'forward') return `Към ${bridges.find((b) => b.id === bridgeId)?.name || 'мост'}: ${fam}`
    if (goal === 'remap') return `Копие: ${fam} → ${newChannel}`
    return `Архив: ${fam}`
  }

  function buildDef(): Definition {
    const famPat = family === '#' ? '#' : family || '#'
    const toks = famPat.split('/')
    // семейството групира ID-токените със '*'; MQTT wildcard-ът е '+' — в
    // include шаблона заместваме, но индексите на токените са от famPat
    const inc = famPat === '#' ? '#' : famPat.replace(/\*/g, '+')
    const d = emptyDefinition(autoName())
    d.conditions.topic.include = [inc]
    if (goal === 'alarm' && !noCond && field) {
      let v: any = value
      if (value !== '' && !isNaN(+value)) v = +value
      d.conditions.payload.terms = [{ path: field, op, value: v }]
    }
    if (goal === 'alarm') {
      // тема с възела, ако каналът има '*' токен; иначе цялата тема
      const star = toks.indexOf('*')
      const nodeTpl = star >= 0 ? `{topic_tokens[${star}]}` : '{topic}'
      const short = (field.split('.').pop() || 'alarm').toLowerCase()
      d.destinations = [{
        type: 'mqtt', target: 'local',
        topic_template: `alarms/${short}/${nodeTpl}`, qos: 1, retain: true,
      }]
    } else if (goal === 'forward') {
      d.destinations = [{ type: 'mqtt', target: `bridge:${bridgeId}`, topic_template: '{topic}', qos: 1, retain: false }]
    } else if (goal === 'remap') {
      const tpl = toks
        .map((t, i) => (t === '*' ? `{topic_tokens[${i}]}` : i === toks.length - 1 ? newChannel : t))
        .join('/')
      d.destinations = [{ type: 'mqtt', target: 'local', topic_template: tpl, qos: 0, retain: false }]
    } else {
      d.destinations = [{ type: 'mqtt', target: 'local', topic_template: 'archive/{topic}', qos: 0, retain: false }]
    }
    return d
  }

  async function test() {
    setBusy(true); setErr(null); setTrace(null)
    try {
      const s = family && family !== '#' ? famSample(family) : samples[0]
      const out = await api('/v1/routing/dry-run', {
        method: 'POST',
        body: JSON.stringify({
          definition: { ...buildDef(), enabled: true },
          topic: s?.topic || 'test/topic',
          payload: s?.payload || '{}',
        }),
      })
      setTrace(out)
    } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }

  async function create(enableNow: boolean) {
    setBusy(true); setErr(null)
    try {
      const def = buildDef()
      def.name = name.trim() || autoName()
      const createdRule = await api('/v1/routing', { method: 'POST', body: JSON.stringify({ definition: def }) })
      await api(`/v1/routing/${createdRule.id}/publish`, { method: 'POST', body: JSON.stringify({ note: 'от Помощника' }) })
      if (enableNow) {
        await api(`/v1/routing/${createdRule.id}/enable`, { method: 'POST' })
        onDone()
      } else {
        setCreated({ id: createdRule.id, name: def.name })
      }
    } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }

  const canNext =
    (step === 1 && !!goal) ||
    (step === 2 && !!family && (goal !== 'forward' || bridgeId)) ||
    (step === 3 && (goal !== 'remap' || /^[A-Za-z0-9_-]+$/.test(newChannel))) ||
    step === 4

  return (
    <>
      <div className="toolbar">
        <h2>🧭 Помощник — правило без знание на MQTT</h2>
        <span className="muted small">стъпка {step}/4</span>
        <span style={{ flex: 1 }} />
        <button className="ghost-btn" onClick={onDone}>Отказ</button>
      </div>
      {err && <div className="error">{err}</div>}

      <div className="panel">
        {step === 1 && (
          <>
            <h3>Какво искаш да направиш?</h3>
            <div className="cards">
              {GOALS.map((g) => {
                const blocked = g.id === 'forward' && !bridges.length
                return (
                  <div key={g.id} className="card"
                    style={{ cursor: blocked ? 'not-allowed' : 'pointer', opacity: blocked ? 0.45 : 1, borderColor: goal === g.id ? 'var(--accent)' : undefined }}
                    onClick={() => { if (!blocked) { setGoal(g.id); setName('') } }}>
                    <strong>{g.icon} {g.title}</strong>
                    <p className="muted small" style={{ minHeight: 44 }}>{g.desc}</p>
                    {blocked && (
                      <p className="small" style={{ color: 'var(--bad)' }}>
                        недостъпно: първо създай мост от Bridges &amp; Routes
                      </p>
                    )}
                  </div>
                )
              })}
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <h3>От кой канал? (това са каналите от реалния ти трафик)</h3>
            <TopicLegend />
            <div className="cards">
              {goal === 'archive' && (
                <div className="card" style={{ cursor: 'pointer', borderColor: family === '#' ? 'var(--accent)' : undefined, borderStyle: 'dashed' }}
                  onClick={() => setFamily('#')}>
                  <strong>🌐 Всичко</strong>
                  <p className="muted small">всички теми, без избор</p>
                </div>
              )}
              {families.map((f) => (
                <div key={f.pattern} className="card" style={{ cursor: 'pointer', borderColor: family === f.pattern ? 'var(--accent)' : undefined }}
                  onClick={() => setFamily(f.pattern)}>
                  <strong>{familyLabel(f.pattern)}</strong>
                  <p style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}><TopicTokens value={f.pattern.replace(/\*/g, '+')} /></p>
                  <p className="small muted">{f.count.toLocaleString('bg-BG')} съобщения (2 ч)</p>
                </div>
              ))}
              {!families.length && <div className="empty">Няма трафик — пусни демо възлите от менюто и опитай отново.</div>}
            </div>
          </>
        )}

        {step === 3 && (
          <>
            {goal === 'alarm' && (
              <>
                <h3>Кога да се алармира?</h3>
                {fields.length > 0 && !noCond && (
                  <div className="form-grid">
                    <label>Поле (от реалните съобщения)
                      <select value={fields.includes(field) ? field : (fields.find((f) => f.includes('battery')) || field)}
                        onChange={(e) => { setFieldTouched(true); setField(e.target.value) }}>
                        {fields.map((p) => <option key={p} value={p}>{fieldLabel(p)} ({p})</option>)}
                      </select>
                    </label>
                    <label>Условие
                      <select value={op} onChange={(e) => setOp(e.target.value)}>
                        {['lt', 'gt', 'eq', 'ne', 'contains', 'exists'].map((o) => <option key={o} value={o}>{OP_LABELS[o]}</option>)}
                      </select>
                    </label>
                    <label>Стойност
                      <input value={value} disabled={op === 'exists'} onChange={(e) => setValue(e.target.value)} />
                    </label>
                  </div>
                )}
                <label className="small" style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8 }}>
                  <input type="checkbox" checked={noCond} onChange={(e) => setNoCond(e.target.checked)} />
                  без условие — аларма на всяко съобщение от канала
                </label>
                {fields.length === 0 && !noCond && (
                  <p className="muted small">Каналът няма разпознати полета — често това значи, че съобщенията са шифровани (бинарни). Включи „без условие“ — правилото ще хваща по канал/тема, което работи и с шифрован трафик.</p>
                )}
              </>
            )}
            {goal === 'forward' && (
              <>
                <h3>Към кой външен брокер?</h3>
                <div className="form-grid">
                  <label>Мост
                    <select value={bridgeId} onChange={(e) => setBridgeId(e.target.value)}>
                      {bridges.map((b) => <option key={b.id} value={b.id}>{b.name} {b.enabled ? '' : '(изключен!)'}</option>)}
                    </select>
                  </label>
                </div>
              </>
            )}
            {goal === 'remap' && (
              <>
                <h3>Ново име на канала</h3>
                <div className="form-grid">
                  <label>Име (латински букви, цифри, - и _)
                    <input value={newChannel} onChange={(e) => setNewChannel(e.target.value)} />
                  </label>
                </div>
              </>
            )}
            {goal === 'archive' && <h3>Готово за архив — без допълнителни настройки.</h3>}
          </>
        )}

        {step === 4 && (
          <>
            <h3>Преглед — какво ще прави правилото</h3>
            <div className="ok-box">
              <div>📋 <strong>{name.trim() || autoName()}</strong></div>
              <div className="small" style={{ marginTop: 6 }}>
                📡 Канал: <strong>{family === '#' ? 'всичко' : familyLabel(family || '')}</strong>{' '}
                <span className="mono muted">({(family || '#').replace(/\*/g, '+')})</span>
              </div>
              {goal === 'alarm' && <div className="small">🔔 Аларма {condText()}</div>}
              <div className="small">➡ Отива към: <strong>{destText()}</strong></div>
            </div>
            <div className="form-grid" style={{ marginTop: 10 }}>
              <label>Име на правилото <input value={name} placeholder={autoName()} onChange={(e) => setName(e.target.value)} /></label>
            </div>
            <button onClick={test} disabled={busy}>{busy ? '…' : '▶ Тест с реално съобщение'}</button>
            {trace && trace.map((t: any, i: number) => (
              <div key={i} className="ok-box small" style={{ marginTop: 8 }}>
                {t.decision === 'match_forward' ? (
                  <>
                    <strong>✓ Да</strong> — такова съобщение ({t.input_topic}) ще отиде към:{' '}
                    {t.outputs?.map((o: any, j: number) => <span key={j} className="mono">{o.topic} </span>)}
                  </>
                ) : (
                  <span className="deny">
                    ✗ Тестовото реално съобщение не отговаря на условието
                    {' '}(това е нормално, ако напр. батериите сега са високи — правилото ще сработи,
                    когато условието стане истина){t.error ? ` · ${t.error}` : ''}
                  </span>
                )}
              </div>
            ))}
            {created && (
              <div className="ok-box" style={{ marginTop: 10 }}>
                ✅ Правилото „{created.name}" е записано (изключено).{' '}
                <button onClick={onDone}>към списъка</button>
              </div>
            )}
          </>
        )}
      </div>

      <div className="toolbar" style={{ marginTop: 14 }}>
        <button className="ghost-btn" disabled={step === 1 || busy} onClick={() => setStep(step - 1)}>← Назад</button>
        {step < 4 ? (
          <button disabled={!canNext || busy} onClick={() => setStep(step + 1)}>Напред →</button>
        ) : !created && (
          <>
            <button disabled={busy} onClick={() => create(true)}>✅ Създай и включи сега</button>
            <button className="ghost-btn" disabled={busy} onClick={() => create(false)}>Създай изключено</button>
          </>
        )}
      </div>
      {step < 4 && !canNext && (
        <p className="muted small" style={{ marginTop: 6 }}>
          ⚠ Напред е заключен: {{
            1: 'избери цел отгоре',
            2: goal === 'forward' && !bridgeId ? 'избери мост (или се върни и избери друга цел — без мост препращането не може)' : 'избери канал отгоре',
            3: goal === 'remap' ? 'въведи валидно име на канала (букви/цифри/-/_)' : 'прегледай настройката',
          }[step] || 'прегледай стъпката'}
        </p>
      )}
    </>
  )
}
