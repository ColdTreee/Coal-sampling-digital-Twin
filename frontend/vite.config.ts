import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({
  plugins: [vue()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          charts: ['echarts'],
          three: ['three'],
        },
      },
    },
  },
  server: {
    proxy: {
      '/health': 'http://127.0.0.1:8000',
      '/api': { target: 'http://127.0.0.1:8000', ws: true },
    },
  },
})
