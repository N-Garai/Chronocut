import { useEffect } from 'react'
import SmoothScroll from '../components/SmoothScroll'
import FilmGrain from '../components/FilmGrain'
import CustomCursor from '../components/CustomCursor'
import Navbar from '../components/Navbar'
import Hero from '../components/Hero'
import Marquee from '../components/Marquee'
import NarrativeScroll from '../components/NarrativeScroll'
import Storyboard from '../components/Storyboard'
import Footer from '../components/Footer'
import { Link, useLocation } from 'react-router-dom'

/**
 * Landing — the marketing page.
 * Storyboard previews the pipeline stages; real job work lives in /studio.
 */
export default function Landing() {
  const location = useLocation()

  // Navbar deep links (/studio#ingest → back to /#storyboard) scroll after arrival.
  useEffect(() => {
    if (!location.hash) return
    const t = setTimeout(() => {
      const el = document.getElementById(location.hash.slice(1))
      if (el) el.scrollIntoView({ behavior: 'smooth' })
    }, 150)
    return () => clearTimeout(t)
  }, [location.pathname, location.hash])

  return (
    <div className="relative min-h-screen bg-void text-bone">
      <SmoothScroll />
      <FilmGrain />
      <CustomCursor />
      <>
        <Navbar />
        <main>
          <Hero />
          <section className="section-deep" />
          <Marquee />
          <section className="section-sky" />
          <NarrativeScroll />
          <section className="section-cream" />
          <Storyboard storyboard={[]} />
        </main>
        <Footer />
      </>
      <Link
        to="/studio"
        className="fixed bottom-6 left-1/2 z-40 -translate-x-1/2 rounded-full bg-amberglow px-6 py-2.5 font-mono text-[10px] font-bold uppercase tracking-widest2 text-void transition-transform hover:scale-105"
      >
        Open Studio →
      </Link>
    </div>
  )
}
