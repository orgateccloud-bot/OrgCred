import { test, expect, type Page } from '@playwright/test'
import { semearCenarioAtivacao, type CenarioAtivacao } from './fixtures/seed'

/**
 * Fluxo crítico espelhando tests/test_capital_engine.py do backend:
 * login -> dashboard com dados reais -> ativar operação -> segunda
 * ativação bloqueada por teto de capital (OC001).
 *
 * Sem projeto Supabase real (ver DECISOES_PENDENTES.md), a resposta do
 * POST de login é interceptada e substituída por um token minted com a
 * mesma secret de dev que o backend usa — a partir daí, banco, API e
 * regras de negócio (trigger de teto) são 100% reais.
 *
 * As duas operações semeadas têm o mesmo valor (30.000) contra um teto
 * de 50.000: qualquer uma pode ser ativada primeiro, o resultado
 * (primeira ativa normalmente, segunda bloqueia) é o mesmo — por isso o
 * teste seleciona pelo botão "Ativar" em si, não por qual operação
 * específica é a linha.
 */

async function mockLoginSupabase(page: Page, cenario: CenarioAtivacao) {
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
}

test.describe('Ativação de operação de crédito', () => {
  test('login real -> dashboard com dados reais -> ativação -> bloqueio por teto', async ({
    page,
  }) => {
    const cenario = await semearCenarioAtivacao()
    await mockLoginSupabase(page, cenario)

    await page.goto('/login')
    await page.getByLabel('E-mail').fill('e2e-operador@orgcred.test')
    await page.getByLabel('Senha').fill('senha-e2e-qualquer')
    await page.getByRole('button', { name: 'Entrar' }).click()

    // Guarda de rota + dashboard real: capital disponível reflete
    // exatamente o que foi semeado (50.000 total, nada comprometido).
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
    // Total e disponível são ambos 50.000 (nada comprometido ainda) — dois
    // elementos batem o texto, então confere a contagem em vez de um único.
    await expect(page.getByText(/50\.000,00/)).toHaveCount(2)

    await page.goto('/operacoes')
    await expect(page.getByRole('button', { name: 'Ativar' })).toHaveCount(2)

    // Ativa a primeira operação — cabe no teto (30.000 de 50.000).
    await page.getByRole('button', { name: 'Ativar' }).first().click()
    await expect(page.getByText('Confirmar ativação de operação')).toBeVisible()
    await page.getByRole('button', { name: 'Confirmar ativação' }).click()
    await expect(page.getByText('Confirmar ativação de operação')).not.toBeVisible()
    await expect(page.getByRole('button', { name: 'Ativar' })).toHaveCount(1)

    // Segunda operação (mesmo valor) excede o disponível remanescente
    // (20.000) — bloqueio real do trigger de banco (OC001), traduzido
    // pelo dicionário de erro do frontend.
    await page.getByRole('button', { name: 'Ativar' }).click()
    await page.getByRole('button', { name: 'Confirmar ativação' }).click()
    // Modal continua aberto com o erro visível — nada foi silenciosamente
    // perdido (o botão "Confirmar ativação" segue presente, provando que
    // o dialog não fechou sozinho).
    await expect(page.getByText('Esta operação excede o teto de capital disponível.')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Confirmar ativação' })).toBeVisible()
  })
})
