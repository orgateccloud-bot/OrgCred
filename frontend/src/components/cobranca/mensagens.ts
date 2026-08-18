import { ApiError, mensagemDeErro } from '@/api/errors'

/**
 * Espelha `TAMANHO_MAXIMO_OFX_BYTES` (app/routers/cobranca.py).
 *
 * O servidor continua sendo a autoridade — ele lê 8 MiB + 1 byte e recusa com
 * 413. A cópia aqui não substitui essa recusa: ela evita subir um extrato
 * anual de 40 MiB por uma conexão de escritório inteira para receber a recusa
 * no fim. O operador descobre o problema em zero byte enviado.
 */
export const TAMANHO_MAXIMO_OFX_BYTES = 8 * 1024 * 1024

const LIMITE_MIB = TAMANHO_MAXIMO_OFX_BYTES / (1024 * 1024)

const COMO_DIVIDIR =
  'Exporte o extrato em períodos menores — um mês por arquivo — e importe um de cada vez.'

function emMiB(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toLocaleString('pt-BR', {
    maximumFractionDigits: 1,
  })} MiB`
}

/**
 * Recusa local, antes de qualquer requisição. Diz explicitamente que nada foi
 * enviado: sem isso o operador fica sem saber se precisa conferir a lista de
 * movimentos para ver o que entrou pela metade.
 */
export function mensagemDeArquivoGrandeDemais(bytes: number): string {
  return (
    `O arquivo tem ${emMiB(bytes)} e o limite de importação é ${LIMITE_MIB} MiB. ` +
    `${COMO_DIVIDIR} Nada foi enviado.`
  )
}

/**
 * Erros da importação de extrato.
 *
 * NÃO duplica o dicionário de `src/api/errors.ts`: os 422 do endpoint
 * (arquivo ilegível, mais de 50.000 transações, valor fora da faixa citando o
 * FITID) chegam como `detail` em texto, e `mensagemDeErro` já os devolve
 * inteiros — reescrevê-los aqui trocaria a causa exata que o parser apontou
 * por uma paráfrase nossa, justamente o texto que o operador leva ao gerente
 * do banco para pedir a exportação de novo.
 *
 * O 413 é o buraco real. O router devolve `detail` legível, mas um 413 pode
 * nascer antes dele — proxy reverso, gateway, limite de corpo do servidor de
 * borda — e aí o corpo não é JSON, `paraApiError` não acha `detail` nenhum e
 * a tela diria "Ocorreu um erro inesperado" para o caso mais previsível que
 * existe aqui. O texto fixo vale para as duas origens porque a causa e a
 * saída são as mesmas.
 */
export function mensagemDeErroDeImportacaoOfx(erro: unknown): string {
  if (erro instanceof ApiError && erro.httpStatus === 413) {
    return (
      `O arquivo foi recusado por tamanho: o limite de importação é ${LIMITE_MIB} MiB. ` +
      `${COMO_DIVIDIR} Nenhum movimento foi criado.`
    )
  }
  return mensagemDeErro(erro)
}

/**
 * `origem` de `movimento_bancario` (migration 024). O rótulo precisa dizer a
 * PROCEDÊNCIA, não o meio: "Extrato OFX" é o arquivo que o banco emitiu,
 * "Digitado" é alguém informando data, valor e documento à mão. Fallback
 * devolve o valor cru — origem nova aparece em vez de sumir.
 */
const ORIGEM_MOVIMENTO: Record<string, string> = {
  ofx: 'Extrato OFX',
  manual: 'Digitado',
}

export const rotuloOrigemMovimento = (valor: string) => ORIGEM_MOVIMENTO[valor] ?? valor
