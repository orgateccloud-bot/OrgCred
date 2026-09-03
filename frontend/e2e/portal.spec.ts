import { test, expect, devices, type Page } from '@playwright/test'
import { semearCenarioPortal, type CenarioPortal } from './fixtures/seed'

/**
 * Portal do tomador (OC027), pela UI, contra backend e Postgres reais —
 * NUM VIEWPORT DE CELULAR, porque é ali que o tomador vive: o operador da
 * ESC tem um monitor; o dono da padaria tem um telefone. Rodar este spec em
 * desktop provaria a forma errada da tela (a agenda vira cartões abaixo de
 * `sm`, e é a forma de cartões que este teste exercita).
 *
 * O que ele existe para provar:
 * 1. o login com papel 'tomador' cai no portal, e o painel o devolve para lá;
 * 2. o tomador vê a própria empresa, a agenda emitida pelo banco e a próxima
 *    parcela em destaque;
 * 3. o cerco: a operação de OUTRO tomador responde como inexistente (404 —
 *    nunca 403, que confirmaria a existência; ver app/routers/portal.py).
 */

test.use({ ...devices['Pixel 7'] })

/**
 * As fontes EXTERNAS da home (clima, indicadores) respondem por fixture:
 * teste que depende da meteorologia real de Formoso/GO passa ou falha
 * conforme o dia — e a suíte precisa rodar offline. O dia 2 da previsão
 * carrega 42 mm de chuva de propósito, para provar o alerta derivado.
 */
async function interceptarFontesExternas(page: Page) {
  await page.route('https://geocoding-api.open-meteo.com/**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        results: [{ latitude: -13.65, longitude: -48.88, name: 'Formoso', admin1: 'Goiás' }],
      }),
    }),
  )
  await page.route('https://api.open-meteo.com/**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        current: {
          temperature_2m: 27.4,
          weather_code: 0,
          wind_speed_10m: 12,
          relative_humidity_2m: 65,
        },
        daily: {
          time: ['2026-08-29', '2026-08-30', '2026-08-31'],
          weather_code: [0, 80, 1],
          temperature_2m_max: [31, 26, 30],
          temperature_2m_min: [18, 17, 18],
          precipitation_sum: [0, 42, 2],
          precipitation_probability_max: [5, 90, 20],
          wind_speed_10m_max: [15, 30, 12],
        },
      }),
    }),
  )
  await page.route('https://api.bcb.gov.br/**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(
        route.request().url().includes('bcdata.sgs.432')
          ? [{ data: '28/08/2026', valor: '15.00' }]
          : [{ data: '01/08/2026', valor: '4,85' }],
      ),
    }),
  )
  await page.route('https://economia.awesomeapi.com.br/**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ USDBRL: { bid: '5.4321', create_date: '2026-08-28 10:00:00' } }),
    }),
  )
}

