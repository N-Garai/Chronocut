import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Landing from './pages/Landing'
import Studio from './pages/Studio'
import Timeline from './pages/Timeline'
import ErrorBoundary from './components/ErrorBoundary'
import { StudioProvider } from './studio/StudioProvider'
import './index.css'

if (typeof window !== 'undefined') {
  window.addEventListener('error', (event) => {
    console.error('ChronoCut global error:', event.error)
  })
  window.addEventListener('unhandledrejection', (event) => {
    console.error('ChronoCut unhandled rejection:', event.reason)
  })
}

// Route split: landing visuals live on /, job work on /studio, the
// editing workspace on /studio/:jobId/timeline. The boundary wraps every
// route so a data-shape crash renders the recovery card instead of an
// unmounted (blank) document.
ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <StudioProvider>
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/studio" element={<Studio />} />
            <Route path="/studio/:jobId/timeline" element={<Timeline />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ErrorBoundary>
      </StudioProvider>
    </BrowserRouter>
  </React.StrictMode>
)
