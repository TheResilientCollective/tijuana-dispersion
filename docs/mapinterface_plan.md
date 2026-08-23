# Map Interface of Data — implementation plan

Plan for the public-facing H₂S map described in
[`docs/prompts/mapinterface_of_data.md`](prompts/mapinterface_of_data.md).

Audience: residents of Imperial Beach, Nestor, San Ysidro and the Tijuana River
Valley who want to know *what am I smelling, how bad is it, and why*. Secondary
audience: reporters and agency staff who want the same picture with numbers
attached.

Status: phases 1, 2 and 4 are built (see the `web/` directory in this repo);
phase 3 is under way. The data inventory below was verified against the live
MinIO endpoint on 2026-08-23 (see *Verification notes*).

---

## 1. Decisions taken

| Question | Decision |
|---|---|
| Where does the app live? | A new standalone repo, `tijuana-map`. Not in this repo — `AGENTS.md` rule 4 makes the deploy surface (`Dockerfile`, `railway.json`) human-approval-only, and a Node/TS build does not belong in a Python service image. Not in `resilient_workflows_public` either — the pipelines should not gate a front-end deploy. |
| Where does the browser read data from? | Directly from the **`resilentpublic`** bucket on `https://oss.resilientservice.mooo.com` — note the spelling, it is missing the second `i` and is not a typo to be corrected. No API server in the read path. |
| UI stack | **MapLibre GL JS + deck.gl**, in a React + Vite + TypeScript shell. Details and rationale in §3. |

---

## 2. Data inventory

Endpoint: `https://oss.resilientservice.mooo.com/resilentpublic/<key>`

The object layout is set in code by `resilient_core.utils.store_assets`. Assets
written with `enable_latest_path=True` also land under a mirrored
`latest/<path>/<name>.<ext>` key that is overwritten in place — those are the
stable URLs the front end should use, because they never change name as new
periods are published. Every dataset is emitted in several formats
(`.csv`, `.json`, `.geojson`, `.parquet`) plus a sidecar `.metadata.json`
carrying schema.org `Dataset` metadata including `dateModified`.

### 2.1 Static map (current conditions)

| Panel | Key | Format / size | Fields | Cadence |
|---|---|---|---|---|
| Current H₂S at the 3 stations | `tijuana/sd_apcd_air/output/hs2_current.geojson` | GeoJSON, ~2 KB | `SiteName`, `Date with time`, `Result` (ppb), `level` | hourly |
| Same, "last known value" (for keeping pins on the map when a station drops out) | `tijuana/sd_apcd_air/output/lastvalue_h2s.geojson` | GeoJSON, ~2 KB | as above | hourly |
| Temperature + humidity | `latest/tijuana/weather_15min/{nestor_bes,ib_civic_ctr,san_ysidro}/forecast_15min.csv` | CSV, ~18 KB each | `time`, `temperature_2m`, `relative_humidity_2m`, `dew_point_2m` | 15-min |
| Wind speed + direction | same files | | `wind_speed_10m`, `wind_direction_10m`, `wind_gusts_10m` | 15-min |
| SBIWTP effluent flow | `latest/tijuana/effluent_flow/yearly/effluent_flow_2026.csv` | CSV, ~5 KB | `Timestamp (UTC-08:00)`, `Value (M US Gal/d)` | **daily** |
| Ocean prediction (Scripps PFM) | `latest/tijuana/oceanmodel/pfm_shoreline_hazard/shoreline_hazard.geojson`, `.../pfm_site_markers/site_markers.geojson`, `.../pfm_site_timeseries/site_timeseries.json`, `.../pfm_hour0_contours/hour0_contours_<YYYYMMDD>.geojson` | GeoJSON / JSON, tens of KB | shoreline hazard classes, dye contours | daily when PFM publishes |

