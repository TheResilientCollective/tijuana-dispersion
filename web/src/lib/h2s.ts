/**
 * H2S concentration bands.
 *
 * These mirror `h2s_guidance()` in
 * workflows/tijuana/src/tijuana/assets/sd_apcd.py, which ships the band as a
 * `level` field on the published GeoJSON. The map must not disagree with the
 * rest of the system, so the thresholds live here in one place and the server's
 * `level` string is treated as authoritative when present.
 *
 * Odour-likelihood wording is drawn from the threshold analysis in
 * docs/project_context.md: complaints begin near 2 ppb, cross 50% likelihood at
 * 8-10 ppb, and are near-certain above 50 ppb.
 */

export type Level = 'green' | 'yellow' | 'orange' | 'purple' | 'white'

export interface Band {
  level: Level
  min: number
  max: number | null
  /** Accessible fill, checked against both light and dark card backgrounds. */
  color: string
}

export const BANDS: Band[] = [
  { level: 'green', min: 0, max: 5, color: '#2e8b57' },
  { level: 'yellow', min: 5, max: 30, color: '#d99b00' },
  { level: 'orange', min: 30, max: 27000, color: '#d4501e' },
  { level: 'purple', min: 27000, max: null, color: '#7b3fa0' },
]

export const NO_DATA_COLOR = '#8b8b90'

export function levelFor(ppb: number | null | undefined): Level {
  if (ppb == null || Number.isNaN(ppb)) return 'white'
  for (const b of BANDS) {
    if (b.max === null) {
      if (ppb >= b.min) return b.level
    } else if (ppb >= b.min && ppb < b.max) {
      return b.level
    }
  }
  return 'white'
}

export function colorFor(level: Level): string {
  return BANDS.find((b) => b.level === level)?.color ?? NO_DATA_COLOR
}

/** deck.gl and MapLibre want RGBA tuples, not hex. */
export function rgbaFor(level: Level, alpha = 255): [number, number, number, number] {
  const hex = colorFor(level).replace('#', '')
  return [
    parseInt(hex.slice(0, 2), 16),
    parseInt(hex.slice(2, 4), 16),
    parseInt(hex.slice(4, 6), 16),
    alpha,
  ]
}
