import { defineConfig } from 'vitest/config'

// Pure-module unit tests only (time math, commands, history, snapping, agent
// bridge/telemetry, EDL helpers). No DOM environment is needed, so the default
// node environment keeps the suite fast.
export default defineConfig({
  test: {
    include: ['src/**/*.test.js'],
    environment: 'node',
    reporters: 'default',
  },
})