H₂S colour bands are already defined server-side by `h2s_guidance()` in
`workflows/tijuana/src/tijuana/assets/sd_apcd.py` and shipped in the `level`
field: **green** < 5 ppb, **yellow** 5–30, **orange** ≥ 30. The map must use the
same bands so the site never disagrees with the rest of the system. Anchor the
public wording on the project's own threshold work (`docs/project_context.md`):
odour complaints start near 2 ppb, cross 50 % likelihood at 8–10 ppb, are
near-certain above 50 ppb.

### 2.2 Dynamic map (last 7 days)

| Layer | Key | Format / size | Notes |
|---|---|---|---|
| H₂S time series (slider + plot) | `latest/tijuana/forecast_data/modeldata_h2s.parquet` (or `_nofill`) | parquet, 6.9 MB | hourly, all stations, to 2026-08-21, already joined to weather, streamflow and tide. The single best backing table for the slider — but see section 5 B, it is a modelling table and the map should be reading a trimmed web bundle instead. |
| H₂S last 24 h at 15-min | `latest/tijuana/forecast_data/modeldata_h2s_15min_24hour.parquet` | parquet, 31 KB | ideal for the "today" default view |
| Raw H₂S history | `latest/tijuana/sd_apcd_air/h2s_all/h2s_all.parquet` | parquet, 288 KB | **last written 2026-04-06 and its rows stop in Dec 2025** — unlike the rest of the bucket this one really is stale, so use `modeldata_*` for anything recent |
| Wind vectors over time | `latest/tijuana/weather_15min/<site>/forecast_15min.csv` and `latest/tijuana/weather/<site>/<year>.parquet` | | 3 point locations only — see §4 for the field question |
| Channel flow (border → estuary) | `latest/tijuana/streamflow/boundary_cms/…`, `latest/tijuana/streamflow/canal_cms/…` (IBWC gauge 11013300 and the Tijuana Canal) | CSV/parquet | hourly discharge |
| Plant effluent | as §2.1 | | daily only |
| Modelled plume frames | `latest/tijuana/dispersion/forward_grid_frames_latest.json` | JSON, **20 MB** | 24 hourly frames, each `{bounds:{n,s,e,w}, data:[[…]]}` — a ready-made animation source, but far too large to ship as-is (§5, item D) |
| Modelled receptor forecast | `latest/tijuana/dispersion/forward_forecast_latest.json` | JSON, 27 KB | per-station predicted ppb at 15-min, plus source attribution (east/west/south g/s) |

### 2.3 Long-term view (7 / 30 / 90 day)

`latest/tijuana/forecast_data/h2s_peaks.parquet` — **39 KB**, and it is exactly
the requested statistic:

```
site_name, date, period(day|night), count_exceeds_5, count_exceeds_30,
total_measurements, max_h2s, mean_h2s, count_filled
```

One row per station per day per day/night period, back to Dec 2024. "Hours over
5 ppb and 30 ppb for an evening at Nestor" is a filter on this file, and the
7/30/90-day window selector is a client-side slice of a 39 KB download. No new
pipeline work is needed for the long-term view.

Companion datasets, if the long-term view grows: `h2s_exceedance_model_data_5ppb`
/ `_30ppb` (full hourly environment during exceedance periods, 1.5 MB / 0.4 MB
parquet) and `h2s_wind_lag_analysis` (8 KB).

### 2.4 Base geography

- `tijuana/gis/tjbasin/streams.geojson` (5.4 MB) and `subbasin.geojson` (3.7 MB) —
  whole-basin hydrography. Too large and too broad to ship to a phone; the map
  needs a hand-curated cut (§5, item C).
- `tijuana/gis/boundaries/tracts.geojson` (18 MB), `subregional_areas.geojson`
  (11 MB) — census/neighbourhood polygons, only if a demographic overlay is
  wanted later. Would need simplification and clipping first.

---

## 3. UI library — recommendation

**MapLibre GL JS 5 + deck.gl 9, in React 19 + Vite + TypeScript.**

Why this combination for these specific requirements:

