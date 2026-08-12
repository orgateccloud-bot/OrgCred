import { client } from './generated/client.gen'
import { paraApiError } from './errors'
import { supabase, supabaseConfigurado } from '../auth/supabaseClient'

/**
 * Normaliza o override de baseUrl. Sem valor (ausente, vazio ou só espaços)
 * devolve string vazia, que o cliente gerado trata como caminho RELATIVO
 * (`getUrl` em generated/core/utils.gen.ts faz `(baseUrl ?? '') + path`).
 *
 * Nunca voltar a usar 'http://localhost:8000' como default de produção: o Vite
 * resolve `import.meta.env` em tempo de BUILD, o literal vaza para o bundle e
 * toda chamada de API passa a apontar para a máquina do operador — foi
 * exatamente esse o bug que deixou o sistema inoperante.
 */
export function resolverBaseUrl(valor: string | undefined): string {
  const bruto = valor?.trim()
  if (!bruto) return ''
  // Barra final duplicaria com o path do endpoint ("//api/operacoes").
  return bruto.replace(/\/+$/, '')
}

/**
 * Produção: caminho relativo. O FastAPI serve a SPA na mesma origem — o SPA é
 * montado depois dos routers `/api` (app/main.py) —, então relativo sempre
 * acerta a API sem depender de nenhuma variável existir no build.
 *
 * Desenvolvimento: backend local. `vite dev` sobe o front em :5173 e o back
 * fica em :8000 (origens distintas, liberadas no CORS de app/main.py) e não há
 * proxy no vite.config.ts; com caminho relativo, `npm run dev` e o Playwright
 * — que sobe o dev server sem VITE_API_BASE_URL, ver playwright.config.ts —
 * bateriam em :5173/api/... e receberiam o index.html do SPA em vez de JSON.
 *
 * `import.meta.env.DEV` vira `false` no build, então o ramo de dev é eliminado
 * do bundle de produção. VITE_API_BASE_URL continua valendo como override
 * explícito em qualquer modo.
 */
const override = resolverBaseUrl(import.meta.env.VITE_API_BASE_URL)

client.setConfig({
  baseUrl: override || (import.meta.env.DEV ? 'http://localhost:8000' : ''),
})

// Anexa o access token da sessão Supabase atual em toda requisição.
client.interceptors.request.use(async (request) => {
  if (!supabaseConfigurado) return request
  const { data } = await supabase.auth.getSession()
  if (data.session) {
    request.headers.set('Authorization', `Bearer ${data.session.access_token}`)
  }
  return request
})

// 401 -> tenta refreshSession() uma vez -> repete a requisição original com
// o token renovado. Se o refresh falhar (ou não houver Supabase
// configurado), deixa o 401 propagar normalmente para o error interceptor.
client.interceptors.response.use(async (response, request) => {
  if (response.status !== 401 || !supabaseConfigurado) return response

  const { data, error } = await supabase.auth.refreshSession()
  if (error || !data.session) return response

  const retryHeaders = new Headers(request.headers)
  retryHeaders.set('Authorization', `Bearer ${data.session.access_token}`)
  return fetch(new Request(request.url, { method: request.method, headers: retryHeaders }))
})

client.interceptors.error.use((error, response) => paraApiError(error, response?.status ?? 0))

export { client }
