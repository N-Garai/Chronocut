import { useRef, useEffect, useState, useCallback } from 'react'
import { Play, Pause, Volume2, VolumeOff, Maximize, Minimize, SkipBack, SkipForward } from 'lucide-react'

/**
 * VideoPreview — professional video preview pane with playback controls.
 * Mirrors Clipchamp/CapCut style preview: video fills the pane, transport
 * controls float at bottom-center, scrubber shows playhead position.
 *
 * Accepts a video URL (from /api/v1/jobs/:id/video?profile=...) and mirrors
 * the timeline playhead so scrubbing the timeline updates the preview and
 * vice-versa.
 */
export default function VideoPreview({
  src,
  playheadMs,
  durationMs,
  playing,
  setPlayheadMs,
  setPlaying,
  onSeek,
  width = 640,
  height = 360,
}) {
  const videoRef = useRef(null)
  const [isHovered, setIsHovered] = useState(false)
  const [isMuted, setIsMuted] = useState(false)
  const [volume, setVolume] = useState(1.0)
  const [error, setError] = useState(false)
  const [loaded, setLoaded] = useState(false)

  // Reset error/loaded state when src changes
  useEffect(() => {
    setError(false)
    setLoaded(false)
  }, [src])

  // Sync video currentTime with playheadMs
  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    const targetTime = playheadMs / 1000
    if (Math.abs(v.currentTime - targetTime) > 0.5) {
      v.currentTime = targetTime
    }
  }, [playheadMs])

  // Sync playheadMs with video currentTime while playing
  useEffect(() => {
    if (!playing || !videoRef.current) return
    const v = videoRef.current
    const onTime = () => setPlayheadMs(Math.round(v.currentTime * 1000))
    v.addEventListener('timeupdate', onTime)
    return () => v.removeEventListener('timeupdate', onTime)
  }, [playing, setPlayheadMs])

  // Play/pause the video element
  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    if (playing) {
      v.play().catch(() => {})
    } else {
      v.pause()
    }
  }, [playing])

  const handleLoad = () => setLoaded(true)
  const handleError = () => {
    setError(true)
    setPlaying(false)
  }

  const handleSeek = (e) => {
    const v = videoRef.current
    if (!v) return
    const rect = v.getBoundingClientRect()
    const x = e.clientX - rect.left
    const pct = Math.max(0, Math.min(1, x / rect.width))
    const ms = Math.round(pct * durationMs)
    setPlayheadMs(ms)
    v.currentTime = ms / 1000
  }

  const handlePlayPause = () => {
    const v = videoRef.current
    if (!v) return
    setPlaying((p) => {
      const next = !p
      if (next) {
        v.play().catch(() => setPlaying(false))
      } else {
        v.pause()
      }
      return next
    })
  }

  return (
    <div className="relative aspect-video w-full max-w-full bg-black overflow-hidden" data-testid="preview-pane">
      {/* Video element */}
      <video
        ref={videoRef}
        src={src || ''}
        playsInline
        preload="metadata"
        onLoadedMetadata={handleLoad}
        onError={handleError}
        onClick={handlePlayPause}
        style={{ pointerEvents: error ? 'none' : 'auto' }}
      />
      {/* Error overlay */}
      {error && !loaded && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80">
          <div className="flex flex-col items-center gap-3">
            <div className="w-16 h-16 rounded-full border-4 border-white/20 border-t-cyanglow animate-spin">
              <div className="w-full h-full border-t-cyanglow" />
            </div>
            <p className="text-white text-sm font-mono">Loading video…</p>
          </div>
        </div>
      )}
      {/* Error state */}
      {error && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80">
          <div className="flex flex-col items-center gap-2">
            <div className="w-16 h-16 rounded-full border-4 border-red-500/50 border-t-red-500 animate-spin">
              <div className="w-full h-full border-t-red-500" />
            </div>
            <p className="text-red-400 text-sm font-mono">Unable to load video</p>
            <button
              onClick={() => {
                setError(false)
                setPlaying(false)
                if (videoRef.current) videoRef.current.src = src
                videoRef.current?.load()
              }}
              className="px-4 py-1 bg-red-500/20 text-red-400 border border-red-500/50 rounded hover:bg-red-500/40"
            >
              Retry
            </button>
          </div>
        </div>
      )}
      {/* Click-to-seek overlay */}
      {!error && (
        <div className="absolute inset-0 cursor-pointer"
          onClick={handleSeek}
          style={{ pointerEvents: playing ? 'none' : 'auto' }}
        />
      )}
      {/* Play/pause overlay when not playing */}
      {!error && !playing && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/40" onClick={handlePlayPause}>
          <button
            onClick={(e) => e.stopPropagation()}
            className="rounded-full bg-white/20 px-4 py-3 text-white/90 hover:bg-white/30"
            aria-label="Play"
          >
            <Play size={48} />
          </button>
        </div>
      )}
      {/* Transport controls overlay (visible on hover) */}
      {!error && (
        <div className="absolute inset-x-0 bottom-0 flex items-end px-4 py-3">
          {/* Transport controls */}
          <div className="flex items-center gap-2 bg-black/60 backdrop-blur-sm rounded-b-lg px-3 py-2 border-t border-white/10">
            <button
              onClick={handlePlayPause}
              className="rounded-full p-2 text-white/80 hover:bg-white/20 hover:text-white transition-colors"
              title={playing ? 'Pause' : 'Play'}
            >
              {playing ? <Pause size={18} /> : <Play size={48} />}
            </button>
            <button
              onClick={() => onSeek?.(Math.max(0, playheadMs - 1000), { preview: false })}
              className="rounded p-1 text-white/60 hover:bg-white/10 hover:text-white"
              title="Back 1s"
            >
              <SkipBack size={14} />
            </button>
            <button
              onClick={() => onSeek?.(Math.min(durationMs, playheadMs + 1000), { preview: false })}
              className="rounded p-1 text-white/60 hover:bg-white/10 hover:text-white"
              title="Forward 1s"
            >
              <SkipForward size={14} />
            </button>
            {/* Volume */}
            <button
              onClick={() => setIsMuted((m) => !m)}
              className="flex items-center gap-1 rounded p-1 text-white/60 hover:bg-white/10 hover:text-white"
              title="Toggle mute"
            >
              {isMuted ? <VolumeOff size={14} /> : <Volume2 size={14} />}
              <input
                type="range"
                min="0"
                max="1"
                step="0.1"
                value={isMuted ? 0 : volume}
                onChange={(e) => {
                  const v = parseFloat(e.target.value)
                  setVolume(v)
                  setIsMuted(v === 0)
                  if (videoRef.current) videoRef.current.volume = v
                }}
                className="w-16 h-1 accent-amberglow"
              />
            </button>
            {/* Fullscreen */}
            <button
              className="rounded p-1 text-white/60 hover:bg-white/10 hover:text-white"
              title="Fullscreen"
            >
              <Maximize size={14} />
            </button>
          </div>
          {/* Time scrubber */}
          <div className="flex items-center gap-2 mt-2">
            <span className="font-mono text-[9px] text-white/50">{formatMs(playheadMs)}</span>
            <div
              className="flex-1 h-1 bg-white/20 rounded-full cursor-pointer relative"
              onClick={(e) => {
                const rect = e.currentTarget.getBoundingClientRect()
                const x = e.clientX - rect.left
                const pct = Math.max(0, Math.min(1, x / rect.width))
                const ms = Math.round(pct * durationMs)
                setPlayheadMs(ms)
                if (videoRef.current) videoRef.current.currentTime = ms / 1000
              }}
            >
              <div
                className="h-full bg-amberglow rounded-full"
                style={{ width: `${Math.min(100, Math.max(0, (playheadMs / Math.max(durationMs, 1))) * 100)}%` }}
              />
            </div>
            <span className="font-mono text-[9px] text-white/50">{formatMs(durationMs)}</span>
          </div>
        </div>
      )}
    </div>
  )
}

function formatMs(ms) {
  const t = Math.max(0, Math.round(ms))
  const m = Math.floor(t / 60000)
  const s = Math.floor((t % 60000) / 1000)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}