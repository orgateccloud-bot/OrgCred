export class ApiError extends Error {
  readonly codigo: string | null
  readonly httpStatus: number

  constructor(detail: string, codigo: string | null, httpStatus: number) {
    super(detail)
    this.name = 'ApiError'
    this.codigo = codigo
    this.httpStatus = httpStatus
  }
}

/**
 * Chave exata do campo `codigo` retornado pelo backend -> mensagem de UI.
 * Nunca usar .includes()/substring no texto de `detail` — o mesmo anti-padrão
 * já foi corrigido no servidor (ver app/main.py, exception handlers) e não
 * deve ser reintroduzido no cliente.
 */
const MENSAGENS_POR_CODIGO: Record<string, string> = {
  TOKEN_AUSENTE: 'Sua sessão expirou. Faça login novamente.',
  TOKEN_INVALIDO: 'Sua sessão expirou. Faça login novamente.',
  PERMISSAO_NEGADA: 'Você não tem permissão para executar esta ação.',
  OC001: 'Esta operação excede o teto de capital disponível.',
  OC002: 'O tomador está fora da área de atuação autorizada.',
  OC003: 'Essa transição de status não é permitida no estado atual da operação.',
  OC004: 'A operação precisa estar registrada na entidade registradora antes de ativar.',
  OC005: 'Essa redução de capital deixaria o comprometido acima do saldo disponível.',
  OC007: 'Falha de integridade na trilha de auditoria. Contate o suporte técnico.',
}

const MENSAGEM_PADRAO = 'Ocorreu um erro inesperado. Tente novamente.'

export function mensagemDeErro(erro: unknown): string {
  if (erro instanceof ApiError) {
    if (erro.codigo && erro.codigo in MENSAGENS_POR_CODIGO) {
      return MENSAGENS_POR_CODIGO[erro.codigo]
    }
    return erro.message || MENSAGEM_PADRAO
  }
  return MENSAGEM_PADRAO
}

interface ErrorBody {
  detail?: string
  codigo?: string | null
}

export function paraApiError(body: unknown, httpStatus: number): ApiError {
  const { detail, codigo } = (body ?? {}) as ErrorBody
  return new ApiError(detail ?? MENSAGEM_PADRAO, codigo ?? null, httpStatus)
}
