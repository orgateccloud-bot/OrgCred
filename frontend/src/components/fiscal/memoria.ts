/**
 * Memória de cálculo de uma apuração fiscal: contrato e serializações.
 *
 * Sem nenhum import de rede, de propósito — a busca vive em `memoria-api.ts`.
 * Assim o que este arquivo tem (as duas saídas para o escritório de
 * contabilidade) é testável sem levantar cliente HTTP nem SDK de autenticação.
 *
 * Tipos escritos à mão, e NÃO gerados: `src/api/generated/` é produto do
 * openapi-ts e não se edita a mão. Enquanto o cliente não é regerado, o
 * caminho honesto é declarar aqui o contrato de
 * `GET /api/fiscal/apuracoes/{id}/memoria` — o mesmo `MemoriaCalculoOut` de
 * app/routers/fiscal.py.
 *
 * Decimais chegam como STRING (o Pydantic serializa `Decimal` assim, para não
 * perder precisão em float) e são mantidos como string até a formatação. Fazer
 * conta com eles aqui reintroduziria erro de ponto flutuante numa base
 * tributária — a aritmética é do banco, e a conferência dela é do backend.
 */

/** Um tributo, do que entrou até o que saiu. */
export interface LinhaMemoria {
  chave: string
  tributo: string
  receita_considerada: string
  /** Nulo em PIS/COFINS: cumulativos incidem sobre a receita, sem presunção. */
  percentual_presuncao: string | null
  base_calculo: string
  /** Só no adicional de IRPJ. */
  limite: string | null
  excedente: string | null
  aliquota: string
  /** Recalculado a partir do snapshot da apuração. */
  valor: string
  /** O que está gravado na linha imutável. */
  valor_gravado: string
  confere: boolean
}

export interface DivergenciaMemoria {
  campo: string
  rotulo: string
  calculado: string
  gravado: string
  diferenca: string
}

export interface MemoriaCalculo {
  apuracao_id: string
  ano: number
  trimestre: number
  versao: number
  regime_reconhecimento: string
  receita_juros: string
  receita_demais: string
  receita_total: string
  receita_total_gravada: string
  linhas: LinhaMemoria[]
  total_tributos: string
  total_tributos_gravado: string
  confere: boolean
  divergencias: DivergenciaMemoria[]
}

export function memoriaQueryKey(apuracaoId: string) {
  return ['fiscal', 'memoria', apuracaoId] as const
}

// ---------------------------------------------------------------------
// Levar para fora
// ---------------------------------------------------------------------
//
// O destino real deste dado é o escritório de contabilidade, não a tela. Por
// isso duas saídas, e não uma: TEXTO para colar em e-mail ou parecer, e CSV
// para abrir na planilha em que a conferência de fato acontece.

const REGIME: Record<string, string> = {
  caixa: 'Caixa (data do extrato)',
  competencia: 'Competência (vencimento)',
}

export function rotuloRegime(regime: string): string {
  return REGIME[regime] ?? regime
}

export function rotuloPeriodo(m: Pick<MemoriaCalculo, 'ano' | 'trimestre' | 'versao'>): string {
  const versao = m.versao > 1 ? ` (retificada, v${m.versao})` : ''
  return `${m.trimestre}º trimestre de ${m.ano}${versao}`
}

/**
 * Número no formato que a planilha pt-BR entende: vírgula decimal e SEM
 * separador de milhar. `formatarMoeda` põe "R$" e ponto de milhar, que numa
 * célula viram texto e param de somar.
 */
function numeroPtBr(valor: string): string {
  return Number(valor).toFixed(2).replace('.', ',')
}

function percentualPtBr(fracao: string): string {
  return `${(Number(fracao) * 100).toFixed(4).replace('.', ',')}%`
}

const CABECALHO = [
  'Tributo',
  'Receita considerada',
  'Presunção',
  'Base de cálculo',
  'Limite do adicional',
  'Excedente',
  'Alíquota',
  'Valor recalculado',
  'Valor gravado',
  'Confere',
] as const

function celulas(linha: LinhaMemoria): string[] {
  return [
    linha.tributo,
    numeroPtBr(linha.receita_considerada),
    linha.percentual_presuncao === null ? '' : percentualPtBr(linha.percentual_presuncao),
    numeroPtBr(linha.base_calculo),
    linha.limite === null ? '' : numeroPtBr(linha.limite),
    linha.excedente === null ? '' : numeroPtBr(linha.excedente),
    percentualPtBr(linha.aliquota),
    numeroPtBr(linha.valor),
    numeroPtBr(linha.valor_gravado),
    linha.confere ? 'sim' : 'NÃO',
  ]
}

