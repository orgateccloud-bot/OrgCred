import { test, expect, type Page } from '@playwright/test'
import { semearCenarioAging, type CenarioAging } from './fixtures/seed'

/**
 * Régua de inadimplência pela UI, contra backend e Postgres reais.
 *
 * O que este spec existe para provar, e que nenhum teste de unidade pega:
 * que o operador vê o atraso calculado a partir da agenda, que a régua
 * transiciona ao ser confirmada, e que a trilha resultante deixa explícito
 * que o ato foi do sistema — sem autor humano.
 */

async function login(page: Page, cenario: CenarioAging) {
  const usuario = {
    id: cenario.usuarioId,
    aud: 'authenticated',
    role: 'authenticated',
    email: 'e2e-operador@orgcred.test',
    app_metadata: { provider: 'email', providers: ['email'] },
    user_metadata: {},
    identities: [],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }

  await page.route('**/auth/v1/token**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        access_token: cenario.accessToken,
        token_type: 'bearer',
        expires_in: 3600,
        expires_at: Math.floor(Date.now() / 1000) + 3600,
        refresh_token: 'fake-refresh-token-e2e',
        user: usuario,
      }),
    }),
  )
  await page.route('**/auth/v1/user**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(usuario) }),
  )

  await page.goto('/login')
  await page.getByLabel('E-mail').fill('e2e-operador@orgcred.test')
  await page.getByLabel('Senha').fill('senha-e2e-qualquer')
  await page.getByRole('button', { name: 'Entrar' }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
}

test.describe('Régua de inadimplência', () => {
  test('aging visível -> régua executada -> trilha atribui o ato ao sistema', async ({ page }) => {
    // Erros de console são falha, não ruído (ver ciclo-de-vida.spec.ts).
    const errosConsole: string[] = []
    page.on('console', (m) => {
      if (m.type() === 'error') errosConsole.push(m.text())
    })
    page.on('pageerror', (e) => errosConsole.push(String(e)))

    const cenario = await semearCenarioAging()
    await login(page, cenario)

    // --- Painel: o atraso vem da agenda, não de coluna atualizada à mão ---
    await page.getByRole('link', { name: 'Cobrança' }).click()
    await expect(page.getByRole('heading', { name: 'Cobrança' })).toBeVisible()

    const linha = page.getByRole('row', { name: /Padaria Atrasada ME/ })
    await expect(linha).toContainText('120 d')
    await expect(linha).toContainText('Acima de 90 dias')
    await expect(linha).toContainText('Ativa')

    // --- Régua: diz quantas serão afetadas ANTES de confirmar --------------
    await page.getByRole('button', { name: 'Executar régua' }).click()
    await expect(page.getByRole('dialog')).toContainText('1 operação se enquadra')
    await page.getByRole('button', { name: 'Confirmar execução' }).click()

    await expect(page.getByText('1 operação marcada como inadimplente.')).toBeVisible()
    await expect(linha).toContainText('Inadimplente')

    // --- Trilha: o ato da régua não é imputado a ninguém -------------------
    await page.getByRole('link', { name: 'Padaria Atrasada ME' }).click()
    await expect(page.getByRole('heading', { name: 'Padaria Atrasada ME' })).toBeVisible()

    const trilha = page.getByText('Trilha de estado').locator('xpath=ancestor::div[3]')
    await expect(trilha).toContainText('Régua automática')
    await expect(trilha).toContainText('sem autor, por construção')

    // Segunda execução não faz nada: a régua é idempotente.
    await page.getByRole('link', { name: 'Cobrança' }).click()
    await page.getByRole('button', { name: 'Executar régua' }).click()
    await expect(page.getByRole('dialog')).toContainText('Nenhuma operação se enquadra agora.')
    await page.getByRole('button', { name: 'Confirmar execução' }).click()
    await expect(page.getByText('Régua executada: nenhuma operação se enquadrou.')).toBeVisible()

    expect(errosConsole, `erros de console: ${errosConsole.join(' | ')}`).toEqual([])
  })
})
