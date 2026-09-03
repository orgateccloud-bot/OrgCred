import { useQueries } from '@tanstack/react-query'
import { getParcelasApiPortalOperacoesOperacaoIdParcelasGetOptions } from '@/api/generated/@tanstack/react-query.gen'
import type { OperacaoPortalOut, ParcelaPortalOut } from '@/api/generated/types.gen'
import type { AgendaDeOperacao } from '@/lib/parcelas'

/**
 * As agendas de TODAS as operações do tomador, para as seções "Minhas
 * parcelas" e "Meus pagamentos" da home.
 *
 * Uma query por operação, com as MESMAS opções geradas que o detalhe usa:
 * o cache é compartilhado (abrir a operação depois da home não busca de
 * novo) e as duas seções da home deduplicam entre si pela chave. A lista do
 * tomador é pequena por natureza — o teto de capital de uma ESC não deixa
 * ninguém ter cinquenta operações.
 */
export function useAgendas(operacoes: OperacaoPortalOut[] | undefined): {
  agendas: Array<AgendaDeOperacao<ParcelaPortalOut>>
  carregando: boolean
} {
  const resultados = useQueries({
    queries: (operacoes ?? []).map((op) =>
      getParcelasApiPortalOperacoesOperacaoIdParcelasGetOptions({ path: { operacao_id: op.id } }),
    ),
  })

  const carregando = operacoes === undefined || resultados.some((r) => r.isLoading)
  const agendas = (operacoes ?? []).flatMap((op, i) => {
    const dados = resultados[i]?.data
    return dados ? [{ operacaoId: op.id, tipo: op.tipo, parcelas: dados.parcelas }] : []
  })

  return { agendas, carregando }
}
