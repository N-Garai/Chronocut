import { useEffect, useMemo, useRef } from 'react'
import { rulerTicks, tickLabel } from '../../timeline/time'

/**
 * Ruler — paints adaptive second/minute ticks. The pointer session (preview
 * on move, commit on release) attaches to the track body; the ruler itself
 * has no state.
 */
export default function Ruler({ widthPx, pps }) {
  const ticks = useMemo(() => rulerTicks(pps), [pps])
  const stepPx = (ticks.major / 1000) * pps
  const minorPx = (ticks.minor / 1000) * pps

  const majors = useMemo(() => {
    const out = []
    for (let i = 0; ; i++) {
      const px = i * stepPx
      if (px > widthPx) break
      out.push({ px, label: tickLabel(i * ticks.major) })
      if (i > 4000) break
    }
    return out
  }, [stepPx, widthPx, ticks.major])

  const minors = useMemo(() => {
    const out = []
    const count = Math.floor(widthPx / minorPx)
    for (let i = 1; i <= count; i++) {
      const px = i * minorPx
      // skip minors coinciding with a major tick
      if (Math.abs(px / stepPx - Math.round(px / stepPx)) < 0.0001) continue
      out.push(px)
    }
    return out
  }, [minorPx, stepPx, widthPx])

  return (
    <div data-ruler="true" className="relative h-7 select-none border-b border-white/10 bg-white/[0.02]">
      <svg className="absolute left-0 top-0 h-full" style={{ width: widthPx }} shapeRendering="crispEdges">
        {minors.map((x) => (
          <line key={`m${x}`} x1={x} x2={x} y1={18} y2={28} className="stroke-white/10" strokeWidth={1} />
        ))}
        {majors.map((m) => (
          <g key={m.px} transform={`translate(${m.px},0)`}>
            <line x1={0} x2={0} y1={10} y2={28} className="stroke-white/25" strokeWidth={1} />
            <text x={3} y={12} className="fill-white/40" fontSize={9} fontFamily="ui-monospace, SFMono-Regular, monospace">{m.label}</text>
          </g>
        ))}
      </svg>
    </div>
  )
}
