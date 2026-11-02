import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { useAppStore } from '@/stores/useAppStore'
import { THEMES, type MobileTheme, type ThemeName } from './theme'

/**
 * Provider de tema do app mobile. Os três temas (Platinum / Obsidian / Aurora)
 * são alternáveis pelo usuário e a escolha é persistida à parte do tema
 * claro/escuro do shadcn — o app mobile é um mundo visual próprio.
 *
 * Sem escolha salva, o padrão deriva do tema do painel: claro → Platinum,
 * escuro → Obsidian (o par que casa com o sistema existente). Aurora é sempre
 * uma opção explícita.
 *
 * Aplicação dos tokens: as telas leem o objeto `theme` por contexto e aplicam
 * via `style` inline (`t.surface`, `t.grad`, …), exatamente como o design faz.
 * É verboso, mas é o que garante o pixel-perfect e não briga com o Tailwind.
 */

const STORAGE_KEY = 'orgcred-mobile-theme'

interface MobileThemeValue {
  name: ThemeName
  theme: MobileTheme
  setName: (name: ThemeName) => void
}

const MobileThemeContext = createContext<MobileThemeValue | null>(null)

function lerTemaSalvo(): ThemeName | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'platinum' || v === 'obsidian' || v === 'aurora') return v
  } catch {
    // storage indisponível (aba privada, bloqueio) — sem preferência salva.
  }
  return null
}

export function MobileThemeProvider({ children }: { children: ReactNode }) {
  // Só para derivar o padrão inicial; trocar o tema do painel depois não
  // sobrescreve uma escolha explícita do usuário no app mobile.
  const temaPainel = useAppStore((state) => state.tema)
  const [name, setNameState] = useState<ThemeName>(
    () => lerTemaSalvo() ?? (temaPainel === 'dark' ? 'obsidian' : 'platinum'),
  )

  const setName = useCallback((proximo: ThemeName) => {
    setNameState(proximo)
    try {
      localStorage.setItem(STORAGE_KEY, proximo)
    } catch {
      // Sem persistência? A troca ainda vale nesta sessão.
    }
  }, [])

  const value = useMemo<MobileThemeValue>(
    () => ({ name, theme: THEMES[name], setName }),
    [name, setName],
  )

  return <MobileThemeContext.Provider value={value}>{children}</MobileThemeContext.Provider>
}

function useCtx(): MobileThemeValue {
  const ctx = useContext(MobileThemeContext)
  if (!ctx) throw new Error('useMobileTheme precisa estar dentro de <MobileThemeProvider>')
  return ctx
}

/** O objeto de tokens do tema ativo — o uso mais comum nas telas. */
export function useMobileTheme(): MobileTheme {
  return useCtx().theme
}

/** Nome do tema ativo + setter, para o seletor de tema. */
export function useMobileThemeControls(): { name: ThemeName; setName: (n: ThemeName) => void } {
  const { name, setName } = useCtx()
  return { name, setName }
}