- *Animated wind vectors.* deck.gl renders particle/vector fields on the GPU.
  Tens of thousands of advected particles stay at 60 fps; the same thing in
  DOM-based Leaflet does not. `WindLayer`-style particle advection over a u/v
  grid is a well-trodden deck.gl pattern.
- *A 24-frame concentration raster.* `BitmapLayer` with a per-frame texture, or a
  `HeatmapLayer` when frames are point-sampled. Frame swapping is a texture bind,
  not a re-layout.
- *Time slider over a week of data.* React state drives both the map layer and
  the plot; a single `currentTime` value in a store keeps them locked together.
- *No API keys and no tile bill.* Basemap from **Protomaps PMTiles** — a single
  `.pmtiles` extract clipped to the Tijuana River Valley / South Bay, served from
  the same MinIO bucket via HTTP range requests. The endpoint already returns
  `Access-Control-Allow-Origin: *` and exposes `Content-Range`, so range reads
  work from the browser today. A valley-sized extract at z0–14 is on the order of
  20–60 MB stored, and a viewer downloads only the tiles it looks at.
- *Charts.* **uPlot** for the H₂S-over-the-week strip under the slider (a few KB,
  handles 10k+ points without effort) and for the long-term exceedance bars. Not
  a heavyweight charting framework.
- *Geometry helpers.* `@turf/turf` for buffering and interpolating along the
  channel centre lines.
- *Parquet in the browser.* `hyparquet` (small, pure-TS, no WASM) or DuckDB-WASM
  if querying gets more ambitious. This is what makes the parquet twins worth
  using instead of the 4–10 MB CSVs.

Leaflet was the alternative and remains a reasonable fallback if the animated
layers turn out to be more than this audience needs — it is smaller and simpler,
and `leaflet-velocity` does static wind particles well. But the raster frames and
the smooth week-long scrub are exactly where it struggles, so start with MapLibre.

Accessibility and reach matter more than usual here: this page is for residents
deciding whether to keep the windows shut. Budget for a text-first fallback panel
("Right now at Nestor: 12 ppb — moderate odour likely"), colour bands that survive
colour-blind viewing, Spanish/English copy, and a page that is useful on a
three-year-old Android phone over cellular.

---

## 4. Where wind data for the vectors comes from

Three tiers, in increasing order of effort:

1. **Point vectors from what we already ingest (do this first).** Open-Meteo
   15-min data at the three station sites, already published as
   `latest/tijuana/weather_15min/<site>/forecast_15min.csv` with
   `wind_speed_10m` / `wind_direction_10m` / `wind_gusts_10m`. Three arrows on
   the map, animated along the time slider. Honest, cheap, immediately available.
   Synoptic station observations (`tijuana/weather/synoptic/<STID>/`, stations
   BFDSD / CVXSD / TIXC1) can be added as observed rather than modelled arrows.

2. **A small gridded field for particle animation (the recommended target).**
   Open-Meteo's forecast API accepts arbitrary lat/lon and is free for
   non-commercial use, so a 6 × 6 grid spanning roughly 32.45–32.70 N,
   −117.25 to −117.00 W at 15-min resolution is 36 points — one scheduled Dagster
   asset, no new credentials, no new vendor. Publish it in the u/v grid format
   the browser wind-particle layers expect (a `header` with `lo1/la1/dx/dy/nx/ny`
   plus flat `data` arrays for the u and v components), which is a ~50 KB JSON
   per timestep set. This is what makes "wind as vectors" look like weather
   rather than three arrows.

3. **A real mesoscale field, if the science later demands it.** NOAA HRRR at 3 km
   (hourly, free on AWS S3 as GRIB2) or NBM. Heavier: GRIB decoding, a much
   larger ingest, and 3 km barely resolves the valley. Not justified for a public
   information page — but worth noting that the dispersion modelling side may
   want it independently.

