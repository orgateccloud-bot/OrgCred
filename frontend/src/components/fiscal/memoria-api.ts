import { client } from '@/api/client'
import type { MemoriaCalculo } from '@/components/fiscal/memoria'

/**
 * Busca a memória de cálculo de uma apuração.
 *
 * Usa o `client` compartilhado, e não `fetch` direto: é ele que carrega o
 * Authorization da sessão, o retry depois do refresh de token e a tradução do
 * corpo de erro do backend em `ApiError`. Um fetch cru aqui devolveria 401 ao
 * contador no meio da conferência.
 *
 * Sozinho num arquivo porque é o único ponto deste diretório que toca a rede —
 * `memoria.ts` fica sem import de cliente HTTP e continua testável isolado.
 */
export async function buscarMemoriaDeCalculo(apuracaoId: string): Promise<MemoriaCalculo> {
  const { data } = await client.get<MemoriaCalculo, unknown, true>({
    security: [{ scheme: 'bearer', type: 'http' }],
    url: `/api/fiscal/apuracoes/${apuracaoId}/memoria`,
    throwOnError: true,
  })
  return data
}
