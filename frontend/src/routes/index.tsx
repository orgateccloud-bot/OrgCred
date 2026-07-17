import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/')({
  component: DashboardPage,
})

function DashboardPage() {
  return <h1 className="text-2xl font-semibold">Dashboard</h1>
}
