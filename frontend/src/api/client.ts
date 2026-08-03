import { client } from './generated/client.gen'
import { paraApiError } from './errors'
import { supabase, supabaseConfigurado } from '../auth/supabaseClient'

client.setConfig({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
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
