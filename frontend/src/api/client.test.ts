import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resolverBaseUrl } from './client'
// Só o tipo: `vi.resetModules()` recria o grafo, então a CLASSE usada em
// `toBeInstanceOf` tem que vir do mesmo import dinâmico do client — a estática
// pertenceria a outro registro de módulos e nunca casaria.
import type { ApiError } from './errors'

const { supabaseMock } = vi.hoisted(() => ({
  supabaseMock: {
    auth: {
      getSession: vi.fn(),
      refreshSession: vi.fn(),
    },
  },
}))

vi.mock(
  '../auth/supabaseClient',
  () =>
    ({
      supabase: supabaseMock,
      supabaseConfigurado: true,
      getSession: vi.fn(),
    }) as unknown as typeof import('../auth/supabaseClient'),
)

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('resolverBaseUrl', () => {
  it('sem override resolve para caminho relativo', () => {
    expect(resolverBaseUrl(undefined)).toBe('')
  })

  it('trata string vazia e só-espaços como ausência de override', () => {
    expect(resolverBaseUrl('')).toBe('')
    expect(resolverBaseUrl('   ')).toBe('')
  })

  it('preserva o override explícito', () => {
    expect(resolverBaseUrl('http://localhost:8000')).toBe('http://localhost:8000')
    expect(resolverBaseUrl('https://api.orgcred.example')).toBe('https://api.orgcred.example')
  })

  it('remove a barra final para não duplicar com o path do endpoint', () => {
    expect(resolverBaseUrl('http://localhost:8000/')).toBe('http://localhost:8000')
    expect(resolverBaseUrl('https://api.orgcred.example//')).toBe('https://api.orgcred.example')
  })
})

describe('baseUrl aplicada ao client', () => {
  it('no build de produção sem VITE_API_BASE_URL o baseUrl é relativo — nunca localhost', async () => {
    vi.resetModules()
    vi.stubEnv('DEV', false)
    vi.stubEnv('VITE_API_BASE_URL', undefined)

    const { client } = await import('./client')
    const { baseUrl } = client.getConfig()

    expect(baseUrl).toBe('')
    expect(baseUrl).not.toContain('localhost')
  })

  it('em dev sem VITE_API_BASE_URL tambem fica RELATIVO', async () => {
    // O caminho relativo em dev é atendido pelo proxy do vite.config.ts. A
    // versão anterior apontava absoluto para :8000 e passou a bater em CORS
    // assim que o backend deixou de rodar em modo permissivo — este teste
    // existe para o endereço não voltar a ter duas fontes de verdade.
    vi.resetModules()
    vi.stubEnv('DEV', true)
    vi.stubEnv('VITE_API_BASE_URL', undefined)

    const { client } = await import('./client')

    expect(client.getConfig().baseUrl).toBe('')
  })

  it('override explícito vence o fallback de dev', async () => {
    vi.resetModules()
    vi.stubEnv('DEV', true)
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.orgcred.example/')

    const { client } = await import('./client')

    expect(client.getConfig().baseUrl).toBe('https://api.orgcred.example')
  })

  it('com VITE_API_BASE_URL definido usa o override', async () => {
    vi.resetModules()
    vi.stubEnv('DEV', false)
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.orgcred.example')

    const { client } = await import('./client')

    expect(client.getConfig().baseUrl).toBe('https://api.orgcred.example')
  })

  it('mantém os interceptors de auth registrados após configurar o baseUrl', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_API_BASE_URL', undefined)

    const { client } = await import('./client')

    // O bug era só de baseUrl: a cadeia de auth (token, refresh no 401 e
    // tradução de erro) tem que continuar montada.
    expect(client.interceptors.request.exists(0)).toBe(true)
    expect(client.interceptors.response.exists(0)).toBe(true)
    expect(client.interceptors.error.exists(0)).toBe(true)
  })
})

