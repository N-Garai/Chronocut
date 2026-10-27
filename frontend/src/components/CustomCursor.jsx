import { useEffect, useRef, useState } from 'react'
import gsap from 'gsap'

const isFinePointer = () =>
  typeof window !== 'undefined' &&
  window.matchMedia('(pointer: fine)').matches

const PLAY_PATH = 'M8 5v14l11-7z'

export default function CustomCursor() {
  const cursorRef = useRef(null)
  const [enabled, setEnabled] = useState(false)

  useEffect(() => {
    if (!isFinePointer()) return
    setEnabled(true)
  }, [])

  useEffect(() => {
    if (!enabled) return

    const el = cursorRef.current
    const xTo = gsap.quickTo(el, 'x', { duration: 0.15, ease: 'power3.out' })
    const yTo = gsap.quickTo(el, 'y', { duration: 0.15, ease: 'power3.out' })

    const onMove = (e) => {
      xTo(e.clientX)
      yTo(e.clientY)
    }

    const getMode = (target) => {
      const node = target && target.closest
        ? target.closest('[data-cursor]')
        : null
      return node ? node.getAttribute('data-cursor') : null
    }

    const onOver = (e) => {
      const mode = getMode(e.target)
      if (!mode) {
        gsap.to(el, { width: 28, height: 28, duration: 0.35, ease: 'power3.out' })
        return
      }
      const size = mode === 'play' ? 64 : 48
      gsap.to(el, {
        width: size,
        height: size,
        duration: 0.35,
        ease: 'back.out(2)',
      })
    }

    const onDown = () => {
      gsap.to(el, { scale: 0.85, duration: 0.15 })
    }
    const onUp = () => {
      gsap.to(el, { scale: 1, duration: 0.35, ease: 'elastic.out(1, 0.4)' })
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseover', onOver)
    window.addEventListener('mousedown', onDown)
    window.addEventListener('mouseup', onUp)

    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseover', onOver)
      window.removeEventListener('mousedown', onDown)
      window.removeEventListener('mouseup', onUp)
    }
  }, [enabled])

  if (!enabled) return null

  return (
    <div
      ref={cursorRef}
      className="pointer-events-none fixed left-0 top-0 z-[100] flex h-7 w-7 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-amberglow/80 bg-amberglow/15 mix-blend-difference"
      style={{ width: 28, height: 28 }}
    >
      <svg
        viewBox="0 0 24 24"
        className="h-3.5 w-3.5 fill-amberglow"
        style={{ marginLeft: 2 }}
      >
        <path d={PLAY_PATH} />
      </svg>
      <style>{`
        @media (pointer: fine) {
          body { cursor: none !important; }
        }
      `}</style>
    </div>
  )
}
