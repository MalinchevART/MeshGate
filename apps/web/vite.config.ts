import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: { outDir: 'dist' },
  server: {
    proxy: {
      // локална разработка: /api/* към api контейнера/процеса
      '/api': { target: 'http://localhost:8000', rewrite: p => p.replace(/^\/api/, '') },
    },
  },
})
