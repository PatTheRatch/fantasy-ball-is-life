import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Standalone from vite.config.ts: tests only need the React (JSX) transform and
// a jsdom DOM — not the dev server/proxy or Tailwind pipeline.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