describe('retry após refresh de token', () => {
  // baseUrl absoluta só para o teste: `new Request('/api/...')` fora do
  // navegador não resolve caminho relativo. Não muda o default de produção,
  // que continua relativo (ver o describe acima).
  const BASE = 'https://api.orgcred.example'

  function resposta(status: number, corpo: unknown): Response {
    return new Response(JSON.stringify(corpo), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  type Enviada = { method: string; url: string; headers: Headers; corpo: string }

  /**
   * Responde com o roteiro dado, na ordem, e guarda um retrato do que saiu.
   *
   * O espião CONSOME o corpo (`request.text()`), como o fetch de verdade faz.
   * É exatamente esse consumo que torna o Request original inservível como
   * molde e obriga o clone preservado: um mock que não lê o corpo deixaria o
   * Request reaproveitável e o teste passaria mesmo sem o clone — provando
   * nada. Por isso o retrato é tirado aqui, e não lido depois.
   */
  function espionarFetch(roteiro: Array<Response>) {
    const enviadas: Array<Enviada> = []
    const fetchMock = vi.fn(async (request: Request) => {
      const corpo = await request.text()
      enviadas.push({
        method: request.method,
        url: request.url,
        headers: new Headers(request.headers),
        corpo,
      })
      const proxima = roteiro[enviadas.length - 1]
      if (!proxima)
        throw new Error(`fetch chamado ${enviadas.length}x, roteiro tem ${roteiro.length}`)
      return proxima
    })
    vi.stubGlobal('fetch', fetchMock)
    return { enviadas, fetchMock }
  }

  async function carregarClient() {
    vi.resetModules()
    vi.stubEnv('DEV', false)
    vi.stubEnv('VITE_API_BASE_URL', BASE)
    const { client } = await import('./client')
    const { ApiError: ApiErrorFresco } = await import('./errors')
    return { client, ApiErrorFresco }
  }

  beforeEach(() => {
    supabaseMock.auth.getSession.mockReset()
    supabaseMock.auth.refreshSession.mockReset()
    supabaseMock.auth.getSession.mockResolvedValue({
      data: { session: { access_token: 'token-expirado' } },
    })
    supabaseMock.auth.refreshSession.mockResolvedValue({
      data: { session: { access_token: 'token-renovado' } },
      error: null,
    })
  })

  it('reenvia o POST com o MESMO corpo, método, URL e headers', async () => {
    const { enviadas, fetchMock } = espionarFetch([
      resposta(401, { detail: 'Token expirado', codigo: 'TOKEN_INVALIDO' }),
      resposta(200, { id: 'op-1' }),
    ])
    const { client } = await carregarClient()

    const corpo = { tomador_id: 't-1', valor_principal: '30000.00', prazo_meses: 12 }
    const resultado = await client.post({
      url: '/api/operacoes',
      body: corpo,
      headers: { 'X-Idempotency-Key': 'chave-1' },
    })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    const [primeira, segunda] = enviadas

    // O bug: a segunda tentativa ia sem corpo e o backend respondia 422.
    expect(JSON.parse(segunda.corpo)).toEqual(corpo)
    expect(JSON.parse(primeira.corpo)).toEqual(corpo)

    expect(segunda.method).toBe('POST')
    expect(segunda.url).toBe(`${BASE}/api/operacoes`)
    expect(segunda.headers.get('Content-Type')).toBe('application/json')
    expect(segunda.headers.get('X-Idempotency-Key')).toBe('chave-1')

    // Só o Authorization muda entre as duas tentativas.
    expect(primeira.headers.get('Authorization')).toBe('Bearer token-expirado')
    expect(segunda.headers.get('Authorization')).toBe('Bearer token-renovado')

    expect(resultado.data).toEqual({ id: 'op-1' })
  })

  it('preserva a query string ao reexecutar um GET', async () => {
    const { enviadas, fetchMock } = espionarFetch([
      resposta(401, { detail: 'Token expirado' }),
      resposta(200, { itens: [] }),
    ])
    const { client } = await carregarClient()

    await client.get({ url: '/api/operacoes', query: { status: 'ativa', limite: 25 } })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(enviadas[1].method).toBe('GET')
    expect(enviadas[1].url).toBe(`${BASE}/api/operacoes?status=ativa&limite=25`)
  })

  it('não reenvia nada quando o refresh falha — o 401 chega ao operador', async () => {
    supabaseMock.auth.refreshSession.mockResolvedValue({
      data: { session: null },
      error: { message: 'refresh token inválido' },
    })
    const { fetchMock } = espionarFetch([
      resposta(401, { detail: 'Token expirado', codigo: 'TOKEN_INVALIDO' }),
    ])
    const { client, ApiErrorFresco } = await carregarClient()

    const resultado = await client.post({ url: '/api/operacoes', body: { valor: '1' } })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(resultado.error).toBeInstanceOf(ApiErrorFresco)
    expect((resultado.error as ApiError).httpStatus).toBe(401)
    expect((resultado.error as ApiError).codigo).toBe('TOKEN_INVALIDO')
  })

  it('não tenta renovar sessão em resposta que não é 401', async () => {
    const { fetchMock } = espionarFetch([resposta(422, { detail: 'valor_principal: obrigatório' })])
    const { client } = await carregarClient()

    const resultado = await client.post({ url: '/api/operacoes', body: {} })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(supabaseMock.auth.refreshSession).not.toHaveBeenCalled()
    expect((resultado.error as ApiError).httpStatus).toBe(422)
  })

  it('reexecuta uma vez só — o retry não passa pelos interceptors de novo', async () => {
    const { fetchMock } = espionarFetch([
      resposta(401, { detail: 'Token expirado' }),
      resposta(401, { detail: 'Token expirado' }),
    ])
    const { client } = await carregarClient()

    const resultado = await client.post({ url: '/api/operacoes', body: { valor: '1' } })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(supabaseMock.auth.refreshSession).toHaveBeenCalledTimes(1)
    expect((resultado.error as ApiError).httpStatus).toBe(401)
  })
})
