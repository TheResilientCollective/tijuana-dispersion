/**
 * Wind direction: conventions, naming, and the glyph.
 *
 * `wind_direction_10m` is a meteorological direction — the direction the wind
 * blows *from*. Two display conventions exist and they point opposite ways:
 *
 *   - Wind barbs and station plots point INTO the wind, toward its origin.
 *   - Flow arrows (windy.com, earth.nullschool) point DOWNWIND, the way the air
 *     is travelling.
 *
 * A reader who assumes the other convention reads every arrow backwards, which
 * on this page means mistaking where an odour plume is heading. So the map does
 * not rely on the reader knowing which convention is in play: the glyph carries
 * a tail on the upwind side and a head on the downwind side, and the direction
 * is also spelled out in words next to it.
 */

import type { Lang } from './i18n'

/**
 * Wind speed below which a direction arrow over-states what is known.
 *
 * Measured on the published record at Nestor: hours above 5 ppb are below this
 * speed 41% of the time, and hours above 30 ppb 55% of the time, against 8% for
 * clean hours. Under this the air is barely moving and the modelled bearing is
 * close to arbitrary.
 */
export const CALM_KMH = 3

/**
 * Is this hour one where a direction arrow would mislead?
 *
 * The model data carries `stable_atm`, and it is the stronger signal: at Nestor,
 * stable hours average 17.8 ppb against 3.5 for unstable ones, and carry a 38%
 * chance of exceeding 5 ppb against 12%. Those are the calm, stratified nights
 * when H2S pools rather than travelling — the same regime the dispersion
 * service's `regime.is_stagnation()` flags as having no plume skill. Where the
 * flag is absent, fall back to the speed threshold.
 */
export function isStagnant(
  stableAtm: number | null | undefined,
  windSpeedKmh: number | null | undefined,
): boolean {
  if (stableAtm === 1) return true
  return windSpeedKmh != null && windSpeedKmh < CALM_KMH
}

const POINTS_EN = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                   'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']

/** Spanish uses O for Oeste, so the western points differ from the English. */
const POINTS_ES = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                   'S', 'SSO', 'SO', 'OSO', 'O', 'ONO', 'NO', 'NNO']

/** Compass point for a bearing in degrees, or an em dash when unknown. */
export function compassPoint(deg: number | null | undefined, lang: Lang = 'en'): string {
  if (deg == null || Number.isNaN(deg)) return '—'
  const points = lang === 'es' ? POINTS_ES : POINTS_EN
  return points[Math.round((((deg % 360) + 360) % 360) / 22.5) % 16]
}

export const kmhToMph = (kmh: number | null | undefined): number | null =>
  kmh == null ? null : kmh * 0.621371

/**
 * Rotation for the glyph, in deck.gl's convention (counter-clockwise positive,
 * zero pointing up/north as the icon is drawn).
 *
 * The glyph is drawn head-up, so pointing the head downwind means rotating
 * clockwise by the downwind bearing — hence the negation.
 */
export function glyphAngle(windFromDeg: number | null | undefined): number {
  return -(((windFromDeg ?? 0) + 180) % 360)
}

/**
 * The wind glyph, drawn once into a canvas and reused as a deck.gl icon atlas.
 *
 * Drawn pointing up, i.e. as if the air were travelling north:
 *
 *        ^        arrowhead — the direction the air is going (downwind)
 *        |
 *        |        shaft
 *       ---       tail bar — the side the wind comes from (upwind)
 *
 * deck.gl rotates the sprite per datum, so one texture serves every station and
 * every timestep. Generating it here keeps the app free of binary assets.
 */
export function windGlyph(): string {
  const size = 128
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  if (!ctx) return ''

  const mid = size / 2
  const fill = '#1c3f6e'
  const halo = 'rgba(255,255,255,0.95)'

  // A white halo under every stroke keeps the glyph legible over any basemap.
  const stroke = (width: number, colour: string, draw: () => void) => {
    ctx.lineWidth = width
    ctx.strokeStyle = colour
    ctx.lineCap = 'round'
    ctx.beginPath()
    draw()
    ctx.stroke()
  }

  const shaft = () => { ctx.moveTo(mid, 26); ctx.lineTo(mid, 104) }
  const tailBar = () => { ctx.moveTo(mid - 22, 104); ctx.lineTo(mid + 22, 104) }

  stroke(16, halo, shaft)
  stroke(16, halo, tailBar)
  stroke(8, fill, shaft)
  stroke(8, fill, tailBar)

  // Arrowhead at the downwind end, haloed the same way.
  const head = () => {
    ctx.moveTo(mid, 12)
    ctx.lineTo(mid + 20, 46)
    ctx.lineTo(mid, 36)
    ctx.lineTo(mid - 20, 46)
    ctx.closePath()
  }
  ctx.lineJoin = 'round'
  ctx.lineWidth = 10
  ctx.strokeStyle = halo
  ctx.beginPath(); head(); ctx.stroke()
  ctx.fillStyle = fill
  ctx.beginPath(); head(); ctx.fill()

  return canvas.toDataURL()
}


/**
 * The calm/stagnation marker: a ring, not an arrow.
 *
 * Drawn when the air is stratified or barely moving. A ring has no direction,
 * which is the point — it says "pooling here" rather than asserting a transport
 * bearing the conditions do not support. This is the regime that produces the
 * worst H2S episodes, so it needs to read as a warning, not as missing data.
 */
export function calmGlyph(): string {
  const size = 128
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  if (!ctx) return ''

  const mid = size / 2

  // White halo first so the ring survives any basemap underneath.
  ctx.lineCap = 'round'
  ctx.strokeStyle = 'rgba(255,255,255,0.95)'
  ctx.lineWidth = 20
  ctx.beginPath()
  ctx.arc(mid, mid, 36, 0, Math.PI * 2)
  ctx.stroke()

  // A dashed ring reads as "unsettled" rather than as a solid boundary.
  ctx.strokeStyle = '#1c3f6e'
  ctx.lineWidth = 10
  ctx.setLineDash([14, 10])
  ctx.beginPath()
  ctx.arc(mid, mid, 36, 0, Math.PI * 2)
  ctx.stroke()
  ctx.setLineDash([])

  // A dot at the centre keeps it legible when scaled down on a phone.
  ctx.fillStyle = '#1c3f6e'
  ctx.beginPath()
  ctx.arc(mid, mid, 7, 0, Math.PI * 2)
  ctx.fill()

  return canvas.toDataURL()
}
