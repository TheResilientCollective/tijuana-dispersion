import { formatAge, formatLocal, type Freshness } from '../lib/time'
import type { Lang, Strings } from '../lib/i18n'

/**
 * Timestamp line shown under every reading.
 *
 * Several upstream feeds have stalled while their objects continue to be
 * rewritten, so the observation time is the only honest signal of currency.
 */
export function FreshnessLine({
  freshness,
  strings,
  lang,
}: {
  freshness: Freshness
  strings: Strings
  lang: Lang
}) {
  if (!freshness.observedAt) {
    return <p className="freshness stale">{strings.noData}</p>
  }
  return (
    <p className={freshness.stale ? 'freshness stale' : 'freshness'}>
      {freshness.stale && <span className="badge">{strings.stale}</span>}
      {strings.asOf} <time dateTime={freshness.observedAt.toISOString()}>
        {formatLocal(freshness.observedAt)}
      </time>{' '}
      ({formatAge(freshness.ageHours, lang)})
    </p>
  )
}
