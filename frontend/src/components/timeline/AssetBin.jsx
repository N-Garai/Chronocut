import { ImageIcon, Music, Film, FileArchive } from 'lucide-react'

/**
 * AssetBin — job sources from the EDL, enriched with the asset endpoint's
 * thumbnails and on-disk availability. A source with no preview row still
 * renders (icon + name), so the bin never depends on the extra metadata.
 */
export default function AssetBin({ sources, assets = [], onSelect }) {
  const icons = { image: ImageIcon, audio: Music, narration: Music, music: Music, video: Film }
  const byId = new Map((assets || []).map((a) => [String(a.asset_id || a.id), a]))

  return (
    <aside className="flex h-full flex-col gap-2 overflow-y-auto border-r border-white/10 bg-carbon/40 p-3" data-lenis-prevent="true">
      <span className="font-mono text-[10px] uppercase tracking-widest text-white/50">assets ({sources.length})</span>
      {sources.length === 0 && (
        <p className="font-mono text-[10px] leading-relaxed text-white/35">
          Sources appear here once the pipeline ingests the media for this job.
        </p>
      )}
      {sources.map((s) => {
        const row = byId.get(String(s.id)) || null
        const Icon = icons[s.type] || FileArchive
        const offline = row ? !row.available : false
        return (
          <button
            key={s.id}
            onClick={() => onSelect?.(s.id)}
            className="flex items-center gap-2 rounded border border-white/10 bg-white/[0.03] px-2 py-1.5 text-left hover:border-cyanglow/50"
            title={offline ? `${s.path} (not on this host)` : s.path}
          >
            {row?.thumb ? (
              <img src={row.thumb} alt="" className="h-6 w-10 shrink-0 rounded object-cover opacity-90" loading="lazy" />
            ) : (
              <Icon
                size={14}
                className={
                  s.type === 'audio' || s.type === 'narration' || s.type === 'music'
                    ? 'text-emerald-400'
                    : s.type === 'video' ? 'text-cyanglow' : 'text-amberglow'
                }
              />
            )}
            <span className="min-w-0 flex-1">
              <span className="block truncate font-mono text-[9px] uppercase tracking-widest text-white/60">{s.id}</span>
              <span className="block truncate font-mono text-[8px] text-white/30">{s.path?.split(/[\\/]/).pop() || s.type}</span>
            </span>
            {s.duration != null && (
              <span className="font-mono text-[9px] text-white/40">{Number(s.duration).toFixed(1)}s</span>
            )}
            {offline && <span className="font-mono text-[8px] uppercase tracking-widest text-amberglow/70">n/a</span>}
          </button>
        )
      })}
    </aside>
  )
}
