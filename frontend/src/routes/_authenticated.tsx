import { Fragment, useState } from 'react'
import { createFileRoute, Outlet, redirect, useRouterState } from '@tanstack/react-router'
import { AlertTriangle, Search } from 'lucide-react'
import { getSession } from '@/auth/supabaseClient'
import { AppSidebar } from '@/components/app-sidebar'
import { CommandPalette } from '@/components/command-palette'
import { ThemeToggle } from '@/components/theme-toggle'
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'

export const Route = createFileRoute('/_authenticated')({
  beforeLoad: async () => {
    const session = await getSession()
    if (!session) {
      throw redirect({ to: '/login' })
    }
  },
  component: AuthenticatedLayout,
  errorComponent: RotaComErro,
})

/**
 * Mapa estático de rota → rótulo humano. Rotas com parâmetro caem no prefixo
 * mais longo que casar (ex.: /operacoes/123 → Operações / Detalhe).
 */
const ROTULOS: Array<{ prefixo: string; rotulo: string }> = [
  { prefixo: '/auditoria', rotulo: 'Auditoria' },
  { prefixo: '/cobranca', rotulo: 'Cobrança' },
  { prefixo: '/compliance', rotulo: 'Compliance' },
  { prefixo: '/fiscal', rotulo: 'Fiscal' },
  { prefixo: '/operacoes', rotulo: 'Operações' },
  { prefixo: '/', rotulo: 'Dashboard' },
]

function migalhas(pathname: string): Array<{ rotulo: string; to?: string }> {
  const base = ROTULOS.find((r) =>
    r.prefixo === '/' ? pathname === '/' : pathname.startsWith(r.prefixo),
  )
  if (!base) return [{ rotulo: 'OrgCred' }]
  if (pathname === base.prefixo || base.prefixo === '/') return [{ rotulo: base.rotulo }]
  return [{ rotulo: base.rotulo, to: base.prefixo }, { rotulo: 'Detalhe' }]
}

function AuthenticatedLayout() {
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const trilha = migalhas(pathname)
  const [paletaAberta, setPaletaAberta] = useState(false)

  return (
    <SidebarProvider>
      <CommandPalette open={paletaAberta} onOpenChange={setPaletaAberta} />
      <AppSidebar />
      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-4">
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="mr-2 h-4" />
          <Breadcrumb>
            <BreadcrumbList>
              {/* Separador é IRMÃO do item, não filho: BreadcrumbItem e
                  BreadcrumbSeparator renderizam ambos <li>, e aninhar um no
                  outro é HTML inválido ("<li> cannot contain a nested <li>").
                  O E2E pegou isso pelo console do React. */}
              {trilha.map((item, i) => (
                <Fragment key={`${item.rotulo}-${i}`}>
                  {i > 0 && <BreadcrumbSeparator />}
                  <BreadcrumbItem>
                    {item.to ? (
                      <BreadcrumbLink href={item.to}>{item.rotulo}</BreadcrumbLink>
                    ) : (
                      <BreadcrumbPage>{item.rotulo}</BreadcrumbPage>
                    )}
                  </BreadcrumbItem>
                </Fragment>
              ))}
            </BreadcrumbList>
          </Breadcrumb>
          {/* Gatilho visível da paleta: sem ele o ⌘K era invisível — recurso
              que só existe para quem já sabe que existe não existe. */}
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPaletaAberta(true)}
              className="hidden items-center gap-2 rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 sm:flex"
            >
              <Search className="size-3.5" aria-hidden />
              <span>Buscar…</span>
              <kbd className="ml-6 rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px]">
                Ctrl K
              </kbd>
            </button>
            <ThemeToggle />
          </div>
        </header>
        <Outlet />
      </SidebarInset>
    </SidebarProvider>
  )
}

function RotaComErro({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-4 p-6 text-center">
      <AlertTriangle className="size-10 text-destructive" aria-hidden />
      <div>
        <h1 className="text-xl font-semibold">Algo deu errado nesta tela</h1>
        <p className="mt-1 max-w-md text-sm text-muted-foreground">{error.message}</p>
      </div>
      <Button onClick={reset}>Tentar novamente</Button>
    </div>
  )
}
