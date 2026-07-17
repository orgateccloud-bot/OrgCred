import { describe, expect, it } from 'vitest'
import { ApiError, mensagemDeErro, paraApiError } from './errors'

describe('paraApiError', () => {
  it('extrai detail e codigo do corpo da resposta', () => {
    const erro = paraApiError({ detail: 'Token inválido: expirado', codigo: 'TOKEN_INVALIDO' }, 401)
    expect(erro).toBeInstanceOf(ApiError)
    expect(erro.message).toBe('Token inválido: expirado')
    expect(erro.codigo).toBe('TOKEN_INVALIDO')
    expect(erro.httpStatus).toBe(401)
  })

  it('usa mensagem padrão quando detail está ausente', () => {
    const erro = paraApiError({}, 500)
    expect(erro.message).toBe('Ocorreu um erro inesperado. Tente novamente.')
    expect(erro.codigo).toBeNull()
  })

  it('lida com corpo null/undefined sem lançar', () => {
    expect(() => paraApiError(null, 500)).not.toThrow()
    expect(() => paraApiError(undefined, 500)).not.toThrow()
  })
})

describe('mensagemDeErro', () => {
  it.each([
    ['TOKEN_AUSENTE', 'Sua sessão expirou. Faça login novamente.'],
    ['TOKEN_INVALIDO', 'Sua sessão expirou. Faça login novamente.'],
    ['PERMISSAO_NEGADA', 'Você não tem permissão para executar esta ação.'],
    ['OC001', 'Esta operação excede o teto de capital disponível.'],
    ['OC002', 'O tomador está fora da área de atuação autorizada.'],
    ['OC003', 'Essa transição de status não é permitida no estado atual da operação.'],
    ['OC004', 'A operação precisa estar registrada na entidade registradora antes de ativar.'],
    ['OC005', 'Essa redução de capital deixaria o comprometido acima do saldo disponível.'],
    ['OC007', 'Falha de integridade na trilha de auditoria. Contate o suporte técnico.'],
  ])('mapeia %s pela chave exata do código', (codigo, mensagemEsperada) => {
    const erro = new ApiError('mensagem técnica original', codigo, 422)
    expect(mensagemDeErro(erro)).toBe(mensagemEsperada)
  })

  it('cai para a mensagem original quando o código é desconhecido', () => {
    const erro = new ApiError('erro específico do backend', 'CODIGO_NUNCA_VISTO', 400)
    expect(mensagemDeErro(erro)).toBe('erro específico do backend')
  })

  it('nunca faz matching por substring do texto — só pela chave exata do código', () => {
    // Mensagem técnica contém "token" mas o código não é um dos mapeados —
    // não deve cair acidentalmente na mensagem de sessão expirada.
    const erro = new ApiError('falha ao processar token de pagamento', 'ALGO_OUTRO', 400)
    expect(mensagemDeErro(erro)).toBe('falha ao processar token de pagamento')
  })

  it('retorna mensagem padrão para erros que não são ApiError', () => {
    expect(mensagemDeErro(new Error('erro genérico de rede'))).toBe(
      'Ocorreu um erro inesperado. Tente novamente.',
    )
    expect(mensagemDeErro('string qualquer')).toBe('Ocorreu um erro inesperado. Tente novamente.')
    expect(mensagemDeErro(null)).toBe('Ocorreu um erro inesperado. Tente novamente.')
  })
})
