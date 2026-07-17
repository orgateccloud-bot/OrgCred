import { useState, type FormEvent } from 'react'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { supabase, supabaseConfigurado } from '@/auth/supabaseClient'
import { useAppStore } from '@/stores/useAppStore'

export const Route = createFileRoute('/login')({
  component: LoginPage,
})

function LoginPage() {
  const navigate = useNavigate()
  const setUsuario = useAppStore((state) => state.setUsuario)
  const [email, setEmail] = useState('')
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setErro(null)

    if (!supabaseConfigurado) {
      setErro(
        'Autenticação ainda não configurada (VITE_SUPABASE_URL/VITE_SUPABASE_ANON_KEY ausentes).',
      )
      return
    }

    setEnviando(true)
    const { data, error } = await supabase.auth.signInWithPassword({ email, password: senha })
    setEnviando(false)

    if (error || !data.user) {
      setErro(error?.message ?? 'Falha ao autenticar.')
      return
    }

    setUsuario({ id: data.user.id, email: data.user.email ?? email })
    navigate({ to: '/' })
  }

  return (
    <div className="flex min-h-svh items-center justify-center p-6">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4">
        <h1 className="text-2xl font-semibold">Entrar</h1>

        <div className="space-y-1">
          <label htmlFor="email" className="text-sm text-muted-foreground">
            E-mail
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
        </div>

        <div className="space-y-1">
          <label htmlFor="senha" className="text-sm text-muted-foreground">
            Senha
          </label>
          <input
            id="senha"
            type="password"
            autoComplete="current-password"
            required
            value={senha}
            onChange={(event) => setSenha(event.target.value)}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
        </div>

        {erro && <p className="text-sm text-destructive">{erro}</p>}

        <Button type="submit" disabled={enviando} className="w-full">
          {enviando ? 'Entrando…' : 'Entrar'}
        </Button>
      </form>
    </div>
  )
}
