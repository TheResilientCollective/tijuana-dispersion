import { STALE_AFTER_HOURS } from '../config'
import { colorFor } from '../lib/h2s'
import type { EffluentRow, StationReading, WeatherRow } from '../lib/fetchers'
import { freshness } from '../lib/time'
import { compassPoint, kmhToMph } from '../lib/wind'
import type { Lang, Strings } from '../lib/i18n'
import { FreshnessLine } from './Freshness'

const cToF = (c: number | null): number | null => (c == null ? null : c * 9 / 5 + 32)

export function CurrentConditions({
  readings,
  weather,
  effluent,
  strings,
  lang,
}: {
  readings: StationReading[]
  weather: WeatherRow | null
  effluent: EffluentRow | null
  strings: Strings
  lang: Lang
}) {
  const anyStale = readings.some((r) => freshness(r.observedAt, STALE_AFTER_HOURS).stale)

  return (
    <section className="panel" aria-labelledby="current-heading">
      <h2 id="current-heading">{strings.currentH2s}</h2>

      {anyStale && <p className="warning">{strings.staleWarning}</p>}

      <ul className="readings">
        {readings.map((r) => {
          const f = freshness(r.observedAt, STALE_AFTER_HOURS)
          return (
            <li key={r.station.slug} className="reading">
              <span className="swatch" style={{ background: colorFor(r.level) }} aria-hidden="true" />
              <div className="reading-body">
                <span className="reading-station">{r.station.label}</span>
                <span className="reading-value">
                  {r.ppb == null ? strings.noData : `${r.ppb.toFixed(1)} ${strings.ppb}`}
                </span>
                {/* The plain-language line is the point of the page — a number
                    alone does not tell a resident whether to shut the windows. */}
                <span className="reading-guidance">{strings.guidance[r.level]}</span>
                <FreshnessLine freshness={f} strings={strings} lang={lang} />
              </div>
            </li>
          )
        })}
      </ul>

      <h2>{strings.conditions}</h2>
      <dl className="metrics">
        <div>
          <dt>{strings.temperature}</dt>
          <dd>
            {weather?.temperatureC == null
              ? '—'
              : `${cToF(weather.temperatureC)!.toFixed(0)}°F / ${weather.temperatureC.toFixed(0)}°C`}
          </dd>
        </div>
        <div>
          <dt>{strings.humidity}</dt>
          <dd>{weather?.humidityPct == null ? '—' : `${weather.humidityPct.toFixed(0)}%`}</dd>
        </div>
        <div>
          <dt>{strings.wind}</dt>
          <dd>
            {weather?.windSpeedKmh == null
              ? '—'
              : `${strings.windFrom} ${compassPoint(weather.windDirDeg, lang)} ${kmhToMph(weather.windSpeedKmh)!.toFixed(0)} mph`}
          </dd>
        </div>
        <div>
          <dt>{strings.effluent}</dt>
          <dd>{effluent?.mgd == null ? '—' : `${effluent.mgd.toFixed(1)} MGD`}</dd>
        </div>
      </dl>
      {weather && (
        <FreshnessLine
          freshness={freshness(weather.time, STALE_AFTER_HOURS)}
          strings={strings}
          lang={lang}
        />
      )}
      <p className="note">{strings.effluentNote}</p>
    </section>
  )
}
