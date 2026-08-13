import { Ban } from 'lucide-react'
import { StatusOperacaoBadge } from '@/components/status-operacao-badge'
import { ROTULO_BAIXADA_PREJUIZO } from '@/components/operacoes/rotulo-status-operacao'
import { Badge } from '@/components/ui/badge'

/**
 * Badge de status com o caso `baixada_prejuizo` explicitado.
 *
 * O badge genérico cai no fallback para status que não conhece e mostra a
 * chave crua do banco ("baixada_prejuizo") com o ícone neutro de proposta —
 * indistinguível, para quem passa o olho, de mais um encerramento comum.
 *
 * Fica aqui, e não no badge compartilhado, porque este pacote é o dono do
 * fluxo de write-off; as demais telas seguem usando o componente genérico.
 */
export function BadgeStatusOperacao({ status }: { status: string }) {
  if (status !== 'baixada_prejuizo') {
    return <StatusOperacaoBadge status={status} />
  }

  return (
    <Badge variant="outline" className="gap-1 text-destructive">
      <Ban />
      {ROTULO_BAIXADA_PREJUIZO}
    </Badge>
  )
}
