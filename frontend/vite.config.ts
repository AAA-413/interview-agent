import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || `http://127.0.0.1:${process.env.BACKEND_PORT || '8002'}`

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
        // WebSocket upgrade — 流式 STT (/api/interview/voice/stream) 走 ws
        ws: true,
      },
    },
  },
  build: {
    // G6 is lazy-loaded by the graph page; keep it away from the main app chunk.
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules') && (id.includes('@antv') || id.includes('/g6/'))) {
            return 'graph-vendor';
          }
        },
      },
    },
  },
})