Caveat worth stating on the page: Open-Meteo winds are a *model* at 10 m, not an
observation, and the calm nocturnal conditions that produce the worst H₂S
episodes are exactly the conditions where gridded wind models are weakest. The
project's own regime work says the same thing — see `regime.py` and the
stagnation guardrail in this repo. Where the wind field says "calm", the map
should say "calm — odour can pool" rather than drawing misleadingly confident
arrows.

---

## 5. Gaps that need pipeline work

These are additions to `resilient_workflows_public` (the `tijuana` code
location), not to this repo.

**A. Public read access.** *Resolved — nothing to do.* `resilentpublic` is
already exactly what the map needs: anonymous `GET` and `ListObjectsV2` both
succeed, `Access-Control-Allow-Origin: *` is set, `Content-Range` is exposed so
parquet and PMTiles range reads work from the browser, and it holds 63,382 live
objects written continuously by the pipelines. No policy change, no mirroring
step, no API proxy.

**B. A `web/` prefix of map-ready bundles.** The analysis outputs are shaped for
modelling, not for a phone. A small set of derived assets, each rewritten in
place on a schedule:

- `web/tijuana/current.json` — one object with current H₂S per station, temp,
  humidity, wind, latest effluent flow, and a `generated_at` stamp. One request
  paints the whole static view.
- `web/tijuana/h2s_7day.json` — 7 days × 3 stations, hourly, ~50 KB. This one
  now matters more than it did: the map currently downloads the full 6.9 MB
  `modeldata` parquet to render one week of it.
- `web/tijuana/wind_grid_7day.json` — the u/v grid from §4.2.
- `web/tijuana/channel_flow_7day.json` — see C.
- `web/tijuana/exceedance_90day.json` — a slice of `h2s_peaks`.

**C. Channel geometry and channel flow colouring.** The prompt asks for two
coloured reaches: the plant to the Saturn Blvd bridge in the north channel, and
the plant down the main channel to the Saturn St crossing. Two pieces are
missing. First, geometry: `streams.geojson` is a 5.4 MB whole-basin layer, so a
hand-curated `web/tijuana/channels.geojson` with those two named reaches (split
into ~200 m segments so colour can vary along the reach) needs to be authored
once and committed. Second, the data: `effluent_flow` is **plant effluent, daily,
one number** — it is not channel flow and it is not hourly. The honest mapping is
to colour the reaches from the hourly IBWC gauges (`boundary_cms`, `canal_cms`)
and show plant effluent as a separate daily indicator, with the label saying
which is which. Worth confirming with the domain owner before building: is the
intent "how much is flowing down each channel" (gauges) or "how much is bypassing
the plant" (effluent deficit — the inverse relationship documented as finding 1
in `docs/project_context.md`)?

**D. Shrink the dispersion frames.** `forward_grid_frames_latest.json` is 20 MB
of JSON for 24 frames. Re-emit as 24 small PNGs (concentration quantised to a
palette, one image per frame, with the bounds in a tiny sidecar JSON) — a few
hundred KB total, and `BitmapLayer` consumes PNGs natively. Alternatively a
quantised binary array. Either way, the current file must not be fetched by a
browser.

**E. `effluent_flow_today` does not publish.** The only genuine data gap. The
asset exists in `ibwc_flows.py` and fetches SBIWTP's *Today* endpoint, but
nothing lands under `tijuana/effluent_flow/output/effluent_flow_today/` — the
only prefixes present are `effluent_flow_current_year/` and
`effluent_flow_yearly/`. So plant discharge is available daily, not hourly, and
the map's "right now" discharge figure is really "yesterday's daily total".
Either fix the asset or label the panel as a daily value; the map currently does
the latter.

**F. Publish freshness on the page, not just in the pipeline.** Every feed is
current (see *Verification notes*), but an object's write time is not the same
as the age of the observation inside it, and the two can diverge silently when a
scraper starts returning stale rows. The front end reads the observation
timestamp on every panel and flags anything older than three hours. Keep that
behaviour rather than assuming currency.

---

## 6. Phased delivery

