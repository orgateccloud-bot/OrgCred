import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/login')({
  component: LoginPage,
})

function LoginPage() {
  return <h1 className="text-2xl font-semibold">Login</h1>
}
