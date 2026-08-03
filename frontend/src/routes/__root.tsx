import { createRootRoute, Link, Outlet } from '@tanstack/react-router'
import { SearchX } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'

/**
 * TooltipProvider é obrigatório no topo: `SidebarMenuButton` com a prop
 * `tooltip` monta um `Tooltip` do Radix, que lança
 * "`Tooltip` must be used within `TooltipProvider`" sem este ancestral.
 * `SidebarProvider` NÃO o embute nesta versão do shadcn — o que derrubava
 * toda rota autenticada (o errorComponent de _authenticated capturava e
 * a tela virava "Algo deu errado"). Fica na raiz, e não no layout
 * autenticado, para valer também em tooltips fora da sidebar.
 */
export const Route = createRootRoute({
  component: () => (
    <TooltipProvider>
      <Outlet />
      <Toaster position="bottom-right" richColors />
    </TooltipProvider>
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