**Phase 0 — unblock.** *Not needed.* The bucket is public, CORS-open and full of
current data. The front end was built straight against it.

**Phase 1 — the static map.** New `tijuana-map` repo: Vite + React + TS,
MapLibre with a PMTiles basemap of the valley, three H₂S station pins coloured by
the existing green/yellow/orange bands, a current-conditions card (temp,
humidity, wind arrow, effluent flow), a plain-language "what does this mean"
panel in English and Spanish, and per-panel freshness stamps. Deployed to
Netlify or Cloudflare Pages as a static site. This alone answers most of what a
resident wants to know.

**Phase 2 — 7-day dynamic map.** Time slider bound to a shared `currentTime`;
H₂S strip chart under the slider (uPlot) doubling as the scrub control; wind
arrows at the three sites animating with the slider; ocean-model and shoreline
hazard layers toggleable. Data from `h2s_7day.json` and the 15-min weather files.

**Phase 3 — wind field and channel colouring.** Pipeline items B (wind grid) and
C (channel geometry + flow), then the deck.gl particle layer and the coloured
reaches. This is the phase that makes the page feel like a live picture of the
valley rather than a dashboard.

**Phase 4 — long-term view.** The 7/30/90-day selector over `h2s_peaks`: hours
over 5 ppb and over 30 ppb per station per evening, as a calendar heatmap plus
per-station bars. Cheap (39 KB of data) and it is the view that shows the scale
of the burden — 22.8 % of days since Jan 2024 above 30 ppb somewhere in the
network.

**Phase 5 (optional) — modelled plume.** Item D, then the animated concentration
frames as a `BitmapLayer` under the station pins, clearly labelled *model, not
measurement*, and honouring the `stagnation_flags` / `out_of_envelope` fields the
service already returns so the map does not show a confident plume during exactly
the calm-night regime where the plume model has no skill.

---

## 7. Open questions for the project owner

1. Channel colouring (§5 C): gauge discharge, or plant-effluent deficit? They
   tell opposite-signed stories about odour risk.
2. Should the public page show the *modelled* plume at all (Phase 5), or only
   measurements? Showing a model to a worried public raises the bar on labelling
   and on handling the stagnation regime.
3. Bilingual copy — who writes and reviews the Spanish?
4. Where does this get hosted and linked from — is there an existing
   Resilient Collective site it should live under?
5. Does the map need a shareable permalink state (time + layers in the URL) for
   reporters and agency staff to cite a specific moment? Cheap to add early,
   awkward to retrofit.

---

## Verification notes

Checked live on 2026-08-23 against `https://oss.resilientservice.mooo.com`:

- **`resilentpublic`** is the production bucket — 63,382 objects, written
  continuously (the newest at 04:00 UTC on the day of checking). Anonymous `GET`
  and `ListObjectsV2` both return 200, `Access-Control-Allow-Origin: *`,
  `Content-Range` exposed. Every key, size, schema and column name quoted above
  was read from it.
- Content, not just object timestamps, is current: `hs2_current.geojson` carried
  readings stamped 19:00 the previous evening (Nestor 1.0 ppb, IB 1.0, San
  Ysidro 0.4, all green); `modeldata_h2s_nofill.parquet` runs to 2026-08-21 with
  53,260 rows; `h2s_peaks.parquet` to 2026-08-21 with 3,908 rows.
- `tijuana/effluent_flow/output/effluent_flow_today/` does not exist; only the
  current-year and yearly prefixes do. This is the one real gap (section 5 E).
- Two similarly-named buckets on the same endpoint are **not** the source and
  caused a wrong reading of this system in an earlier draft of this document:
  `resilientpublic` (correctly spelled, publicly listable, **empty**) and `test`
  (publicly listable, holds a partial copy whose H2S feeds stopped in April
  2026). An earlier version of this plan drew its inventory from `test` and
  concluded the monitoring feeds had stalled. They had not. If a dataset here
  looks months old, check which bucket is being read before concluding anything
  about the pipelines.
