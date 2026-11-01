import { useEffect, useRef, useState } from 'react'
import gsap from 'gsap'
import Magnetic from './Magnetic'
import { useLocation, useNavigate } from 'react-router-dom'
import { useStudio } from '../studio/StudioProvider'

// Route-aware navigation. The landing page links to the narrative surfaces;
// the studio page links to the working sections. On the right route the navbar
// scrolls; otherwise it navigates (the destination page scrolls to the hash
// when it mounts). Section badges stay unique per page: the studio numbers its
// own sections 01–03, the landing page continues at 04–05.
const LANDING_LINKS = [
  { label: 'Meet Your Agent Teams', hash: 'narrative' },
  { label: 'Storyboard', hash: 'storyboard' },
]

const STUDIO_LINKS = [
  { label: 'Ingest', hash: 'ingest' },
  { label: 'Agent Telemetry', hash: 'swarm' },
  { label: 'Editor Mode', timeline: true },
  { label: 'Output', hash: 'output' },
]

/**
 * Navbar — fixed cinematic top bar. Logo + mono links, hides on scroll down.
 */
export default function Navbar() {
  const ref = useRef(null)
  const [hidden, setHidden] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const { activeJobId } = useStudio()

  const onStudio = location.pathname.startsWith('/studio')
  const links = onStudio ? STUDIO_LINKS : LANDING_LINKS

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

  const scrollToElement = (href) => {
    const el = document.querySelector(href)
    if (!el) return
    const lenis = window.__lenis
    if (lenis) lenis.scrollTo(el, { offset: -20 })
    else el.scrollIntoView({ behavior: 'smooth' })
  }

  const goHash = (e, hash) => {
    e.preventDefault()
    if (location.pathname === '/') scrollToElement(`#${hash}`)
    else navigate(`/#${hash}`)
  }

  const openEditor = (e) => {
    e.preventDefault()
    if (activeJobId) navigate(`/studio/${activeJobId}/timeline`)
    else navigate('/studio#ingest') // no job yet → land on the ingestion dock
  }

  const go = (e, item) => {
    if (item.timeline) return openEditor(e)
    goHash(e, item.hash)
  }

  return (
    <header
      ref={ref}
      className="fixed inset-x-0 top-0 z-[80] flex items-center justify-between px-6 py-5 sm:px-10"
    >
      <Magnetic strength={0.2}>
        <a
          href="/#top"
          onClick={(e) => {
            e.preventDefault()
            if (location.pathname === '/') scrollToElement('#top')
            else navigate('/#top')
          }}
          className="flex items-center gap-3 font-heading text-lg font-semibold tracking-[0.25em] text-bone"
        >
          <span className="relative flex h-3 w-3">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amberglow opacity-60" />
            <span className="relative inline-flex h-3 w-3 rounded-full bg-amberglow" />
          </span>
          CHRONOCUT
        </a>
      </Magnetic>

      <nav className="hidden items-center gap-8 md:flex">
        {links.map((item) => {
          // The editor opens on a job's timeline; without an active job the
          // link still responds — it walks the user to the ingest dock instead
          // of dying silently.
          const noJob = item.timeline && !activeJobId
          return (
            <a
              key={item.label}
              href={item.timeline ? (noJob ? '/studio#ingest' : `/studio/${activeJobId}/timeline`) : `/#${item.hash}`}
              onClick={(e) => go(e, item)}
              title={noJob ? 'Create a job first — your next click opens the ingestion dock' : undefined}
              className={`group relative font-mono text-[11px] uppercase tracking-widest2 transition-colors ${
                noJob ? 'text-ash/40 hover:text-ash/80' : 'text-ash/70 hover:text-amberglow'
              }`}
            >
              {item.label}
              <span className="absolute -bottom-1 left-0 h-px w-0 bg-amberglow transition-all duration-300 group-hover:w-full" />
            </a>
          )
        })}
      </nav>

      <Magnetic strength={0.3}>
        <a
          href={onStudio ? '/#top' : '/studio#ingest'}
          onClick={(e) => {
            e.preventDefault()
            if (onStudio) navigate('/#top')
            else navigate('/studio#ingest')
          }}
          className="rounded-full border border-white/20 px-5 py-2 font-mono text-[10px] uppercase tracking-widest2 text-bone transition-colors hover:border-amberglow hover:text-amberglow sm:block"
        >
          {onStudio ? 'Home' : 'Open Studio'}
        </a>
      </Magnetic>
    </header>
  )
}
