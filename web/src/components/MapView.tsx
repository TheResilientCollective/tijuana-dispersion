import { useEffect, useRef } from 'react'
import maplibregl, { Map as MapLibreMap } from 'maplibre-gl'
import { MapboxOverlay } from '@deck.gl/mapbox'
import { IconLayer, ScatterplotLayer, TextLayer, GeoJsonLayer } from '@deck.gl/layers'

import { BASEMAP_STYLE, INITIAL_VIEW, SBIWTP, STATIONS, type Station } from '../config'
import { rgbaFor, type Level } from '../lib/h2s'
import type { GeoJson } from '../lib/fetchers'
import type { Lang, Strings } from '../lib/i18n'
import { calmGlyph, compassPoint, glyphAngle, isStagnant, windGlyph } from '../lib/wind'

/** What the map draws at the currently selected instant. */
export interface MapPoint {
  station: Station
  ppb: number | null
  level: Level
  windSpeedKmh: number | null
  windDirDeg: number | null
  /** 1 when the model classes the hour as stably stratified. */
  stableAtm: number | null
}

/** Current treated flow leaving the plant, with the day it was measured. */
export interface PlantReading {
  mgd: number | null
  observedAt: Date | null
}

interface Props {
  points: MapPoint[]
  plant: PlantReading | null
  showPlant: boolean
  ocean: GeoJson | null
  showWind: boolean
  showOcean: boolean
  strings: Strings
  lang: Lang
}

/**
 * The treatment-plant marker.
 *
 * A square, not a circle: the round pins on this map are H2S readings coloured
 * by concentration band, and a plant is not a reading. Keeping the shape and
 * the palette distinct stops it being read as a fourth monitoring station.
 */
function plantGlyph(): string {
  const size = 128
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  if (!ctx) return ''

  const x = 30
  const w = size - 60
  const r = 10
  const box = () => {
    ctx.beginPath()
    ctx.moveTo(x + r, x)
    ctx.arcTo(x + w, x, x + w, x + w, r)
    ctx.arcTo(x + w, x + w, x, x + w, r)
    ctx.arcTo(x, x + w, x, x, r)
    ctx.arcTo(x, x, x + w, x, r)
    ctx.closePath()
  }

  ctx.strokeStyle = 'rgba(255,255,255,0.95)'
  ctx.lineWidth = 16
  box()
  ctx.stroke()

  ctx.fillStyle = '#37474f'
  box()
  ctx.fill()

  // A gap through the middle reads as a works/facility rather than a solid pin.
  ctx.strokeStyle = '#ffffff'
  ctx.lineWidth = 8
  ctx.beginPath()
  ctx.moveTo(x + 12, x + w / 2)
  ctx.lineTo(x + w - 12, x + w / 2)
  ctx.stroke()

  return canvas.toDataURL()
}

