import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In production the React app is built and served by the FastAPI backend
// (FRONTEND_DIR). The dev proxy only matters for `npm run dev`, where the
// backend runs on :8000.
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
