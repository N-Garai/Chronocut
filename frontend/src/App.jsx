import { useState, useCallback, useRef, useEffect } from 'react'
import Loader from './components/Loader'
import SmoothScroll from './components/SmoothScroll'
import FilmGrain from './components/FilmGrain'
import CustomCursor from './components/CustomCursor'
import Navbar from './components/Navbar'
import Hero from './components/Hero'
import Marquee from './components/Marquee'
import AgentTerminal from './components/AgentTerminal'
import Storyboard from './components/Storyboard'
import NarrativeScroll from './components/NarrativeScroll'
import OutputPlayer from './components/OutputPlayer'
import Footer from './components/Footer'
import ErrorBoundary from './components/ErrorBoundary'
import Studio from './components/Studio'
import { createJob as apiCreateJob, getJob } from './lib/api'
import { useCapabilities } from './hooks/useCapabilities'
import { useJobEvents } from './hooks/useJobEvents'

export default function App() {
  const [loading, setLoading] = useState(true)
  const { caps } = useCapabilities()
  const [activeJob, setActiveJob] = useState(null)
  const [jobStatus, setJobStatus] = useState(null)
  const [jobOutput, setJobOutput] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState(null)
  const { events } = useJobEvents(activeJob)
  const pollRef = useRef(null)

  const handleLoadingComplete = useCallback(() => setLoading(false), [])

  useEffect(() => {
    const failsafe = setTimeout(() => setLoading(false), 12000)
    return () => clearTimeout(failsafe)
  }, [])

  const pollJob = useCallback((jid) => {
    const tick = async () => {
      try {
        const data = await getJob(jid)
        setJobStatus(data)
        if (data.status === 'COMPLETE' || data.status === 'NEEDS_REVIEW') {
          setJobOutput(data)
          setUploading(false)
          clearTimeout(pollRef.current)
        } else if (data.status === 'FAILED') {
          setUploadError(data.error_log?.message || 'Pipeline failed')
          setUploading(false)
          clearTimeout(pollRef.current)
        } else {
          pollRef.current = setTimeout(tick, 1500)
        }
      } catch {
        pollRef.current = setTimeout(tick, 2000)
      }
    }
    clearTimeout(pollRef.current)
    tick()
  }, [])

  const runJob = useCallback(async (payload) => {
    if (uploading) return
    setUploading(true)
    setUploadError(null)
    setJobOutput(null)
    setJobStatus(null)
    try {
      const fdPayload = { ...payload }
      if (payload.files && !payload.file) {
        const { default: JSZip } = await import('jszip')
        const zip = new JSZip()
        const folder = zip.folder('media')
        for (const f of payload.files) folder.file(f.name, f)
        fdPayload.file = await zip.generateAsync({ type: 'blob' })
      }
      const data = await apiCreateJob(fdPayload)
      setActiveJob(data.job_id)
      pollJob(data.job_id)
      requestAnimationFrame(() => {
        const el = document.querySelector('#studio')
        const lenis = window.__lenis
        if (lenis) lenis.scrollTo(el, { offset: -40, duration: 1.4 })
        else if (el) el.scrollIntoView({ behavior: 'smooth' })
      })
      return data
    } catch (e) {
      setUploadError(e.message)
      setUploading(false)
      throw e
    }
  }, [uploading, pollJob])

  const storyboard = jobOutput?.director_output?.storyboard || []
  const swarmLaunched = !!activeJob

  return (
    <div className="relative min-h-screen bg-void text-bone">
      {loading && (
        <Loader key="loader" onComplete={handleLoadingComplete} />
      )}

      {!loading && (
        <ErrorBoundary>
          <SmoothScroll />
          <FilmGrain />
          <CustomCursor />
          <>
            <Navbar />
            <main>
              <Hero />
              <section className="section-deep" />
              <Studio
                activeJob={activeJob}
                jobStatus={jobStatus}
                caps={caps}
                createJob={runJob}
                uploading={uploading}
                uploadError={uploadError}
              />
              <section className="section-sky" />
              <AgentTerminal
                play={swarmLaunched}
                jobStatus={jobStatus}
                uploading={uploading}
                uploadError={uploadError}
                events={events}
              />
              <section className="section-cyan" />
              <OutputPlayer jobOutput={jobOutput} />
              <section className="section-cream" />
              <NarrativeScroll />
              <Storyboard storyboard={storyboard} />
            </main>
            <Footer />
          </>
        </ErrorBoundary>
      )}
    </div>
  )
}
