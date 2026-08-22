/**
 * Freshness handling.
 *
 * Several of the upstream feeds have stalled while their objects continue to be
 * rewritten, so an object's own timestamp is not evidence that the reading in it
 * is current. Every panel therefore carries the timestamp of the *observation*
 * and says plainly how old it is. A map that silently shows a months-old H2S
 * reading is worse than a map that shows nothing.
 */

export interface Freshness {
  observedAt: Date | null
  ageHours: number | null
  stale: boolean
}

export function freshness(observedAt: Date | null, staleAfterHours: number): Freshness {
  if (!observedAt || Number.isNaN(observedAt.getTime())) {
    return { observedAt: null, ageHours: null, stale: true }
  }
  const ageHours = (Date.now() - observedAt.getTime()) / 3_600_000
  return { observedAt, ageHours, stale: ageHours > staleAfterHours }
}

const PACIFIC = 'America/Los_Angeles'

export function formatLocal(d: Date | null, opts: Intl.DateTimeFormatOptions = {}): string {
  if (!d || Number.isNaN(d.getTime())) return '—'
  return new Intl.DateTimeFormat('en-US', {
    timeZone: PACIFIC,
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    ...opts,
  }).format(d)
}

export function formatAge(ageHours: number | null, lang: 'en' | 'es'): string {
  if (ageHours == null) return lang === 'es' ? 'sin datos' : 'no data'
  if (ageHours < 1.5) {
    const mins = Math.max(1, Math.round(ageHours * 60))
    return lang === 'es' ? `hace ${mins} min` : `${mins} min ago`
  }
  if (ageHours < 48) {
    const h = Math.round(ageHours)
    return lang === 'es' ? `hace ${h} h` : `${h} h ago`
  }
  const days = Math.round(ageHours / 24)
  return lang === 'es' ? `hace ${days} días` : `${days} days ago`
}

/** Pick the row nearest a target instant — the feeds are not on a shared clock. */
export function nearestByTime<T>(rows: T[], time: (r: T) => Date, target: Date): T | null {
  let best: T | null = null
  let bestDelta = Infinity
  for (const r of rows) {
    const d = Math.abs(time(r).getTime() - target.getTime())
    if (d < bestDelta) {
      bestDelta = d
      best = r
    }
  }
  return best
}
