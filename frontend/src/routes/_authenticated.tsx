import { createFileRoute, Outlet, redirect, useRouterState } from '@tanstack/react-router'
import { AlertTriangle } from 'lucide-react'
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

  return (
    <SidebarProvider>
      <CommandPalette />
      <AppSidebar />
      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-4">
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="mr-2 h-4" />
          <Breadcrumb>
            <BreadcrumbList>
              {trilha.map((item, i) => (
                <BreadcrumbItem key={`${item.rotulo}-${i}`}>
                  {i > 0 && <BreadcrumbSeparator />}
                  {item.to ? (
                    <BreadcrumbLink href={item.to}>{item.rotulo}</BreadcrumbLink>
                  ) : (
                    <BreadcrumbPage>{item.rotulo}</BreadcrumbPage>
                  )}
                </BreadcrumbItem>
              ))}
            </BreadcrumbList>
          </Breadcrumb>
          <div className="ml-auto">
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
