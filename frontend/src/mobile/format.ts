import { formatarMoeda } from '@/lib/format'

/**
 * Helpers de formatação/parse do app mobile. `formatarMoeda` (o `formatBRL` do
 * design) vem de `@/lib/format` e é reusado como está — a fonte única de
 * formatação de moeda do app inteiro.
 */
export { formatarMoeda }

/** `parseBRL` do design: "1.234,56" | "R$ 1.234,56" → 1234.56. */
export function parseBRL(str: string | number | null | undefined): number {
  if (str === null || str === undefined || str === '') return 0
  const cleaned = String(str)
    .replace(/[^\d,.-]/g, '')
    .replace(/\.(?=\d{3}(\D|$))/g, '')
    .replace(',', '.')
  const n = parseFloat(cleaned)
  return Number.isNaN(n) ? 0 : n
}

/** Percentual em fração ou string ("2.10") → "2,10%". */
export function formatarTaxa(taxa: string | number): string {
  return (Number(taxa) || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2 }) + '%'
}

/** ISO/date → "28 jul" (dia + mês curto). */
export function dataCurta(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' }).replace('.', '')
}

/** ISO/date → "28 jul, 09:42". */
export function dataHora(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const dia = d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' }).replace('.', '')
  const hora = d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
  return `${dia}, ${hora}`
}
