import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import Ruler from './Ruler'
import Track from './Track'
import Playhead from './Playhead'
import { edlDurationMs } from '../../lib/edl'
import { attachPlayhead } from '../../timeline/controllers/playhead'
import { snapOrRaw, snapCandidates } from '../../timeline/snapping'

/**
 * TimelineShell — the scroll surface: ruler + track rows + playhead.
 * Owns the ruler seek pointer session (preview on move, commit on release)
 * and forwards trim / drag sessions to Track → ClipBlock.
 */
export default function TimelineShell({
  edl, playheadMs, previewPlayheadMs, pps, selectedClipIds, diff,
  snapping, ripple, waveforms, thumbs, readOnly = false,
  onSeek, onZoom, onSelectMany,
  onClipSelect, onTrimCommit, onDragCommit,
}) {
  const bodyRef = useRef(null)
  const [seekPreview, setSeekPreview] = useState(null)
  const [trimPreview, setTrimPreview] = useState(null)
  const [dragPreview, setDragPreview] = useState(null)
  const [marquee, setMarquee] = useState(null)

  const durationMs = edlDurationMs(edl)
  const widthPx = useMemo(
    () => Math.max(800, Math.round(((durationMs + 6000) / 1000) * pps)),
    [durationMs, pps]
  )

  // ruler/track-body seek: pointer capture with preview/commit
  useEffect(() => {
    const el = bodyRef.current
    if (!el) return
    const snapTo = (ms) =>
      snapOrRaw(ms, snapCandidates(edl, ms, null, { excludeClipIds: selectedClipIds }), pps, { disabled: !snapping })
    return attachPlayhead({
      container: el,
      pps,
      setPreview: (ms) => setSeekPreview(snapTo(ms)),
      commit: (ms) => {
        setSeekPreview(null)
        onSeek?.(Math.min(Math.max(0, snapTo(ms)), Math.max(durationMs, 1)))
      },
    })
  }, [edl, pps, snapping, durationMs, onSeek, selectedClipIds])

  const effPreview = previewPlayheadMs != null ? previewPlayheadMs : seekPreview

  // Box select: drag on empty track space to marquee-select clips; shift/cmd
  // adds to the current selection. Disabled in the read-only (small screen) view.
  const marqueeStart = useRef(null)
  const onPointerDown = (e) => {
    if (readOnly || e.button !== 0) return
    if (e.target.closest('[data-clip-id]')) return      // clip handles its own select
    if (e.target.closest('[data-ruler]')) return         // ruler = seek
    const rect = bodyRef.current?.getBoundingClientRect()
    if (!rect) return
    marqueeStart.current = { x: e.clientX, y: e.clientY, additive: e.shiftKey || e.metaKey || e.ctrlKey,
                             scrollLeft: bodyRef.current.scrollLeft, scrollTop: bodyRef.current.scrollTop }
    setMarquee({ x: e.clientX - rect.left + bodyRef.current.scrollLeft,
                 y: e.clientY - rect.top + bodyRef.current.scrollTop, w: 0, h: 0 })
    e.currentTarget.setPointerCapture?.(e.pointerId)
  }
  const onPointerMove = (e) => {
    const start = marqueeStart.current
    if (!start) return
    const rect = bodyRef.current?.getBoundingClientRect()
    if (!rect) return
    const x = e.clientX - rect.left + bodyRef.current.scrollLeft
    const y = e.clientY - rect.top + bodyRef.current.scrollTop
    setMarquee({
      x: Math.min(start.x - rect.left + start.scrollLeft, x),
      y: Math.min(start.y - rect.top + start.scrollTop, y),
      w: Math.abs(x - (start.x - rect.left + start.scrollLeft)),
      h: Math.abs(y - (start.y - rect.top + start.scrollTop)),
    })
  }
  const onPointerUp = () => {
    const start = marqueeStart.current
    if (!start) return
    marqueeStart.current = null
    const box = marquee
    setMarquee(null)
    if (!box || box.w < 6 || box.h < 6) return           // a click, not a drag
    const root = bodyRef.current
    if (!root) return
    const base = root.getBoundingClientRect()
    const sel = {
      left: base.left + box.x - root.scrollLeft,
      top: base.top + box.y - root.scrollTop,
      right: base.left + box.x + box.w - root.scrollLeft,
      bottom: base.top + box.y + box.h - root.scrollTop,
    }
    const hits = []
    root.querySelectorAll('[data-clip-id]').forEach((el) => {
      const r = el.getBoundingClientRect()
      const overlaps = r.left < sel.right && r.right > sel.left && r.top < sel.bottom && r.bottom > sel.top
      if (overlaps) hits.push(el.getAttribute('data-clip-id'))
    })
    onSelectMany?.(hits, { additive: start.additive })
  }

  return (
    <div
      ref={bodyRef}
      className="relative min-h-0 flex-1 overflow-auto bg-black/30"
      data-testid="timeline-body"
      data-lenis-prevent="true"
      data-readonly={readOnly ? 'true' : 'false'}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
    >
      {marquee && (
        <div
          className="pointer-events-none absolute z-20 rounded-sm border border-cyanglow/70 bg-cyanglow/10"
          style={{ left: marquee.x, top: marquee.y, width: marquee.w, height: marquee.h }}
        />
      )}
      <div className="relative" style={{ width: widthPx + 96, minHeight: '100%' }}>
        <div className="sticky left-0 z-10 ml-24">
          <Ruler widthPx={widthPx} pps={pps} />
        </div>
        <div className="relative">
          {(edl?.tracks || []).map((track) => (
            <Track
              key={track.id}
              track={track}
              pps={pps}
              widthPx={widthPx}
              selectedClipIds={selectedClipIds}
              diff={diff}
              waveforms={waveforms}
              thumbs={thumbs}
              readOnly={readOnly}
              onClipSelect={onClipSelect}
              onTrimPreview={setTrimPreview}
              onTrimCommit={(p) => { setTrimPreview(null); onTrimCommit?.(p) }}
              onDragPreview={setDragPreview}
              onDragCommit={(p) => { setDragPreview(null); onDragCommit?.(p) }}
            />
          ))}
          <Playhead playheadMs={playheadMs} previewMs={effPreview} pps={pps} />
        </div>
        {!edl && (
          <div className="absolute inset-0 grid place-items-center">
            <span className="font-mono text-[10px] uppercase tracking-widest2 text-white/30">no timeline yet</span>
          </div>
        )}
      </div>
    </div>
  )
}
