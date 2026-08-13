import { rotuloStatus } from '@/lib/rotulos'

/**
 * Rótulo do estado terminal de write-off.
 *
 * O dicionário compartilhado (`lib/rotulos`) ainda não conhece
 * `baixada_prejuizo` e devolve a chave crua do banco. Numa tela onde o
 * vizinho é "Liquidada", exibir "baixada_prejuizo" convida ao erro de
 * leitura mais caro do sistema: quitação devolveu capital, prejuízo não.
 */
export const ROTULO_BAIXADA_PREJUIZO = 'Baixada como prejuízo'

export function rotuloStatusOperacao(status: string): string {
  return status === 'baixada_prejuizo' ? ROTULO_BAIXADA_PREJUIZO : rotuloStatus(status)
}
