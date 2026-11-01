import { Scissors, ScissorsSquare, SplitSquareHorizontal, Trash2, Undo2, Redo2, Clapperboard, Download } from 'lucide-react'

/**
 * TimelineToolbar — semantic edit actions over the selection/playhead.
 * Every button maps to a server op through the command path (one undo entry).
 */
export default function TimelineToolbar({
  selection, playheadMs,
  onSplit, onDelete, onSplitEvery, onRemoveSilence,
  onRenderPreview, onExportOtio,
  canUndo, canRedo, onUndo, onRedo, saving, stale,
}) {
  const clipTarget = selection[0]
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-white/10 bg-white/[0.02] px-3 py-2">
      <button
        onClick={onSplit}
        disabled={!clipTarget}
        className="flex items-center gap-1 rounded border border-white/15 px-2 py-1 font-mono text-[9px] uppercase tracking-widest text-white/80 hover:border-cyanglow/60 hover:text-cyanglow disabled:opacity-30"
        title="Split selected clip at playhead (S)"
        data-testid="tl-split"
      >
        <Scissors size={12} /> split at playhead
      </button>
      <button
        onClick={onDelete}
        disabled={!selection.length}
        className="flex items-center gap-1 rounded border border-white/15 px-2 py-1 font-mono text-[9px] uppercase tracking-widest text-white/80 hover:border-red-400/60 hover:text-red-400 disabled:opacity-30"
        title="Delete selected (ripple closes the gap)"
        data-testid="tl-delete"
      >
        <Trash2 size={12} /> delete {selection.length ? `(${selection.length})` : ''}
      </button>
      <button
        onClick={onSplitEvery}
        className="flex items-center gap-1 rounded border border-white/15 px-2 py-1 font-mono text-[9px] uppercase tracking-widest text-white/80 hover:border-cyanglow/60 hover:text-cyanglow"
        title="Split the whole video track every 3 s"
      >
        <SplitSquareHorizontal size={12} /> cut every 3s
      </button>
      <button
        onClick={onRemoveSilence}
        className="flex items-center gap-1 rounded border border-white/15 px-2 py-1 font-mono text-[9px] uppercase tracking-widest text-white/80 hover:border-emerald-400/60 hover:text-emerald-400"
        title="Remove silence (global ripple, server macro)"
      >
        <ScissorsSquare size={12} /> remove silence
      </button>

      <span className="mx-1 h-4 w-px bg-white/10" />

      <button
        onClick={onUndo} disabled={!canUndo} data-testid="tl-undo"
        className="rounded border border-white/15 p-1 text-white/70 hover:border-white/40 disabled:opacity-25" title="Undo (Ctrl+Z)"
      >
        <Undo2 size={13} />
      </button>
      <button
        onClick={onRedo} disabled={!canRedo} data-testid="tl-redo"
        className="rounded border border-white/15 p-1 text-white/70 hover:border-white/40 disabled:opacity-25" title="Redo (Ctrl+Shift+Z)"
      >
        <Redo2 size={13} />
      </button>

      <div className="ml-auto flex items-center gap-2">
        <button
          onClick={onExportOtio}
          className="flex items-center gap-1 rounded border border-white/15 px-2 py-1 font-mono text-[9px] uppercase tracking-widest text-white/70 hover:border-violet-400/60 hover:text-violet-300"
          title="Download the cut as OpenTimelineIO"
        >
          <Download size={12} /> .otio
        </button>
        <button
          onClick={onRenderPreview}
          className="flex items-center gap-1 rounded bg-amberglow px-3 py-1.5 font-mono text-[9px] font-bold uppercase tracking-widest text-void hover:bg-amberglow/85"
          title="Render a 480p preview of the current draft"
          data-testid="tl-render"
        >
          <Clapperboard size={12} /> render preview
        </button>
      </div>
    </div>
  )
}
