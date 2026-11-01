import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The frontend is always a static build hosted separately from the API; this
// dev proxy only matters for `npm run dev`, where the backend runs on :8000.
// A deployment sets VITE_API_BASE_URL to the API origin at build time.
export default defineConfig({
  plugins: [react()],
  base: '/',
  server: {
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
