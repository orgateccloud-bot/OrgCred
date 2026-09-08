import { Link } from '@tanstack/react-router'
import { AlertTriangle, CalendarClock } from 'lucide-react'
import type { ParcelaPortalOut } from '@/api/generated/types.gen'
import { formatarDataIso } from '@/components/identificacao/mensagens'
import { formatarMoeda } from '@/lib/format'
import {
  diasAteVencer,
  diasDeAtraso,
  proximasParcelas,
  type AgendaDeOperacao,
} from '@/lib/parcelas'
import { rotuloTipo } from '@/lib/rotulos'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

/**
 * Minhas parcelas: os próximos vencimentos do tomador, atravessando todas
 * as operações. Cada linha leva à operação dona da parcela — a home mostra
 * o QUANDO; o COMO PAGAR continua no detalhe.
 */
export function MinhasParcelas({
  agendas,
  carregando,
  hoje,
}: {
  agendas: Array<AgendaDeOperacao<ParcelaPortalOut>>
  carregando: boolean
  hoje?: Date
}) {
  const proximas = proximasParcelas(agendas, 3)

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium text-muted-foreground">Minhas parcelas</h2>

      {carregando ? (
        <Skeleton className="h-24 w-full" />
      ) : proximas.length === 0 ? (
        <p className="rounded-lg border border-border p-4 text-sm text-muted-foreground">
          Nenhuma parcela em aberto — sua agenda está em dia.
        </p>
      ) : (
        <ul className="space-y-2">
          {proximas.map(({ operacaoId, tipo, parcela }) => {
            const atraso = diasDeAtraso(parcela.vencimento, hoje)
            const faltam = diasAteVencer(parcela.vencimento, hoje)
            return (
              <li key={`${operacaoId}-${parcela.numero}`}>
                <Link
                  to="/portal/operacoes/$id"
                  params={{ id: operacaoId }}
                  className="flex items-center justify-between gap-3 rounded-lg border border-border p-3 transition-colors hover:bg-muted active:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium">
                      Parcela {parcela.numero} · {rotuloTipo(tipo)}
                    </p>
                    <p className="text-sm text-muted-foreground tabular-nums">
                      Vencimento {formatarDataIso(parcela.vencimento)}
                    </p>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <span className="font-mono text-sm font-medium tabular-nums">
                      {formatarMoeda(parcela.valor_total)}
                    </span>
                    <span
                      className={cn(
                        'inline-flex items-center gap-1 text-xs',
                        atraso > 0 ? 'text-destructive' : 'text-muted-foreground',
                      )}
                    >
                      {atraso > 0 ? (
                        <>
                          <AlertTriangle className="size-3" aria-hidden />
                          em atraso há {atraso} {atraso === 1 ? 'dia' : 'dias'}
                        </>
                      ) : (
                        <>
                          <CalendarClock className="size-3" aria-hidden />
                          {faltam === 0
                            ? 'vence hoje'
                            : `vence em ${faltam} ${faltam === 1 ? 'dia' : 'dias'}`}
                        </>
                      )}
                    </span>
                  </div>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
