import { describe, expect, it } from 'vitest'
import { ApiError, mensagemDeErro, normalizarDetail, paraApiError } from './errors'

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

  it('ignora codigo que não é string', () => {
    expect(paraApiError({ detail: 'x', codigo: 42 }, 400).codigo).toBeNull()
    expect(paraApiError({ detail: 'x', codigo: null }, 400).codigo).toBeNull()
  })

  // O bug: o detail de um 422 do FastAPI é uma LISTA de objetos. Tratado como
  // string, virava "[object Object]" na tela.
  it('normaliza o 422 de validação do FastAPI (detail em lista)', () => {
    const erro = paraApiError(
      {
        detail: [
          {
            type: 'greater_than',
            loc: ['body', 'valor_principal'],
            msg: 'Input should be greater than 0',
            input: '0',
          },
        ],
      },
      422,
    )
    expect(erro.message).not.toContain('[object Object]')
    expect(erro.message).toContain('valor_principal')
    expect(erro.message).toContain('Input should be greater than 0')
    expect(mensagemDeErro(erro)).toBe(erro.message)
  })

  it('cai na mensagem padrão quando a lista de validação não traz nada legível', () => {
    const erro = paraApiError({ detail: [] }, 422)
    expect(erro.message).toBe('Ocorreu um erro inesperado. Tente novamente.')
  })
})

