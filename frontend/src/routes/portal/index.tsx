import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ChevronRight, Inbox } from 'lucide-react'
import {
  getOperacoesApiPortalOperacoesGetOptions,
  getPerfilApiPortalPerfilGetOptions,
} from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { formatarMoeda } from '@/lib/format'
import { rotuloTipo } from '@/lib/rotulos'
import { StatusOperacaoBadge } from '@/components/status-operacao-badge'
import { Skeleton } from '@/components/ui/skeleton'

export const Route = createFileRoute('/portal/')({
  component: PortalHome,
})

function PortalHome() {
  const perfil = useQuery(getPerfilApiPortalPerfilGetOptions())
  const operacoes = useQuery(getOperacoesApiPortalOperacoesGetOptions())

  return (
    <div className="space-y-6">
      <section>
        {perfil.isLoading ? (
          <Skeleton className="h-8 w-64" />
        ) : perfil.data ? (
          <>
            <h1 className="text-2xl font-semibold">{perfil.data.razao_social}</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              CNPJ {perfil.data.cnpj} · {perfil.data.municipio}/{perfil.data.uf} ·{' '}
              {perfil.data.operacoes_ativas}{' '}
              {perfil.data.operacoes_ativas === 1 ? 'operação ativa' : 'operações ativas'}
            </p>
          </>
        ) : (
          <h1 className="text-2xl font-semibold">Suas operações</h1>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium text-muted-foreground">Seus créditos</h2>

        {operacoes.isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        ) : operacoes.isError ? (
          <p
            role="alert"
            className="flex gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm"
          >
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
            {mensagemDeErro(operacoes.error)}
          </p>
        ) : !operacoes.data || operacoes.data.length === 0 ? (
          <p className="flex items-center gap-2 rounded-lg border border-border p-6 text-sm text-muted-foreground">
            <Inbox className="size-5 shrink-0" aria-hidden />
            Você ainda não tem nenhuma operação de crédito registrada.
          </p>
        ) : (
          <ul className="space-y-2">
            {operacoes.data.map((op) => (
              <li key={op.id}>
                <Link
                  to="/portal/operacoes/$id"
                  params={{ id: op.id }}
                  className="flex items-center gap-3 rounded-lg border border-border p-4 transition-colors hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{rotuloTipo(op.tipo)}</span>
                      <StatusOperacaoBadge status={op.status} />
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {formatarMoeda(op.valor_principal)} · {op.numero_parcelas}x ·{' '}
                      {op.parcelas_pagas}/{op.numero_parcelas} pagas
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-xs text-muted-foreground">Em aberto</p>
                    <p className="font-mono font-medium tabular-nums">
                      {formatarMoeda(op.saldo_em_aberto)}
                    </p>
                  </div>
                  <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
