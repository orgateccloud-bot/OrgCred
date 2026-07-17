import { createClient, type Session } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

/**
 * Projeto Supabase ainda não provisionado neste repositório (ver
 * DECISOES_PENDENTES.md) — sem VITE_SUPABASE_URL/VITE_SUPABASE_ANON_KEY,
 * o SDK é criado com placeholders e toda chamada de auth falha de forma
 * previsível, em vez de lançar em tempo de import.
 */
export const supabaseConfigurado = Boolean(url && anonKey)

export const supabase = createClient(
  url || 'https://placeholder.supabase.co',
  anonKey || 'placeholder-anon-key',
)

export async function getSession(): Promise<Session | null> {
  if (!supabaseConfigurado) return null
  const { data } = await supabase.auth.getSession()
  return data.session
}
