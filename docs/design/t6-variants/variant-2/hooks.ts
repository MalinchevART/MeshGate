/* ============================================================================
 * MeshGate · Т6 „Топбар + sidebar + брояч аларми" — Вариант 2
 * hooks/useAnomalyCount — броячът на аларми за шел-а
 * ----------------------------------------------------------------------------
 * Дестинация при внедряване: apps/web/src/hooks/useAnomalyCount.ts
 * (нова папка hooks/ — първият й обитател; vite/tsconfig я вдигат без
 * промяна, защото include: ["src"]).
 *
 * Какво прави: polling на /v1/anomalies?hours=24 на всеки 10s →
 * { summary, error, refresh }. summary.alarm е ЧИСЛОТО В БРОЯЧА:
 *   alarm = deadletter + notify_failed        (ЛОШИТЕ събития)
 * notify_sent / rule_publish са НОРМАЛНА работа (информационни) — те НЕ
 * са аларми и не вдигат брояча; суровите им бройки се излагат в summary
 * (за tooltip и за бъдещи консуматори).
 *
 * Източникът е превключваем (спек Т6): source: 'anomalies' | 'critical-events'.
 * Днес реализиран е само 'anomalies' (готовият endpoint, meta.py ред 254+);
 * 'critical-events' идва след Т7 — тогава в ADAPTERS се добавя втори
 * fetcher (endpoint + правило кои събития са „аларма", напр. не-ACK-нати),
 * а Shell сменя само пропа alarmSource. Интерфейсът е готов сега.
 *
 * Живот (строга гигиена, както в Т3):
 *   · setInterval + clearTimeout/clearInterval при unmount — нула таймери
 *     след демонтиране; disposed флаг пази от setState след unmount;
 *   · документът е скрит (друг таб) → НЕ се пращат заявки; при връщане
 *     (visibilitychange → visible) — веднага refresh;
 *   · в полет (бавен API) → новият tick се пропуска (inFlight ref), не
 *     се трупат заявки;
 *   · грешка ( вкл. 401 Unauthorized ) → задържа последния добър summary
 *     (badge-ът не мига/не изчезва при транзиентен срив), error полето
 *     се вдига; ако няма никакъв успешен poll → summary = null → без badge.
 *
 * Честност за капацитета: /v1/anomalies връща до 400 събития (200 deadletter
 * + 200 известия + 100 публикации, meta.py) — при повече, броячът е „поне
 * толкова". За индикатор „има ли проблем" това е достатъчно; авторитетният
 * точен брой идва с Т7 (critical-events). Вж. notes.md §Рискове.
 *
 * TypeScript strict (apps/web/tsconfig.json); нула нови npm пакети.
 * ========================================================================== */
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'

/* ============================================================================
 * 1. Типове
 * ========================================================================== */

/** kind-овете на /v1/anomalies (meta.py ред 254+):
 * deadletter | notify_failed | notify_sent | rule_publish */
export type AnomalyKind = 'deadletter' | 'notify_failed' | 'notify_sent' | 'rule_publish'

/** Всички познати kind-ове — списъкът на `byKind`. Непознат kind (бъдещ
 *  бекенд) НЕ чупи нищо: брои се в total, не се брои в byKind/аларми. */
export const ANOMALY_KINDS: readonly AnomalyKind[] = [
  'deadletter',
  'notify_failed',
  'notify_sent',
  'rule_publish',
]

/** ЛОШИТЕ kind-ове — само те правят „аларма" в брояча:
 * мъртва буква (рутирането се провали) и провалено известие.
 * notify_sent (известието тръгна) и rule_publish (админ публикува версия)
 * са нормална работа, не аларми. */
export const ALARM_KINDS: readonly AnomalyKind[] = ['deadletter', 'notify_failed']

/** Източник на брояча (спек Т6): днес /v1/anomalies; след Т7 —
 * /v1/critical-events (превключвателят е проп на Shell). */
export type AnomalySource = 'anomalies' | 'critical-events'

/** Агрегираният резултат от един успешен poll — всичко, което шел-а (и
 *  бъдещи консуматори: Т9 панел „Критични събития", tooltip, Т18 канаря)
 *  може да поиска, без да пази суровите събития. */
export interface AnomalySummary {
  /** Прозорецът, за който е смятано (серверът го клампва 1..168). */
  hours: number
  /** ЧИСЛОТО В БРОЯЧА: deadletter + notify_failed (ЛОШИТЕ). */
  alarm: number
  deadletter: number
  notifyFailed: number
  /** Информационни (не аларми): излезли известия / публикувани правила. */
  notifySent: number
  rulePublish: number
  /** Сурови бройки по kind — за tooltip/Т7. */
  byKind: Record<AnomalyKind, number>
  /** Всички събития в отговора (вкл. непознати kind-ове). */
  total: number
  /** ts на последното ЛОШО събитие; null → няма аларми в прозореца. */
  lastAlarmTs: string | null
  /** ts на последното събитие от какъвто и да е вид. */
  lastTs: string | null
  /** Date.now() на последния УСПЕШЕН poll — за „проверено в HH:MM:SS". */
  updatedAt: number
}

/* ============================================================================
 * 2. Пресмятане — чиста функция (лесна за unit тест при внедряване)
 * ========================================================================== */

