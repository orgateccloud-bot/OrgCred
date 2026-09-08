import { ApiError, mensagemDeErro } from '@/api/errors'

/**
 * Erros do fluxo de convite ao portal, no mesmo espírito de
 * identificacao/mensagens.ts: os status que carregam instrução própria não
 * podem cair no texto genérico do dicionário.
 *
 * - 503: o servidor está sem as credenciais do Supabase (mesmo par do acervo
 *   de evidências). Instrução de infraestrutura, não de formulário.
 * - 409 e 502 já chegam com `detail` escrito para gente (app/routers/
 *   tomadores.py e app/core/convites.py) — o fallback de mensagemDeErro os
 *   exibe como vieram.
 */
export function mensagemDeErroDeConvite(erro: unknown): string {
  if (erro instanceof ApiError && erro.httpStatus === 503) {
    return (
      'Convite indisponível (HTTP 503): o servidor está sem as credenciais do Supabase ' +
      '(SUPABASE_URL e service_role key — o mesmo par do acervo de evidências). ' +
      'Nenhum convite foi criado. Peça a configuração a quem administra o ambiente.'
    )
  }
  return mensagemDeErro(erro)
}
