import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/mobile/',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8050',
        changeOrigin: true,
      },
      '/static': {
        target: 'http://localhost:8050',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
          'query':        ['@tanstack/react-query'],
          'charts':       ['recharts', 'lightweight-charts'],
          'ui':           ['lucide-react', 'clsx', 'tailwind-merge'],
        },
      },
    },
  },
})