/** Суров ред от /v1/anomalies (label не ни трябва за броенето). */
interface RawEvent {
  ts: string
  kind: string
  label?: string
}

/** Отговорът на /v1/anomalies след развързването на api() (body.data). */
interface AnomaliesResponse {
  hours?: number
  events?: RawEvent[]
}

function summarize(hours: number, events: RawEvent[]): AnomalySummary {
  const byKind: Record<AnomalyKind, number> = {
    deadletter: 0,
    notify_failed: 0,
    notify_sent: 0,
    rule_publish: 0,
  }
  let lastMs = -1
  let lastAlarmMs = -1
  let lastTs: string | null = null
  let lastAlarmTs: string | null = null
  for (const e of events) {
    // defensive (правило №4 на docs/16): лош ред не чупи брояча
    if (e == null || typeof e.ts !== 'string' || typeof e.kind !== 'string') continue
    const k = e.kind as AnomalyKind
    if (ANOMALY_KINDS.includes(k)) byKind[k] += 1
    // ts сървърът праща ISO 8601; сравняваме по Date.parse, не лексикално
    const ms = Date.parse(e.ts)
    if (Number.isNaN(ms)) continue
    if (ms > lastMs) {
      lastMs = ms
      lastTs = e.ts
    }
    if (ALARM_KINDS.includes(k) && ms > lastAlarmMs) {
      lastAlarmMs = ms
      lastAlarmTs = e.ts
    }
  }
  return {
    hours,
    alarm: byKind.deadletter + byKind.notify_failed,
    deadletter: byKind.deadletter,
    notifyFailed: byKind.notify_failed,
    notifySent: byKind.notify_sent,
    rulePublish: byKind.rule_publish,
    byKind,
    total: events.length,
    lastAlarmTs,
    lastTs,
    updatedAt: Date.now(),
  }
}

/* ============================================================================
 * 3. Адаптери по източник — Т7 включва се тук с един ред в ADAPTERS
 * ========================================================================== */

type SourceFetcher = (hours: number) => Promise<AnomalySummary>

/** /v1/anomalies?hours=N → {hours, events:[{ts, kind, label}]}
 *  (meta.py ред 254+; api() вече е свалил обвивката {data: …}). */
async function fetchAnomalies(hours: number): Promise<AnomalySummary> {
  const raw = await api<AnomaliesResponse>(`/v1/anomalies?hours=${hours}`)
  const events: RawEvent[] = Array.isArray(raw?.events) ? raw.events : []
  return summarize(raw?.hours ?? hours, events)
}

/** Единственото място за разширяване след Т7: добави fetchCriticalEvents
 *  (GET /v1/critical-events?hours= ; аларма = незаглушени/не-ACK-нати
 *  събития — точният агрегат се решава в Т7) и Shell превключва с
 *  alarmSource='critical-events'. Дотогава изрична, четима грешка. */
const ADAPTERS: Record<AnomalySource, SourceFetcher> = {
  anomalies: fetchAnomalies,
  'critical-events': () =>
    Promise.reject(
      new Error("източник 'critical-events' не е наличен — включва се след Т7"),
    ),
}

/* ============================================================================
 * 4. useAnomalyCount
 * ========================================================================== */

export interface UseAnomalyCountOptions {
  /** Прозорец в часове (default 24; сървърът клампва 1..168). */
  hours?: number
  /** Интервал на polling в ms (default 10s). */
  intervalMs?: number
  /** Източник (default 'anomalies'; 'critical-events' след Т7). */
  source?: AnomalySource
}

export interface AnomalyCountResult {
  /** null → още няма успешен poll → консуматорът не показва badge. */
  summary: AnomalySummary | null
  /** Грешка от последния poll (ако има); summary остава последният добър. */
  error: string | null
  /** Незабавен извънреден poll (напр. след ack в Т9). Стабилна референция. */
  refresh: () => void
}

export function useAnomalyCount({
  hours = 24,
  intervalMs = 10_000,
  source = 'anomalies',
}: UseAnomalyCountOptions = {}): AnomalyCountResult {
  const [summary, setSummary] = useState<AnomalySummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  // nonce за извънреден refresh: промяна → ефектът се преинсталира → нов
  // immediate poll, после интервалът продължава като по часовник
  const [tick, setTick] = useState(0)
  const inFlight = useRef(false)

  const refresh = useCallback(() => setTick((n) => n + 1), [])

  useEffect(() => {
    let disposed = false

    const load = async () => {
      if (inFlight.current) return // бавен API → без трупане на заявки
      inFlight.current = true
      try {
        const next = await ADAPTERS[source](hours)
        if (disposed) return
        setSummary(next)
        setError(null)
      } catch (e) {
        if (disposed) return
        // НЕ зануляваме summary: транзиентният срив не мига с badge-а
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        inFlight.current = false
      }
    }

    // връщане в таб-а → веднага свежи данни, без да се чака края на интервала
    const onVisible = () => {
      if (!document.hidden) void load()
    }

    void load()
    document.addEventListener('visibilitychange', onVisible)
    const timer = setInterval(() => {
      if (document.hidden) return // скрит таб → нула заявки (NOC табове!)
      void load()
    }, intervalMs)

    return () => {
      disposed = true
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [hours, intervalMs, source, tick])

  return { summary, error, refresh }
}
