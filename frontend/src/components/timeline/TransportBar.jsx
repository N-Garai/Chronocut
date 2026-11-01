import { Play, Pause, ZoomIn, ZoomOut, Magnet, RefreshCcw, ChevronLeft, ChevronRight } from 'lucide-react'
import { formatMs } from '../../lib/edl'
import { PPS_MIN, PPS_MAX } from '../../timeline/time'

/** TransportBar — playhead time, frame-less transport, zoom, snapping/ripple toggles. */
export default function TransportBar({
  playheadMs, durationMs, playing, pps,
  onPlayPause, onSeek, onZoom, snapping, ripple, onToggleSnapping, onToggleRipple,
}) {
  const disabledPlayhead = durationMs <= 0
  return (
    <div className="flex items-center gap-2 border-b border-white/10 bg-white/[0.02] px-3 py-1.5">
      <button
        onClick={() => onSeek?.(Math.max(0, playheadMs - 1000), { preview: false })}
        className="rounded p-1 text-white/60 hover:bg-white/10 hover:text-white"
        title="Back 1s"
      >
        <ChevronLeft size={14} />
      </button>
      <button
        onClick={() => onPlayPause?.()}
        disabled={disabledPlayhead}
        data-testid="transport-play"
        className={`rounded-full p-1.5 ${playing ? 'bg-amberglow text-void' : 'bg-white/10 text-white/80 hover:bg-white/20'} disabled:opacity-30`}
        title={playing ? 'Pause' : 'Play'}
      >
        {playing ? <Pause size={13} /> : <Play size={13} className="translate-x-[1px]" />}
      </button>
      <button
        onClick={() => onSeek?.(Math.min(durationMs, playheadMs + 1000), { preview: false })}
        className="rounded p-1 text-white/60 hover:bg-white/10 hover:text-white"
        title="Forward 1s"
      >
        <ChevronRight size={14} />
      </button>
      <span className="ml-2 font-mono text-[11px] text-amberglow" data-testid="transport-time">
        {formatMs(playheadMs)} / {formatMs(durationMs)}
      </span>

      <div className="ml-auto flex items-center gap-2">
        <button
          onClick={onToggleSnapping}
          className={`flex items-center gap-1 rounded border px-2 py-0.5 font-mono text-[9px] uppercase tracking-widest ${
            snapping ? 'border-cyanglow/50 bg-cyanglow/10 text-cyanglow' : 'border-white/15 text-white/40'
          }`}
          title="Toggle snapping (N)"
        >
          <Magnet size={11} /> snap
        </button>
        <button
          onClick={onToggleRipple}
          className={`rounded border px-2 py-0.5 font-mono text-[9px] uppercase tracking-widest ${
            ripple ? 'border-emerald-400/50 bg-emerald-400/10 text-emerald-400' : 'border-white/15 text-white/40'
          }`}
          title="Toggle ripple delete (R)"
        >
          ripple
        </button>
        <button
          onClick={() => onZoom?.(Math.max(PPS_MIN, Math.round(pps / 1.25)))}
          className="rounded p-1 text-white/60 hover:bg-white/10 hover:text-white"
          title="Zoom out (-)"
        >
          <ZoomOut size={13} />
        </button>
        <span className="font-mono text-[9px] text-white/40">{pps}px/s</span>
        <button
          onClick={() => onZoom?.(Math.min(PPS_MAX, Math.round(pps * 1.25)))}
          className="rounded p-1 text-white/60 hover:bg-white/10 hover:text-white"
          title="Zoom in (+)"
        >
          <ZoomIn size={13} />
        </button>
        <RefreshCcw size={10} className="text-white/25" title="Zoom 10–200 px/s" />
      </div>
    </div>
  )
}
