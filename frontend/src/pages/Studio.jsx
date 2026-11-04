import { useState, useCallback, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import SmoothScroll from '../components/SmoothScroll'
import FilmGrain from '../components/FilmGrain'
import CustomCursor from '../components/CustomCursor'
import Navbar from '../components/Navbar'
import AgentTerminal from '../components/AgentTerminal'
import OutputPlayer from '../components/OutputPlayer'
import Footer from '../components/Footer'
import ErrorBoundary from '../components/ErrorBoundary'
import StudioPanel from '../components/Studio'
import { createJob, getJob, renderedUrl } from '../lib/api'
import { useJobEvents } from '../hooks/useJobEvents'
import { useStudio } from '../studio/StudioProvider'

/**
 * Studio — the working page: Ingestion, Agent Telemetry, and Output,
 * running a full job; upon COMPLETE it offers the timeline workspace.
 */
export default function Studio() {
  const navigate = useNavigate()
  const location = useLocation()
  const { activeJobId, setActiveJob, caps } = useStudio()
  const [jobStatus, setJobStatus] = useState(null)
  const [jobOutput, setJobOutput] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState(null)
  const { events } = useJobEvents(activeJobId)
  // A pre-rendered demo job id (set via VITE_DEMO_JOB_ID) can be loaded
  // instantly when the live run is unavailable during a presentation.
  const demoJobId = import.meta.env.VITE_DEMO_JOB_ID || ''

  // Navbar deep links (/#ingest etc.) scroll to their section after arrival.
  useEffect(() => {
    if (!location.hash) return
    const t = setTimeout(() => {
      const el = document.getElementById(location.hash.slice(1))
      if (el) el.scrollIntoView({ behavior: 'smooth' })
    }, 150)
    return () => clearTimeout(t)
  }, [location.pathname, location.hash])

  useEffect(() => {
    if (!activeJobId) { setJobStatus(null); setJobOutput(null); return }
    let timer
    let misses = 0
    const poll = async () => {
      try {
        const data = await getJob(activeJobId)
        misses = 0
        setJobStatus(data)
        if (data.status === 'COMPLETE' || data.status === 'NEEDS_REVIEW') {
          setJobOutput(data)
          setUploading(false)
          return
        }
        if (data.status === 'FAILED') {
          setUploadError(data.error_log?.message || 'Pipeline failed')
          setUploading(false)
          return
        }
      } catch {
        // Occasional net noise gets a grace period, but a persistent miss
        // (most often a stale or expired job id) surfaces as an error instead
        // of polling forever.
        misses += 1
        if (misses >= 6) {
          setUploadError('This job is no longer reachable — it may have expired on the server.')
          setUploading(false)
          return
        }
      }
      timer = setTimeout(poll, misses >= 2 ? 4000 : 1500)
    }
    poll()
    return () => clearTimeout(timer)
  }, [activeJobId])

  const runJob = useCallback(async (payload) => {
    if (uploading) return
    setUploading(true)
    setUploadError(null)
    setJobOutput(null)
    setJobStatus(null)
    try {
      // Files ride as media[] so every type keeps its name and extension.
      const data = await createJob(payload)
      setActiveJob(data.job_id)
      return data
    } catch (e) {
      setUploadError(e.message)
      setUploading(false)
      throw e
    }
  }, [uploading, setActiveJob])

  const status = jobStatus?.status
  const timelineReady = status === 'COMPLETE' || status === 'NEEDS_REVIEW'
  const inFlight = !!activeJobId && !timelineReady && status !== 'FAILED'

  return (
    <div className="relative min-h-screen bg-void text-bone">
      <SmoothScroll />
      <FilmGrain />
      <CustomCursor />
      <ErrorBoundary>
        <Navbar />
        <main>
          <section id="studio" className="pt-28" />
          {!activeJobId && demoJobId && (
            <div className="flex justify-center pb-4">
              <button
                onClick={() => setActiveJob(demoJobId)}
                className="rounded-full border border-cyanglow/50 px-6 py-2 font-mono text-[10px] uppercase tracking-widest2 text-cyanglow hover:border-cyanglow hover:bg-cyanglow/10"
                data-testid="load-demo"
              >
                Load demo project
              </button>
            </div>
          )}
          <section id="ingest" className="scroll-mt-24">
          <StudioPanel
            activeJob={activeJobId}
            jobStatus={jobStatus}
            caps={caps}
            createJob={runJob}
            uploading={uploading}
            uploadError={uploadError}
          />
          </section>
          <AgentTerminal
            play={!!activeJobId}
            jobStatus={jobStatus}
            uploading={uploading}
            uploadError={uploadError}
            events={events}
            onOpenTimeline={timelineReady ? () => navigate(`/studio/${activeJobId}/timeline`) : null}
          />
          {!inFlight && timelineReady && (
            <div className="px-6 py-8 text-center">
              <button
                onClick={() => navigate(`/studio/${activeJobId}/timeline`)}
                className="rounded-full bg-cyanglow px-8 py-3 font-mono text-[11px] font-bold uppercase tracking-widest2 text-void hover:bg-cyanglow/85"
                data-testid="open-timeline"
              >
                Open Timeline Studio →
              </button>
              {jobOutput?.render_id && (
                <button
                  onClick={() => {
                    // ?download=1 makes the API send Content-Disposition: attachment —
                    // a plain URL would just play in the new tab.
                    const url = `${renderedUrl(activeJobId, jobOutput.render_id)}?download=1`
                    window.open(url, "_blank")
                  }}
                  className="rounded-full border border-cyanglow px-8 py-3 font-mono text-[11px] font-bold uppercase tracking-widest2 text-cyanglow hover:bg-cyanglow/10 hover:border-cyanglow/80"
                  data-testid="download-video"
                >
                  Download Final Render →
                </button>
              )}
            </div>
          )}
          <OutputPlayer jobOutput={jobOutput} />
        </main>
        <Footer />
      </ErrorBoundary>
    </div>
  )
}
