import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'node:path'

export default defineConfig(({ mode, command }) => {
  const target = mode === 'buyer' ? 'buyer' : 'admin'
  const development = command === 'serve'
  return {
    root: 'frontend',
    base: development ? '/' : `/${target}-static/`,
    plugins: [vue()],
    build: {
      outDir: `dist/${target}`,
      emptyOutDir: true,
      rollupOptions: {
        input: resolve('frontend', `${target}.html`),
      },
    },
    server: {
      proxy: {
        '/api': 'http://127.0.0.1:5230',
      },
    },
  }
})
