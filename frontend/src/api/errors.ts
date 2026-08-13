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
 *
 * A fonte da verdade é o contrato de erro do backend: `PGCODE_MAP` em
 * app/core/db_errors.py (SQLSTATE da classe OC -> exceção de domínio), que o
 * handler de `RegraNegocioViolada` devolve como `{detail, codigo}`, mais os
 * códigos que não vêm do banco — TOKEN_AUSENTE, TOKEN_INVALIDO,
 * PERMISSAO_NEGADA e OC429 (rate limit), todos escritos à mão em app/main.py.
 *
 * BURACOS DELIBERADOS, alinhados com o backend:
 * - OC006 está reservado ao gate de IOF (DECISOES_PENDENTES.md §2) e não
 *   existe no banco.
 * - OC020 (campo econômico alterado em operação que compromete capital) e
 *   OC021 (histórico de capital social é append-only) existem na migration
 *   015 mas NÃO estão no PGCODE_MAP do backend, porque nenhum endpoint os
 *   alcança: não há PATCH/PUT/DELETE de operação e /capital/eventos só faz
 *   INSERT. Sem tradução no servidor eles nunca chegam aqui com `codigo` —
 *   viriam como 500 genérico. Uma entrada aqui seria mensagem morta. Se algum
 *   dia um endpoint os alcançar, eles entram no PGCODE_MAP e aqui juntos.
 */
const MENSAGENS_POR_CODIGO: Record<string, string> = {
  TOKEN_AUSENTE: 'Sua sessão expirou. Faça login novamente.',
  TOKEN_INVALIDO: 'Sua sessão expirou. Faça login novamente.',
  PERMISSAO_NEGADA: 'Você não tem permissão para executar esta ação.',
  OC001: 'Esta operação excede o teto de capital disponível.',
  OC002: 'O tomador está fora da área de atuação autorizada.',
  OC003: 'Essa transição de status não é permitida no estado atual da operação.',
  // Desde a migration 013 não basta ter uma referência de registro
  // preenchida: é preciso registro CONFIRMADO, com protocolo. A mensagem
  // diz o que fazer, porque a ação fica noutra parte da tela.
  OC004:
    'A operação precisa de um registro CONFIRMADO em entidade registradora antes de ativar. Abra e confirme o registro na seção "Registro em entidade registradora".',
  OC005: 'Essa redução de capital deixaria o comprometido acima do saldo disponível.',
  OC007: 'Falha de integridade na trilha de auditoria. Contate o suporte técnico.',
  OC008:
    'Renegociação exige informar as condições da nova operação — a baixa e a substituta são feitas juntas.',
  OC009:
    'Parcela já emitida não pode ser alterada nem apagada — a agenda é a prova do que foi contratado. Para registrar pagamento, faça a baixa da parcela contra o movimento bancário.',
  OC010:
    'A trilha de eventos da operação é somente inclusão e não aceita alteração nem exclusão. Registre um novo evento em vez de corrigir o anterior.',
  // Os quatro caminhos do trigger da 016 num texto só, porque o backend
  // devolve o mesmo SQLSTATE para todos e o operador precisa saber onde olhar.
  OC011:
    'A baixa não tem lastro bancário válido: a parcela pode já estar baixada, ou o movimento não existe, já foi usado em outra parcela ou tem valor menor que a parcela. Confira o extrato e selecione outro movimento.',
  OC012:
    'Movimento bancário é fato externo: registra-se, não se edita. Importe o extrato corrigido em vez de alterar o lançamento.',
  // Não é OC011: reimportar o mesmo extrato é rotina, e chamar isso de "baixa
  // sem lastro" manda o operador conferir a coisa errada. O `documento` é
  // UNIQUE justamente para que o mesmo crédito não baixe duas parcelas — a
  // recusa aqui é a proteção funcionando, não um erro dele.
  MOVIMENTO_DUPLICADO:
    'Este documento já foi registrado — o extrato provavelmente foi importado antes. Confira a lista de movimentos: o lançamento já está lá e pode ser usado na baixa.',
  OC013:
    'Esta evidência de identificação está dentro do prazo de retenção legal de 5 anos (Lei 9.613/98) e não pode ser alterada nem excluída. Se o documento mudou, arquive uma nova evidência ao lado da atual.',
  OC014:
    'Ocorrência de atipicidade é somente inclusão — uma trilha de PLD que se edita não serve como defesa. Só o registro da comunicação ao canal externo pode ser preenchido depois.',
  OC015:
    'Não há parâmetro fiscal vigente para o período informado. Cadastre os percentuais de presunção e as alíquotas do trimestre antes de apurar.',
  OC016:
    'Apuração fiscal já gravada não se edita. Para corrigir, gere uma nova versão retificadora do período.',
  OC017:
    'Instrumento contratual já emitido não pode ser alterado — o tomador tem uma via do documento original. Reemita o contrato para gerar uma nova versão.',
  OC018:
    'Essa mudança de status do registro não é permitida: confirmado e rejeitado são terminais. Se o registro precisa ser refeito, abra um novo registro.',
  // Regra e lei diferentes do OC004 (que é registro em entidade
  // registradora): esta é identificação do cliente, Lei 9.613/98. Por isso
  // código próprio — a instrução ao operador é outra.
  OC019:
    'O tomador precisa ter evidência de identificação arquivada antes de ativar. Arquive o documento na ficha do tomador.',
  // Liquidação é QUITAÇÃO e devolve capital ao teto do Art. 5º, por isso o
  // gate da migration 017. A mensagem precisa citar a saída alternativa: sem
  // a baixa por prejuízo, o operador de uma operação que nunca será paga fica
  // sem caminho nenhum para encerrar.
  OC022:
    'A operação só pode ser liquidada com todas as parcelas baixadas — liquidar é quitar, e devolve o capital ao teto. Baixe as parcelas em aberto contra o extrato bancário; se o valor não será recebido, encerre pela baixa por prejuízo, que encerra a cobrança e não devolve capital.',
  OC429: 'Muitas requisições em pouco tempo. Aguarde cerca de um minuto e tente novamente.',
}

