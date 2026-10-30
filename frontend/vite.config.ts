import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import fs from 'fs'
import type { Plugin } from 'vite'

// Dev only: serve the engine's OFL fonts at /api/fonts/{file} so specimens render in VITE_MOCK mode without a backend.
function engineFonts(): Plugin {
  const root = path.resolve(__dirname, '../engine/comic/fonts')
  const find = (name: string) => [path.join(root, name), path.join(root, 'library', name)].find(p => fs.existsSync(p))
  return {
    name: 'engine-fonts',
    configureServer(server) {
      server.middlewares.use('/api/fonts/', (req, res, next) => {
        const name = decodeURIComponent((req.url ?? '').replace(/^\//, '').split('?')[0])
        const file = /^[\w.-]+\.ttf$/.test(name) ? find(name) : undefined
        if (!file) return next()
        res.setHeader('Content-Type', 'font/ttf'); res.setHeader('Cache-Control', 'public, max-age=31536000')
        fs.createReadStream(file).pipe(res)
      })
    },
  }
}

export default defineConfig({
  base: './',
  plugins: [react(), engineFonts()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://localhost:8787', changeOrigin: true },
      '/media': { target: 'http://localhost:8787', changeOrigin: true },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
