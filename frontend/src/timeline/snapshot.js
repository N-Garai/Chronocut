/**
 * timeline/snapshot.js — client-side state chips ONLY.
 * The server's timeline_context.build_timeline_snapshot is source of truth for
 * agent context; this module builds the compact summary for the UI chips
 * (clip count, duration, selection, revision, stale) and for the
 * "Copy timeline summary" debug action.
 */
export function buildSnapshot(chips) {
  const o = {
    revision: String(chips.revision ?? 1),
    clips: Number(chips.clips ?? 0),
    captions: Number(chips.captions ?? 0),
    duration_s: Math.round(Number(chips.durationMs ?? 0)) / 1000,
    playhead_s: Math.round(Number(chips.playheadMs ?? 0)) / 1000,
    selection: String(chips.selection?.length ?? 0),
    dirty: Boolean(chips.dirty),
    stale: Boolean(chips.stale),
    renderState: String(chips.renderState ?? 'unrendered'),
  }
  return JSON.stringify(o)
}

export function summarizeChips(edl, state) {
  return buildSnapshot({
    revision: state?.revision,
    clips: (edl?.tracks || []).find((t) => t.id === 'v1')?.clips?.length || 0,
    captions: (edl?.tracks || []).find((t) => t.id === 'c1')?.clips?.length || 0,
    durationMs: Math.round(Number(edl?.project?.duration || 0) * 1000),
    playheadMs: state?.playheadMs,
    selection: state?.selectedClipIds,
    dirty: state?.dirty,
    stale: state?.stale,
    renderState: state?.renderState,
  })
}
