import { getMeApiMeGet } from '@/api/generated/sdk.gen'
import { supabase, supabaseConfigurado } from '@/auth/supabaseClient'
import { useAppStore } from '@/stores/useAppStore'

/**
 * Mantém a store espelhando a sessão real do Supabase.
 *
 * Sem isto, `usuario` só era populado no submit do login: após um F5 a sessão
 * persistida continuava válida (guarda de rota passava), mas a store voltava
 * vazia e qualquer tela que dependesse do usuário quebrava em silêncio.
 * O evento INITIAL_SESSION cobre exatamente o caso do reload.
 *
 * Além do id/email do token, busca papel/nome em GET /api/me (tabela usuario)
 * — o token Supabase não os carrega. A UI usa papel só para exibir/esconder;
 * o enforcement real continua no backend a cada request (Zero-Trust).
 */
export function initAuthSync(): void {
  if (!supabaseConfigurado) return

  supabase.auth.onAuthStateChange((_event, session) => {
    const setUsuario = useAppStore.getState().setUsuario
    if (session?.user) {
      setUsuario({ id: session.user.id, email: session.user.email ?? '' })
      // Enriquecimento assíncrono: se falhar (ex.: usuário sem linha em
      // usuario), a sessão segue válida, só sem papel — a UI degrada para o
      // conjunto mínimo de ações, e o backend barra o resto.
      void getMeApiMeGet()
        .then((res) => {
          if (res.data) {
            setUsuario({
              id: res.data.id,
              email: res.data.email,
              nome: res.data.nome,
              papel: res.data.papel as 'admin' | 'operador',
            })
          }
        })
        .catch(() => {})
    } else {
      setUsuario(null)
    }
  })
}
