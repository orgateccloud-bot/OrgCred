import { test, expect, type Page } from '@playwright/test'
import { semearTomadorSemIdentificacao, type CenarioSemIdentificacao } from './fixtures/seed'

/**
 * Evidência de identificação (Lei 9.613/98, art. 10, I) pela interface.
 *
 * Este spec existe por uma lacuna específica: os componentes da seção de
 * Identificação foram testados com o SDK mockado, então o caminho real do
 * upload — o `formDataBodySerializer` do cliente gerado montando o corpo
 * multipart — nunca passou por uma requisição de verdade. Um corpo malformado
 * passaria despercebido em todos os testes de unidade.
 *
 * Por que a asserção é sobre a REQUISIÇÃO e não sobre a resposta: sem a
 * `service_role` key do Supabase Storage o servidor responde 503, e essa
 * dependência é resolvida ANTES da validação do corpo — ou seja, 503 viria
 * igual com um corpo quebrado. Inspecionar o que sai pela rede é o que
 * distingue "o cliente monta multipart certo" de "o cliente manda lixo".
 */

async function mockLoginSupabase(page: Page, cenario: CenarioSemIdentificacao) {
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

async function entrar(page: Page) {
  await page.goto('/login')
  await page.getByLabel('E-mail').fill('e2e-operador@orgcred.test')
  await page.getByLabel('Senha').fill('senha-e2e')
  await page.getByRole('button', { name: 'Entrar' }).click()
  await expect(page).toHaveURL('/')
}

test.describe('Identificação do tomador', () => {
  test('o vazio avisa do bloqueio e o upload sai como multipart de verdade', async ({ page }) => {
    const cenario = await semearTomadorSemIdentificacao()
    await mockLoginSupabase(page, cenario)
    await entrar(page)

    await page.goto(`/tomadores/${cenario.tomadorId}`)
    await expect(page.getByText(cenario.razaoSocial)).toBeVisible()

    // O estado vazio precisa nomear a CONSEQUÊNCIA, não só a ausência: é o
    // bloqueio que o operador vai encontrar ao tentar ativar.
    await expect(page.getByText(/nenhuma operação deste tomador/i)).toBeVisible()

    // Captura a requisição de arquivamento antes de disparar a ação.
    const requisicao = page.waitForRequest(
      (req) =>
        req.method() === 'POST' &&
        /\/api\/compliance\/tomadores\/[^/]+\/documentos$/.test(new URL(req.url()).pathname),
    )

    await page.getByRole('button', { name: /arquivar documento/i }).click()
    await page
      .getByLabel(/arquivo/i)
      .setInputFiles({
        name: 'contrato-social.pdf',
        mimeType: 'application/pdf',
        buffer: Buffer.from('%PDF-1.4 conteudo de teste e2e'),
      })
    await page.getByRole('button', { name: /^arquivar$/i }).click()

    const req = await requisicao

    // 1. É multipart de verdade, com boundary — não JSON, não urlencoded.
    const contentType = req.headers()['content-type'] ?? ''
    expect(contentType).toMatch(/^multipart\/form-data; boundary=/)

    // 2. O arquivo vai no corpo, com nome e bytes.
    const corpo = req.postData() ?? ''
    expect(corpo).toContain('contrato-social.pdf')
    expect(corpo).toContain('%PDF-1.4 conteudo de teste e2e')

    // 3. O tipo do documento acompanha, como campo de formulário.
    expect(corpo).toMatch(/name="tipo"/)

    // 4. E o hash NÃO é enviado pelo cliente: quem calcula é o servidor, a
    //    partir dos bytes. Um campo de hash aqui reabriria o buraco que a
    //    migration 019 fechou — evidência "arquivada" sem arquivo nenhum.
    expect(corpo).not.toMatch(/name="sha256"/)

    // 5. O token da sessão viaja junto: sem isto o backend responderia 401 e
    //    o teste passaria pelo motivo errado.
    expect(req.headers()['authorization']).toContain('Bearer ')

    // Sem service_role key configurada neste ambiente, o servidor recusa com
    // 503 — e a tela precisa explicar que falta configuração de infra, em vez
    // de despejar "erro inesperado" em cima do operador.
    await expect(page.getByRole('alert')).toContainText(/armazenamento|storage/i)
  })
})
