/* MeshGate — Т6 „Топбар + sidebar + брояч аларми" · Вариант 3 „NOC операторски фокус"
 * ============================================================================
 * Вариантен файл (преглед, НЕ е свързан в билда).
 * Дестинация при внедряване: apps/web/src/hooks.ts (нов файл).
 * ----------------------------------------------------------------------------
 * useAnomalyCount — ЕДИНСТВЕНИЯТ източник на алармен брой за ТОПБАР чипа и
 * sidebar badge-а. Стратегия В3: App вика hook-а ВЕДНЪЖ и подава резултата
 * надолу с props → един fetch на 10 s, двете места са синхронни по
 * конструкция (не по договаряне).
 *
 * Източник на данни: GET /v1/anomalies?hours=24 (готов; apps/api/app/routes/
 * meta.py, ред 254+): { hours, events: [{ ts, kind, label }] }, kind ∈
 * deadletter | notify_failed | notify_sent | rule_publish; до 400 събития,
 * сортирани низходящо по ts (капаци 200/200/100 — виж notes.md §Рискове).
 *
 * „Броня" (ARMOR) = видовете, които алармират оператора: deadletter +
 * notify_failed. notify_sent и rule_publish са НОРМА (изпратено известие,
 * публикувано правило), не аномалия — не вдигат брояча. Филтърът живее на
 * ЕДНО място (isArmor по-долу): при Т7 източникът се превключва към
 * GET /v1/critical-events, без нито една промяна по UI-то — интерфейсът на
 * hook-а остава { total, deadletter, notifyFailed, clean, lastTs } (+ раз-
 * ширения за tooltip и честност на състоянието).
 *
 * NOC правила, вградени тук:
 *   · „чисто" се потвърждава САМО от успешен отговор: clean = loaded &&
 *     total === 0 && без грешка. Мъртъв API никога не се чете като „без
 *     аларми" (тишина ≠ здраве);
 *   · при грешка след успешен отговор се пази последното известно
 *     състояние (stale, но честно: ако последното известно е „3 аларми",
 *     чипът продължава да алармира, докато не чуем друго);
 *   · полингът не пули в скрит таб и наваксва при visibilitychange.
 *
 * TypeScript strict; зависимости: само съществуващият api клиент (api.ts)
 * — НУЛА нови npm пакети.
 * ========================================================================== */
import { useEffect, useState } from 'react'
import { api } from './api'

/* ============================================================================
 * 1. Типове
 * ========================================================================== */

/** Видовете събития от /v1/anomalies (мета.py). */
export type AnomalyKind = 'deadletter' | 'notify_failed' | 'notify_sent' | 'rule_publish'

/** Едно събитие от лентата на аномалиите. */
export interface AnomalyEvent {
  /** ISO низ (лексикографското сравнение на ISO низове = хронологично). */
  ts: string
  kind: AnomalyKind
  /** Човешки етикет, напр. „мъртва буква: <ref>" / „известие failed: <канал>". */
  label: string
}

/** Форматът на успешния отговор (api() вече е развързал обвивката .data). */
interface AnomaliesResponse {
  hours: number
  events: AnomalyEvent[]
}

/** ЕДНОТО място с филтъра „бронирано или информационно". Т7 мени само него. */
function isArmor(kind: string): kind is 'deadletter' | 'notify_failed' {
  return kind === 'deadletter' || kind === 'notify_failed'
}

/** Състоянието, което консумират топбар чипът и sidebar badge-ът. */
export interface AnomalyCountState {
  /** deadletter + notifyFailed — числото в чипа и badge-а. */
  total: number
  deadletter: number
  notifyFailed: number
  /** true само при потвърдени от API „0 аларми" (виж clean логиката горе). */
  clean: boolean
  /** ts на най-новото бронирано събитие (ISO) или null при няма/неизвестно. */
  lastTs: string | null
  /* --- разширения: tooltip на чипа, дедуп анализ, честност на състоянието --- */
  /** Различни label-и сред бронята (индикатор за шум — notes.md §Рискове). */
  uniqueLabels: number
  notifySent: number
  rulePublish: number
  /** Първият успешен fetch минал ли е („зареждане…" vs „без аларми"). */
  loaded: boolean
  /** Последна грешка от /v1/anomalies (tooltip) или null. */
  error: string | null
  /** Оглед на hours от сървъра (1..168) — за етикета „(24ч)". */
  hours: number
}

