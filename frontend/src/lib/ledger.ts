import { formatarMoeda } from '@/lib/format'

const VERBO_POR_EVENTO: Record<string, string> = {
  ativacao_operacao: 'ativou uma operação de crédito',
  liquidacao: 'liquidou uma operação de crédito',
}

/**
 * Só o que a narrativa realmente lê. Tipar estruturalmente (e não com o
 * `LedgerEventoOut` gerado) é o que permite servir tanto `GET /auditoria`
 * quanto o resumo de eventos de `GET /operacoes/{id}` — este último não
 * traz operacao_id/prev_hash/current_hash, porque a tela de detalhe não
 * precisa deles.
 */
export interface EventoNarravel {
  usuario_nome?: string | null
  evento_tipo: string
  created_at: string
  valor: string
}

export function narrativa(evento: EventoNarravel): string {
  const autor = evento.usuario_nome ?? 'Sistema'
  const verbo = VERBO_POR_EVENTO[evento.evento_tipo] ?? `registrou o evento "${evento.evento_tipo}"`
  const quando = new Date(evento.created_at).toLocaleString('pt-BR')
  return `${autor} ${verbo} em ${quando}, no valor de ${formatarMoeda(evento.valor)}.`
}