const MENSAGEM_PADRAO = 'Ocorreu um erro inesperado. Tente novamente.'

export function mensagemDeErro(erro: unknown): string {
  if (erro instanceof ApiError) {
    // Object.hasOwn e não `in`: `in` acha a cadeia de protótipos, e um código
    // chamado "toString" ou "constructor" devolveria a função de Object —
    // tipada como string pelo Record, renderizada como lixo na tela.
    if (erro.codigo && Object.hasOwn(MENSAGENS_POR_CODIGO, erro.codigo)) {
      return MENSAGENS_POR_CODIGO[erro.codigo]
    }
    return erro.message || MENSAGEM_PADRAO
  }
  return MENSAGEM_PADRAO
}

/**
 * Primeiro elemento de `loc` que só diz ONDE o dado veio, não QUAL campo é.
 * Mostrar "body" ao operador não ajuda; mostrar "valor_principal" ajuda.
 */
const ORIGENS_DE_LOC = new Set(['body', 'query', 'path', 'header', 'cookie'])

function campoDeLoc(loc: unknown): string | null {
  if (!Array.isArray(loc)) return null
  const partes = loc.slice(
    typeof loc[0] === 'string' && ORIGENS_DE_LOC.has(loc[0]) ? 1 : 0,
  ) as unknown[]
  const nomes = partes
    .filter((p): p is string | number => typeof p === 'string' || typeof p === 'number')
    .map(String)
  return nomes.length > 0 ? nomes.join('.') : null
}

function textoDoItem(item: unknown): string | null {
  if (typeof item === 'string') return item.trim() || null
  if (!item || typeof item !== 'object') return null
  const { msg, loc } = item as { msg?: unknown; loc?: unknown }
  if (typeof msg !== 'string' || !msg.trim()) return null
  const campo = campoDeLoc(loc)
  return campo ? `${campo}: ${msg.trim()}` : msg.trim()
}

/**
 * Reduz o `detail` do corpo de erro a uma única string legível.
 *
 * O FastAPI tem DUAS formas de `detail`: string (todo `raise HTTPException`
 * dos routers e os handlers de app/main.py) e LISTA de objetos
 * `{type, loc, msg, input}` nos 422 de validação do Pydantic. O código antigo
 * tratava tudo como string, então a lista virava "[object Object]" na tela —
 * o operador via um erro sem nenhuma informação sobre qual campo recusou.
 *
 * Devolve `null` quando não há nada aproveitável, para o chamador cair na
 * mensagem padrão em vez de exibir "" ou "[object Object]".
 */
export function normalizarDetail(detail: unknown): string | null {
  if (typeof detail === 'string') return detail.trim() || null

  const itens = Array.isArray(detail) ? detail : [detail]
  const partes = itens
    .map(textoDoItem)
    .filter((parte): parte is string => parte !== null)
    // Erro repetido em campos distintos já vem com o nome do campo na frente;
    // idênticos de verdade (mesmo campo, mesma msg) só poluiriam a leitura.
    .filter((parte, i, todas) => todas.indexOf(parte) === i)

  if (partes.length === 0) return null
  return `Dados inválidos. Corrija e envie novamente: ${partes.join('; ')}.`
}

interface ErrorBody {
  detail?: unknown
  codigo?: unknown
}

export function paraApiError(body: unknown, httpStatus: number): ApiError {
  const { detail, codigo } = (body ?? {}) as ErrorBody
  return new ApiError(
    normalizarDetail(detail) ?? MENSAGEM_PADRAO,
    typeof codigo === 'string' ? codigo : null,
    httpStatus,
  )
}
