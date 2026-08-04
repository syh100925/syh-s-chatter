import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: '/app/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:5000',
      '/static': 'http://127.0.0.1:5000',
      '/chat': 'http://127.0.0.1:5000',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
