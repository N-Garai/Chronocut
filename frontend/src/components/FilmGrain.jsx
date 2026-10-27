import { useEffect, useRef } from 'react'
import gsap from 'gsap'

/**
 * FilmGrain — fixed, animated film grain/noise overlay across the whole site.
 * Pure SVG turbulence layer animated via background-position jitter.
 */
export default function FilmGrain() {
  const ref = useRef(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    let frame
    let x = 0
    let y = 0

    const tick = () => {
      x = (x + (Math.random() * 80 - 40)) % 100
      y = (y + (Math.random() * 80 - 40)) % 100
      el.style.backgroundPosition = `${x}% ${y}%`
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)

    return () => cancelAnimationFrame(frame)
  }, [])

  return <div ref={ref} className="grain-overlay" aria-hidden="true" />
}
