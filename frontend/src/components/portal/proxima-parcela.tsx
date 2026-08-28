import { AlertTriangle, CalendarClock } from 'lucide-react'
import type { ParcelaPortalOut } from '@/api/generated/types.gen'
import { formatarDataIso } from '@/components/identificacao/mensagens'
import { diasDeAtraso } from '@/lib/parcelas'
import { formatarMoeda } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * O número que o tomador abre o portal para ver: a próxima parcela.
 *
 * Em atraso, o cartão muda de tom E de texto — cor sozinha não comunica
 * (daltonismo, tela ao sol). O valor vem do banco; aqui só se escolhe qual
 * parcela destacar e se contam dias (ver lib/parcelas.ts).
 *
 * `hoje` é injetável só para teste: componente que lê o relógio por dentro
 * não tem como ser testado nos dois lados da fronteira do vencimento.
 */
export function ProximaParcelaCard({ parcela, hoje }: { parcela: ParcelaPortalOut; hoje?: Date }) {
  const atraso = diasDeAtraso(parcela.vencimento, hoje)
  const emAtraso = atraso > 0

  return (
    <div
      className={cn(
        'rounded-xl border p-4',
        emAtraso ? 'border-destructive/40 bg-destructive/5' : 'border-border bg-card',
      )}
    >
      <p
        className={cn(
          'flex items-center gap-1.5 text-sm font-medium',
          emAtraso ? 'text-destructive' : 'text-muted-foreground',
        )}
      >
        {emAtraso ? (
          <>
            <AlertTriangle className="size-4" aria-hidden />
            Parcela {parcela.numero} em atraso há {atraso} {atraso === 1 ? 'dia' : 'dias'}
          </>
        ) : (
          <>
            <CalendarClock className="size-4" aria-hidden />
            Próxima parcela ({parcela.numero})
          </>
        )}
      </p>
      <p className="mt-1 font-mono text-2xl font-semibold tabular-nums">
        {formatarMoeda(parcela.valor_total)}
      </p>
      <p className="mt-0.5 text-sm text-muted-foreground">
        {emAtraso ? 'Venceu em' : 'Vence em'} {formatarDataIso(parcela.vencimento)}
      </p>
    </div>
  )
}
