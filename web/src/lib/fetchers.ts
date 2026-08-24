import { KEYS, STATIONS, stationByApcdName, url, type SiteSlug, type Station } from '../config'
import { levelFor, type Level } from './h2s'

/* ------------------------------------------------------------------ fetching */

async function getText(key: string): Promise<string> {
  const res = await fetch(url(key))
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${key}`)
  return res.text()
}

async function getJson<T>(key: string): Promise<T> {
  const res = await fetch(url(key))
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${key}`)
  return res.json() as Promise<T>
}

/**
 * Read a parquet published by the pipelines. They are written by pandas with
 * SNAPPY compression, so the compressors bundle is required. Range requests are
 * used under the hood, which the object store permits (it exposes Content-Range).
 */
async function getParquet(key: string, columns?: string[]): Promise<Record<string, unknown>[]> {
  // Imported on demand: the current-conditions panel does not need the parquet
  // reader, and it is ~90 KB gzipped that would otherwise block first paint.
  const [{ asyncBufferFromUrl, parquetReadObjects }, { compressors }] = await Promise.all([
    import('hyparquet'),
    import('hyparquet-compressors'),
  ])
  const file = await asyncBufferFromUrl({ url: url(key) })
  return parquetReadObjects({ file, compressors, columns })
}

/* -------------------------------------------------------------------- csv */

/**
 * Minimal CSV reader. The published files are machine-generated with plain
 * comma separators and quoted fields only where a value contains a comma, so a
 * full RFC-4180 parser would be more than this needs — but quotes are handled
 * because station long-names do contain commas.
 */
export function parseCsv(text: string): Record<string, string>[] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false

  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++ } else { quoted = false }
      } else field += c
      continue
    }
    if (c === '"') { quoted = true; continue }
    if (c === ',') { row.push(field); field = ''; continue }
    if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; continue }
    if (c === '\r') continue
    field += c
  }
  if (field.length || row.length) { row.push(field); rows.push(row) }
  if (!rows.length) return []

  const header = rows[0].map((h) => h.trim())
  return rows.slice(1)
    .filter((r) => r.some((v) => v.trim() !== ''))
    .map((r) => Object.fromEntries(header.map((h, i) => [h, (r[i] ?? '').trim()])))
}

const num = (v: unknown): number | null => {
  if (v == null || v === '') return null
  const n = typeof v === 'number' ? v : Number(String(v))
  return Number.isFinite(n) ? n : null
}

/* ------------------------------------------------------------ current H2S */

export interface StationReading {
  station: Station
  ppb: number | null
  level: Level
  observedAt: Date | null
}

interface H2SFeature {
  properties: Record<string, unknown>
}

/**
 * Current H2S per station.
 *
 * `hs2_current` carries only stations reporting in the current window, so
 * `lastvalue_h2s` is merged in behind it to keep every station on the map with
 * its last known reading rather than dropping the pin entirely.
 */
export async function fetchCurrentH2S(): Promise<StationReading[]> {
  const settled = await Promise.allSettled([
    getJson<{ features: H2SFeature[] }>(KEYS.h2sCurrent),
    getJson<{ features: H2SFeature[] }>(KEYS.h2sLastValue),
  ])

  const byStation = new Map<string, StationReading>()
  for (const result of settled) {
    if (result.status !== 'fulfilled') continue
    for (const f of result.value.features ?? []) {
      const p = f.properties
      const station = stationByApcdName(String(p.SiteName ?? p['Site Name'] ?? ''))
      if (!station || byStation.has(station.slug)) continue
      const ppb = num(p.Result)
      const raw = p['Date with time']
      const observedAt = raw ? new Date(String(raw)) : null
      byStation.set(station.slug, {
        station,
        ppb,
        level: (p.level as Level) ?? levelFor(ppb),
        observedAt,
      })
    }
  }

  return STATIONS.map(
    (station) =>
      byStation.get(station.slug) ?? { station, ppb: null, level: 'white' as Level, observedAt: null },
  )
}

/* ---------------------------------------------------------------- weather */

export interface WeatherRow {
  time: Date
  site: SiteSlug
  temperatureC: number | null
  humidityPct: number | null
  windSpeedKmh: number | null
  windDirDeg: number | null
  windGustKmh: number | null
}

/** 15-minute weather per station, from the Open-Meteo ingest. */
export async function fetchWeather(): Promise<WeatherRow[]> {
  const perSite = await Promise.allSettled(
    STATIONS.map(async (s) => {
      const rows = parseCsv(await getText(KEYS.weather15min(s.slug)))
      return rows.map((r): WeatherRow => ({
        time: new Date(r.time),
        site: s.slug,
        temperatureC: num(r.temperature_2m),
        humidityPct: num(r.relative_humidity_2m),
        windSpeedKmh: num(r.wind_speed_10m),
        windDirDeg: num(r.wind_direction_10m),
        windGustKmh: num(r.wind_gusts_10m),
      }))
    }),
  )
  return perSite
    .filter((r): r is PromiseFulfilledResult<WeatherRow[]> => r.status === 'fulfilled')
    .flatMap((r) => r.value)
    .filter((r) => !Number.isNaN(r.time.getTime()))
    .sort((a, b) => a.time.getTime() - b.time.getTime())
}

/* --------------------------------------------------------------- effluent */

export interface EffluentRow {
  time: Date
  mgd: number | null
}

/**
 * SBIWTP plant effluent, daily, in million US gallons per day.
 *
 * This is plant discharge, not channel flow. Low plant throughput means more
 * sewage reaching the river, which is why it belongs on a page about odor —
 * see finding 1 in docs/project_context.md (r = -0.47 at Nestor, 1-day lag).
 */