export function MapView({ points, plant, ocean, showWind, showOcean, showPlant, strings, lang }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const overlayRef = useRef<MapboxOverlay | null>(null)
  const iconRef = useRef<string>('')
  const calmRef = useRef<string>('')
  const plantRef = useRef<string>('')

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
    iconRef.current = windGlyph()
    calmRef.current = calmGlyph()
    plantRef.current = plantGlyph()

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

    const hasWind = points.filter((p) => p.windDirDeg != null && p.windSpeedKmh != null)
    // A direction arrow on a stagnant night asserts transport that is not
    // happening. Those stations get a ring instead. See lib/wind.ts.
    const withWind = hasWind.filter((p) => !isStagnant(p.stableAtm, p.windSpeedKmh))
    const stagnant = hasWind.filter((p) => isStagnant(p.stableAtm, p.windSpeedKmh))

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

        showPlant && plant && plantRef.current
          ? new IconLayer<PlantReading>({
              id: 'plant',
              data: [plant],
              getPosition: () => [SBIWTP.lon, SBIWTP.lat],
              getIcon: () => ({
                url: plantRef.current,
                width: 128,
                height: 128,
                anchorX: 64,
                anchorY: 64,
                mask: false,
              }),
              getSize: 26,
              sizeUnits: 'pixels',
              pickable: true,
            })
          : null,

        showPlant && plant
          ? new TextLayer<PlantReading>({
              id: 'plant-label',
              data: [plant],
              getPosition: () => [SBIWTP.lon, SBIWTP.lat],
              getText: (d) =>
                d.mgd == null
                  ? SBIWTP.label
                  : `${SBIWTP.label} · ${d.mgd.toFixed(1)} MGD`,
              getSize: 12,
              getColor: [55, 71, 79, 255],
              // Left of the marker: the San Ysidro monitor is 1.8 km north-east
              // and its pin, calm ring and wind text fill the space above and
              // below. Centring this label would put it under that cluster.
              getTextAnchor: 'end',
              getPixelOffset: [-18, 0],
              fontWeight: 700,
              outlineWidth: 4,
              outlineColor: [255, 255, 255, 255],
              fontSettings: { sdf: true },
              characterSet: 'auto',
              background: false,
              pickable: false,
              updateTriggers: { getText: plant.mgd },
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
              characterSet: 'auto',
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
              // The glyph's head points downwind and its tail bar sits on the
              // upwind side, so the reader does not have to know which
              // convention is in play. See lib/wind.ts.
              getAngle: (d) => glyphAngle(d.windDirDeg),
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

        showWind && calmRef.current
          ? new IconLayer<MapPoint>({
              id: 'wind-calm',
              data: stagnant,
              getPosition: (d) => [d.station.lon, d.station.lat],
              getIcon: () => ({
                url: calmRef.current,
                width: 128,
                height: 128,
                anchorX: 64,
                anchorY: 64,
                mask: false,
              }),
              getSize: 34,
              sizeUnits: 'pixels',
              getPixelOffset: [0, 30],
              pickable: false,
              updateTriggers: { getPosition: stagnant.map((p) => p.station.slug).join(',') },
            })
          : null,

        showWind
          ? new TextLayer<MapPoint>({
              id: 'wind-calm-labels',
              data: stagnant,
              getPosition: (d) => [d.station.lon, d.station.lat],
              getText: () => strings.windCalm,
              getSize: 11,
              getColor: [28, 63, 110, 255],
              getPixelOffset: [0, 68],
              fontWeight: 600,
              outlineWidth: 4,
              outlineColor: [255, 255, 255, 255],
              fontSettings: { sdf: true },
              characterSet: 'auto',
              background: false,
              pickable: false,
              updateTriggers: { getText: strings.windCalm },
            })
          : null,

        // The direction in words, because an arrow alone is ambiguous to anyone
        // who assumes the opposite convention — and reading it backwards here
        // means mistaking which way an odor plume is heading.
        showWind
          ? new TextLayer<MapPoint>({
              id: 'wind-labels',
              data: withWind,
              getPosition: (d) => [d.station.lon, d.station.lat],
              getText: (d) => `${strings.windFrom} ${compassPoint(d.windDirDeg, lang)}`,
              getSize: 11,
              getColor: [28, 63, 110, 255],
              getPixelOffset: [0, 68],
              fontWeight: 600,
              outlineWidth: 4,
              outlineColor: [255, 255, 255, 255],
              fontSettings: { sdf: true },
              characterSet: 'auto',
              background: false,
              pickable: false,
              updateTriggers: {
                getText: withWind.map((p) => p.windDirDeg).join(',') + lang,
              },
            })
          : null,
      ].filter(Boolean) as never[],

      getTooltip: ({ object }: { object?: MapPoint | PlantReading }) => {
        if (!object) return null
        const style = { fontSize: '0.85rem', padding: '6px 8px', maxWidth: '260px' }
        if ('station' in object) {
          return {
            html: `<strong>${object.station.label}</strong><br/>${
              object.ppb == null ? strings.noData : `${object.ppb.toFixed(1)} ${strings.ppb}`
            }`,
            style,
          }
        }
        // The plant reading runs days behind the monitors, so the tooltip
        // carries its own date rather than borrowing the map's cursor.
        const when = object.observedAt
          ? new Intl.DateTimeFormat(lang === 'es' ? 'es-US' : 'en-US', {
              timeZone: 'America/Los_Angeles', month: 'short', day: 'numeric',
            }).format(object.observedAt)
          : '—'
        return {
          html: `<strong>${strings.plantName}</strong><br/>${
            object.mgd == null ? strings.noData : `${object.mgd.toFixed(1)} MGD · ${when}`
          }<br/><span style="opacity:.8">${strings.plantTooltip}</span>`,
          style,
        }
      },
    })
  }, [points, plant, ocean, showWind, showOcean, showPlant, strings, lang])

  return <div className="map" ref={containerRef} aria-label={STATIONS.map((s) => s.label).join(', ')} />
}
