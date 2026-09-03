import { useQuery } from '@tanstack/react-query'
import {
  Cloud,
  CloudFog,
  CloudLightning,
  CloudRain,
  Droplets,
  Snowflake,
  Sun,
  Wind,
  type LucideIcon,
} from 'lucide-react'
import { buscarClima, interpretarCodigoTempo } from '@/lib/clima'
import { dataPorExtenso, saudacao } from '@/lib/saudacao'

const ICONE_POR_FAMILIA: Record<string, LucideIcon> = {
  sol: Sun,
  nublado: Cloud,
  nevoeiro: CloudFog,
  chuva: CloudRain,
  tempestade: CloudLightning,
  neve: Snowflake,
}

/**
 * Boas-vindas da home: saudação pela hora, a empresa, a data e o tempo AGORA
 * no município do cadastro (ver lib/clima.ts — não é geolocalização).
 *
 * O gradiente da marca aparece aqui como no login: lavagem discreta de
 * fundo, nunca sobre texto ou dado. Clima é cortesia: se a busca falhar, a
 * seção simplesmente não mostra o bloco do tempo — sem erro na cara de quem
 * só veio ver a parcela.
 */
export function HeroBoasVindas({
  razaoSocial,
  municipio,
  uf,
  descricao,
}: {
  razaoSocial: string
  municipio: string
  uf: string
  descricao: string
}) {
  const clima = useQuery({
    queryKey: ['clima', municipio, uf],
    queryFn: () => buscarClima(municipio, uf),
    staleTime: 30 * 60_000,
    retry: false,
  })

  const atual = clima.data?.atual
  const tempo = atual ? interpretarCodigoTempo(atual.codigo) : null
  const IconeTempo = tempo ? ICONE_POR_FAMILIA[tempo.familia] : null

  return (
    <section className="relative overflow-hidden rounded-xl border border-border bg-card p-4 sm:p-5">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-24 h-48 opacity-15 blur-3xl"
        style={{ background: 'var(--oc-grad-globe)' }}
      />
      <div className="relative flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm text-muted-foreground">{dataPorExtenso()}</p>
          <h1 className="mt-0.5 text-2xl font-semibold">
            {saudacao()}, {razaoSocial}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">{descricao}</p>
        </div>

        {atual && tempo && IconeTempo && (
          <div className="flex items-center gap-3 rounded-lg border border-border bg-background/60 px-3 py-2">
            <IconeTempo className="size-7 text-primary" aria-hidden />
            <div>
              <p className="font-mono text-xl leading-6 font-semibold tabular-nums">
                {Math.round(atual.temperatura)}°C
              </p>
              <p className="text-xs text-muted-foreground">
                {tempo.rotulo} · {clima.data?.local}
              </p>
              <p className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  <Wind className="size-3" aria-hidden />
                  {Math.round(atual.vento)} km/h
                </span>
                <span className="inline-flex items-center gap-1">
                  <Droplets className="size-3" aria-hidden />
                  {Math.round(atual.umidade)}%
                </span>
              </p>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
