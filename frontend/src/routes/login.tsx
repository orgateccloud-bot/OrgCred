import { useState, type FormEvent } from 'react'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
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

    // LOGIN DE DESENVOLVIMENTO. `import.meta.env.DEV` é resolvido em tempo de
    // build pelo Vite: `true` sob `vite dev`, `false` — e o ramo inteiro morto,
    // eliminado do bundle — em `vite build`. Casado com o endpoint /api/dev/login,
    // que o backend só monta fora de produção, o bypass não existe em produção
    // por dois motivos independentes. No dev a senha é ignorada de propósito: a
    // senha real vive no Supabase, ausente aqui; o papel continua vindo do banco
    // a cada request.
    if (import.meta.env.DEV) {
      setEnviando(true)
      try {
        const res = await fetch('/api/dev/login', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ email }),
        })
        if (!res.ok) {
          const corpo = await res.json().catch(() => ({}))
          setErro(corpo.detail ?? 'Usuário de desenvolvimento não encontrado.')
          return
        }
        const sess = await res.json()

        // Escreve a sessão direto no storage do supabase-js e recarrega. NÃO
        // uso `supabase.auth.setSession`: ele valida o token contra o servidor
        // do Supabase, que aqui é uma URL placeholder que não resolve — a
        // chamada falha e nada acontece. Escrevendo no storage e recarregando,
        // o SDK reinicializa lendo a sessão do disco (sem rede), e o
        // interceptor de request (`getSession`) a encontra. É o mesmo caminho
        // do E2E, sem o mock de rede do Playwright.
        //
        // A chave é `sb-<ref>-auth-token`, com o ref sendo o primeiro rótulo do
        // host da URL do Supabase — a convenção do próprio supabase-js.
        const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
        if (!supabaseUrl) {
          setErro(
            'Login de dev precisa de VITE_SUPABASE_URL (mesmo placeholder) no .env.local do frontend.',
          )
          setEnviando(false)
          return
        }
        const ref = new URL(supabaseUrl).hostname.split('.')[0]
        localStorage.setItem(
          `sb-${ref}-auth-token`,
          JSON.stringify({
            access_token: sess.access_token,
            refresh_token: sess.refresh_token,
            expires_at: sess.expires_at,
            expires_in: sess.expires_at - Math.floor(Date.now() / 1000),
            token_type: 'bearer',
            user: { id: sess.user.id, email: sess.user.email, aud: 'authenticated' },
          }),
        )
        setUsuario({ id: sess.user.id, email: sess.user.email })
        // Reload completo de propósito (não `navigate`): reinicializa o SDK
        // para ele carregar a sessão recém-escrita.
        window.location.assign('/')
      } catch {
        setErro('Falha no login de desenvolvimento (backend está de pé?).')
        setEnviando(false)
      }
      return
    }

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
      {/* Gradiente-assinatura da ORGATEC (navy→ciano, --oc-grad-globe) aparece
          só aqui, como fundo discreto — nunca em texto corrido ou em elemento
          que carregue dado. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-40 h-80 opacity-25 blur-3xl"
        style={{ background: 'var(--oc-grad-globe)' }}
      />

      <Card className="w-full max-w-sm">
        <CardHeader className="items-center text-center">
          {/* Aqui há espaço para a marca respirar, ao contrário da sidebar:
              o logotipo entra em tamanho legível e o nome do produto vem
              logo abaixo. */}
          <img src="/orgatec-logo.png" alt="Orgatec" className="mb-3 h-10 w-auto object-contain" />
          <CardTitle className="font-heading text-2xl font-bold tracking-tight">OrgCred</CardTitle>
          <CardDescription>Painel de operações da ESC · ORGATEC</CardDescription>
        </CardHeader>
        <CardContent>
          {import.meta.env.DEV && (
            <div className="mb-4 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs text-muted-foreground">
              <strong className="text-foreground">Modo desenvolvimento.</strong> A senha é ignorada
              — entre com um e-mail já semeado:{' '}
              <code className="font-mono">admin@orgcred.local</code> (painel) ou{' '}
              <code className="font-mono">cliente@demo.local</code> (portal do tomador).
            </div>
          )}
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
                // No dev a senha é ignorada (Supabase ausente); exigir preenchimento
                // aqui contradiz o aviso amarelo e trava o submit com "Preencha este
                // campo". Fora de produção o campo é opcional; em produção continua
                // obrigatório.
                required={!import.meta.env.DEV}
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
