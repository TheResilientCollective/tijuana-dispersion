/** Runtime configuration. Everything the map reads is a static object-store key. */

/**
 * `resilientpublic` is the public bucket: anonymously readable and listable,
 * CORS open, Content-Range exposed. It is also empty at the time of writing —
 * the pipelines still publish to `test`. Until that moves, set VITE_DATA_BASE
 * to the `test` bucket to see real data. See docs/mapinterface_plan.md §5 A in
 * the tijuana-dispersion repo.
 */
export const DATA_BASE: string = (
  import.meta.env.VITE_DATA_BASE ?? 'https://oss.resilientservice.mooo.com/resilientpublic'
).replace(/\/$/, '')

export const BASEMAP_STYLE: string =
  import.meta.env.VITE_BASEMAP_STYLE ??
  'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json'

export const url = (key: string): string => `${DATA_BASE}/${key.replace(/^\//, '')}`

/**
 * Object keys, as written by `resilient_core.utils.store_assets` in
 * resilient_workflows_public. Assets published with `enable_latest_path=True`
 * are mirrored under `latest/` and overwritten in place, so those keys are
 * stable across publishing runs and are what we read wherever possible.
 */
export const KEYS = {
  /** Current H2S reading per station, one GeoJSON point each. */
  h2sCurrent: 'tijuana/sd_apcd_air/output/hs2_current.geojson',
  /** Last known value per station — keeps a pin on the map when a station drops out. */
  h2sLastValue: 'tijuana/sd_apcd_air/output/lastvalue_h2s.geojson',
  /** Hourly H2S joined to weather, streamflow, tide and SBIWTP flow. Backs the 7-day view. */
  modelData: 'latest/tijuana/forecast_data/modeldata_h2s_nofill.parquet',
  /** Day/night exceedance counts per station per date. Backs the long-term view. */
  peaks: 'latest/tijuana/forecast_data/h2s_peaks.parquet',
  /** 15-minute weather per station. */
  weather15min: (site: SiteSlug) => `latest/tijuana/weather_15min/${site}/forecast_15min.csv`,
  /** SBIWTP plant effluent, daily, million US gallons per day. */
  effluentYear: (year: number) =>
    `latest/tijuana/effluent_flow/yearly/effluent_flow_${year}.csv`,
  /** Scripps Plume Forecast Model shoreline hazard. */
  shorelineHazard: 'latest/tijuana/oceanmodel/pfm_shoreline_hazard/shoreline_hazard.geojson',
  /** Scripps PFM sampling sites. */
  pfmSites: 'latest/tijuana/oceanmodel/pfm_site_markers/site_markers.geojson',
} as const

export type SiteSlug = 'nestor_bes' | 'ib_civic_ctr' | 'san_ysidro'

export interface Station {
  slug: SiteSlug
  /** `SiteName` as it appears in the APCD feeds — the join key across datasets. */
  apcdName: string
  label: string
  lat: number
  lon: number
}

/** The three SDAPCD continuous H2S monitors. Coordinates from docs/project_context.md. */
export const STATIONS: Station[] = [
  { slug: 'nestor_bes', apcdName: 'NESTOR - BES', label: 'Nestor', lat: 32.567097, lon: -117.090656 },
  { slug: 'ib_civic_ctr', apcdName: 'IB CIVIC CTR', label: 'Imperial Beach', lat: 32.576139, lon: -117.115361 },
  { slug: 'san_ysidro', apcdName: 'SAN YSIDRO', label: 'San Ysidro', lat: 32.552794, lon: -117.047286 },
]

export const stationByApcdName = (name: string): Station | undefined =>
  STATIONS.find((s) => s.apcdName === name.trim())

/** Map view over the valley, the estuary and the border crossings. */
export const INITIAL_VIEW = { longitude: -117.09, latitude: 32.5655, zoom: 11.6 }

/** A panel older than this is called out as stale rather than shown as current. */
export const STALE_AFTER_HOURS = 3
