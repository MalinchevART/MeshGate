import { useEffect, useState } from 'react'
import { api, fmtTime } from '../api'
import { Panel, StatusChip } from '../components/ui'
import type { Me } from '../App'

type Channel = {
  id: string; name: string; kind: string; topic_pattern: string
  config: Record<string, any>; template: string | null; severity: string
  min_interval_s: number; enabled: boolean
}
type LogRow = {
  id: number; channel: string | null; topic: string; message: string
  status: string; error: string | null; ts: string
}

const KIND_HINT: Record<string, string> = {
  telegram: 'bot_token и chat_id (от @BotFather / @userinfobot)',
  email: 'to (получател); SMTP се настройва в deploy/.env',
  webhook: 'url (https://…); POST JSON {topic, message}',
  whatsapp: 'phone и apikey от callmebot.com (безплатно, праща на личния ти номер)',
}

const TEMPLATE_VARS = '{topic} {channel} {severity} {node} {text} {battery} {snr} {rssi} {lat} {lng} {origin}'

const SEVERITY_LABEL: Record<string, string> = {
  info: 'всичко',
  important: 'важно+',
  critical: 'само критично',
}

export default function Notifications({ me }: { me: Me }) {
  const [channels, setChannels] = useState<Channel[] | null>(null)
  const [log, setLog] = useState<LogRow[]>([])
  const [digest, setDigest] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)

  const isAdmin = me.role === 'admin'

  async function refresh() {
    try {
      setChannels(await api('/v1/notifications'))
      setLog(await api('/v1/notifications/log?limit=50'))
    } catch (e: any) {
      setErr(e.message)
    }
  }

  // брифът е 6 агрегатни заявки — не го теглим на всеки 10 s с останалите
  async function refreshDigest() {
    api('/v1/notifications/digest').then((r: any) => setDigest(r.text)).catch(() => {})
  }

  useEffect(() => {
    refresh()
    refreshDigest()
    const t = setInterval(refresh, 10000)
    const td = setInterval(refreshDigest, 60000)
    return () => { clearInterval(t); clearInterval(td) }
  }, [])

  if (err) return <div className="error">{err}</div>
  if (!channels) return <div className="center muted">Известията се зареждат…</div>

  return (
    <>
      <div className="kicker">АВТОМАТИЗАЦИЯ</div>
      <h1 className="h-page">Известия</h1>
      <div className="toolbar">
        <span className="muted small">
          канали, които следят MQTT теми и пращат съобщение при нов пакет (аларми, мрежови събития)
        </span>
        {isAdmin && !formOpen && (
          <button className="nav-btn" onClick={() => setFormOpen(true)}>+ Нов канал</button>
        )}
      </div>

      {formOpen && (
        <ChannelForm
          onDone={() => { setFormOpen(false); refresh() }}
          onCancel={() => setFormOpen(false)}
        />
      )}

      <Panel title="Канали" subtitle="кой следи коя тема и с каква важност" padded={false}>
        {!channels.length ? (
          <div className="empty">
            Няма канали. Типична употреба: правило „ниска батерия“ публикува в alerts/… —
            направи канал с тема alerts/# и съобщенията идват в Telegram/имейл.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Име</th><th>Вид</th><th>Тема (MQTT filter)</th>
                <th>Важност</th><th>Шаблон</th><th>Интервал</th><th>Статус</th><th></th>
              </tr>
            </thead>
            <tbody>
              {channels.map((c) => (
                <tr key={c.id}>
                  <td>{c.name}</td>
                  <td><span className="tag">{c.kind}</span></td>
                  <td><code>{c.topic_pattern}</code></td>
                  <td>
                    <StatusChip size="sm" flat tone={c.severity === 'critical' ? 'danger' : c.severity === 'important' ? 'warning' : 'success'}>
                      {SEVERITY_LABEL[c.severity] ?? c.severity}
                    </StatusChip>
                    {c.config?.quiet_hours && (
                      <div className="muted small">
                        тихо {c.config.quiet_hours.start}–{c.config.quiet_hours.end}
                      </div>
                    )}
                    {c.config?.digest_hour != null && (
                      <div className="muted small" title="сутрешен бриф">☕ {String(c.config.digest_hour).padStart(2, '0')}:00</div>
                    )}
                  </td>
                  <td className="small" title={c.template ?? undefined} style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {c.template ? c.template.split('\n')[0].slice(0, 30) : 'стандартен'}
                  </td>
                  <td>{c.min_interval_s}s</td>
                  <td>
                    <span className={c.enabled ? 'tag ok' : 'tag'}>{c.enabled ? 'включен' : 'изключен'}</span>
                  </td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {isAdmin && (
                      <>
                        <button
                          className="nav-btn ghost"
                          title="Тестово известие"
                          onClick={async () => {
                            try {
                              await api(`/v1/notifications/${c.id}/test`, { method: 'POST' })
                              refresh()
                            } catch (e: any) { setErr(e.message); setTimeout(() => setErr(null), 4000) }
                          }}
                        >
                          ⚡
                        </button>
                        <button
                          className="nav-btn ghost"
                          title={c.enabled ? 'Изключи' : 'Включи'}
                          onClick={async () => {
                            await api(`/v1/notifications/${c.id}/${c.enabled ? 'disable' : 'enable'}`, { method: 'POST' })
                            refresh()
                          }}
                        >
                          {c.enabled ? '⏸' : '▶'}
                        </button>
                        <button
                          className="nav-btn ghost"
                          title="Изтрий"
                          onClick={async () => {
                            if (!confirm(`Изтрий канал „${c.name}“?`)) return
                            await api(`/v1/notifications/${c.id}`, { method: 'DELETE' })
                            refresh()
                          }}
                        >
                          ✕
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      {digest && (
        <Panel title="☕ Сутрешен бриф — преглед" subtitle="какво ще получава канал с включен бриф (обновява се всяка минута · последни 24 ч)">
          <pre style={{ whiteSpace: 'pre-wrap', margin: 0, fontFamily: 'inherit' }}>{digest}</pre>
        </Panel>
      )}

      <Panel title="Журнал" subtitle="последни 50 изпращания" padded={false}>
        {!log.length ? (
          <div className="empty">Още нищо не е изпращано.</div>
        ) : (
          <table>
            <thead>
              <tr><th>Време</th><th>Канал</th><th>Тема</th><th>Статус</th><th>Съобщение</th></tr>
            </thead>
            <tbody>
              {log.map((l) => (
                <tr key={l.id}>
                  <td className="muted small">{fmtTime(l.ts)}</td>
                  <td>{l.channel ?? '—'}</td>
                  <td><code>{l.topic}</code></td>
                  <td>
                    <StatusChip size="sm" flat tone={l.status === 'sent' ? 'success' : l.status === 'failed' ? 'danger' : 'neutral'}>
                      {l.status}
                    </StatusChip>
                    {l.error && <div className="muted small">{l.error}</div>}
                  </td>
                  <td style={{ whiteSpace: 'pre-wrap', maxWidth: 420 }}>{l.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </>
  )
}

function ChannelForm({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [name, setName] = useState('')
  const [kind, setKind] = useState<'telegram' | 'email' | 'webhook' | 'whatsapp'>('telegram')
  const [topic, setTopic] = useState('alerts/#')
  const [minInterval, setMinInterval] = useState(30)
  const [cfgText, setCfgText] = useState('{\n  "bot_token": "",\n  "chat_id": ""\n}')
  const [template, setTemplate] = useState('')
  const [severity, setSeverity] = useState('info')
  const [quietFrom, setQuietFrom] = useState('')
  const [quietTo, setQuietTo] = useState('')
  const [digestHour, setDigestHour] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const TEMPLATES: Record<string, string> = {
    telegram: '{\n  "bot_token": "",\n  "chat_id": ""\n}',
    email: '{\n  "to": "you@example.com"\n}',
    webhook: '{\n  "url": "https://example.com/hook"\n}',
    whatsapp: '{\n  "phone": "+359888123456",\n  "apikey": ""\n}',
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    let config: any
    try {
      config = JSON.parse(cfgText)
    } catch {
      setError('Конфигурацията не е валиден JSON')
      setBusy(false)
      return
    }
    if (quietFrom && quietTo) {
      config.quiet_hours = { start: quietFrom, end: quietTo }
    }
    if (digestHour !== '') {
      const h = Number(digestHour)
      if (!Number.isInteger(h) || h < 0 || h > 23) {
        setError('Часът на брифа трябва да е цяло число 0–23')
        setBusy(false)
        return
      }
      config.digest_hour = h
    }
    try {
      await api('/v1/notifications', {
        method: 'POST',
        body: JSON.stringify({
          name, kind, topic_pattern: topic, config,
          template: template.trim() || null,
          severity, min_interval_s: minInterval, enabled: true,
        }),
      })
      onDone()
    } catch (err: any) {
      setError(err.message || 'грешка при създаване')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel">
      <h2>Нов канал за известия</h2>
      <form onSubmit={submit} className="cards" style={{ gap: 8 }}>
        <div className="card" style={{ padding: 12 }}>
          <label>Име</label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="alarm-telegram" required />
          <label>Вид</label>
          <select
            value={kind}
            onChange={(e) => { setKind(e.target.value as any); setCfgText(TEMPLATES[e.target.value]) }}
          >
            <option value="telegram">Telegram</option>
            <option value="email">Имейл (SMTP)</option>
            <option value="webhook">Webhook</option>
            <option value="whatsapp">WhatsApp (CallMeBot)</option>
          </select>
          <div className="muted small">{KIND_HINT[kind]}</div>
        </div>
        <div className="card" style={{ padding: 12 }}>
          <label>Тема (MQTT filter)</label>
          <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="alerts/#" required />
          <label>Важност — какво да приема</label>
          <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
            <option value="info">всичко (info+)</option>
            <option value="important">важно и критично</option>
            <option value="critical">само критично</option>
          </select>
          <div className="muted small">
            важността идва от съобщението (payload severity — правилата могат да я
            зададат с трансформация set_fields severity=critical)
          </div>
          <label>Тихи часове (по избор; критичното минава винаги)</label>
          <div style={{ display: 'flex', gap: 6 }}>
            <input type="time" value={quietFrom} onChange={(e) => setQuietFrom(e.target.value)} />
            <span className="muted">–</span>
            <input type="time" value={quietTo} onChange={(e) => setQuietTo(e.target.value)} />
          </div>
          <label>Сутрешен бриф — час (0–23; празно = без бриф)</label>
          <input type="number" min={0} max={23} value={digestHour}
            placeholder="8"
            onChange={(e) => setDigestHour(e.target.value)} />
          <div className="muted small">
            всеки ден в този час (24-часов формат, местно време на сървъра)
            каналът получава ЕДНО резюме за последните 24 ч — трафик, нови
            възли, тихи фаворити, слаби батерии, мъртви букви — независимо
            от MQTT филтъра на канала
          </div>
          <label>Мин. интервал между известия (сек)</label>
          <input
            type="number" min={0} max={86400} value={minInterval}
            onChange={(e) => setMinInterval(Number(e.target.value))}
          />
          <label>Конфигурация (JSON)</label>
          <textarea
            rows={5} value={cfgText} style={{ fontFamily: 'monospace', width: '100%' }}
            onChange={(e) => setCfgText(e.target.value)}
          />
        </div>
        <div className="card" style={{ padding: 12, flexBasis: '100%' }}>
          <label>Шаблон на съобщението (по избор)</label>
          <textarea
            rows={3} value={template} style={{ width: '100%' }}
            placeholder={'⚠ {node} на {channel}: {text} (бат. {battery})\nпразно → стандартният формат'}
            onChange={(e) => setTemplate(e.target.value)}
          />
          <div className="muted small">променливи: {TEMPLATE_VARS}</div>
        </div>
        {error && <div className="error" style={{ width: '100%' }}>{error}</div>}
        <div style={{ width: '100%', display: 'flex', gap: 8 }}>
          <button disabled={busy || !name || !topic}>{busy ? '…' : 'Създай'}</button>
          <button type="button" className="ghost" onClick={onCancel}>Отказ</button>
        </div>
      </form>
    </div>
  )
}
