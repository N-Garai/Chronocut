import { useState } from 'react'
import { Image, Film, Music, Plus, Upload, X } from 'lucide-react'
import { uploadFiles } from '../../lib/api'

/**
 * AssetBin — media library rail. Shows every EDL source (videos, images,
 * audio, generated b-roll) with thumbnails; drag-and-drop uploads new media
 * and refreshes the bin via onUploaded.
 */
export default function AssetBin({
  sources = [],
  assets = [],
  selectedIds = [],
  onSelect,
  onUploaded,
  jobId,
}) {
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [search, setSearch] = useState('')

  const doUpload = async (files) => {
    if (!files.length) return
    setUploading(true)
    try {
      await uploadFiles(jobId, files)
      onUploaded?.()
    } catch (err) {
      console.error('Upload failed:', err)
    }
    setUploading(false)
  }

  const filteredAssets = assets.filter((a) => {
    const name = String(a.name || a.asset_id || a.id || '').toLowerCase()
    return name.includes(search.toLowerCase())
  })

  return (
    <div className="relative flex h-full w-full flex-col bg-carbon">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/10 bg-black/10 px-3 py-2">
        <div className="flex items-center gap-2">
          <Film size={14} className="text-cyanglow" />
          <span className="font-mono text-[10px] uppercase tracking-widest text-white/70">
            Assets{assets.length ? ` · ${assets.length}` : ''}
          </span>
        </div>
        <div className="relative w-24">
          <input
            type="text"
            placeholder="Search…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded border border-white/10 bg-white/[0.04] px-2 py-1 font-mono text-[10px] text-bone placeholder-white/25 outline-none focus:border-cyanglow/60"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="absolute right-2 top-1/2 -mt-1 text-white/40 hover:text-white"
            >
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      {/* Drag overlay */}
      {dragOver && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/50">
          <div className="flex flex-col items-center gap-2 rounded-lg border-2 border-dashed border-white/30 bg-black/50 p-6">
            <Upload size={24} className="text-cyanglow" />
            <p className="font-mono text-[10px] uppercase tracking-widest text-cyanglow">Drop files to upload</p>
          </div>
        </div>
      )}

      {/* Asset list */}
      <div
        className="flex-1 space-y-2 overflow-y-auto p-2"
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); doUpload(Array.from(e.dataTransfer.files)) }}
      >
        {filteredAssets.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center pt-16 text-center">
            <Upload size={32} className="text-white/20" />
            <p className="mt-2 font-mono text-[10px] text-white/40">
              {assets.length ? 'No assets match' : 'No media yet'}
            </p>
            <button
              onClick={() => document.getElementById('asset-file-input')?.click()}
              className="mt-2 rounded border border-white/20 px-3 py-1 font-mono text-[10px] text-white/70 hover:bg-white/10"
            >
              Browse files
            </button>
          </div>
        )}
        <div className="grid grid-cols-1 gap-2">
          {filteredAssets.map((asset) => (
            <AssetCard
              key={String(asset.asset_id || asset.id || asset.name)}
              asset={asset}
              selected={selectedIds.includes(String(asset.asset_id || asset.id))}
              onSelect={() => onSelect?.(String(asset.asset_id || asset.id))}
            />
          ))}
        </div>
      </div>

      {uploading && (
        <div className="border-t border-white/10 px-3 py-1.5 font-mono text-[9px] uppercase tracking-widest text-cyanglow">
          uploading…
        </div>
      )}

      {/* Hidden file input */}
      <input
        id="asset-file-input"
        type="file"
        multiple
        hidden
        onChange={(e) => {
          doUpload(Array.from(e.target.files || []))
          e.target.value = ''
        }}
      />
    </div>
  )
}

const AssetCard = ({ asset, onSelect, selected }) => {
  const id = String(asset.asset_id || asset.id || asset.name || '')
  const name = String(asset.name || id)
  const kind = String(asset.kind || '').toLowerCase()
  const thumb = asset.thumb
  const isVideo = kind === 'video'
  const isImage = kind === 'image'
  const isAudio = kind === 'narration' || kind === 'music' || kind === 'sfx' || kind === 'audio'

  const icon = isVideo ? <Film size={20} className="text-amberglow" />
    : isImage ? <Image size={20} className="text-cyanglow" />
    : isAudio ? <Music size={20} className="text-emerald-400" />
    : <Plus size={20} className="text-white/40" />

  const bytes = Number(asset.bytes ?? asset.size ?? 0)
  const sizeLabel = bytes > 0 ? (bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`) : ''

  return (
    <div
      className={`group relative rounded border transition-all cursor-pointer ${
        selected ? 'border-amberglow bg-amberglow/10' : 'border-white/10 bg-white/[0.02] hover:border-cyanglow/60 hover:bg-amberglow/5'
      }`}
      onClick={onSelect}
      data-testid={`asset-${id}`}
      title={asset.available === false ? 'Source file unavailable on this instance' : name}
    >
      {isAudio ? (
        <div className="flex aspect-video items-center justify-center rounded-t-md bg-black/60">
          {icon}
        </div>
      ) : (
        <div className="relative aspect-video overflow-hidden rounded-t-md bg-black">
          {thumb ? (
            <img
              src={thumb}
              alt={name}
              className="absolute inset-0 h-full w-full object-cover"
              loading="lazy"
            />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center bg-black/50">
              {icon}
            </div>
          )}
        </div>
      )}
      <div className="flex items-center justify-between px-1 py-1">
        <span className="block max-w-[70%] truncate font-mono text-[9px] uppercase tracking-widest text-white/70" title={name}>
          {name}
        </span>
        <span className="flex items-center gap-1">
          {asset.available === false && (
            <span className="rounded bg-red-500/20 px-1 font-mono text-[8px] text-red-300" title="Missing on this instance">!</span>
          )}
          <span className="rounded bg-black/50 px-1 font-mono text-[8px] text-white/60">
            {kind || 'media'}
          </span>
        </span>
      </div>
      {sizeLabel && (
        <span className="block px-1 pb-1 font-mono text-[8px] text-white/40">{sizeLabel}</span>
      )}
    </div>
  )
}
