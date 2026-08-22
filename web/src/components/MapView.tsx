import { useEffect, useRef } from 'react'
import maplibregl, { Map as MapLibreMap } from 'maplibre-gl'
import { MapboxOverlay } from '@deck.gl/mapbox'
import { IconLayer, ScatterplotLayer, TextLayer, GeoJsonLayer } from '@deck.gl/layers'
import { BASEMAP_STYLE, INITIAL_VIEW, STATIONS, type Station } from '../config'
import { rgbaFor, type Level } from '../lib/h2s'
import type { GeoJson } from '../lib/fetchers'
import type { Strings } from '../lib/i18n'

/** What the map draws at the currently selected instant. */
export interface MapPoint {
  station: Station
  ppb: number | null
  level: Level
  windSpeedKmh: number | null
  windDirDeg: number | null
}

interface Props {
  points: MapPoint[]
  ocean: GeoJson | null
  showWind: boolean
  showOcean: boolean
  strings: Strings
}

/**
 * A single arrow, drawn once into a canvas and reused as a deck.gl icon atlas.
 *
 * deck.gl rotates the sprite per-datum, so one texture serves every station and
 * every timestep. Drawing it here rather than shipping a PNG keeps the app free
 * of binary assets and makes the arrow's proportions easy to tune.
 */
function arrowIcon(): string {
  const size = 128
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  if (!ctx) return ''
  ctx.fillStyle = '#1c3f6e'
  ctx.strokeStyle = 'rgba(255,255,255,0.9)'
  ctx.lineWidth = 5
  ctx.beginPath()
  ctx.moveTo(size / 2, 8)              // tip
  ctx.lineTo(size - 24, size - 20)     // right barb
  ctx.lineTo(size / 2, size - 44)      // notch
  ctx.lineTo(24, size - 20)            // left barb
  ctx.closePath()
  ctx.fill()
  ctx.stroke()
  return canvas.toDataURL()
}

export function MapView({ points, ocean, showWind, showOcean, strings }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const overlayRef = useRef<MapboxOverlay | null>(null)
  const iconRef = useRef<string>('')

  // Create the map once. Layer data changes go through the deck.gl overlay.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASEMAP_STYLE,
      center: [INITIAL_VIEW.longitude, INITIAL_VIEW.latitude],
      zoom: INITIAL_VIEW.zoom,
      attributionControl: { compact: true },
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    map.addControl(new maplibregl.ScaleControl({ unit: 'imperial' }), 'bottom-left')

    const overlay = new MapboxOverlay({ interleaved: false, layers: [] })
    map.addControl(overlay)

    mapRef.current = map
    overlayRef.current = overlay
    iconRef.current = arrowIcon()

    return () => {
      overlay.finalize()
      map.remove()
      mapRef.current = null
      overlayRef.current = null
    }
  }, [])

  useEffect(() => {
    const overlay = overlayRef.current
    if (!overlay) return

    const withWind = points.filter((p) => p.windDirDeg != null && p.windSpeedKmh != null)

    overlay.setProps({
      layers: [
        showOcean && ocean
          ? new GeoJsonLayer({
              id: 'ocean-hazard',
              data: ocean as never,
              stroked: true,
              filled: true,
              getFillColor: [56, 116, 178, 60],
              getLineColor: [56, 116, 178, 200],
              getLineWidth: 12,
              lineWidthMinPixels: 1,
              pointRadiusMinPixels: 3,
            })
          : null,

        // Halo behind each station so a pin stays legible over any basemap.
        new ScatterplotLayer<MapPoint>({
          id: 'station-halo',
          data: points,
          getPosition: (d) => [d.station.lon, d.station.lat],
          getFillColor: [255, 255, 255, 235],
          getRadius: 15,
          radiusUnits: 'pixels',
          pickable: false,
        }),

        new ScatterplotLayer<MapPoint>({
          id: 'stations',
          data: points,
          getPosition: (d) => [d.station.lon, d.station.lat],
          getFillColor: (d) => rgbaFor(d.level),
          getRadius: 11,
          radiusUnits: 'pixels',
          pickable: true,
          updateTriggers: { getFillColor: points.map((p) => p.level).join(',') },
        }),

        new TextLayer<MapPoint>({
          id: 'station-labels',
          data: points,
          getPosition: (d) => [d.station.lon, d.station.lat],
          getText: (d) =>
            d.ppb == null ? `${d.station.label} · —` : `${d.station.label} · ${d.ppb.toFixed(1)} ppb`,
          getSize: 13,
          getColor: [26, 26, 30, 255],
          getPixelOffset: [0, -24],
          fontWeight: 700,
          outlineWidth: 4,
          outlineColor: [255, 255, 255, 255],
          fontSettings: { sdf: true },
          background: false,
          pickable: false,
        }),

        showWind && iconRef.current
          ? new IconLayer<MapPoint>({
              id: 'wind-arrows',
              data: withWind,
              getPosition: (d) => [d.station.lon, d.station.lat],
              getIcon: () => ({
                url: iconRef.current,
                width: 128,
                height: 128,
                anchorX: 64,
                anchorY: 64,
                mask: false,
              }),
              // Meteorological convention: direction is where the wind comes
              // FROM, so the arrow points 180 degrees away, downwind.
              getAngle: (d) => -((d.windDirDeg ?? 0) + 180),
              // Scale with speed so a calm night reads as calm at a glance.
              getSize: (d) => 22 + Math.min(28, (d.windSpeedKmh ?? 0) * 1.2),
              sizeUnits: 'pixels',
              getPixelOffset: [0, 30],
              pickable: false,
              updateTriggers: {
                getAngle: withWind.map((p) => p.windDirDeg).join(','),
                getSize: withWind.map((p) => p.windSpeedKmh).join(','),
              },
            })
          : null,
      ].filter(Boolean) as never[],

      getTooltip: ({ object }: { object?: MapPoint }) =>
        object
          ? {
              html: `<strong>${object.station.label}</strong><br/>${
                object.ppb == null ? strings.noData : `${object.ppb.toFixed(1)} ${strings.ppb}`
              }`,
              style: { fontSize: '0.85rem', padding: '6px 8px' },
            }
          : null,
    })
  }, [points, ocean, showWind, showOcean, strings])

  return <div className="map" ref={containerRef} aria-label={STATIONS.map((s) => s.label).join(', ')} />
}
