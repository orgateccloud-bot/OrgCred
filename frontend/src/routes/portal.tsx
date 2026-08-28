import { createFileRoute, Outlet, redirect, useNavigate } from '@tanstack/react-router'
import { AlertTriangle, Building2, LogOut } from 'lucide-react'
import { papelDoLogin } from '@/auth/papel'
import { getSession, supabase, supabaseConfigurado } from '@/auth/supabaseClient'
import { ThemeToggle } from '@/components/theme-toggle'
import { Button } from '@/components/ui/button'

/**
 * O layout do PORTAL DO TOMADOR — deliberadamente sem a sidebar de operação.
 *
 * O tomador não é operador da ESC: ele acompanha o próprio crédito. Dar-lhe a
 * mesma casca do painel (capital, cobrança, compliance) seria oferecer botões
 * que só respondem 403. O portal é uma casca própria, enxuta, com o nome da
 * empresa e a saída.
 *
 * O guarda espelha `_authenticated` ao contrário: exige sessão E papel de
 * tomador. Um operador que digite /portal é mandado ao painel — cada papel na
 * sua casa. O enforcement de dados continua no backend (get_tomador_user).
 */
export const Route = createFileRoute('/portal')({
  beforeLoad: async () => {
    const session = await getSession()
    if (!session) {
      throw redirect({ to: '/login' })
    }
    if ((await papelDoLogin()) !== 'tomador') {
      throw redirect({ to: '/' })
    }
  },
  component: PortalLayout,
  errorComponent: PortalComErro,
})

function PortalLayout() {
  const navigate = useNavigate()

  async function sair() {
    if (supabaseConfigurado) await supabase.auth.signOut()
    navigate({ to: '/login' })
  }

  return (
    <div className="min-h-svh bg-background">
      <header className="flex h-14 items-center gap-3 border-b border-border px-4 sm:px-6">
        <Building2 className="size-5 text-primary" aria-hidden />
        <span className="font-semibold">Portal do tomador</span>
        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle />
          <Button variant="ghost" size="sm" onClick={sair}>
            <LogOut className="size-4" aria-hidden />
            <span className="hidden sm:inline">Sair</span>
          </Button>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-6 sm:px-6">
        <Outlet />
      </main>
    </div>
  )
}

function PortalComErro({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-4 p-6 text-center">
      <AlertTriangle className="size-10 text-destructive" aria-hidden />
      <div>
        <h1 className="text-xl font-semibold">Não foi possível abrir o portal</h1>
        <p className="mt-1 max-w-md text-sm text-muted-foreground">{error.message}</p>
      </div>
      <Button onClick={reset}>Tentar novamente</Button>
    </div>
  )
}