export async function fetchEffluent(): Promise<EffluentRow[]> {
  const year = new Date().getUTCFullYear()
  let text: string
  try {
    text = await getText(KEYS.effluentYear(year))
  } catch {
    text = await getText(KEYS.effluentYear(year - 1))
  }
  const rows = parseCsv(text)
  if (!rows.length) return []
  const tsKey = Object.keys(rows[0]).find((k) => k.toLowerCase().startsWith('timestamp'))
  const valKey = Object.keys(rows[0]).find((k) => k.toLowerCase().startsWith('value'))
  if (!tsKey || !valKey) return []
  return rows
    // The file is stamped UTC-08:00 year-round; it is not a local-time clock.
    .map((r) => ({ time: new Date(`${r[tsKey].replace(' ', 'T')}-08:00`), mgd: num(r[valKey]) }))
    .filter((r) => !Number.isNaN(r.time.getTime()))
    .sort((a, b) => a.time.getTime() - b.time.getTime())
}

/* ----------------------------------------------------------- model series */

export interface SeriesRow {
  time: Date
  site: SiteSlug
  h2s: number | null
  temperatureC: number | null
  humidityPct: number | null
  windSpeedKmh: number | null
  windDirDeg: number | null
  sbiwtpMgd: number | null
  borderFlowCms: number | null
  /** 1 when the model classes the hour as stably stratified. See lib/wind.ts. */
  stableAtm: number | null
}

/**
 * Hourly H2S already joined to weather, tide, streamflow and SBIWTP flow.
 *
 * This is the modelling table, not a web bundle — around 2.6 MB. It is the only
 * published source with H2S and wind on a shared hourly clock, so the 7-day view
 * uses it until the `web/` bundles described in the plan exist.
 */
export async function fetchSeries(): Promise<SeriesRow[]> {
  const raw = await getParquet(KEYS.modelData, [
    'time', 'site_name', 'H2S', 'temperature_2m', 'relative_humidity_2m',
    'wind_speed_10m', 'wind_direction_10m', 'sbiwtp_flow_mgd', 'Flow (m^3/s)--Border',
    'stable_atm',
  ])
  return raw
    .map((r): SeriesRow | null => {
      const station = stationByApcdName(String(r.site_name ?? ''))
      if (!station) return null
      const time = toDate(r.time)
      if (!time) return null
      return {
        time,
        site: station.slug,
        h2s: num(r.H2S),
        temperatureC: num(r.temperature_2m),
        humidityPct: num(r.relative_humidity_2m),
        windSpeedKmh: num(r.wind_speed_10m),
        windDirDeg: num(r.wind_direction_10m),
        sbiwtpMgd: num(r.sbiwtp_flow_mgd),
        borderFlowCms: num(r['Flow (m^3/s)--Border']),
        stableAtm: num(r.stable_atm),
      }
    })
    .filter((r): r is SeriesRow => r !== null)
    .sort((a, b) => a.time.getTime() - b.time.getTime())
}

/* -------------------------------------------------------------- long term */

export interface PeakRow {
  site: SiteSlug
  date: Date
  period: 'day' | 'night'
  hoursOver5: number
  hoursOver30: number
  measurements: number
  maxH2s: number | null
  meanH2s: number | null
}

/**
 * Day/night exceedance counts per station per date — 21 KB for the whole record,
 * which is why the 7/30/90-day selector can be a client-side slice.
 */
export async function fetchPeaks(): Promise<PeakRow[]> {
  const raw = await getParquet(KEYS.peaks)
  return raw
    .map((r): PeakRow | null => {
      const station = stationByApcdName(String(r.site_name ?? ''))
      const date = toDate(r.date)
      if (!station || !date) return null
      return {
        site: station.slug,
        date,
        period: r.period === 'night' ? 'night' : 'day',
        hoursOver5: num(r.count_exceeds_5) ?? 0,
        hoursOver30: num(r.count_exceeds_30) ?? 0,
        measurements: num(r.total_measurements) ?? 0,
        maxH2s: num(r.max_h2s),
        meanH2s: num(r.mean_h2s),
      }
    })
    .filter((r): r is PeakRow => r !== null)
    .sort((a, b) => a.date.getTime() - b.date.getTime())
}

/* ----------------------------------------------------------- ocean model */

export type GeoJson = { type: string; features: unknown[] }

/** Scripps Plume Forecast Model layers. Optional — they lag the other feeds. */
export async function fetchOceanLayers(): Promise<{ hazard: GeoJson | null; sites: GeoJson | null }> {
  const [hazard, sites] = await Promise.allSettled([
    getJson<GeoJson>(KEYS.shorelineHazard),
    getJson<GeoJson>(KEYS.pfmSites),
  ])
  return {
    hazard: hazard.status === 'fulfilled' ? hazard.value : null,
    sites: sites.status === 'fulfilled' ? sites.value : null,
  }
}

/* ------------------------------------------------------------------ dates */

/**
 * Parquet timestamps arrive as epoch millis, `Date`, or an ISO string depending
 * on the column's logical type, and the date32 columns arrive as day counts.
 */
function toDate(v: unknown): Date | null {
  if (v == null) return null
  if (v instanceof Date) return Number.isNaN(v.getTime()) ? null : v
  if (typeof v === 'bigint') return new Date(Number(v))
  if (typeof v === 'number') {
    // date32 columns are days since the epoch; anything larger is millis.
    const d = new Date(Math.abs(v) < 100_000 ? v * 86_400_000 : v)
    return Number.isNaN(d.getTime()) ? null : d
  }
  const d = new Date(String(v))
  return Number.isNaN(d.getTime()) ? null : d
}
