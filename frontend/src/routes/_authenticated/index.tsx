import { createFileRoute } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { getCapitalSnapshotCapitalSnapshotGetOptions } from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { formatarMoeda } from '@/lib/format'

export const Route = createFileRoute('/_authenticated/')({
  component: DashboardPage,
})

function DashboardPage() {
  const { data, error, isPending } = useQuery({
    ...getCapitalSnapshotCapitalSnapshotGetOptions(),
    refetchInterval: 20_000,
  })

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>

      {isPending && <p className="mt-4 text-muted-foreground">Carregando…</p>}
      {error && <p className="mt-4 text-destructive">{mensagemDeErro(error)}</p>}

      {data && <CapitalSnapshotCard {...data} />}
    </div>
  )
}

function CapitalSnapshotCard({
  total,
  comprometido,
  disponivel,
}: {
  total: string
  comprometido: string
  disponivel: string
}) {
  const totalNum = Number(total)
  const comprometidoNum = Number(comprometido)
  const utilizacaoPct = totalNum > 0 ? Math.min(100, (comprometidoNum / totalNum) * 100) : 0

  return (
    <div className="mt-4 max-w-md rounded-lg border border-border p-4">
      <div className="grid grid-cols-3 gap-4">
        <div>
          <p className="text-sm text-muted-foreground">Total</p>
          <p className="mt-1 font-mono text-lg">{formatarMoeda(total)}</p>
        </div>
        <div>
          <p className="text-sm text-muted-foreground">Comprometido</p>
          <p className="mt-1 font-mono text-lg">{formatarMoeda(comprometido)}</p>
        </div>
        <div>
          <p className="text-sm text-muted-foreground">Disponível</p>
          <p className="mt-1 font-mono text-lg">{formatarMoeda(disponivel)}</p>
        </div>
      </div>

      <div className="mt-4">
        <div className="flex justify-between text-xs text-muted-foreground">
          <span>Utilização do teto</span>
          <span>{utilizacaoPct.toFixed(1)}%</span>
        </div>
        <div
          className="mt-1 h-2 w-full overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuenow={Math.round(utilizacaoPct)}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="h-full rounded-full bg-primary transition-[width]"
            style={{ width: `${utilizacaoPct}%` }}
          />
        </div>
      </div>
    </div>
  )
}
