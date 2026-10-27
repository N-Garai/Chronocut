import { useEffect, useRef } from 'react'

/**
 * CanvasField — dark, moody, slow-moving abstract "shader" background.
 * Layered sinusoidal color fields + drifting dust motes, GPU-free but cheap.
 * Renders once on a resized canvas at reduced DPR for perf.
 */
export default function CanvasField({ className = '' }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    let raf
    let w = 0
    let h = 0
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5)

    const particles = Array.from({ length: 90 }, () => ({
      x: Math.random(),
      y: Math.random(),
      r: Math.random() * 1.6 + 0.3,
      sx: (Math.random() - 0.5) * 0.00025,
      sy: (Math.random() - 0.5) * 0.00018,
      a: Math.random() * 0.5 + 0.1,
      pulse: Math.random() * Math.PI * 2,
    }))

    const resize = () => {
      const rect = canvas.parentElement.getBoundingClientRect()
      w = rect.width
      h = rect.height
      canvas.width = w * dpr
      canvas.height = h * dpr
      canvas.style.width = `${w}px`
      canvas.style.height = `${h}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    const frame = (t) => {
      const time = t * 0.0001
      const grad = ctx.createLinearGradient(0, 0, w, h)
      grad.addColorStop(0, '#070707')
      grad.addColorStop(0.5, '#0b0b0c')
      grad.addColorStop(1, '#040404')
      ctx.fillStyle = grad
      ctx.fillRect(0, 0, w, h)

      ctx.globalCompositeOperation = 'screen'

      const blob = (x, y, r, rgb, alpha) => {
        const g = ctx.createRadialGradient(x, y, 0, x, y, r)
        g.addColorStop(0, `rgba(${rgb},${alpha})`)
        g.addColorStop(1, `rgba(${rgb},0)`)
        ctx.fillStyle = g
        ctx.beginPath()
        ctx.arc(x, y, r, 0, Math.PI * 2)
        ctx.fill()
      }

      const cx = w * 0.5 + Math.sin(time * 0.35) * w * 0.22
      const cy = h * 0.42 + Math.cos(time * 0.28) * h * 0.12
      blob(cx, cy, w * 0.6, '255,195,0', 0.05 + Math.sin(time * 0.9) * 0.015)

      const cx2 = w * 0.8 + Math.cos(time * 0.4) * w * 0.12
      const cy2 = h * 0.65 + Math.sin(time * 0.22) * h * 0.15
      blob(cx2, cy2, w * 0.5, '0,229,255', 0.045 + Math.cos(time * 0.7) * 0.012)

      const cx3 = w * 0.18 + Math.sin(time * 0.5) * w * 0.08
      const cy3 = h * 0.25 + Math.cos(time * 0.33) * h * 0.1
      blob(cx3, cy3, w * 0.35, '234,234,234', 0.02)

      ctx.globalCompositeOperation = 'source-over'

      particles.forEach((p, i) => {
        p.x += p.sx
        p.y += p.sy
        if (p.x < -0.05) p.x = 1.05
        if (p.x > 1.05) p.x = -0.05
        if (p.y < -0.05) p.y = 1.05
        if (p.y > 1.05) p.y = -0.05
        const tw = 0.6 + 0.4 * Math.sin(time * 2 + p.pulse + i)
        ctx.globalAlpha = p.a * tw
        ctx.fillStyle = i % 5 === 0 ? '#FFC300' : '#EAEAEA'
        ctx.beginPath()
        ctx.arc(p.x * w, p.y * h, p.r * (0.8 + tw * 0.4), 0, Math.PI * 2)
        ctx.fill()
      })
      ctx.globalAlpha = 1

      raf = requestAnimationFrame(frame)
    }

    resize()
    raf = requestAnimationFrame(frame)

    const onResize = () => resize()
    window.addEventListener('resize', onResize)

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', onResize)
    }
  }, [])

  return <canvas ref={canvasRef} className={className} aria-hidden="true" />
}
