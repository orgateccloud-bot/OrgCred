import { test, expect, type Page } from '@playwright/test'
import {
  semearCenarioAtivacao,
  semearCenarioGeografico,
  type CenarioAtivacao,
} from './fixtures/seed'

/**
 * Ciclo de vida completo de uma operação de crédito, pela UI, contra
 * backend e Postgres reais — e o gate geográfico do Art. 5º.
 *
 * O spec de ativação (ativacao.spec.ts) cobre o caminho de bloqueio por
 * teto (OC001). Este cobre o que faltava: criar, registrar, liquidar, e o
 * bloqueio por município não autorizado (OC002) — que é o único gate legal
 * que não depende de dinheiro, e portanto o mais fácil de passar
 * despercebido em teste.
 */

type CenarioAutenticavel = Pick<CenarioAtivacao, 'usuarioId' | 'accessToken'>

async function mockLoginSupabase(page: Page, cenario: CenarioAutenticavel) {
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

async function login(page: Page, cenario: CenarioAutenticavel) {
  await mockLoginSupabase(page, cenario)
  await page.goto('/login')
  await page.getByLabel('E-mail').fill('e2e-operador@orgcred.test')
  await page.getByLabel('Senha').fill('senha-e2e-qualquer')
  await page.getByRole('button', { name: 'Entrar' }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
}

test.describe('Ciclo de vida da operação de crédito', () => {
  test('criar -> registrar -> ativar -> liquidar, com capital voltando ao fim', async ({
    page,
  }) => {
    // Erros de console são falha, não ruído: foi assim que apareceram o
    // TooltipProvider ausente (derrubava toda rota autenticada) e o <li>
    // aninhado no breadcrumb. Silenciar aqui é desperdiçar o melhor
    // detector de regressão que a suíte tem.
    const errosConsole: string[] = []
    page.on('console', (m) => {
      if (m.type() === 'error') errosConsole.push(m.text())
    })
    page.on('pageerror', (e) => errosConsole.push(String(e)))

    const cenario = await semearCenarioAtivacao()
    await login(page, cenario)

    // --- Criar: nasce como proposta e NÃO compromete capital ---------------
    await page.goto('/operacoes/nova')
    await expect(page.getByRole('heading', { name: 'Nova operação' })).toBeVisible()

    await page.getByLabel('Tomador').click()
    await page.getByRole('option', { name: /Padaria E2E ME/ }).click()
    await page.getByLabel('Valor principal (R$)').fill('5000')
    await page.getByLabel('Taxa de juros (% a.m.)').fill('2')
    await page.getByLabel('Número de parcelas').fill('10')
    await page.getByRole('button', { name: 'Criar proposta' }).click()

    // Navega para o detalhe da operação recém-criada.
    await expect(page.getByRole('heading', { name: 'Padaria E2E ME' })).toBeVisible()
    await expect(page.getByText('Proposta', { exact: true })).toBeVisible()

    // --- Registrar: exige a referência da entidade registradora (OC004) ----
    await page.getByRole('button', { name: 'Registrar' }).click()
    await page.getByLabel('Referência do registro').fill('B3-REG-E2E-CICLO')
    await page.getByRole('button', { name: 'Confirmar registro' }).click()
    await expect(page.getByText('Registrada', { exact: true })).toBeVisible()

    // Antes da ativação não há agenda: ela é emitida pelo banco no momento
    // em que o crédito passa a existir de fato.
    await expect(page.getByText(/a agenda é emitida no momento da ativação/)).toBeVisible()

    // --- Ativar: passa a comprometer capital -------------------------------
    await page.getByRole('button', { name: 'Ativar' }).click()
    await page.getByRole('button', { name: 'Confirmar ativação' }).click()
    await expect(page.getByText('Ativa', { exact: true })).toBeVisible()

    // --- Agenda emitida na mesma transação da ativação ---------------------
    const agenda = page.getByRole('table')
    await expect(agenda.getByRole('row')).toHaveCount(12) // cabeçalho + 10 parcelas + totais
    // A soma das amortizações fecha EXATAMENTE no principal. Esse é o
    // invariante que importa: se sobrar centavo, a quitação nunca fecha.
    await expect(page.getByRole('cell', { name: 'R$ 5.000,00', exact: true })).toBeVisible()

    // O ledger registrou o evento — a operação aparece na linha do tempo.
    await expect(page.getByText(/ativou uma operação de crédito/)).toBeVisible()

    // Dashboard reflete o comprometimento (5.000 de 50.000 = 10,0%).
    await page.goto('/')
    await expect(page.getByText('10,0% de')).toBeVisible()

    // --- Liquidar: devolve o capital --------------------------------------
    await page.goto('/operacoes')
    await page.getByRole('link', { name: 'Padaria E2E ME' }).first().click()
    await page.getByRole('button', { name: 'Liquidar' }).click()
    await page.getByRole('button', { name: 'Confirmar liquidação' }).click()
    await expect(page.getByText('Liquidada', { exact: true })).toBeVisible()

    // Os dois eventos ficam na linha do tempo — o ledger é append-only.
    await expect(page.getByText(/ativou uma operação de crédito/)).toBeVisible()
    await expect(page.getByText(/liquidou uma operação de crédito/)).toBeVisible()

    // Capital voltou: comprometido de novo em 0,0%.
    await page.goto('/')
    await expect(page.getByText('0,0% de')).toBeVisible()

    expect(errosConsole, `erros de console durante o ciclo: ${errosConsole.join(' | ')}`).toEqual(
      [],
    )
  })

  test('gate geográfico bloqueia ativação de tomador fora da área (OC002)', async ({ page }) => {
    const cenario = await semearCenarioGeografico()
    await login(page, cenario)

    // Esta operação tem capital de sobra (1.000 de 50.000) e referência de
    // registro presente — se for bloqueada, só pode ser pelo município.
    await page.goto(`/operacoes/${cenario.operacaoForaDaAreaId}`)
    await expect(page.getByRole('heading', { name: 'Mercado Fora da Area ME' })).toBeVisible()

    // A própria tela já avisa antes de tentar.
    await expect(page.getByText(/Não autorizado \(OC002 bloqueia ativação\)/)).toBeVisible()

    await page.getByRole('button', { name: 'Ativar' }).click()
    await page.getByRole('button', { name: 'Confirmar ativação' }).click()

    // Mensagem traduzida do SQLSTATE, não "erro 400".
    await expect(page.getByText('O tomador está fora da área de atuação autorizada.')).toBeVisible()

    // O diálogo continua aberto — nada foi perdido em silêncio.
    await expect(page.getByRole('button', { name: 'Confirmar ativação' })).toBeVisible()
  })
})
