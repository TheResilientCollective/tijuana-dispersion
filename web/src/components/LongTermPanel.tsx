import { useMemo, useState } from 'react'
import { STATIONS } from '../config'
import { BANDS } from '../lib/h2s'
import { formatLocal } from '../lib/time'
import type { PeakRow } from '../lib/fetchers'
import type { Strings } from '../lib/i18n'

type Window = 7 | 30 | 90

/**
 * Hours per evening above 5 ppb and 30 ppb, per station, over a selectable
 * window. `h2s_peaks` already carries these counts, so the whole view is a
 * client-side slice of a 21 KB file.
 *
 * Nights are what matter: 98% of extreme events are nocturnal
 * (docs/project_context.md, finding 4), so night periods lead and day periods
 * are folded into the same daily bar behind them.
 */
export function LongTermPanel({ peaks, strings }: { peaks: PeakRow[]; strings: Strings }) {
  const [days, setDays] = useState<Window>(30)

  const { byStation, latest } = useMemo(() => {
    if (!peaks.length) return { byStation: [], latest: null as Date | null }
    const latest = peaks[peaks.length - 1].date
    const cutoff = latest.getTime() - days * 86_400_000
    const windowed = peaks.filter((p) => p.date.getTime() >= cutoff)

    // Every day in the window gets a slot, including days with no record at
    // all. Plotting only the days that happen to have rows makes a sparse
    // record look like a dense one, and stretches two bars across the panel.
    const dayStarts: number[] = []
    const endDay = Date.UTC(latest.getUTCFullYear(), latest.getUTCMonth(), latest.getUTCDate())
    for (let i = days - 1; i >= 0; i--) dayStarts.push(endDay - i * 86_400_000)

    const byStation = STATIONS.map((station) => {
      const rows = windowed.filter((p) => p.site === station.slug)
      const nights = rows.filter((p) => p.period === 'night')
      const over5 = rows.reduce((a, p) => a + p.hoursOver5, 0)
      const over30 = rows.reduce((a, p) => a + p.hoursOver30, 0)

      const perDate = new Map<number, { over5: number; over30: number; recorded: boolean }>()
      for (const p of rows) {
        const key = Date.UTC(p.date.getUTCFullYear(), p.date.getUTCMonth(), p.date.getUTCDate())
        const cur = perDate.get(key) ?? { over5: 0, over30: 0, recorded: false }
        perDate.set(key, {
          over5: cur.over5 + p.hoursOver5,
          over30: cur.over30 + p.hoursOver30,
          recorded: true,
        })
      }

      return {
        station,
        over5,
        over30,
        daysRecorded: perDate.size,
        nightsWithAny: nights.filter((p) => p.hoursOver5 > 0).length,
        bars: dayStarts.map((t) => ({ t, ...(perDate.get(t) ?? { over5: 0, over30: 0, recorded: false }) })),
      }
    })
    return { byStation, latest }
  }, [peaks, days])

  const maxBar = Math.max(
    1,
    ...byStation.flatMap((s) => s.bars.map((b) => b.over5)),
  )

  return (
    <section className="panel" aria-labelledby="longterm-heading">
      <h2 id="longterm-heading">{strings.longTerm}</h2>
      <p className="note">{strings.longTermNote}</p>

      <div className="window-select" role="group" aria-label={strings.longTerm}>
        {([7, 30, 90] as Window[]).map((w) => (
          <button
            key={w}
            type="button"
            className={w === days ? 'chip chip-active' : 'chip'}
            aria-pressed={w === days}
            onClick={() => setDays(w)}
          >
            {w === 7 ? strings.window7 : w === 30 ? strings.window30 : strings.window90}
          </button>
        ))}
      </div>

      {!peaks.length ? (
        <p className="freshness stale">{strings.noData}</p>
      ) : (
        <>
          <ul className="longterm">
            {byStation.map((s) => (
              <li key={s.station.slug}>
                <div className="longterm-head">
                  <span className="reading-station">{s.station.label}</span>
                  <span className="longterm-counts">
                    <span style={{ color: BANDS[1].color }}>
                      {s.over5} {strings.hoursOver5.toLowerCase()}
                    </span>
                    {' · '}
                    <span style={{ color: BANDS[2].color }}>
                      {s.over30} {strings.hoursOver30.toLowerCase()}
                    </span>
                  </span>
                </div>
                <div className="bars" aria-hidden="true">
                  {s.bars.map((b) => (
                    <span
                      key={b.t}
                      className={b.recorded ? 'bar' : 'bar bar-missing'}
                      title={`${formatLocal(new Date(b.t), { hour: undefined, minute: undefined })}: ${
                        b.recorded ? `${b.over5} h > 5 ppb, ${b.over30} h > 30 ppb` : 'no record'
                      }`}
                    >
                      <span
                        className="bar-fill"
                        style={{
                          height: `${Math.max(b.over5 > 0 ? 6 : 0, (b.over5 / maxBar) * 100)}%`,
                          background: BANDS[1].color,
                        }}
                      />
                      <span
                        className="bar-fill bar-over"
                        style={{
                          height: `${Math.max(b.over30 > 0 ? 6 : 0, (b.over30 / maxBar) * 100)}%`,
                          background: BANDS[2].color,
                        }}
                      />
                    </span>
                  ))}
                </div>
                {s.daysRecorded === 0 && <p className="freshness">{strings.noData}</p>}
              </li>
            ))}
          </ul>
          {latest && (
            <p className="freshness">
              {strings.asOf} {formatLocal(latest, { hour: undefined, minute: undefined })}
            </p>
          )}
        </>
      )}
    </section>
  )
}
