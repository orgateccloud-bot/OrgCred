import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Newspaper, ShieldAlert } from 'lucide-react'
import { buscarClima, derivarAlertas } from '@/lib/clima'
import { buscarIndicadores } from '@/lib/indicadores'
import { formatarDataIso } from '@/components/identificacao/mensagens'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

/**
 * Radar do dia: o noticiário utilitário do tomador — alertas de tempo
 * derivados da previsão do município e os três indicadores que mudam a
 * conversa de crédito de uma empresa pequena (Selic, IPCA, dólar).
 *
 * Tudo aqui é determinístico e tem fonte no rodapé. Sem manchete gerada,
 * sem opinião: número com data de referência, alerta com critério no texto
 * (ver lib/clima.ts e lib/indicadores.ts). As duas buscas degradam em
 * silêncio e independentes — radar parcial vale mais que radar nenhum.
 */
export function RadarDoDia({ municipio, uf }: { municipio: string; uf: string }) {
  const clima = useQuery({
    // Mesma chave do hero: uma busca só serve os dois blocos.
    queryKey: ['clima', municipio, uf],
    queryFn: () => buscarClima(municipio, uf),
    staleTime: 30 * 60_000,
    retry: false,
  })
  const indicadores = useQuery({
    queryKey: ['indicadores'],
    queryFn: buscarIndicadores,
    staleTime: 60 * 60_000,
    retry: false,
  })

  const alertas = clima.data ? derivarAlertas(clima.data.dias) : []
  const carregando = clima.isLoading || indicadores.isLoading

  return (
    <section className="space-y-3">
      <h2 className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
        <Newspaper className="size-4" aria-hidden />
        Radar do dia
      </h2>

      {carregando ? (
        <Skeleton className="h-32 w-full" />
      ) : (
        <div className="space-y-3 rounded-xl border border-border bg-card p-4">
          {/* ---- Alertas de tempo (próximos 3 dias) ---------------------- */}
          {clima.data &&
            (alertas.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Sem alertas de tempo para os próximos 3 dias em {clima.data.local}.
              </p>
            ) : (
              <ul className="space-y-2">
                {alertas.map((alerta) => (
                  <li
                    key={`${alerta.data}-${alerta.titulo}`}
                    className={cn(
                      'flex gap-2.5 rounded-lg border p-3 text-sm',
                      alerta.severidade === 'alerta'
                        ? 'border-destructive/40 bg-destructive/5'
                        : 'border-warning/40 bg-warning/5',
                    )}
                  >
                    {alerta.severidade === 'alerta' ? (
                      <ShieldAlert
                        className="mt-0.5 size-4 shrink-0 text-destructive"
                        aria-hidden
                      />
                    ) : (
                      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
                    )}
                    <div>
                      <p className="font-medium">
                        {alerta.titulo} — {formatarDataIso(alerta.data)}
                      </p>
                      <p className="text-muted-foreground">{alerta.detalhe}</p>
                    </div>
                  </li>
                ))}
              </ul>
            ))}

          {/* ---- Indicadores para o negócio ------------------------------ */}
          {indicadores.data && indicadores.data.length > 0 && (
            <div className="grid grid-cols-3 gap-2">
              {indicadores.data.map((ind) => (
                <div key={ind.rotulo} className="rounded-lg border border-border p-3">
                  <p className="text-xs text-muted-foreground">{ind.rotulo}</p>
                  <p className="mt-0.5 font-mono text-base font-semibold tabular-nums">
                    {ind.unidade === 'R$'
                      ? `R$ ${ind.valor.toLocaleString('pt-BR', {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}`
                      : `${ind.valor.toLocaleString('pt-BR', {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}${ind.unidade}`}
                  </p>
                  <p className="mt-0.5 text-[10px] text-muted-foreground tabular-nums">
                    {ind.referencia}
                  </p>
                </div>
              ))}
            </div>
          )}

          {!clima.data && (!indicadores.data || indicadores.data.length === 0) && (
            <p className="text-sm text-muted-foreground">
              O radar está indisponível agora — os dados de tempo e mercado não puderam ser
              carregados. Suas parcelas e operações acima não dependem dele.
            </p>
          )}

          <p className="text-[10px] text-muted-foreground">
            Alertas derivados da previsão (critérios simples, não são avisos oficiais de Defesa
            Civil). Fontes: Open-Meteo · Banco Central (SGS) · AwesomeAPI.
          </p>
        </div>
      )}
    </section>
  )
}