async function loginTomador(page: Page, cenario: CenarioPortal) {
  const usuario = {
    id: cenario.usuarioId,
    aud: 'authenticated',
    role: 'authenticated',
    email: 'e2e-tomador@orgcred.test',
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
  await page.getByLabel('E-mail').fill('e2e-tomador@orgcred.test')
  await page.getByLabel('Senha').fill('senha-e2e-qualquer')
  await page.getByRole('button', { name: 'Entrar' }).click()
}

test.describe('Portal do tomador', () => {
  test('login cai no portal, agenda no celular, e o cerco responde 404', async ({ page }) => {
    // Erros de console são falha, não ruído (ver ciclo-de-vida.spec.ts).
    const errosConsole: string[] = []
    page.on('console', (m) => {
      if (m.type() === 'error') errosConsole.push(m.text())
    })
    page.on('pageerror', (e) => errosConsole.push(String(e)))

    const cenario = await semearCenarioPortal()
    await interceptarFontesExternas(page)
    await loginTomador(page, cenario)

    // --- Home: a própria empresa, e só ela ------------------------------
    await expect(page.getByRole('heading', { name: cenario.razaoSocial })).toBeVisible()
    await expect(page.getByText('1 operação ativa')).toBeVisible()
    await expect(page.getByText('Empréstimo').first()).toBeVisible()
    await expect(page.getByText('0/6 pagas')).toBeVisible()
    // A empresa alheia não pode nem ser mencionada.
    await expect(page.getByText('Comercio Alheio')).toHaveCount(0)

    // --- Boas-vindas: o tempo AGORA no município do cadastro ------------
    await expect(page.getByText('27°C')).toBeVisible()
    await expect(page.getByText('Céu limpo · Formoso/GO')).toBeVisible()

    // --- Minhas parcelas: o próximo vencimento atravessa as operações ---
    await expect(page.getByText('Parcela 1 · Empréstimo')).toBeVisible()
    // .first(): as três próximas parcelas dizem "vence em N dias" — a
    // asserção é sobre a contagem regressiva existir, não sobre uma linha.
    await expect(page.getByText(/vence em \d+ dias/).first()).toBeVisible()

    // --- Meus pagamentos: nada pago ainda é estado, não erro ------------
    await expect(page.getByText('Nenhum pagamento registrado ainda.')).toBeVisible()

    // --- Radar: alerta derivado COM critério, e indicadores com fonte ---
    await expect(page.getByText('Chuva forte prevista — 30/08/2026')).toBeVisible()
    await expect(page.getByText('42 mm previstos, 90% de chance')).toBeVisible()
    await expect(page.getByText('Selic (meta)')).toBeVisible()
    await expect(page.getByText('15,00% a.a.')).toBeVisible()
    await expect(page.getByText('R$ 5,43')).toBeVisible()

    // --- Compliance: a frase do dia fecha a home ------------------------
    await expect(page.getByText(/Compliance · Frase do dia/)).toBeVisible()

    // --- Solicitar crédito: prévia honesta, nenhum POST -----------------
    await page.getByRole('button', { name: 'Solicitar crédito' }).click()
    await expect(page.getByText('nenhum crédito nasce aprovado automaticamente')).toBeVisible()
    await page.getByLabel('Valor pretendido (R$)').fill('20.000,00')
    await page.getByLabel('Finalidade').fill('Reforma do forno')
    await expect(page.getByText('Valor pretendido: R$ 20.000,00')).toBeVisible()
    await expect(page.getByText('não representa aprovação automática')).toBeVisible()
    await page.keyboard.press('Escape')

    // --- Painel devolve o tomador ao portal -----------------------------
    await page.goto('/')
    await expect(page.getByRole('heading', { name: cenario.razaoSocial })).toBeVisible()

    // --- Detalhe: agenda emitida pelo banco, na forma de cartões --------
    // Pelo cartão de "Seus créditos" (o valor principal só aparece nele —
    // "Empréstimo" sozinho agora também nomeia linhas de Minhas parcelas).
    await page.getByRole('link', { name: /12\.000,00 · 6x/ }).click()
    await expect(page.getByRole('heading', { name: 'Empréstimo' })).toBeVisible()
    await expect(page.getByText('Ativa')).toBeVisible()
    await expect(page.getByText('juros de 2,0% a.m.')).toBeVisible()

    // A próxima parcela em destaque: nenhuma vencida, então é a 1.
    await expect(page.getByText('Próxima parcela (1)')).toBeVisible()

    // No celular a agenda são cartões ("Parcela N"), não a tabela.
    await expect(page.getByText('Parcela 6', { exact: true })).toBeVisible()
    await expect(page.getByRole('table')).toBeHidden()
    await expect(page.getByText('Total da agenda:')).toBeVisible()

    // Contrato ainda não emitido é estado legítimo, não erro.
    await expect(page.getByText('O contrato desta operação ainda não foi emitido.')).toBeVisible()

    // --- O cerco: o que não é dele não está lá --------------------------
    await page.goto(`/portal/operacoes/${cenario.operacaoDeOutroTomadorId}`)
    await expect(page.getByRole('alert')).toContainText('Operação não encontrada.')

    // O 404 do cerco é o comportamento sob teste e o navegador loga toda
    // resposta 4xx como erro de console; filtrar só essas linhas mantém o
    // detector de erro de JavaScript (ver ciclo-de-vida.spec.ts).
    const inesperados = errosConsole.filter((e) => !e.includes('404 (Not Found)'))
    expect(inesperados, `erros de console: ${inesperados.join(' | ')}`).toEqual([])
  })
})
