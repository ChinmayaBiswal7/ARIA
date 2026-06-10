import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  base: './',
  plugins: [react()],
  build: {
    outDir: '../health_bridge_android/app/src/main/assets/www',
    emptyOutDir: true,
  }
})

