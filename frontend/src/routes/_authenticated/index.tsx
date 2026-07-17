import { createFileRoute } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { getCapitalDisponivelCapitalDisponivelGetOptions } from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'

export const Route = createFileRoute('/_authenticated/')({
  component: DashboardPage,
})

function DashboardPage() {
  const { data, error, isPending } = useQuery(getCapitalDisponivelCapitalDisponivelGetOptions())

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <div className="mt-4 rounded-lg border border-border p-4">
        <p className="text-sm text-muted-foreground">Capital disponível</p>
        {isPending && <p className="mt-1 text-lg">Carregando…</p>}
        {error && <p className="mt-1 text-lg text-destructive">{mensagemDeErro(error)}</p>}
        {data && <p className="mt-1 text-lg font-mono">R$ {data.disponivel}</p>}
      </div>
    </div>
  )
}
