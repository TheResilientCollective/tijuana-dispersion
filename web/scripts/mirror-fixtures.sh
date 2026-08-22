#!/usr/bin/env bash
# Mirror the objects the map reads into public/data/ for offline development.
#
# The app normally fetches straight from the object store. This script snapshots
# the same keys to disk so the UI can be developed, screenshotted and reviewed
# without network access — point VITE_DATA_BASE at /data to use them.
#
#   ./scripts/mirror-fixtures.sh [BASE_URL]
set -euo pipefail

BASE="${1:-https://oss.resilientservice.mooo.com/test}"
OUT="$(dirname "$0")/../public/data"

KEYS=(
  "tijuana/sd_apcd_air/output/hs2_current.geojson"
  "tijuana/sd_apcd_air/output/lastvalue_h2s.geojson"
  "latest/tijuana/forecast_data/modeldata_h2s_nofill.parquet"
  "latest/tijuana/forecast_data/h2s_peaks.parquet"
  "latest/tijuana/weather_15min/nestor_bes/forecast_15min.csv"
  "latest/tijuana/weather_15min/ib_civic_ctr/forecast_15min.csv"
  "latest/tijuana/weather_15min/san_ysidro/forecast_15min.csv"
  "latest/tijuana/effluent_flow/yearly/effluent_flow_2026.csv"
  "latest/tijuana/oceanmodel/pfm_shoreline_hazard/shoreline_hazard.geojson"
  "latest/tijuana/oceanmodel/pfm_site_markers/site_markers.geojson"
)

for key in "${KEYS[@]}"; do
  dest="$OUT/$key"
  mkdir -p "$(dirname "$dest")"
  if curl -fsS -o "$dest" "$BASE/$key"; then
    printf '  ok   %8s  %s\n' "$(du -h "$dest" | cut -f1)" "$key"
  else
    printf '  MISS           %s\n' "$key"
    rm -f "$dest"
  fi
done

# An offline basemap so the UI can be reviewed without third-party tiles: the
# basin hydrography clipped to the valley, drawn as lines under the stations.
STREAMS_SRC="$BASE/tijuana/gis/tjbasin/streams.geojson"
STREAMS_OUT="$(dirname "$0")/../public/basemap/streams-valley.geojson"
mkdir -p "$(dirname "$STREAMS_OUT")"
if curl -fsS -o /tmp/tj-streams.geojson "$STREAMS_SRC"; then
  python3 - "$STREAMS_OUT" <<'PYEOF'
import json, sys
W, S, E, N = -117.28, 32.42, -116.96, 32.72
src = json.load(open('/tmp/tj-streams.geojson'))

def inside(c):
    if isinstance(c[0], (int, float)):
        return W <= c[0] <= E and S <= c[1] <= N
    return any(inside(x) for x in c)

feats = [f for f in src['features']
         if f.get('geometry') and inside(f['geometry']['coordinates'])]
json.dump({'type': 'FeatureCollection', 'features': feats}, open(sys.argv[1], 'w'))
print(f'  ok   {len(feats)} stream features clipped to the valley')
PYEOF
  rm -f /tmp/tj-streams.geojson
else
  printf '  MISS           basin hydrography for the offline basemap\n'
fi
