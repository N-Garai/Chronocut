import { useState, useEffect } from 'react'
import { Image, Film, Music, Plus, Upload, Search, X } from 'lucide-react'
import { uploadFiles } from '../../lib/api'

/**
 * AssetBin — media library panel. Shows uploaded assets (videos, images,
 * audio) with thumbnails. Supports drag-and-drop upload of new media.
 *
 * Assets are passed in as `sources` (from EDL) plus newly uploaded files.
 * Clicking an asset selects it for the timeline (onSelect callback).
 */
export default function AssetBin({
  sources = [],
  assets = [],
  onSelect,
  jobId,
}) {
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [search, setSearch] = useState('')

  const handleDrop = async (e) => {
    e.preventDefault()
    setDragOver(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length === 0) return
    setUploading(true)
    try {
        await uploadFiles(jobId, files)
    } catch (err) {
        console.error('Upload failed:', err)
    }
    setUploading(false)
  }

  const handleDragEnter = (e) => {
    e.preventDefault()
    setDragOver(true)
  }

  const handleDragLeave = (e) => {
    e.preventDefault()
    setDragOver(false)
  }

  const filteredAssets = assets.filter((a) => {
    const name = String(a.name || a.id || '').toLowerCase()
    return name.includes(search.toLowerCase())
  })

  return (
    <div className="flex h-full flex-col border-r border-white/10 bg-carbon">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2 bg-black/10">
        <div className="flex items-center gap-2">
          <Film size={14} className="text-cyanglow" />
          <span className="font-mono text-[10px] uppercase tracking-widest text-white/70">Assets</span>
        </div>
        <div className="relative w-24">
          <input
            type="text"
            placeholder="Search assets…"
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
        <div className="absolute inset-0 bg-black/50 flex items-center justify-center z-10">
          <div className="flex flex-col items-center gap-2 rounded-lg border-2 border-dashed border-white/30 bg-black/50 p-6">
            <Upload size={24} className="text-cyanglow" />
            <p className="text-cyanglow font-mono text-[10px] uppercase tracking-widest">Drop files to upload</p>
          </div>
        </div>
      )}

      {/* Asset grid */}
      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {filteredAssets.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center pt-16 text-center">
            <Upload size={32} className="text-white/20" />
            <p className="mt-2 font-mono text-[10px] text-white/40">No media yet</p>
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
              key={asset.id}
              asset={asset}
              selected={selectedAssetId === asset.id}
              onSelect={() => onSelect?.(asset.id)}
            />
          ))}
        </div>
      </div>

      {/* Hidden file input */}
      <input
        id="asset-file-input"
        type="file"
        multiple
        hidden
        onChange={async (e) => {
          const files = Array.from(e.target.files || [])
          setUploading(true)
          try {
            await uploadFiles(jobId, files)
          } catch (err) {
            console.error('Upload failed:', err)
          }
          setUploading(false)
          setTimeout(() => setUploading(false), 500)
        }}
      />
    </div>
  )
}

const AssetCard = ({ asset, onSelect, selected }) => {
  const id = String(asset.id || asset.name || '')
  const name = String(asset.name || id)
  const kind = String(asset.kind || '').toLowerCase()
  const thumb = asset.thumb
  const isVideo = kind === 'video' || ['mp4', 'mov', 'avi', 'mkv'].some((e) => name.toLowerCase().endsWith('.' + e))
  const isImage = ['jpg', 'jpeg', 'png', 'webp', 'gif'].some((e) => name.toLowerCase().endsWith('.' + e))
  const isAudio = ['mp3', 'wav', 'aac', 'ogg'].some((e) => name.toLowerCase().endsWith('.' + e))

  const thumbUrl = thumb ? `${thumb}` : null
  const isSelected = selected === id

  const getIcon = () => {
    if (isVideo) return <Film size={20} className="text-amberglow" />
    if (isImage) return <Image size={20} className="text-cyanglow" />
    if (isAudio) return <Music size={20} className="text-emerald-400" />
    return <Plus size={20} className="text-white/40" />
  }

  return (
    <div
      className={`relative group rounded border border-white/10 bg-white/[0.02] hover:border-cyanglow/60 hover:bg-amberglow/5 transition-all cursor-pointer`}
      onClick={() => onSelect(id)}
      data-testid={`asset-${id}`}
    >
      <div className="aspect-video overflow-hidden rounded-t-md bg-black">
        {thumbUrl ? (
          <img
            src={thumbUrl}
            alt={name}
            className="absolute inset-0 w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50">
            {getIcon()}
          </div>
        )}
        <div className="absolute top-1 right-1 z-10 flex flex-col gap-1">
          <span className="text-[8px] font-mono text-white/60 bg-black/50 px-1 rounded">
            {kind.charAt(0).toUpperCase() + kind.slice(1)}
          </span>
        </div>
      </div>
      <div className="px-1 py-1">
        <span className="block font-mono text-[9px] uppercase tracking-widest text-white/70 truncate" title={name}>
          {name}
        </span>
        <span className="block font-mono text-[8px] text-white/40 truncate">
          {asset.size ? `${Math.round(Number(asset.size) / 1024)} KB` : ''}
        </span>
      </div>
    </div>
  )
}