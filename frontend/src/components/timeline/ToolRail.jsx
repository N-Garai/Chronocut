import { useMemo } from 'react'
import { Film, Type, Shuffle, Wand2 } from 'lucide-react'
import AssetBin from './AssetBin'
import { GRADES, MOTIONS, TRANSITIONS, TRANSITION_LABELS, TEXT_PRESETS } from '../../timeline/presets'

const TABS = [
  { id: 'assets', label: 'Assets', icon: Film },
  { id: 'text', label: 'Text', icon: Type },
  { id: 'transitions', label: 'Transitions', icon: Shuffle },
  { id: 'effects', label: 'Effects', icon: Wand2 },
]

/**
 * ToolRail — the left workspace rail: a vertical icon tab column (assets,
 * text, transitions, effects) plus the active tool panel. Every non-asset
 * panel dispatches real server ops through ``onCommand``.
 */
export default function ToolRail({
  tab, onTab,
  assetsProps,            // {sources, assets, selectedIds, onSelect, onUploaded, jobId}
  onCommand,              // (ops[]) => void — server op batch
  selectedClip,           // v1 clip under edit, or null
  playheadMs = 0,
  durationMs = 0,
  readOnly = false,
}) {
  const active = TABS.find((t) => t.id === tab) || TABS[0]

  const currentTransition = useMemo(() => {
    if (!selectedClip) return null
    return selectedClip.transition_in || selectedClip.transition_out || 'cut'
  }, [selectedClip])

  return (
    <div className="flex h-full shrink-0 border-r border-white/10 bg-carbon" data-testid="tool-rail">
      {/* icon tab column */}
      <nav className="flex w-11 shrink-0 flex-col items-center gap-1 border-r border-white/10 bg-black/30 py-2">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => onTab(id)}
            title={label}
            aria-pressed={tab === id}
            data-testid={`tool-tab-${id}`}
            className={`rounded p-2 transition-colors ${
              tab === id
                ? 'bg-amberglow/15 text-amberglow'
                : 'text-white/45 hover:bg-white/10 hover:text-white'
            }`}
          >
            <Icon size={15} />
          </button>
        ))}
      </nav>

      {/* active panel */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-white/10 bg-black/10 px-3 py-2">
          <active.icon size={13} className="text-cyanglow" />
          <span className="font-mono text-[10px] uppercase tracking-widest text-white/70">{active.label}</span>
        </div>

        {tab === 'assets' && <AssetBin {...assetsProps} />}

        {tab === 'text' && (
          <TextPanel
            onCommand={onCommand}
            playheadMs={playheadMs}
            readOnly={readOnly}
          />
        )}

        {tab === 'transitions' && (
          <TransitionsPanel
            onCommand={onCommand}
            current={currentTransition}
            hasClip={!!selectedClip}
            readOnly={readOnly}
          />
        )}

        {tab === 'effects' && (
          <EffectsPanel
            onCommand={onCommand}
            selectedClip={selectedClip}
            readOnly={readOnly}
          />
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Text panel — add title / lower-third / caption at the playhead
// ---------------------------------------------------------------------------
function TextPanel({ onCommand, playheadMs, readOnly }) {
  return (
    <div className="flex-1 space-y-2 overflow-y-auto p-2" data-lenis-prevent="true">
      {TEXT_PRESETS.map((p) => (
        <button
          key={p.id}
          disabled={readOnly}
          onClick={() => onCommand?.([{ op: 'add_caption', args: {
            start: Math.round(playheadMs) / 1000,
            duration: p.durationMs / 1000,
            text: p.text,
          } }])}
          className="w-full rounded border border-white/10 bg-white/[0.02] p-2 text-left transition-colors hover:border-cyanglow/60 hover:bg-cyanglow/5 disabled:opacity-40"
          data-testid={`text-preset-${p.id}`}
        >
          <span className="block font-mono text-[9px] uppercase tracking-widest text-white/70">{p.label}</span>
          <span className="mt-0.5 block truncate font-mono text-[10px] text-white/40">“{p.text}”</span>
          <span className="mt-0.5 block font-mono text-[8px] uppercase tracking-widest text-white/30">
            at playhead · {p.durationMs / 1000}s
          </span>
        </button>
      ))}
      <button
        disabled={readOnly}
        onClick={() => onCommand?.([{ op: 'ensure_captions', args: {} }])}
        className="w-full rounded border border-white/15 bg-white/[0.02] px-2 py-1.5 font-mono text-[9px] uppercase tracking-widest text-white/60 hover:border-amberglow/60 hover:text-amberglow disabled:opacity-40"
        data-testid="text-auto-captions"
      >
        auto captions from narration
      </button>
      <p className="px-1 font-mono text-[9px] leading-relaxed text-white/30">
        Text lands on the captions track. Select a caption clip to rewrite it in the inspector.
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Transitions panel — applied at every junction of the video track
// ---------------------------------------------------------------------------
function TransitionsPanel({ onCommand, current, hasClip, readOnly }) {
  return (
    <div className="flex-1 space-y-1.5 overflow-y-auto p-2" data-lenis-prevent="true">
      <p className="px-1 font-mono text-[9px] leading-relaxed text-white/35">
        Applies at every junction of the video track{hasClip ? '' : ' (select a clip to see its current transition)'}.
      </p>
      {TRANSITIONS.map((t) => (
        <button
          key={t}
          disabled={readOnly}
          onClick={() => onCommand?.([{ op: 'set_transition_all', args: { value: t } }])}
          className={`flex w-full items-center justify-between rounded border px-2 py-1.5 font-mono text-[10px] transition-colors disabled:opacity-40 ${
            current === t
              ? 'border-amberglow/70 bg-amberglow/10 text-amberglow'
              : 'border-white/10 bg-white/[0.02] text-white/65 hover:border-cyanglow/60 hover:bg-cyanglow/5'
          }`}
          data-testid={`transition-${t}`}
        >
          <span>{TRANSITION_LABELS[t] || t}</span>
          {current === t && <span className="font-mono text-[8px] uppercase tracking-widest">active</span>}
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Effects panel — grade + motion presets, per selected clip or all clips
// ---------------------------------------------------------------------------
function EffectsPanel({ onCommand, selectedClip, readOnly }) {
  const clipId = selectedClip?.id || null
  const grade = (selectedClip?.effects || []).find((e) => e.type === 'grade')?.value || null
  const motion = (selectedClip?.effects || []).find((e) => e.type === 'motion')?.value || null

  return (
    <div className="flex-1 space-y-3 overflow-y-auto p-2" data-lenis-prevent="true">
      <section>
        <div className="mb-1 flex items-center justify-between px-1">
          <span className="font-mono text-[9px] uppercase tracking-widest text-white/45">grade</span>
          <button
            disabled={readOnly}
            onClick={() => onCommand?.([{ op: 'set_grade_all', args: { value: grade || 'clean' } }])}
            className="font-mono text-[8px] uppercase tracking-widest text-white/35 hover:text-cyanglow disabled:opacity-40"
            title="Apply this grade to every video clip"
          >
            apply all
          </button>
        </div>
        <div className="flex flex-wrap gap-1">
          {GRADES.map((g) => (
            <button
              key={g}
              disabled={readOnly || !clipId}
              onClick={() => onCommand?.([{ op: 'set_effect', args: { clip_id: clipId, effect: 'grade', value: g } }])}
              className={`rounded border px-1.5 py-0.5 font-mono text-[9px] transition-colors disabled:opacity-40 ${
                grade === g
                  ? 'border-amberglow/70 bg-amberglow/10 text-amberglow'
                  : 'border-white/10 bg-white/[0.02] text-white/60 hover:border-cyanglow/60'
              }`}
              data-testid={`effect-grade-${g}`}
            >
              {g}
            </button>
          ))}
        </div>
      </section>

      <section>
        <div className="mb-1 flex items-center justify-between px-1">
          <span className="font-mono text-[9px] uppercase tracking-widest text-white/45">motion</span>
          <button
            disabled={readOnly || !motion}
            onClick={() => onCommand?.([{ op: 'set_motion_all', args: { value: motion } }])}
            className="font-mono text-[8px] uppercase tracking-widest text-white/35 hover:text-cyanglow disabled:opacity-40"
            title="Apply this motion to every video clip"
          >
            apply all
          </button>
        </div>
        <div className="flex flex-wrap gap-1">
          {MOTIONS.map((m) => (
            <button
              key={m}
              disabled={readOnly || !clipId}
              onClick={() => onCommand?.([{ op: 'set_effect', args: { clip_id: clipId, effect: 'motion', value: m } }])}
              className={`rounded border px-1.5 py-0.5 font-mono text-[9px] transition-colors disabled:opacity-40 ${
                motion === m
                  ? 'border-amberglow/70 bg-amberglow/10 text-amberglow'
                  : 'border-white/10 bg-white/[0.02] text-white/60 hover:border-cyanglow/60'
              }`}
              data-testid={`effect-motion-${m}`}
            >
              {m}
            </button>
          ))}
        </div>
      </section>

      <section>
        <span className="mb-1 block px-1 font-mono text-[9px] uppercase tracking-widest text-white/45">speed</span>
        <div className="flex flex-wrap gap-1">
          {[0.5, 0.75, 1, 1.25, 1.5, 2].map((s) => (
            <button
              key={s}
              disabled={readOnly || !clipId}
              onClick={() => onCommand?.([{ op: 'set_speed', args: { clip_id: clipId, value: s } }])}
              className="rounded border border-white/10 bg-white/[0.02] px-1.5 py-0.5 font-mono text-[9px] text-white/60 transition-colors hover:border-cyanglow/60 disabled:opacity-40"
              data-testid={`effect-speed-${s}`}
            >
              {s}×
            </button>
          ))}
        </div>
      </section>

      {!clipId && (
        <p className="px-1 font-mono text-[9px] leading-relaxed text-white/30">
          Select a clip on the video track to apply per-clip effects. “Apply all” affects every clip.
        </p>
      )}
    </div>
  )
}
