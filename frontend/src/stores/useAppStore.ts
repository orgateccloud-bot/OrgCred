import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Papel = 'admin' | 'operador'
export type Tema = 'dark' | 'light'

/**
 * `papel`/`nome` vêm do backend (tabela usuario), não do Supabase — e não
 * existe endpoint `/me` ainda (gap técnico, não bloqueador de negócio; ver
 * DECISOES_PENDENTES.md). Ficam opcionais até essa integração existir; o
 * enforcement real de papel já acontece no backend a cada request
 * (Zero-Trust, ver app/core/security.py), então a ausência aqui não é um
 * risco de segurança — só limita o que a UI pode decidir mostrar/esconder.
 */
interface UsuarioAutenticado {
  id: string
  email: string
  nome?: string
  papel?: Papel
}

interface AppState {
  usuario: UsuarioAutenticado | null
  tema: Tema
  setUsuario: (usuario: UsuarioAutenticado | null) => void
  setTema: (tema: Tema) => void
}

function aplicarTema(tema: Tema) {
  document.documentElement.classList.toggle('dark', tema === 'dark')
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      usuario: null,
      tema: 'dark',
      setUsuario: (usuario) => set({ usuario }),
      setTema: (tema) => {
        aplicarTema(tema)
        set({ tema })
      },
    }),
    {
      name: 'orgcred-app-store',
      partialize: (state) => ({ tema: state.tema }),
      onRehydrateStorage: () => (state) => {
        if (state) aplicarTema(state.tema)
      },
    },
  ),
)

// Aplica o tema padrão (dark) antes da primeira renderização, para não
// piscar light->dark quando não há tema persistido ainda.
aplicarTema(useAppStore.getState().tema)
