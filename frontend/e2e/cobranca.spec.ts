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

  test('baixa só acontece com lastro bancário, e tira a parcela do atraso', async ({ page }) => {
    const errosConsole: string[] = []
    page.on('console', (m) => {
      if (m.type() === 'error') errosConsole.push(m.text())
    })
    page.on('pageerror', (e) => errosConsole.push(String(e)))

    const cenario = await semearCenarioAging()
    await login(page, cenario)

    // --- Sem extrato registrado, não há como baixar -----------------------
    await page.goto(`/operacoes/${cenario.operacaoAtrasadaId}`)
    await expect(page.getByText('120 dias')).toBeVisible()

    await page.getByRole('row', { name: /^1 / }).getByRole('button', { name: 'Baixar' }).click()
    await expect(page.getByRole('dialog')).toContainText('Nenhum movimento disponível cobre')
    await page.getByRole('button', { name: 'Cancelar' }).click()

    // --- Registrar a linha do extrato ------------------------------------
    await page.goto('/cobranca')
    await page.getByRole('button', { name: 'Registrar movimento' }).click()
    await page.getByLabel('Valor (R$)').fill('2000')
    await page.getByLabel('Documento').fill('FITID-E2E-001')
    await page.getByLabel('Descrição (opcional)').fill('TED Padaria Atrasada')
    await page.getByRole('button', { name: 'Registrar', exact: true }).click()
    await expect(page.getByText('Movimento registrado.')).toBeVisible()

    const linhaExtrato = page.getByRole('row', { name: /FITID-E2E-001/ })
    await expect(linhaExtrato).toContainText('Disponível')

    // O documento é único: reimportar o mesmo extrato não duplica crédito.
    await page.getByRole('button', { name: 'Registrar movimento' }).click()
    await page.getByLabel('Valor (R$)').fill('2000')
    await page.getByLabel('Documento').fill('FITID-E2E-001')
    await page.getByRole('button', { name: 'Registrar', exact: true }).click()
    // A mensagem vem do dicionário de UI (código MOVIMENTO_DUPLICADO), não do
    // texto cru do servidor: reimportar extrato é rotina, e o operador precisa
    // ser mandado para a lista de movimentos, onde o lançamento já está.
    await expect(page.getByRole('dialog')).toContainText('Este documento já foi registrado')
    await page.getByRole('button', { name: 'Cancelar' }).click()

    // --- Agora a baixa acontece, e o atraso some --------------------------
    await page.goto(`/operacoes/${cenario.operacaoAtrasadaId}`)
    await page.getByRole('row', { name: /^1 / }).getByRole('button', { name: 'Baixar' }).click()
    await page.getByLabel('Movimento bancário').click()
    await page.getByRole('option', { name: /FITID-E2E-001/ }).click()
    await page.getByRole('button', { name: 'Confirmar baixa' }).click()
    await expect(page.getByText('Parcela 1 baixada.')).toBeVisible()

    // O documento fica visível na linha: baixa sem origem exibida é
    // indistinguível de um "marcar como pago" sem lastro.
    await expect(page.getByRole('row', { name: /^1 / })).toContainText('FITID-E2E-001')
    await expect(page.getByText('Em dia')).toBeVisible()

    // E o movimento sai dos disponíveis — não baixa uma segunda parcela.
    await page.goto('/cobranca')
    await expect(page.getByRole('row', { name: /FITID-E2E-001/ })).toContainText('Conciliado')

    // Este teste PROVOCA um 409 de propósito (documento duplicado), e o
    // navegador loga toda resposta 4xx como erro de console. Filtrar só essa
    // linha — em vez de abandonar a asserção — mantém o detector de erro de
    // JavaScript, que é o que já pegou TooltipProvider ausente e HTML
    // inválido nesta suíte.
    //
    // 409 e não 422: reimportar extrato manda um corpo VÁLIDO; o conflito é
    // com o estado do servidor, que já tem aquele documento.
    const inesperados = errosConsole.filter((e) => !e.includes('409 (Conflict)'))
    expect(inesperados, `erros de console: ${inesperados.join(' | ')}`).toEqual([])
  })
})
