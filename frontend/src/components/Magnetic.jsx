import { useRef } from 'react'
import gsap from 'gsap'

/**
 * Magnetic — wraps children and pulls them toward the cursor with
 * springy physics. `strength` controls the pull radius multiplier.
 */
export default function Magnetic({ children, strength = 0.4, className = '' }) {
  const ref = useRef(null)

  const onMove = (e) => {
    const el = ref.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const x = e.clientX - (rect.left + rect.width / 2)
    const y = e.clientY - (rect.top + rect.height / 2)
    gsap.to(el, {
      x: x * strength,
      y: y * strength,
      duration: 0.6,
      ease: 'power3.out',
    })
  }

  const onLeave = () => {
    const el = ref.current
    if (!el) return
    gsap.to(el, { x: 0, y: 0, duration: 0.8, ease: 'elastic.out(1, 0.3)' })
  }

  return (
    <div
      ref={ref}
      className={`magnetic inline-block ${className}`}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
    >
      {children}
    </div>
  )
}
