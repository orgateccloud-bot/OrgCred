import { getMeApiMeGet } from '@/api/generated/sdk.gen'

/**
 * O papel do login autenticado, lido de GET /api/me.
 *
 * Existe separado da store porque os guardas de rota (`beforeLoad`) rodam ANTES
 * de qualquer componente montar — a store pode ainda estar vazia num F5 direto
 * numa URL profunda. O guarda precisa saber o papel para decidir o destino, e a
 * única fonte confiável nesse momento é a API.
 *
 * NÃO é enforcement: o backend barra cada request pelo papel a cada chamada
 * (get_painel_user / get_tomador_user). Isto é só roteamento — mandar o tomador
 * para o portal e o operador para o painel. Se a chamada falhar, devolve null e
 * o guarda decide o fail-safe (tratar como sem papel definido).
 */
export async function papelDoLogin(): Promise<string | null> {
  try {
    const res = await getMeApiMeGet()
    return res.data?.papel ?? null
  } catch {
    return null
  }
}
