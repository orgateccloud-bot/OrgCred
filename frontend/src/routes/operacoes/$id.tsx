import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/operacoes/$id')({
  component: OperacaoDetailPage,
})

function OperacaoDetailPage() {
  const { id } = Route.useParams()
  return <h1 className="text-2xl font-semibold">Operação {id}</h1>
}
