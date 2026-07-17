import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/auditoria')({
  component: AuditoriaPage,
})

function AuditoriaPage() {
  return <h1 className="text-2xl font-semibold">Auditoria</h1>
}
