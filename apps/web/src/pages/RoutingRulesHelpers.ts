// Споделени чисти функции и типове за Routing Rules (страницата и Помощника).
// Сверени с apps/api/app/routing/model.py.

export type Term = { path: string; op: string; value: any }

/** Т20: вложена AND/OR група — terms позволява рекурсия (група|термин). */
export type TermGroup = { mode: string; terms: (Term | TermGroup)[] }
export type TermNode = Term | TermGroup
export function isGroup(n: TermNode): n is TermGroup {
  return n != null && typeof n === 'object' && Array.isArray((n as any).terms)
}
export type Dest = {
  id?: string
  type: string              // 'mqtt' | 'http'
  target: string            // mqtt: 'local' | 'bridge:<id>'; http: 'http'
  topic_template: string
  qos: number
  retain: boolean
  url?: string | null       // само за type=http: абсолютен адрес
}
export type Definition = {
  name: string
  description?: string | null
  enabled?: boolean
  priority: number
  execution_mode: string
  source: { type: string; broker: string; topic_filter: string }
  conditions: {
    topic: { include: string[]; exclude: string[] }
    payload: { mode: string; terms: TermNode[]; on_unparseable?: string }
  }
  transform: {
    topic_template?: string | null
    set_fields: Record<string, any>
    remove_fields: string[]
    add_envelope: boolean
  }
  destinations: Dest[]
  error_policy: { on_destination_failure: string; retry: { max: number; backoff_ms: number }; dead_letter: boolean }
}
export type Bridge = { id: string; name: string; enabled: boolean; health: string }
export type Sample = { topic: string; payload: string; ts: string }
export type Template = { id: string; title: string; description: string; definition: Definition }
export type Rule = {
  id: string; name: string; description: string | null; enabled: boolean
  priority: number; execution_mode: string; definition: Definition; draft: Definition | null
  current_version: number
  stats: { matched: number; forwarded: number; errors: number; last_fired_at: string | null }
}

export const OPS = ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains', 'exists']

export function emptyDefinition(name = ''): Definition {
  return {
    name, description: '', priority: 100, execution_mode: 'first_match',
    source: { type: 'mqtt', broker: 'local', topic_filter: 'mesh/#' },
    conditions: { topic: { include: ['mesh/+/+/up'], exclude: [] }, payload: { mode: 'all', terms: [] } },
    transform: { topic_template: null, set_fields: {}, remove_fields: [], add_envelope: false },
    destinations: [{ type: 'mqtt', target: 'local', topic_template: '{topic}', qos: 0, retain: false }],
    error_policy: { on_destination_failure: 'continue', retry: { max: 2, backoff_ms: 1000 }, dead_letter: true },
  }
}

/** Допълва всяка (частична) дефиниция до пълната схема — данни отвън никога
 *  не са гаранция, редакторът не бива да гръмне на липсващо поле. */
export function normalizeDefinition(p: any): Definition {
  const b = emptyDefinition(String(p?.name ?? ''))
  return {
    ...b, ...p,
    priority: Number(p?.priority) || 100,
    source: { ...b.source, ...(p?.source || {}) },
    conditions: {
      topic: { include: [], exclude: [], ...(p?.conditions?.topic || {}) },
      payload: {
        mode: p?.conditions?.payload?.mode === 'any' ? 'any' : 'all',
        terms: Array.isArray(p?.conditions?.payload?.terms) ? p.conditions.payload.terms : [],
        // Т20 П3: не изхвърляй стойността — иначе селектът в wizard стъпка 2
        // мига обратно на „не пасва" и edit-ът занулява on_unparseable
        on_unparseable: p?.conditions?.payload?.on_unparseable === 'match' ? 'match' : 'no_match',
      },
    },
    transform: { ...b.transform, ...(p?.transform || {}) },
    destinations: (Array.isArray(p?.destinations) && p.destinations.length ? p.destinations : b.destinations)
      .map((d: any) => ({ type: 'mqtt', qos: 0, retain: false, ...d })),
    error_policy: { ...b.error_policy, ...(p?.error_policy || {}) },
  }
}

export function mqttMatch(pattern: string, topic: string): boolean {
  if (pattern === '#') return true
  const p = pattern.split('/'), t = topic.split('/')
  for (let i = 0; i < p.length; i++) {
    if (p[i] === '#') return true
    if (i >= t.length) return false
    if (p[i] !== '+' && p[i] !== t[i]) return false
  }
  return p.length === t.length
}

/** Проверява тема срещу include/exclude — като backend topic_matches. */
export function topicVerdict(def: Definition, topic: string): { ok: boolean; why: string } {
  for (const pat of def.conditions.topic.exclude) {
    if (mqttMatch(pat, topic)) return { ok: false, why: `exclude: ${pat}` }
  }
  const inc = def.conditions.topic.include
  if (!inc.length) return { ok: true, why: 'без include (всички)' }
  for (const pat of inc) if (mqttMatch(pat, topic)) return { ok: true, why: `include: ${pat}` }
  return { ok: false, why: 'нищо от include не пасва' }
}

/** Групира тема по канал: ID-подобните токени (вкл. Meshtastic !hex) стават '*'. */
export function familyOf(topic: string): string {
  const idlike = (t: string) =>
    t.startsWith('!') ||
    /^(node|dev|emu|n)\d/i.test(t) || (/^[0-9a-f-]{4,}$/i.test(t) && t.includes('-')) || (/^\d+$/.test(t) && t !== '1' && t !== '2')
  return topic.split('/').map((t) => (idlike(t) ? '*' : t)).join('/')
}

const LAST_TOKEN_BG: Record<string, string> = {
  up: 'телеметрия', pos: 'позиции', msg: 'съобщения', priv: 'частни',
}

/** Човешки етикет на канал: „демо мрежа — телеметрия“ / „Meshtastic EU — LongFast“. */
export function familyLabel(fam: string): string {
  const toks = fam.split('/')
  if (fam.startsWith('msh/')) {
    // msh/<region>/2/e|json/<channel>/* → регион + канал
    const chIdx = toks.findIndex((t) => t === 'e' || t === 'c' || t === 'json')
    const channel = chIdx >= 0 && toks[chIdx + 1] ? toks[chIdx + 1] : (toks[3] || '')
    const region = toks[1] || ''
    return `Meshtastic ${region} — ${channel}`
  }
  const net = toks.slice(0, 2).join('/')
  const kind = LAST_TOKEN_BG[toks[toks.length - 1]] || toks[toks.length - 1]
  return `${net === 'mesh/emul' ? 'демо мрежа' : net} — ${kind}`
}

/** Предлага include шаблон от реална тема: ID-подобните токени стават '+'. */
export function suggestPattern(topic: string): string {
  return familyOf(topic).replace(/\*/g, '+')
}

/** Пътища в JSON документ (2 нива) — за подсказки при payload условията. */
export function payloadPaths(doc: any, prefix = '$', depth = 0): string[] {
  const out: string[] = []
  // 4 нива: стига до $.decoded.telemetry.device_metrics.battery_level в Meshtastic envelope
  if (doc == null || typeof doc !== 'object' || depth > 3) return out
  if (Array.isArray(doc)) {
    if (doc.length && typeof doc[0] === 'object') out.push(...payloadPaths(doc[0], `${prefix}[0]`, depth + 1))
    return out
  }
  for (const [k, v] of Object.entries(doc)) {
    const p = `${prefix}.${k}`
    out.push(p)
    if (v && typeof v === 'object') out.push(...payloadPaths(v, p, depth + 1))
  }
  return out
}
