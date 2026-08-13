/// <reference types="vitest/config" />
import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [tanstackRouter({ target: 'react', autoCodeSplitting: true }), react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    // Em produção o FastAPI serve a SPA e a API na MESMA origem, e por isso o
    // `baseUrl` do cliente é relativo (ver src/api/client.ts — cravar
    // `http://localhost:8000` ali já publicou um bundle inoperante).
    //
    // O dev server precisa reproduzir essa topologia, senão `/api` seria
    // pedido ao próprio 5173 e voltaria 404. Com o proxy, dev e produção
    // exercitam o mesmo caminho de código, e não é preciso VITE_API_BASE_URL
    // para o fluxo normal — a variável fica só para quem aponta o front para
    // um backend em outro host.
    //
    // 127.0.0.1 e não `localhost`: neste ambiente `localhost` resolve para
    // ::1 primeiro, que não responde, e cada conexão paga ~21s de timeout.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    exclude: ['node_modules', 'e2e'],
  },
})
