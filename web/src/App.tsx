import { Suspense, lazy, useEffect, useMemo, useState } from 'react'
import { STALE_AFTER_HOURS, STATIONS } from './config'
import {
  fetchCurrentH2S, fetchEffluent, fetchOceanLayers, fetchPeaks, fetchSeries, fetchWeather,
  type EffluentRow, type GeoJson, type PeakRow, type SeriesRow, type StationReading, type WeatherRow,
} from './lib/fetchers'
import { levelFor } from './lib/h2s'
import { formatLocal, nearestByTime } from './lib/time'
import { STRINGS, type Lang } from './lib/i18n'
import type { MapPoint, PlantReading } from './components/MapView'

/** deck.gl and MapLibre are most of the bundle. Loading them after first paint
 *  lets the readings — the part a resident actually came for — render first. */
const MapView = lazy(() =>
  import('./components/MapView').then((m) => ({ default: m.MapView })),
)
import { CurrentConditions } from './components/CurrentConditions'
import { H2SChart, type PlotGeometry } from './components/H2SChart'
import { LongTermPanel } from './components/LongTermPanel'
import { DATA_BASE } from './config'

const WEEK_MS = 7 * 86_400_000

/** Each feed loads independently so one stalled source cannot blank the page. */
function useAsync<T>(fn: () => Promise<T>, fallback: T) {
  const [state, setState] = useState<{ data: T; loading: boolean; error: string | null }>({
    data: fallback, loading: true, error: null,
  })
  useEffect(() => {
    let alive = true
    fn().then(
      (data) => alive && setState({ data, loading: false, error: null }),
      (err: unknown) =>
        alive && setState({ data: fallback, loading: false, error: String(err) }),
    )
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return state
}

export default function App() {
  const [lang, setLang] = useState<Lang>('en')
  const strings = STRINGS[lang]

  const current = useAsync<StationReading[]>(fetchCurrentH2S, [])
  const weather = useAsync<WeatherRow[]>(fetchWeather, [])
  const effluent = useAsync<EffluentRow[]>(fetchEffluent, [])
  const series = useAsync<SeriesRow[]>(fetchSeries, [])
  const peaks = useAsync<PeakRow[]>(fetchPeaks, [])
  const ocean = useAsync<{ hazard: GeoJson | null; sites: GeoJson | null }>(
    fetchOceanLayers, { hazard: null, sites: null },
  )

  // The slider is lined up with the chart's plotting area so the handle sits
  // directly above the moment it selects; the y-axis inset would otherwise
  // offset the two by the axis width.
  const [plotGeometry, setPlotGeometry] = useState<PlotGeometry>({ left: 0, right: 0 })

  const [showWind, setShowWind] = useState(true)
  const [showOcean, setShowOcean] = useState(false)
  const [showPlant, setShowPlant] = useState(true)

  /**
   * The 7-day window ends at the last hour actually present in the data, not at
   * "now". When the ingest stalls, an empty window centred on today would be
   * indistinguishable from a genuinely quiet week.
   */
  const window7 = useMemo(() => {
    if (!series.data.length) return { rows: [] as SeriesRow[], times: [] as number[] }
    const end = series.data[series.data.length - 1].time.getTime()
    const rows = series.data.filter((r) => r.time.getTime() >= end - WEEK_MS)
    const times = [...new Set(rows.map((r) => r.time.getTime()))].sort((a, b) => a - b)
    return { rows, times }
  }, [series.data])

  const [cursorIdx, setCursorIdx] = useState<number | null>(null)
  useEffect(() => {
    if (window7.times.length) setCursorIdx(window7.times.length - 1)
  }, [window7.times.length])

  const cursorTime = cursorIdx != null && window7.times[cursorIdx] != null
    ? new Date(window7.times[cursorIdx]) : null

  /**
   * What the map draws. Live readings when the cursor is at the end of the
   * window; the historical row for that hour when the user scrubs back.
   */
  const points: MapPoint[] = useMemo(() => {
    const atCursor = cursorTime
      ? window7.rows.filter((r) => r.time.getTime() === cursorTime.getTime())
      : []
    const scrubbed = cursorIdx != null && cursorIdx < window7.times.length - 1

    return STATIONS.map((station) => {
      const row = atCursor.find((r) => r.site === station.slug)
      const live = current.data.find((r) => r.station.slug === station.slug)
      const w = nearestByTime(
        weather.data.filter((x) => x.site === station.slug),
        (x) => x.time,
        cursorTime ?? new Date(),
      )
      const ppb = scrubbed ? (row?.h2s ?? null) : (live?.ppb ?? row?.h2s ?? null)
      return {
        station,
        ppb,
        level: scrubbed ? levelFor(ppb) : (live?.level ?? levelFor(ppb)),
        windSpeedKmh: row?.windSpeedKmh ?? w?.windSpeedKmh ?? null,
        windDirDeg: row?.windDirDeg ?? w?.windDirDeg ?? null,
        stableAtm: row?.stableAtm ?? null,
      }
    })
  }, [cursorTime, cursorIdx, window7, current.data, weather.data])

  const latestWeather = useMemo(() => {
    const rows = weather.data.filter((w) => w.site === 'nestor_bes')
    return rows.length ? nearestByTime(rows, (r) => r.time, new Date()) : null
  }, [weather.data])

  const latestEffluent = effluent.data.length ? effluent.data[effluent.data.length - 1] : null

  const plantReading: PlantReading | null = latestEffluent
    ? { mgd: latestEffluent.mgd, observedAt: latestEffluent.time }
    : null

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>{strings.title}</h1>
          <p className="subtitle">{strings.subtitle}</p>
        </div>
        <div className="lang" role="group" aria-label="Language / Idioma">
          <button type="button" className={lang === 'en' ? 'chip chip-active' : 'chip'}
                  aria-pressed={lang === 'en'} onClick={() => setLang('en')}>English</button>
          <button type="button" className={lang === 'es' ? 'chip chip-active' : 'chip'}
                  aria-pressed={lang === 'es'} onClick={() => setLang('es')}>Español</button>
        </div>
      </header>

      <main className="layout">
        <div className="map-column">
          <Suspense fallback={<div className="map map-loading">{strings.loading}</div>}>
            <MapView
              points={points}
              plant={plantReading}
              showPlant={showPlant}
              ocean={ocean.data.hazard}
              showWind={showWind}
              showOcean={showOcean}
              strings={strings}
              lang={lang}
            />
          </Suspense>

          <div className="map-controls">
            <fieldset className="layers">
              <legend>{strings.layers}</legend>
              <label>
                <input type="checkbox" checked={showWind} onChange={(e) => setShowWind(e.target.checked)} />
                {strings.layerWind}
              </label>
              <label>
                <input type="checkbox" checked={showPlant}
                       onChange={(e) => setShowPlant(e.target.checked)} />
                {strings.layerPlant}
              </label>
              <label>
                <input type="checkbox" checked={showOcean}
                       disabled={!ocean.data.hazard}
                       onChange={(e) => setShowOcean(e.target.checked)} />
                {strings.layerOcean}
              </label>
            </fieldset>
          </div>

          <section className="panel" aria-labelledby="week-heading">
            <h2 id="week-heading">{strings.sevenDay}</h2>
            <p className="note">{strings.sevenDayNote}</p>
            {window7.times.length > 0 && (
              <>
                <p className="note">
                  {strings.windowRange}{' '}
                  {formatLocal(new Date(window7.times[0]), { hour: undefined, minute: undefined })}
                  {' – '}
                  {formatLocal(new Date(window7.times[window7.times.length - 1]))}
                </p>
                {/* The heading says "the last 7 days"; when the feed is behind,
                    say so rather than letting the heading imply currency. */}
                {Date.now() - window7.times[window7.times.length - 1] > 2 * 86_400_000 && (
                  <p className="warning">{strings.windowHistoric}</p>
                )}
              </>
            )}

            {series.loading ? (
              <p className="freshness">{strings.loading}</p>
            ) : series.error || !window7.times.length ? (
              <p className="freshness stale">{strings.loadError}</p>
            ) : (
              <>
                <div className="slider-head">
                  <output>{formatLocal(cursorTime)}</output>
                </div>
                <div className="slider-row">
                  <input
                    type="range"
                    min={0}
                    max={window7.times.length - 1}
                    value={cursorIdx ?? window7.times.length - 1}
                    onChange={(e) => setCursorIdx(Number(e.target.value))}
                    aria-label={strings.sevenDay}
                    style={{
                      marginLeft: `${plotGeometry.left}px`,
                      marginRight: `${plotGeometry.right}px`,
                    }}
                  />
                </div>
                <H2SChart
                  rows={window7.rows}
                  cursorTime={cursorTime}
                  onScrub={(t) => {
                    const i = window7.times.indexOf(t.getTime())
                    if (i >= 0) setCursorIdx(i)
                  }}
                  onGeometry={setPlotGeometry}
                  strings={strings}
                />
              </>
            )}
          </section>
        </div>

        <aside className="side">
          {current.loading ? (
            <section className="panel"><p className="freshness">{strings.loading}</p></section>
          ) : (
            <CurrentConditions
              readings={current.data}
              weather={latestWeather}
              effluent={latestEffluent}
              strings={strings}
              lang={lang}
            />
          )}

          <LongTermPanel peaks={peaks.data} strings={strings} />

          <section className="panel">
            <h2>{strings.whatThisMeans}</h2>
            <ul className="legend">
              {(['green', 'yellow', 'orange'] as const).map((level) => (
                <li key={level}>
                  <span className="swatch" style={{ background: `var(--band-${level})` }} aria-hidden="true" />
                  <span>{strings.guidance[level]}</span>
                </li>
              ))}
            </ul>
            <p className="note">{strings.windLegend}</p>
            <p className="note">{strings.windCalmLegend}</p>
            <h2>{strings.aboutTitle}</h2>
            <p className="note">{strings.about}</p>
            <p className="note">
              {strings.dataFrom}: <code>{DATA_BASE}</code>
            </p>
            <p className="note">{strings.staleFootnote(STALE_AFTER_HOURS)}</p>
          </section>
        </aside>
      </main>
    </div>
  )
}
