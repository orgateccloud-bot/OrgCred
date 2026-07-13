import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/operacoes/')({
  component: OperacoesListPage,
})

function OperacoesListPage() {
  return <h1 className="text-2xl font-semibold">Operações</h1>
}
