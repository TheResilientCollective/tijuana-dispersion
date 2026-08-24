import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { STATIONS } from '../config'
import { BANDS } from '../lib/h2s'
import type { SeriesRow } from '../lib/fetchers'
import type { Strings } from '../lib/i18n'

const SERIES_COLORS = ['#1c3f6e', '#a6572a', '#4b7f52']

/**
 * H2S over the selected window, one line per station, with the 5 and 30 ppb
 * thresholds drawn in and a cursor marking the instant the map is showing.
 *
 * uPlot rather than a charting framework: this redraws on every slider tick and
 * needs to stay smooth on a mid-range phone.
 */
/** Insets of the plotting area within the chart, in CSS pixels. */
export interface PlotGeometry {
  left: number
  right: number
}

export function H2SChart({
  rows,
  cursorTime,
  onScrub,
  onGeometry,
  strings,
}: {
  rows: SeriesRow[]
  cursorTime: Date | null
  onScrub?: (t: Date) => void
  /** Reports where the plotting area sits so the slider can line up with it. */
  onGeometry?: (g: PlotGeometry) => void
  strings: Strings
}) {
  const hostRef = useRef<HTMLDivElement>(null)
  const plotRef = useRef<uPlot | null>(null)
  const scrubRef = useRef(onScrub)
  scrubRef.current = onScrub
  const geometryRef = useRef(onGeometry)
  geometryRef.current = onGeometry

  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    // One shared time axis; stations are sampled onto it by timestamp.
    const times = [...new Set(rows.map((r) => r.time.getTime()))].sort((a, b) => a - b)
    if (!times.length) {
      plotRef.current?.destroy()
      plotRef.current = null
      host.innerHTML = ''
      return
    }
    const index = new Map(times.map((t, i) => [t, i]))
    const perStation = STATIONS.map(() => new Array<number | null>(times.length).fill(null))
    for (const r of rows) {
      const i = index.get(r.time.getTime())
      const s = STATIONS.findIndex((st) => st.slug === r.site)
      if (i != null && s >= 0) perStation[s][i] = r.h2s
    }

    const data: uPlot.AlignedData = [
      times.map((t) => t / 1000),
      ...perStation,
    ] as uPlot.AlignedData

    // uPlot reports its plotting box in canvas pixels; the slider needs CSS.
    const reportGeometry = (u: uPlot) => {
      const ratio = uPlot.pxRatio || window.devicePixelRatio || 1
      const left = u.bbox.left / ratio
      const right = Math.max(0, u.width - (u.bbox.left + u.bbox.width) / ratio)
      geometryRef.current?.({ left, right })
    }

    const thresholds: uPlot.Plugin = {
      hooks: {
        draw: (u) => {
          const { ctx } = u
          ctx.save()
          for (const ppb of [5, 30]) {
            const y = u.valToPos(ppb, 'y', true)
            if (!Number.isFinite(y)) continue
            ctx.strokeStyle = ppb === 5 ? BANDS[1].color : BANDS[2].color
            ctx.setLineDash([4, 4])
            ctx.lineWidth = 1
            ctx.beginPath()
            ctx.moveTo(u.bbox.left, y)
            ctx.lineTo(u.bbox.left + u.bbox.width, y)
            ctx.stroke()
          }
          ctx.restore()
        },
      },
    }

    const plot = new uPlot(
      {
        width: host.clientWidth || 640,
        height: 190,
        padding: [10, 24, 0, 0],
        cursor: { drag: { x: false, y: false } },
        legend: { show: true },
        scales: { x: { time: true } },
        axes: [
          {},
          { label: `H₂S (${strings.ppb})`, labelSize: 42, size: 46 },
        ],
        series: [
          {},
          ...STATIONS.map((s, i) => ({
            label: s.label,
            stroke: SERIES_COLORS[i],
            width: 1.6,
            spanGaps: false,
          })),
        ],
        plugins: [thresholds],
        hooks: {
          // Clicking the chart scrubs the map to that moment.
          ready: [
            (u: uPlot) => {
              u.over.addEventListener('click', () => {
                const i = u.cursor.idx
                if (i != null && scrubRef.current) {
                  scrubRef.current(new Date((u.data[0][i] as number) * 1000))
                }
              })
              reportGeometry(u)
            },
          ],
          // The axis width depends on the tick labels, so it is only known
          // after a draw and changes when the data does.
          setSize: [reportGeometry],
          draw: [reportGeometry],
        },
      },
      data,
      host,
    )
    plotRef.current = plot

    const onResize = () => plot.setSize({ width: host.clientWidth || 640, height: 190 })
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      plot.destroy()
      plotRef.current = null
    }
  }, [rows, strings])

  // Keep the chart cursor on the instant the map is drawing. `rows` is a
  // dependency because a data change rebuilds the plot, which drops the cursor.
  useEffect(() => {
    const plot = plotRef.current
    if (!plot || !cursorTime) return
    const xs = plot.data[0] as number[]
    const target = cursorTime.getTime() / 1000
    let best = 0
    for (let i = 1; i < xs.length; i++) {
      if (Math.abs(xs[i] - target) < Math.abs(xs[best] - target)) best = i
    }
    plot.setCursor({ left: plot.valToPos(xs[best], 'x'), top: 1 })
  }, [cursorTime, rows])

  return <div className="chart" ref={hostRef} />
}
