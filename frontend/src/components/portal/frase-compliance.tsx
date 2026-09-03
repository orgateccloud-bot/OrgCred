import { ShieldCheck } from 'lucide-react'
import { fraseDoDia } from '@/lib/compliance'

/**
 * Frase do dia de compliance — uma linha, determinística (lib/compliance.ts),
 * fechando a home. Educação em dose homeopática: quem lê uma por dia sabe,
 * em um mês, por que a agenda é imutável e por que o contrato tem impressão
 * digital.
 */
export function FraseCompliance({ hoje }: { hoje?: Date }) {
  const frase = fraseDoDia(hoje)

  return (
    <section className="flex gap-3 rounded-xl border border-border bg-card p-4">
      <ShieldCheck className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden />
      <div>
        <p className="text-xs font-medium text-muted-foreground">
          Compliance · Frase do dia · {frase.tema}
        </p>
        <p className="mt-1 text-sm">{frase.texto}</p>
      </div>
    </section>
  )
}
