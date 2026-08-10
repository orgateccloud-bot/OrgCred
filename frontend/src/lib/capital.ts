/**
 * Derivações do painel de capital.
 *
 * Ficam aqui, e não dentro do componente do dashboard, porque são regras de
 * leitura do domínio — quanto do teto está usado, quanto está prestes a
 * sair, como o comprometido se distribui — e não apresentação. Na view elas
 * não tinham teste algum; aqui são verificáveis sem montar React.
 *
 * IMPORTANTE: nada aqui decide nada. O teto real é imposto pelo trigger no
 * Postgres (OC001); estes números são leitura informativa para a tela e
 * podem ficar desatualizados entre a consulta e uma ativação concorrente.
 */

/** Só o que estas funções realmente leem — tipar estruturalmente evita
 *  exigir campos que o chamador não tem (ex.: o donut recebe operações já
 *  filtradas, sem `status`). */
export interface OperacaoValorada {
  tipo: string
  valor_principal: string
}

export interface OperacaoResumo extends OperacaoValorada {
  status: string
}

export interface EventoSaldo {
  created_at: string
  saldo_disponivel_pos: string
}

/**
 * Percentual do teto já comprometido. Teto zero devolve 0 (e não divisão por
 * zero): é o estado real de produção enquanto o capital social não for
 * integralizado.
 */
export function percentualUtilizacao(total: number, comprometido: number): number {
  if (total <= 0) return 0
  return Math.min(100, (comprometido / total) * 100)
}

export function operacoesPorStatus(
  operacoes: readonly OperacaoResumo[],
  status: string,
): OperacaoResumo[] {
  return operacoes.filter((op) => op.status === status)
}

/** Soma dos valores principais — usada para "quanto está prestes a sair". */
export function somarValorPrincipal(operacoes: readonly OperacaoValorada[]): number {
  return operacoes.reduce((soma, op) => soma + Number(op.valor_principal), 0)
}

/** Composição do comprometido por tipo de operação, para o donut. */
export function comprometidoPorTipo(
  operacoes: readonly OperacaoValorada[],
): Array<{ tipo: string; valor: number }> {
  const porTipo = new Map<string, number>()
  for (const op of operacoes) {
    porTipo.set(op.tipo, (porTipo.get(op.tipo) ?? 0) + Number(op.valor_principal))
  }
  return [...porTipo.entries()].map(([tipo, valor]) => ({ tipo, valor }))
}

/**
 * Série temporal do saldo disponível, do mais antigo ao mais recente.
 *
 * A ordenação é explícita porque o ledger pode chegar em qualquer ordem — e
 * um gráfico de saldo com o eixo X embaralhado conta uma história errada
 * sobre a evolução do capital.
 */
export function serieSaldoDisponivel(
  eventos: readonly EventoSaldo[],
): Array<{ quando: string; saldo: number }> {
  return [...eventos]
    .sort((a, b) => a.created_at.localeCompare(b.created_at))
    .map((e) => ({
      quando: new Date(e.created_at).toLocaleDateString('pt-BR', {
        day: '2-digit',
        month: '2-digit',
      }),
      saldo: Number(e.saldo_disponivel_pos),
    }))
}
