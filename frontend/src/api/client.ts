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
 * RELATIVO NOS DOIS MODOS, e é a mesma razão em produção e em desenvolvimento:
 * a API responde na mesma origem que serviu a página.
 *
 * Em produção porque o FastAPI serve a SPA (montada depois dos routers `/api`,
 * ver app/main.py). Em desenvolvimento porque o `vite.config.ts` faz proxy de
 * `/api` e `/health` para o backend local.
 *
 * ESTE RAMO JÁ EXISTIU e foi `import.meta.env.DEV ? 'http://localhost:8000'`,
 * escrito quando o proxy ainda não existia. Ele apontava absoluto para :8000 a
 * partir de :5173 e passou a ser bloqueado por CORS assim que o backend deixou
 * de rodar em modo permissivo — quebrando metade do E2E com um erro que não se
 * parece com "o baseUrl está errado". Duas fontes de verdade para o mesmo
 * endereço (aqui e o proxy) é o que produz esse tipo de divergência: agora há
 * uma só.
 *
 * VITE_API_BASE_URL continua valendo como override explícito, para quem aponta
 * o front para um backend em outro host.
 */
const override = resolverBaseUrl(import.meta.env.VITE_API_BASE_URL)

client.setConfig({ baseUrl: override })

/**
 * Cópia intacta de cada requisição em voo, para poder reexecutá-la depois do
 * refresh de token.
 *
 * O corpo de um `Request` é um ReadableStream de leitura única: assim que o
 * `fetch` o envia, ele está consumido e o objeto original não serve mais como
 * molde. A versão anterior reexecutava com `new Request(url, {method, headers})`
 * e por isso o retry ia SEM CORPO — toda mutação que pegasse o token expirado
 * chegava vazia no backend e voltava 422 (ou pior, gravava errado), com o
 * operador vendo um erro sem relação nenhuma com a causa real.
 *
 * Guardamos um `clone()` ANTES do envio; o clone tem método, URL (com query),
 * headers e corpo intactos. Chave fraca: se a requisição for descartada sem
 * passar pelo interceptor de resposta (erro de rede, por exemplo), a cópia é
 * coletada junto e não vaza memória.
 */
const requisicoesPreservadas = new WeakMap<Request, Request>()

// Anexa o access token da sessão Supabase atual em toda requisição.
client.interceptors.request.use(async (request) => {
  if (!supabaseConfigurado) return request
  const { data } = await supabase.auth.getSession()
  if (data.session) {
    request.headers.set('Authorization', `Bearer ${data.session.access_token}`)
  }
  // Depois de montar os headers definitivos: o clone precisa ser fiel ao que
  // efetivamente sai na primeira tentativa.
  requisicoesPreservadas.set(request, request.clone())
  return request
})

// 401 -> tenta refreshSession() uma vez -> repete a requisição original com
// o token renovado, preservando método, URL+query, headers e CORPO. Se o
// refresh falhar (ou não houver Supabase configurado), deixa o 401 propagar
// normalmente para o error interceptor.
client.interceptors.response.use(async (response, request, options) => {
  const preservada = requisicoesPreservadas.get(request)
  // Consome a cópia: cada requisição é reexecutada no máximo uma vez.
  requisicoesPreservadas.delete(request)

  if (response.status !== 401 || !supabaseConfigurado) return response

  // Sem cópia preservada (interceptor de request não rodou) o corpo já foi
  // consumido pelo fetch e não há como reenviá-lo. Reexecutar só é seguro se
  // não havia corpo nenhum; caso contrário, deixar o 401 subir é melhor do que
  // repetir a mutação vazia.
  const molde = preservada ?? (request.bodyUsed ? undefined : request)
  if (!molde) return response

  const { data, error } = await supabase.auth.refreshSession()
  if (error || !data.session) return response

  const retryHeaders = new Headers(molde.headers)
  retryHeaders.set('Authorization', `Bearer ${data.session.access_token}`)

  // `new Request(molde, { headers })` herda método, URL com query string,
  // corpo, credentials, mode e redirect do molde — só os headers são trocados.
  const reexecucao = new Request(molde, { headers: retryHeaders })
  // Mesma implementação de fetch que o cliente usou na primeira tentativa
  // (`options.fetch` já vem resolvido); em variável local para não perder o
  // binding de `globalThis` ("Illegal invocation").
  const executarFetch = options.fetch ?? globalThis.fetch
  return executarFetch(reexecucao)
})

client.interceptors.error.use((error, response) => paraApiError(error, response?.status ?? 0))

export { client }
