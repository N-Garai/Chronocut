import { useState } from 'react'
import { Bold, Italic, Underline, AlignLeft, AlignCenter, AlignRight, X } from 'lucide-react'

/**
 * TextEditor — add/edit caption text overlays on a clip.
 *
 * Supports font size, color, alignment, bold/italic/underline, and position.
 * Saves via `onChange({ op: 'set_effect', args: { clip_id, effect: 'caption', ... } })`.
 */
export default function TextEditor({
  clip,
  onChange,
  onClose,
}) {
  const [text, setText] = useState(clip.text || '')
  const [fontSize, setFontSize] = useState(24)
  const [color, setColor] = useState('#ffffff')
  const [align, setAlign] = useState('bottom')
  const [bold, setBold] = useState(false)
  const [italic, setItalic] = useState(false)
  const [underline, setUnderline] = useState(false)
  const [position, setPosition] = useState('bottom')

  const handleSave = () => {
    if (!text.trim()) {
      onChange?.(clip.id, {
        op: 'update_caption',
        args: { clip_id: clip.id, text: '' },
      })
      onClose?.()
      return
    }
    onChange?.(clip.id, {
      op: 'set_effect',
      args: {
        clip_id: clip.id,
        effect: 'caption',
        text,
        font_size: fontSize,
        color,
        align,
        bold,
        italic,
        underline,
        position,
      },
    })
    onClose?.()
  }

  return (
    <div className="relative z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 w-[420px] bg-carbon/90 border border-white/10 rounded-lg p-6 shadow-2xl">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-mono text-[11px] uppercase tracking-widest text-white">Text Overlay</h2>
          <button onClick={onClose} className="rounded p-1 text-white/50 hover:bg-white/10 hover:text-white">
            <X size={14} />
          </button>
        </div>

        <div className="space-y-3">
          <div className="flex flex-col gap-1">
            <label className="font-mono text-[9px] uppercase tracking-widest text-white/50">Text</label>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={3}
              className="w-full rounded border border-white/10 bg-white/[0.04] px-2 py-1 font-mono text-[11px] text-bone outline-none focus:border-cyanglow/60"
              placeholder="Enter caption text…"
            />
          </div>

          <div className="flex flex-col gap-1">
            <label className="font-mono text-[9px] uppercase tracking-widest text-white/50">Font Size</label>
            <input
              type="number"
              min="8"
              max="72"
              value={fontSize}
              onChange={(e) => setFontSize(Math.max(8, Math.min(72, Number(e.target.value))))}
              className="w-full rounded border border-white/10 bg-white/[0.04] px-2 py-1 font-mono text-[11px] text-bone outline-none focus:border-cyanglow/60"
            />
          </div>

          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1 cursor-pointer select-none">
              <input type="checkbox" checked={bold} onChange={() => setBold(!bold)} className="rounded border border-white/10 bg-white/[0.04] text-amberglow focus:ring-0" />
              <span className="font-mono text-[9px] font-bold text-white/60">Bold</span>
            </label>
            <label className="flex items-center gap-1 cursor-pointer select-none">
              <input type="checkbox" checked={italic} onChange={() => setItalic(!italic)} className="rounded border border-white/10 bg-white/[0.04] text-amberglow focus:ring-0" />
              <span className="font-mono text-[9px] italic text-white/60">Italic</span>
            </label>
            <label className="flex items-center gap-1 cursor-pointer select-none">
              <input type="checkbox" checked={underline} onChange={() => setUnderline(!underline)} className="rounded border border-white/10 bg-white/[0.04] text-amberglow focus:ring-0" />
              <span className="font-mono text-[9px] underline text-white/60">Underline</span>
            </label>
          </div>

          <div className="flex flex-col gap-1">
            <label className="font-mono text-[9px] uppercase tracking-widest text-white/50">Color</label>
            <div className="flex items-center gap-2">
              <input type="color" value={color} onChange={(e) => setColor(e.target.value)} className="w-10 h-8 rounded border-0 bg-transparent cursor-pointer" style={{ appearance: 'none', width: 40, height: 24 }} />
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <label className="font-mono text-[9px] uppercase tracking-widest text-white/50">Position</label>
            <div className="flex gap-2">
              {['bottom', 'center', 'top'].map((pos) => (
                <button key={pos} onClick={() => setPosition(pos)} className={`flex h-8 w-8 items-center justify-center rounded border px-2 py-0.5 font-mono text-[9px] ${align === pos ? 'border-cyanglow text-cyanglow bg-cyanglow/10' : 'border-white/15 text-white/50 hover:border-white/30'}`}>
                  {pos.charAt(0).toUpperCase() + pos.slice(1)}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-4 border border-white/10 rounded bg-black/40 p-2">
          <div className="relative h-24">
            <span className={`text-white font-mono text-[12px] font-bold ${bold ? 'font-bold' : ''} ${italic ? 'italic' : ''} ${underline ? 'underline' : ''} ${align === 'center' ? 'text-center' : align === 'left' ? 'text-left' : 'text-right'} ${color ? `text-[${color}]` : ''}`} style={{ position: position === 'center' ? 'absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2' : position === 'top' ? 'absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-full' : 'absolute bottom-1/2 left-1/2 -translate-x-1/2' }}>
              {text || 'Your text here'}
            </span>
          </div>
        </div>

        <div className="mt-4 flex items-center gap-2">
          <button onClick={onClose} className="flex-1 rounded border border-white/15 px-3 py-1.5 font-mono text-[9px] text-white/50 hover:bg-white/10">Cancel</button>
          <button onClick={handleSave} className="flex-1 rounded bg-amberglow px-3 py-1.5 font-mono text-[9px] font-bold uppercase tracking-widest text-void hover:bg-amberglow/85">Save Caption</button>
        </div>
      </div>
    </div>
  )
}