import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  // Execução serial, 1 worker: o seed (e2e/fixtures/seed.ts) TRUNCA tabelas
  // compartilhadas para tornar cada cenário repetível. Com paralelismo, dois
  // specs se atropelam — um trunca o banco enquanto o outro conta linhas.
  // Isso já se manifestou: um spec temporário inflou a contagem de botões
  // "Ativar" do spec de ativação e o derrubou.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? 'github' : 'html',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    env: {
      // Placeholders só para satisfazer o guard `supabaseConfigurado` e
      // fazer o SDK tentar a chamada de rede de verdade — a resposta é
      // sempre interceptada pelos testes (ver e2e/ativacao.spec.ts),
      // nunca sai para a internet.
      VITE_SUPABASE_URL: 'https://e2e-test.supabase.co',
      VITE_SUPABASE_ANON_KEY: 'e2e-test-anon-key',
    },
  },
})
