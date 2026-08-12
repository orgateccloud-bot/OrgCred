import { afterEach, describe, expect, it, vi } from 'vitest'
import { resolverBaseUrl } from './client'

afterEach(() => {
  vi.unstubAllEnvs()
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

  it('em dev sem VITE_API_BASE_URL aponta para o backend local', async () => {
    // Guarda o fluxo de `npm run dev` e o Playwright, que sobe o dev server
    // sem VITE_API_BASE_URL (ver playwright.config.ts).
    vi.resetModules()
    vi.stubEnv('DEV', true)
    vi.stubEnv('VITE_API_BASE_URL', undefined)

    const { client } = await import('./client')

    expect(client.getConfig().baseUrl).toBe('http://localhost:8000')
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
