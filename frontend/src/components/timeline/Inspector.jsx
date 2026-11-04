import { useState } from 'react'
import { SlidersHorizontal } from 'lucide-react'
import { GRADES, MOTIONS, TRANSITIONS } from '../../timeline/presets'

/**
 * Inspector — editable fields for the selected clip.
 * Non-video edits are disabled until a v1 clip is selected.
 */
export default function Inspector({ selectedClip, onChange, onCaptionChange }) {
  if (!selectedClip) {
    return (
      <aside className="flex h-full flex-col gap-2 border-l border-white/10 bg-carbon/40 p-3">
        <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest text-white/50">
          <SlidersHorizontal size={13} className="text-amberglow" /> inspector
        </div>
        <p className="font-mono text-[10px] leading-relaxed text-white/35">
          Select a clip on the video track to edit grade, motion, transitions, speed and captions.
        </p>
      </aside>
    )
  }
  const grade = (selectedClip.effects || []).find((e) => e.type === 'grade')?.value || 'clean'
  const motion = (selectedClip.effects || []).find((e) => e.type === 'motion')?.value || 'hold'
  const isVideoRow = (selectedClip.effects != null)

  return (
    <aside className="flex h-full flex-col gap-3 overflow-y-auto border-l border-white/10 bg-carbon/40 p-3" data-lenis-prevent="true">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest text-white/50">
          <SlidersHorizontal size={13} className="text-amberglow" /> inspector
        </div>
        <span className="rounded border border-white/15 px-1.5 font-mono text-[9px] text-cyanglow">{selectedClip.id}</span>
      </div>

      <label className="flex flex-col gap-1">
        <span className="font-mono text-[9px] uppercase tracking-widest text-white/45">start (s)</span>
        <input
          type="number" step={0.001} min={0}
          value={Number(selectedClip.start) || 0}
          readOnly
          className="rounded border border-white/10 bg-white/[0.04] px-2 py-1 font-mono text-[11px] text-white/60"
        />
      </label>

      {isVideoRow && (
        <>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[9px] uppercase tracking-widest text-white/45">grade</span>
            <select
              value={grade}
              onChange={(e) => onChange?.(selectedClip.id, 'set_effect', { effect: 'grade', value: e.target.value })}
              className="rounded border border-white/10 bg-white/[0.04] px-2 py-1 font-mono text-[11px] text-bone outline-none focus:border-cyanglow/60"
            >
              {GRADES.map((g) => <option key={g} value={g} className="bg-carbon">{g}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[9px] uppercase tracking-widest text-white/45">motion</span>
            <select
              value={motion}
              onChange={(e) => onChange?.(selectedClip.id, 'set_effect', { effect: 'motion', value: e.target.value })}
              className="rounded border border-white/10 bg-white/[0.04] px-2 py-1 font-mono text-[11px] text-bone outline-none focus:border-cyanglow/60"
            >
              {MOTIONS.map((m) => <option key={m} value={m} className="bg-carbon">{m}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[9px] uppercase tracking-widest text-white/45">transition out</span>
            <select
              value={selectedClip.transition_out || 'cut'}
              disabled
              title="Per-clip transitions apply via agent ops (set_transition_all) — read-only here"
              className="rounded border border-white/10 bg-white/[0.04] px-2 py-1 font-mono text-[11px] text-white/50"
            >
              {TRANSITIONS.map((t) => <option key={t} value={t} className="bg-carbon">{t}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[9px] uppercase tracking-widest text-white/45">speed</span>
            <select
              value={Number(selectedClip.speed || 1)}
              onChange={(e) => onChange?.(selectedClip.id, 'set_speed', { value: Number(e.target.value) })}
              className="rounded border border-white/10 bg-white/[0.04] px-2 py-1 font-mono text-[11px] text-bone outline-none focus:border-cyanglow/60"
            >
              {[0.5, 0.75, 1, 1.25, 1.5, 2].map((s) => <option key={s} value={s} className="bg-carbon">{s}×</option>)}
            </select>
          </label>
        </>
      )}

      {selectedClip.text != null && (
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[9px] uppercase tracking-widest text-white/45">caption text</span>
          <textarea
            value={selectedClip.text || ''}
            maxLength={240}
            onChange={(e) => onCaptionChange?.(selectedClip.id, e.target.value)}
            className="h-20 rounded border border-white/10 bg-white/[0.04] p-2 font-mono text-[11px] text-bone outline-none focus:border-cyanglow/60"
          />
        </label>
      )}
    </aside>
  )
}
