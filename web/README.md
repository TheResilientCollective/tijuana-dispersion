# tijuana-map

A public map of hydrogen sulfide (H₂S), wind and river conditions in the
Tijuana River Valley — for residents of Imperial Beach, Nestor and San Ysidro
who want to know what they are smelling and how bad it is.

Static site. No server, no API keys, no build-time data. Everything on the page
is fetched at runtime from the public object store that the
[`resilient_workflows_public`](https://github.com/TheResilientCollective/resilient_workflows_public)
Dagster pipelines publish to.

Implements Phases 1, 2 and 4 of the plan in
`docs/mapinterface_plan.md` in the
[`tijuana-dispersion`](https://github.com/TheResilientCollective/tijuana-dispersion)
repo.

## Quick start

```
npm install
cp .env.example .env      # then pick a VITE_DATA_BASE, see below
npm run dev
```

`npm run build` produces a static `dist/` for Netlify, Cloudflare Pages, or any
static host. `npm run typecheck` runs the TypeScript project check.

## Which bucket

`resilientpublic` is the public bucket and the intended source — it is
anonymously readable and listable, sends `Access-Control-Allow-Origin: *`, and
exposes `Content-Range` so parquet range reads work from the browser.

**It is empty today.** The pipelines still publish to the `test` bucket. Until
that is repointed (section 5 A of the plan), override the default to see real
data:

```
VITE_DATA_BASE=https://oss.resilientservice.mooo.com/test
```

### Working offline

```
./scripts/mirror-fixtures.sh                 # snapshot the keys the app reads
VITE_DATA_BASE=/data \
VITE_BASEMAP_STYLE=./basemap/offline-style.json npm run dev
```

The script also clips the basin hydrography into a minimal MapLibre style, so
the UI can be developed and reviewed with no third-party tile requests.

## What it shows

| Panel | Source |
|---|---|
| Current H₂S at the three SDAPCD monitors | `tijuana/sd_apcd_air/output/hs2_current.geojson`, with `lastvalue_h2s` behind it so a station that drops out keeps its pin |
| Temperature, humidity, wind | `latest/tijuana/weather_15min/<site>/forecast_15min.csv` (Open-Meteo, 15-minute) |
| Treatment plant discharge | `latest/tijuana/effluent_flow/yearly/effluent_flow_<year>.csv` (SBIWTP, daily, MGD) |
| 7-day slider, chart and wind vectors | `latest/tijuana/forecast_data/modeldata_h2s_nofill.parquet` |
| Hours above 5 / 30 ppb, 7–90 days | `latest/tijuana/forecast_data/h2s_peaks.parquet` |
| Ocean plume forecast (optional layer) | `latest/tijuana/oceanmodel/pfm_shoreline_hazard/shoreline_hazard.geojson` |

H₂S bands (green < 5 ppb, yellow 5–30, orange ≥ 30) mirror `h2s_guidance()` in
the pipelines, which also ships the band as a `level` field. The server's value
wins where present, so the map cannot disagree with the rest of the system.

## Honesty about stale data

Several upstream feeds have stalled while their objects continue to be
rewritten, so an object's own timestamp is not evidence that the reading in it
is current. Every panel therefore shows the *observation* time, flags anything
older than three hours, and the 7-day view says plainly when it is showing the
most recent published week rather than the week just gone. A map that silently
shows a months-old reading is worse than a map that shows nothing.

## Stack

- **MapLibre GL JS** — vector basemap, no API key.
- **deck.gl** — station pins, labels and wind arrows on the GPU; the layer that
  Phase 3's wind-particle field will plug into.
- **uPlot** — the H₂S strip chart, which redraws on every slider tick.
- **hyparquet** — reads the published parquet directly in the browser, loaded on
  demand so it stays off the critical path.
- **React + Vite + TypeScript**.

The map engine is code-split and lazy-loaded: the readings paint first, on a
~20 KB gzipped entry chunk, because that is what a resident actually came for.

## Accessibility and reach

Built for a three-year-old Android phone on cellular. Colour is never the only
signal — every band is stated in words as well. Interface and guidance copy are
bilingual (English / Spanish); the Spanish is a working draft and needs a native
speaker's review before launch.

## Not built yet

Phase 3 (gridded wind field and channel flow colouring) and Phase 5 (modelled
plume frames) both need new pipeline assets first — see sections 5 B–D of the
plan.