/**
 * CSV separado por PONTO E VÍRGULA: com vírgula decimal, o separador vírgula
 * quebraria toda linha no meio dos números ao abrir no Excel em pt-BR.
 */
export function memoriaComoCsv(m: MemoriaCalculo): string {
  const escapar = (valor: string) =>
    /[";\n]/.test(valor) ? `"${valor.replace(/"/g, '""')}"` : valor
  const linha = (colunas: string[]) => colunas.map(escapar).join(';')

  const partes = [
    linha(['Memória de cálculo da apuração fiscal']),
    linha(['Período', rotuloPeriodo(m)]),
    linha(['Regime de reconhecimento', rotuloRegime(m.regime_reconhecimento)]),
    linha(['Apuração', m.apuracao_id]),
    linha(['Receita de juros', numeroPtBr(m.receita_juros)]),
    linha(['Mora e multa recebidas', numeroPtBr(m.receita_demais)]),
    linha(['Receita total tributada', numeroPtBr(m.receita_total)]),
    '',
    linha([...CABECALHO]),
    ...m.linhas.map((l) => linha(celulas(l))),
    linha([
      'Total de tributos',
      '',
      '',
      '',
      '',
      '',
      '',
      numeroPtBr(m.total_tributos),
      numeroPtBr(m.total_tributos_gravado),
      m.confere ? 'sim' : 'NÃO',
    ]),
  ]

  if (!m.confere) {
    partes.push(
      '',
      linha(['DIVERGÊNCIA: o recálculo não reproduz o valor gravado']),
      linha(['Campo', 'Recalculado', 'Gravado', 'Diferença']),
      ...m.divergencias.map((d) =>
        linha([d.rotulo, numeroPtBr(d.calculado), numeroPtBr(d.gravado), numeroPtBr(d.diferenca)]),
      ),
    )
  }

  return partes.join('\r\n')
}

/** Bloco de texto para colar em e-mail ou parecer. */
export function memoriaComoTexto(m: MemoriaCalculo): string {
  const linhas = [
    `Memória de cálculo — ${rotuloPeriodo(m)}`,
    `Regime: ${rotuloRegime(m.regime_reconhecimento)}`,
    `Apuração: ${m.apuracao_id}`,
    '',
    `Receita de juros ......... ${numeroPtBr(m.receita_juros)}`,
    `Mora e multa recebidas ... ${numeroPtBr(m.receita_demais)}`,
    `Receita total tributada .. ${numeroPtBr(m.receita_total)}`,
    '',
  ]

  for (const l of m.linhas) {
    const presuncao =
      l.percentual_presuncao === null
        ? `base = receita ${numeroPtBr(l.base_calculo)} (sem presunção)`
        : `receita ${numeroPtBr(l.receita_considerada)} x presunção ${percentualPtBr(
            l.percentual_presuncao,
          )} = base ${numeroPtBr(l.base_calculo)}`
    linhas.push(`${l.tributo}:`)
    linhas.push(`  ${presuncao}`)
    if (l.limite !== null && l.excedente !== null) {
      linhas.push(
        `  base ${numeroPtBr(l.base_calculo)} - limite ${numeroPtBr(
          l.limite,
        )} = excedente ${numeroPtBr(l.excedente)}`,
      )
      linhas.push(
        `  excedente ${numeroPtBr(l.excedente)} x ${percentualPtBr(l.aliquota)} = ${numeroPtBr(
          l.valor,
        )}`,
      )
    } else {
      linhas.push(
        `  base ${numeroPtBr(l.base_calculo)} x ${percentualPtBr(l.aliquota)} = ${numeroPtBr(
          l.valor,
        )}`,
      )
    }
    if (!l.confere) {
      linhas.push(`  DIVERGE do valor gravado: ${numeroPtBr(l.valor_gravado)}`)
    }
  }

  linhas.push('', `Total de tributos ........ ${numeroPtBr(m.total_tributos)}`)

  if (!m.confere) {
    linhas.push(
      '',
      'DIVERGÊNCIA: o recálculo a partir dos parâmetros gravados na própria',
      'apuração não reproduz os valores gravados. A apuração é imutável, então',
      'a correção se faz retificando o trimestre.',
    )
    for (const d of m.divergencias) {
      linhas.push(
        `  ${d.rotulo}: recalculado ${numeroPtBr(d.calculado)}, gravado ${numeroPtBr(d.gravado)}`,
      )
    }
  }

  return linhas.join('\n')
}

export function nomeDoArquivo(m: MemoriaCalculo): string {
  return `memoria-calculo-${m.ano}-T${m.trimestre}-v${m.versao}.csv`
}
