import { createRootRoute, Link, Outlet } from '@tanstack/react-router'
import { SearchX } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Toaster } from '@/components/ui/sonner'

export const Route = createRootRoute({
  component: () => (
    <>
      <Outlet />
      <Toaster position="bottom-right" richColors />
    </>
  ),
  notFoundComponent: PaginaNaoEncontrada,
})

function PaginaNaoEncontrada() {
  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-4 p-6 text-center">
      <SearchX className="size-10 text-muted-foreground" aria-hidden />
      <div>
        <h1 className="text-xl font-semibold">Página não encontrada</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          O endereço acessado não existe ou foi movido.
        </p>
      </div>
      <Button asChild>
        <Link to="/">Ir para o Dashboard</Link>
      </Button>
    </div>
  )
}
