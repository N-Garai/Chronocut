import { useEffect, useRef } from 'react'
import { formatSecond } from '../../lib/edl'
import { attachResize } from '../../timeline/controllers/resize'
import { attachDrag } from '../../timeline/controllers/drag'

const DIFF_CLS = {
  added: 'ring-1 ring-emerald-400/80 shadow-[0_0_14px_rgba(52,211,153,0.35)]',
  changed: 'ring-1 ring-amberglow/80 shadow-[0_0_14px_rgba(255,195,0,0.25)]',
  removed: 'ring-1 ring-red-400/80 opacity-60',
}

/**
 * ClipBlock — one clip on a track. Renders trim handles (video/attached
 * audio), supports drag move, selection click, and the presentational
 * diff pulse (green added / amber changed / red removed, ~1.5 s).
 */
export default function ClipBlock({
  clip, trackId, type, pps, selected, diffKind, waveform, thumb, readOnly = false,
  onSelect, onTrimPreview, onTrimCommit, onDragPreview, onDragCommit,
}) {
  const ref = useRef(null)
  const leftPx = Math.round((Number(clip.start || 0) * 1000 / 1000) * pps)
  const widthPx = Math.max(4, Math.round(Number(clip.duration || 0) * pps))

  useEffect(() => {
    if (!ref.current || type === 'caption' || readOnly) return
    const el = ref.current
    const cleanups = []
    for (const edge of ['start', 'end']) {
      const handle = el.querySelector(`[data-edge="${edge}"]`)
      if (handle) {
        cleanups.push(attachResize({
          clipEl: handle, edge, clipId: clip.id, pps,
          setPreview: (p) => onTrimPreview?.(p),
          commit: (p) => onTrimCommit?.(p),
        }))
      }
    }
    if (type === 'video') {
      cleanups.push(attachDrag({
        clipEl: el, clipId: clip.id, pps,
        setPreview: (p) => onDragPreview?.(p),
        commit: (p) => onDragCommit?.(p),
      }))
    }
    return () => cleanups.forEach((fn) => fn())
  }, [clip.id, clip.start, clip.duration, pps, type, readOnly, onTrimPreview, onTrimCommit, onDragPreview, onDragCommit])

  const grade = (clip.effects || []).find((e) => e.type === 'grade')?.value
  const motion = (clip.effects || []).find((e) => e.type === 'motion')?.value
  const isAudio = type === 'narration' || type === 'music' || type === 'sfx'

  const tone = trackId === 'v1' ? 'border-amberglow/50 bg-amberglow/10'
    : trackId === 'c1' ? 'border-cyanglow/40 bg-cyanglow/10'
    : isAudio ? 'border-emerald-400/40 bg-emerald-400/10' : 'border-white/20 bg-white/5'

  return (
    <div
      ref={ref}
      data-clip-id={clip.id}
      data-testid={`clip-${clip.id}`}
      className={`group absolute top-1 bottom-1 overflow-hidden rounded-md border ${tone} ${
        readOnly ? 'cursor-default' : 'cursor-grab'
      } ${
        selected ? 'ring-2 ring-cyanglow z-10' : ''
      } ${DIFF_CLS[diffKind] || ''}`}
      style={{ left: `${leftPx}px`, width: `${widthPx}px` }}
      onPointerDown={(e) => {
        if (readOnly) return
        if (e.button === 0) onSelect?.(clip.id, { additive: e.shiftKey || e.metaKey || e.ctrlKey })
        // NOTE: not stopPropagation so drag controller handles the rest
      }}
      title={`${clip.id} · ${formatSecond(clip.start)} → ${formatSecond(Math.round((clip.start + clip.duration) * 1000) / 1000)}`}
    >
      {!isAudio && !readOnly && (
        <>
          <span
            data-edge="start"
            className="absolute left-0 top-0 h-full w-2 cursor-w-resize bg-white/0 hover:bg-cyanglow/40"
          />
          <span
            data-edge="end"
            className="absolute right-0 top-0 h-full w-2 cursor-e-resize bg-white/0 hover:bg-amberglow/40"
          />
        </>
      )}
      {waveform && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-emerald-300/25 mix-blend-screen"
          style={{ backgroundImage: `url(${waveform})`, backgroundSize: '100% 100%', backgroundRepeat: 'no-repeat' }}
        />
      )}
      {thumb && !waveform && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 opacity-25"
          style={{ backgroundImage: `url(${thumb})`, backgroundSize: 'cover', backgroundPosition: 'center' }}
        />
      )}
      <div className="pointer-events-none relative flex h-full flex-col justify-between px-2 py-1">
        <span className="truncate font-mono text-[9px] uppercase tracking-widest text-white/70">
          {type === 'caption' ? String(clip.text || '').slice(0, 40) : (clip.name || clip.source_id || clip.id)}
        </span>
        {trackId === 'v1' && (grade || motion) && (
          <span className="truncate font-mono text-[8px] uppercase tracking-widest text-amberglow/80">
            {[grade, motion].filter(Boolean).join(' · ')}
          </span>
        )}
        {isAudio && clip.gain != null && (
          <span className="truncate font-mono text-[8px] uppercase tracking-widest text-emerald-300/70">
            gain {Number(clip.gain).toFixed(2)}
          </span>
        )}
      </div>
    </div>
  )
}
