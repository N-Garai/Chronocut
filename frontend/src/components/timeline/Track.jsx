import ClipBlock from './ClipBlock'
import { TRACK_LABELS } from '../../lib/edl'

/**
 * Track — one row per EDL track. Renders clips positioned by start/duration
 * and delegates all interaction (select/trim/drag) to ClipBlock callbacks.
 * Height hint adapts: caption/audio rows are slim.
 */
export default function Track({
  track, pps, selectedClipIds, diff, widthPx, waveforms, thumbs, readOnly,
  onClipSelect, onTrimPreview, onTrimCommit, onDragPreview, onDragCommit,
}) {
  const heightOf = track.type === 'video' ? 'h-14' : track.type === 'caption' ? 'h-9' : 'h-10'

  return (
    <div className={`relative flex ${heightOf} border-b border-white/[0.06]`} data-track={track.id}>
      <div className="sticky left-0 z-10 w-24 shrink-0 border-r border-white/10 bg-carbon/90 px-2 py-1 backdrop-blur-sm">
        <span className="block font-mono text-[9px] uppercase tracking-widest text-white/50">{TRACK_LABELS[track.id] || track.id}</span>
        <span className="block font-mono text-[8px] text-white/30">{track.clips?.length || 0}</span>
      </div>
      <div className="relative flex-1" style={{ width: Math.max(0, widthPx) }}>
        {(track.clips || []).map((c) => (
          <ClipBlock
            key={c.id}
            clip={c}
            trackId={track.id}
            type={track.type}
            pps={pps}
            selected={selectedClipIds.includes(c.id)}
            waveform={waveforms?.[c.source_id] || null}
            thumb={thumbs?.[c.source_id] || null}
            readOnly={readOnly}
            diffKind={(diff?.added || []).includes(c.id) ? 'added' : (diff?.changed || []).includes(c.id) ? 'changed' : (diff?.removed || []).includes(c.id) ? 'removed' : null}
            onSelect={onClipSelect}
            onTrimPreview={onTrimPreview}
            onTrimCommit={onTrimCommit}
            onDragPreview={onDragPreview}
            onDragCommit={onDragCommit}
          />
        ))}
      </div>
    </div>
  )
}
