import { useState, type FormEvent } from 'react'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Landmark } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
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
  const [recuperando, setRecuperando] = useState(false)

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

  async function handleEsqueciSenha() {
    setErro(null)
    if (!supabaseConfigurado) {
      setErro('Autenticação ainda não configurada neste ambiente.')
      return
    }
    if (!email) {
      setErro('Preencha o e-mail acima para receber o link de redefinição.')
      return
    }

    setRecuperando(true)
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/definir-senha`,
    })
    setRecuperando(false)

    if (error) {
      setErro(error.message)
      return
    }
    toast.success('Link de redefinição enviado', {
      description: `Confira a caixa de entrada de ${email}.`,
    })
  }

  return (
    <div className="relative flex min-h-svh items-center justify-center overflow-hidden p-6">
      {/* Assinatura Aurora: o gradiente da marca aparece só aqui, como fundo
          discreto — nunca em texto corrido ou elementos de dado. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-40 h-80 opacity-20 blur-3xl"
        style={{
          background: 'linear-gradient(135deg, #0052FF 0%, #4D7CFF 52%, #0EA5E9 100%)',
        }}
      />

      <Card className="w-full max-w-sm">
        <CardHeader className="items-center text-center">
          <div className="mb-2 flex size-12 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <Landmark className="size-6" aria-hidden />
          </div>
          <CardTitle className="text-2xl">OrgCred</CardTitle>
          <CardDescription>Painel de operações da ESC · ORGATEC</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1">
              <label htmlFor="email" className="text-sm text-muted-foreground">
                E-mail
              </label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>

            <div className="space-y-1">
              <label htmlFor="senha" className="text-sm text-muted-foreground">
                Senha
              </label>
              <Input
                id="senha"
                type="password"
                autoComplete="current-password"
                required
                value={senha}
                onChange={(event) => setSenha(event.target.value)}
              />
            </div>

            {erro && <p className="text-sm text-destructive">{erro}</p>}

            <Button type="submit" disabled={enviando} className="w-full">
              {enviando ? 'Entrando…' : 'Entrar'}
            </Button>

            <Button
              type="button"
              variant="link"
              size="sm"
              className="w-full text-muted-foreground"
              disabled={recuperando}
              onClick={handleEsqueciSenha}
            >
              {recuperando ? 'Enviando link…' : 'Esqueci minha senha'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
