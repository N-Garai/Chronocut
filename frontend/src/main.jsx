import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

if (typeof window !== 'undefined') {
  window.addEventListener('error', (event) => {
    console.error('ChronoCut global error:', event.error)
  })
  window.addEventListener('unhandledrejection', (event) => {
    console.error('ChronoCut unhandled rejection:', event.reason)
  })
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
