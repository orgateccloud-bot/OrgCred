import type { LedgerEventoOut } from '@/api/generated/types.gen'
import { formatarMoeda } from '@/lib/format'

const VERBO_POR_EVENTO: Record<string, string> = {
  ativacao_operacao: 'ativou uma operação de crédito',
  liquidacao: 'liquidou uma operação de crédito',
}

export function narrativa(evento: LedgerEventoOut): string {
  const autor = evento.usuario_nome ?? 'Sistema'
  const verbo = VERBO_POR_EVENTO[evento.evento_tipo] ?? `registrou o evento "${evento.evento_tipo}"`
  const quando = new Date(evento.created_at).toLocaleString('pt-BR')
  return `${autor} ${verbo} em ${quando}, no valor de ${formatarMoeda(evento.valor)}.`
}
