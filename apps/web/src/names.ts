/* ============================================================================
 * MeshGate · Т36: имена на възлите — ОБОБЩЕНО през целия фронтенд.
 * ----------------------------------------------------------------------------
 * За ЧОВЕКА името е главното (кратко → дълго), ID-то (!hex) е второстепенно.
 * Една карта, кеширана на ниво модул (споделена между всички страници,
 * refresh на 60s от първия консуматор); няма prop-drilling.
 * ========================================================================== */
import { useEffect, useState } from 'react'
import { api } from './api'

type NameEntry = { short: string | null; long: string | null }
type NameMap = Record<string, NameEntry>

let cache: NameMap = {}
let cacheAt = 0
let lastErrorAt = 0
let inflight: Promise<void> | null = null

const TTL_MS = 60_000
const ERROR_COOLDOWN_MS = 5_000

async function ensure() {
  // свеж кеш → нищо; скорошна грешка → кратка пауза (без hammering),
  // НО не 60 s — иначе след login имената чакат минута (живо установено)
  if (cacheAt && Date.now() - cacheAt < TTL_MS) return
  if (lastErrorAt && Date.now() - lastErrorAt < ERROR_COOLDOWN_MS) return
  if (inflight) return inflight
  inflight = api<NameMap>('/v1/names')
    .then((m: NameMap) => { cache = m ?? {}; cacheAt = Date.now(); lastErrorAt = 0 })
    .catch(() => { lastErrorAt = Date.now() }) // transient — пазим старата карта
    .finally(() => { inflight = null })
  return inflight
}

/** hook: връща функция id → {main, sub, tip}.
 *  main = името (кратко, иначе дълго, иначе ID); sub = дългото или ID;
 *  tip = и трите за tooltip. */
export function useNodeNames(): (id: string | null | undefined) => {
  main: string
  sub: string | null
  tip: string
} {
  const [, bump] = useState(0)
  useEffect(() => {
    void ensure().then(() => bump((n) => n + 1))
    const t = setInterval(() => { void ensure().then(() => bump((n) => n + 1)) }, TTL_MS)
    return () => clearInterval(t)
  }, [])
  return (id) => {
    const key = (id ?? '').toLowerCase()
    const e = cache[key]
    if (!e) {
      const bare = id ?? '—'
      return { main: bare, sub: null, tip: bare }
    }
    const main = e.short ?? e.long ?? id ?? '—'
    const sub = e.short && e.long && e.long !== e.short ? e.long : (e.short ? id : e.long)
    const tip = `${e.long ?? '—'} (${e.short ?? '—'}) · ${id ?? '—'}`
    return { main, sub: sub ?? null, tip }
  }
}