describe('normalizarDetail', () => {
  it('devolve a string como veio quando detail é string', () => {
    expect(normalizarDetail('Operação 7 não existe.')).toBe('Operação 7 não existe.')
  })

  it('devolve null para detail vazio, ausente ou sem conteúdo aproveitável', () => {
    expect(normalizarDetail(undefined)).toBeNull()
    expect(normalizarDetail(null)).toBeNull()
    expect(normalizarDetail('   ')).toBeNull()
    expect(normalizarDetail([])).toBeNull()
    expect(normalizarDetail([{ type: 'missing' }])).toBeNull()
    expect(normalizarDetail(42)).toBeNull()
  })

  it('nomeia o campo e descarta a origem ("body") do loc', () => {
    expect(normalizarDetail([{ loc: ['body', 'numero_parcelas'], msg: 'Field required' }])).toBe(
      'Dados inválidos. Corrija e envie novamente: numero_parcelas: Field required.',
    )
  })

  it('junta caminho aninhado do loc com ponto', () => {
    expect(
      normalizarDetail([{ loc: ['body', 'parcelas', 0, 'valor'], msg: 'Input inválido' }]),
    ).toBe('Dados inválidos. Corrija e envie novamente: parcelas.0.valor: Input inválido.')
  })

  it('lista todos os campos recusados, separados por ponto e vírgula', () => {
    const texto = normalizarDetail([
      { loc: ['body', 'taxa_juros_mensal'], msg: 'Input should be greater than 0' },
      { loc: ['body', 'tomador_id'], msg: 'Field required' },
    ])
    expect(texto).toContain('taxa_juros_mensal: Input should be greater than 0')
    expect(texto).toContain('tomador_id: Field required')
    expect(texto).toContain('; ')
  })

  it('remove itens idênticos repetidos', () => {
    const texto = normalizarDetail([
      { loc: ['body', 'cpf'], msg: 'Documento inválido' },
      { loc: ['body', 'cpf'], msg: 'Documento inválido' },
    ])
    expect(texto).toBe('Dados inválidos. Corrija e envie novamente: cpf: Documento inválido.')
  })

  it('aceita um objeto de erro solto (não embrulhado em lista)', () => {
    expect(normalizarDetail({ loc: ['query', 'trimestre'], msg: 'Trimestre inválido' })).toBe(
      'Dados inválidos. Corrija e envie novamente: trimestre: Trimestre inválido.',
    )
  })

  it('usa só a msg quando o loc não identifica campo algum', () => {
    expect(normalizarDetail([{ loc: ['body'], msg: 'Corpo ausente' }])).toBe(
      'Dados inválidos. Corrija e envie novamente: Corpo ausente.',
    )
    expect(normalizarDetail([{ msg: 'Corpo ausente' }])).toBe(
      'Dados inválidos. Corrija e envie novamente: Corpo ausente.',
    )
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
    [
      'OC004',
      'A operação precisa de um registro CONFIRMADO em entidade registradora antes de ativar. Abra e confirme o registro na seção "Registro em entidade registradora".',
    ],
    ['OC005', 'Essa redução de capital deixaria o comprometido acima do saldo disponível.'],
    ['OC007', 'Falha de integridade na trilha de auditoria. Contate o suporte técnico.'],
    [
      'OC008',
      'Renegociação exige informar as condições da nova operação — a baixa e a substituta são feitas juntas.',
    ],
    [
      'OC009',
      'Parcela já emitida não pode ser alterada nem apagada — a agenda é a prova do que foi contratado. Para registrar pagamento, faça a baixa da parcela contra o movimento bancário.',
    ],
    [
      'OC010',
      'A trilha de eventos da operação é somente inclusão e não aceita alteração nem exclusão. Registre um novo evento em vez de corrigir o anterior.',
    ],
    [
      'OC011',
      'A baixa não tem lastro bancário válido: a parcela pode já estar baixada, ou o movimento não existe, já foi usado em outra parcela ou tem valor menor que a parcela. Confira o extrato e selecione outro movimento.',
    ],
    [
      'OC012',
      'Movimento bancário é fato externo: registra-se, não se edita. Importe o extrato corrigido em vez de alterar o lançamento.',
    ],
    [
      'OC013',
      'Esta evidência de identificação está dentro do prazo de retenção legal de 5 anos (Lei 9.613/98) e não pode ser alterada nem excluída. Se o documento mudou, arquive uma nova evidência ao lado da atual.',
    ],
    [
      'OC014',
      'Ocorrência de atipicidade é somente inclusão — uma trilha de PLD que se edita não serve como defesa. Só o registro da comunicação ao canal externo pode ser preenchido depois.',
    ],
    [
      'OC015',
      'Não há parâmetro fiscal vigente para o período informado. Cadastre os percentuais de presunção e as alíquotas do trimestre antes de apurar.',
    ],
    [
      'OC016',
      'Apuração fiscal já gravada não se edita. Para corrigir, gere uma nova versão retificadora do período.',
    ],
    [
      'OC017',
      'Instrumento contratual já emitido não pode ser alterado — o tomador tem uma via do documento original. Reemita o contrato para gerar uma nova versão.',
    ],
    [
      'OC018',
      'Essa mudança de status do registro não é permitida: confirmado e rejeitado são terminais. Se o registro precisa ser refeito, abra um novo registro.',
    ],
    [
      'OC019',
      'O tomador precisa ter evidência de identificação arquivada antes de ativar. Arquive o documento na ficha do tomador.',
    ],
    [
      'OC022',
      'A operação só pode ser liquidada com todas as parcelas baixadas — liquidar é quitar, e devolve o capital ao teto. Baixe as parcelas em aberto contra o extrato bancário; se o valor não será recebido, encerre pela baixa por prejuízo, que encerra a cobrança e não devolve capital.',
    ],
    ['OC429', 'Muitas requisições em pouco tempo. Aguarde cerca de um minuto e tente novamente.'],
  ])('mapeia %s pela chave exata do código', (codigo, mensagemEsperada) => {
    const erro = new ApiError('mensagem técnica original', codigo, 422)
    expect(mensagemDeErro(erro)).toBe(mensagemEsperada)
  })

  // Cobertura do contrato: todo SQLSTATE traduzido pelo backend
  // (PGCODE_MAP em app/core/db_errors.py) precisa ter mensagem aqui, senão o
  // operador recebe o texto técnico do trigger.
  it.each([
    'OC001',
    'OC002',
    'OC003',
    'OC004',
    'OC005',
    'OC007',
    'OC008',
    'OC009',
    'OC010',
    'OC011',
    'OC012',
    'OC013',
    'OC014',
    'OC015',
    'OC016',
    'OC017',
    'OC018',
    'OC019',
    'OC022',
  ])('%s tem tradução própria, e não o texto cru do backend', (codigo) => {
    const tecnico = `ERROR: trigger recusou a operação (SQLSTATE ${codigo})`
    const traduzida = mensagemDeErro(new ApiError(tecnico, codigo, 422))
    expect(traduzida).not.toBe(tecnico)
    expect(traduzida.length).toBeGreaterThan(20)
  })

  // OC022 é o gate de liquidação: sem citar a baixa por prejuízo, o operador
  // de uma operação que nunca será paga fica sem saída nenhuma.
  it('OC022 cita a saída alternativa (baixa por prejuízo)', () => {
    const mensagem = mensagemDeErro(new ApiError('...', 'OC022', 422))
    expect(mensagem).toContain('parcelas')
    expect(mensagem.toLowerCase()).toContain('prejuízo')
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

  it('não casa código por prefixo nem por sufixo', () => {
    // "OC0221" e "oc022" não são OC022. Chave exata, sempre.
    expect(mensagemDeErro(new ApiError('cru', 'OC0221', 422))).toBe('cru')
    expect(mensagemDeErro(new ApiError('cru', 'oc022', 422))).toBe('cru')
    expect(mensagemDeErro(new ApiError('cru', 'OC02', 422))).toBe('cru')
  })

  it('não confunde chave herdada do protótipo com código conhecido', () => {
    // `'toString' in objeto` é true — por isso o lookup usa Object.hasOwn.
    expect(mensagemDeErro(new ApiError('detalhe cru', 'toString', 400))).toBe('detalhe cru')
    expect(mensagemDeErro(new ApiError('detalhe cru', 'constructor', 400))).toBe('detalhe cru')
  })

  it('retorna mensagem padrão para erros que não são ApiError', () => {
    expect(mensagemDeErro(new Error('erro genérico de rede'))).toBe(
      'Ocorreu um erro inesperado. Tente novamente.',
    )
    expect(mensagemDeErro('string qualquer')).toBe('Ocorreu um erro inesperado. Tente novamente.')
    expect(mensagemDeErro(null)).toBe('Ocorreu um erro inesperado. Tente novamente.')
  })
})
