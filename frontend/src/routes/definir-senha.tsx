import { useEffect, useState, type FormEvent } from 'react'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { supabase, supabaseConfigurado } from '@/auth/supabaseClient'

export const Route = createFileRoute('/definir-senha')({
  component: DefinirSenhaPage,
})

/**
 * Destino dos links de recuperação/convite do Supabase. O SDK, com
 * detectSessionInUrl (padrão), consome o token do fragmento da URL e emite
 * PASSWORD_RECOVERY, estabelecendo uma sessão temporária que autoriza apenas
 * updateUser. Aqui o próprio usuário digita a senha — ela nunca trafega por
 * fora do navegador dele.
 */
function DefinirSenhaPage() {
  const navigate = useNavigate()
  const [pronto, setPronto] = useState(false)
  const [senha, setSenha] = useState('')
  const [confirma, setConfirma] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [ok, setOk] = useState(false)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (!supabaseConfigurado) {
      setErro('Autenticação ainda não configurada neste ambiente.')
      return
    }
    // Se o link já foi consumido antes deste efeito rodar, a sessão de
    // recuperação já existe; caso contrário, o evento PASSWORD_RECOVERY chega
    // em seguida. Qualquer um dos dois libera o formulário.
    supabase.auth.getSession().then(({ data }) => {
      if (data.session) setPronto(true)
    })
    const { data: sub } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === 'PASSWORD_RECOVERY' || (event === 'SIGNED_IN' && session)) {
        setPronto(true)
      }
    })
    return () => sub.subscription.unsubscribe()
  }, [])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setErro(null)

    if (senha.length < 8) {
      setErro('A senha precisa ter ao menos 8 caracteres.')
      return
    }
    if (senha !== confirma) {
      setErro('As senhas não conferem.')
      return
    }

    setEnviando(true)
    const { error } = await supabase.auth.updateUser({ password: senha })
    setEnviando(false)

    if (error) {
      setErro(error.message)
      return
    }

    // Encerra a sessão de recuperação: o login definitivo é pela tela de login,
    // com a senha recém-definida.
    await supabase.auth.signOut()
    setOk(true)
    setTimeout(() => navigate({ to: '/login' }), 1500)
  }

  return (
    <div className="flex min-h-svh items-center justify-center p-6">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4">
        <h1 className="text-2xl font-semibold">Definir senha</h1>

        {ok ? (
          <p className="text-sm text-muted-foreground">
            Senha definida. Redirecionando para o login…
          </p>
        ) : !pronto ? (
          <p className="text-sm text-muted-foreground">{erro ?? 'Validando o link de acesso…'}</p>
        ) : (
          <>
            <div className="space-y-1">
              <label htmlFor="senha" className="text-sm text-muted-foreground">
                Nova senha
              </label>
              <input
                id="senha"
                type="password"
                autoComplete="new-password"
                required
                value={senha}
                onChange={(event) => setSenha(event.target.value)}
                className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              />
            </div>

            <div className="space-y-1">
              <label htmlFor="confirma" className="text-sm text-muted-foreground">
                Confirmar senha
              </label>
              <input
                id="confirma"
                type="password"
                autoComplete="new-password"
                required
                value={confirma}
                onChange={(event) => setConfirma(event.target.value)}
                className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              />
            </div>

            {erro && <p className="text-sm text-destructive">{erro}</p>}

            <Button type="submit" disabled={enviando} className="w-full">
              {enviando ? 'Salvando…' : 'Salvar senha'}
            </Button>
          </>
        )}
      </form>
    </div>
  )
}
