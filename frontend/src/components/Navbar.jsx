import { useEffect, useRef, useState } from 'react'
import gsap from 'gsap'
import Magnetic from './Magnetic'

const links = [
  { label: 'Ingest', href: '#ingest' },
  { label: 'Swarm', href: '#swarm' },
  { label: 'Storyboard', href: '#storyboard' },
  { label: 'Output', href: '#output' },
]

/**
 * Navbar — fixed cinematic top bar. Logo + mono links, hides on scroll down.
 */
export default function Navbar() {
  const ref = useRef(null)
  const [hidden, setHidden] = useState(false)

  useEffect(() => {
    let lastY = window.scrollY
    const onScroll = () => {
      const y = window.scrollY
      if (y > lastY && y > 120) setHidden(true)
      else setHidden(false)
      lastY = y
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    gsap.to(ref.current, {
      yPercent: hidden ? -120 : 0,
      opacity: hidden ? 0 : 1,
      duration: 0.5,
      ease: 'power3.out',
    })
  }, [hidden])

  const scrollTo = (e, href) => {
    e.preventDefault()
    const el = document.querySelector(href)
    if (!el) return
    const lenis = window.__lenis
    if (lenis) lenis.scrollTo(el, { offset: -20 })
    else el.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <header
      ref={ref}
      className="fixed inset-x-0 top-0 z-[80] flex items-center justify-between px-6 py-5 sm:px-10"
    >
      <Magnetic strength={0.2}>
        <a
          href="#top"
          onClick={(e) => scrollTo(e, '#top')}
          className="flex items-center gap-3 font-heading text-lg font-600 tracking-[0.25em] text-bone"
        >
          <span className="relative flex h-3 w-3">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amberglow opacity-60" />
            <span className="relative inline-flex h-3 w-3 rounded-full bg-amberglow" />
          </span>
          CHRONOCUT
        </a>
      </Magnetic>

      <nav className="hidden items-center gap-8 md:flex">
        {links.map((l) => (
          <a
            key={l.href}
            href={l.href}
            onClick={(e) => scrollTo(e, l.href)}
            className="group relative font-mono text-[11px] uppercase tracking-widest2 text-ash/70 transition-colors hover:text-amberglow"
          >
            {l.label}
            <span className="absolute -bottom-1 left-0 h-px w-0 bg-amberglow transition-all duration-300 group-hover:w-full" />
          </a>
        ))}
      </nav>

      <Magnetic strength={0.3}>
        <a
          href="#ingest"
          onClick={(e) => scrollTo(e, '#ingest')}
          className="hidden rounded-full border border-white/20 px-5 py-2 font-mono text-[10px] uppercase tracking-widest2 text-bone transition-colors hover:border-amberglow hover:text-amberglow sm:block"
        >
          Deploy Folder
        </a>
      </Magnetic>
    </header>
  )
}
