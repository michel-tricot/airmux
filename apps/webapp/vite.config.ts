import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '^/instance/': 'http://127.0.0.1:8000',
      '^/org/': 'http://127.0.0.1:8000',
    },
  },
})