/* ============================================================================
 * 2. Опции + начално състояние
 * ========================================================================== */

export interface UseAnomalyCountOptions {
  /** Прозорец в часове (сървърът клампва 1..168). Default 24 — спекът на Т6. */
  hours?: number
  /** Каданс на полинга. Default 10 s — стратегия В3. */
  pollMs?: number
}

export const ANOMALY_DEFAULT_HOURS = 24
export const ANOMALY_DEFAULT_POLL_MS = 10_000

const INITIAL_STATE: AnomalyCountState = {
  total: 0,
  deadletter: 0,
  notifyFailed: 0,
  clean: false,
  lastTs: null,
  uniqueLabels: 0,
  notifySent: 0,
  rulePublish: 0,
  loaded: false,
  error: null,
  hours: ANOMALY_DEFAULT_HOURS,
}

/* ============================================================================
 * 3. useAnomalyCount
 * ========================================================================== */

/**
 * Алармен брой за шел-а: полинг на /v1/anomalies?hours=… на всеки pollMs.
 *
 * Жизнен цикъл: интервал + AbortController + visibilitychange, всички
 * чистени в cleanup (StrictMode-безопасно — двоен ефект само прави по един
 * излишен fetch при mount в dev). При демонтиране вървящата заявка се
 * прекъсва (abort) и disposed флагът гаси късните setState.
 */
export function useAnomalyCount({
  hours = ANOMALY_DEFAULT_HOURS,
  pollMs = ANOMALY_DEFAULT_POLL_MS,
}: UseAnomalyCountOptions = {}): AnomalyCountState {
  const [state, setState] = useState<AnomalyCountState>(INITIAL_STATE)

  useEffect(() => {
    let disposed = false
    let busy = false // без паралелни заявки при бавен API + кратък интервал
    let ctl: AbortController | null = null

    const load = async () => {
      if (busy || disposed || document.hidden) return
      busy = true
      ctl = new AbortController()
      try {
        const body = await api<AnomaliesResponse>(`/v1/anomalies?hours=${hours}`, {
          signal: ctl.signal,
        })
        if (disposed) return
        // defensive (правило №4 на docs/16): API-то може да изненада
        const events: AnomalyEvent[] = Array.isArray(body?.events) ? body.events : []

        let deadletter = 0
        let notifyFailed = 0
        let notifySent = 0
        let rulePublish = 0
        let lastTs: string | null = null
        const labels = new Set<string>()
        for (const ev of events) {
          const kind: string = ev?.kind ?? ''
          if (!isArmor(kind)) {
            if (kind === 'notify_sent') notifySent += 1
            else if (kind === 'rule_publish') rulePublish += 1
            continue // информационно събитие — не броим
          }
          if (kind === 'deadletter') deadletter += 1
          else notifyFailed += 1
          labels.add(typeof ev?.label === 'string' ? ev.label : '')
          if (typeof ev?.ts === 'string' && (lastTs === null || ev.ts > lastTs)) {
            lastTs = ev.ts // max по ISO низ = най-новото (без доверие в сорта)
          }
        }
        const total = deadletter + notifyFailed
        setState({
          total,
          deadletter,
          notifyFailed,
          notifySent,
          rulePublish,
          uniqueLabels: labels.size,
          clean: total === 0, // успешен отговор → 0 е потвърдено „чисто"
          loaded: true,
          error: null,
          lastTs,
          hours: typeof body?.hours === 'number' ? body.hours : hours,
        })
      } catch (err) {
        if (disposed) return // abort при unmount не е събитие за UI-то
        // пази последното известно (stale); clean се отмята — не твърдим „чисто"
        setState((prev) => ({
          ...prev,
          error: err instanceof Error ? err.message : String(err),
          clean: false,
        }))
      } finally {
        busy = false
      }
    }

    const onVisible = () => {
      if (!document.hidden) void load() // скритият таб не пули; върнал се → веднага
    }

    const id = setInterval(() => void load(), pollMs)
    void load() // първо четене веднага, не след 10 s
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      disposed = true
      clearInterval(id)
      document.removeEventListener('visibilitychange', onVisible)
      ctl?.abort()
    }
  }, [hours, pollMs])

  return state
}
