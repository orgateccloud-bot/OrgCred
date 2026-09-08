import { CheckCircle2 } from 'lucide-react'
import type { ParcelaPortalOut } from '@/api/generated/types.gen'
import { formatarDataIso } from '@/components/identificacao/mensagens'
import { formatarMoeda } from '@/lib/format'
import { ultimosPagamentos, type AgendaDeOperacao } from '@/lib/parcelas'
import { rotuloTipo } from '@/lib/rotulos'
import { Skeleton } from '@/components/ui/skeleton'

/**
 * Meus pagamentos: as últimas parcelas que a ESC deu por pagas, com a data
 * da baixa. É o espelho tranquilizador da agenda — o que já ficou para trás.
 */
export function MeusPagamentos({
  agendas,
  carregando,
}: {
  agendas: Array<AgendaDeOperacao<ParcelaPortalOut>>
  carregando: boolean
}) {
  const pagos = ultimosPagamentos(agendas, 3)

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium text-muted-foreground">Meus pagamentos</h2>

      {carregando ? (
        <Skeleton className="h-20 w-full" />
      ) : pagos.length === 0 ? (
        <p className="rounded-lg border border-border p-4 text-sm text-muted-foreground">
          Nenhum pagamento registrado ainda.
        </p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {pagos.map(({ operacaoId, tipo, parcela }) => (
            <li
              key={`${operacaoId}-${parcela.numero}`}
              className="flex items-center justify-between gap-3 p-3"
            >
              <div className="flex min-w-0 items-center gap-2.5">
                <CheckCircle2 className="size-4 shrink-0 text-success" aria-hidden />
                <div className="min-w-0">
                  <p className="text-sm font-medium">
                    Parcela {parcela.numero} · {rotuloTipo(tipo)}
                  </p>
                  <p className="text-xs text-muted-foreground tabular-nums">
                    {parcela.pago_em ? `Pago em ${formatarDataIso(parcela.pago_em)}` : ''}
                  </p>
                </div>
              </div>
              <span className="font-mono text-sm font-medium tabular-nums">
                {formatarMoeda(parcela.valor_total)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
