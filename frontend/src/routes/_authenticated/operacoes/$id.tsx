import { createFileRoute, Link } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CircleDot, MapPin } from 'lucide-react'
import {
  getOperacaoApiOperacoesOperacaoIdGetOptions,
  getOperacoesApiOperacoesGetQueryKey,
  getCapitalSnapshotApiCapitalSnapshotGetOptions,
  postCancelarOperacaoApiOperacoesOperacaoIdCancelarPostMutation,
  postLiquidarOperacaoApiOperacoesOperacaoIdLiquidarPostMutation,
  postMarcarInadimplenteApiOperacoesOperacaoIdMarcarInadimplentePostMutation,
  postRenegociarOperacaoApiOperacoesOperacaoIdRenegociarPostMutation,
} from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { formatarMoeda } from '@/lib/format'
import { narrativa } from '@/lib/ledger'
import { AtivarOperacaoDialog } from '@/components/ativar-operacao-dialog'
import { RegistrarOperacaoDialog } from '@/components/registrar-operacao-dialog'
import { StatusOperacaoBadge } from '@/components/status-operacao-badge'
import { TransicaoOperacaoDialog } from '@/components/transicao-operacao-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

export const Route = createFileRoute('/_authenticated/operacoes/$id')({
  component: OperacaoDetailPage,
})

function OperacaoDetailPage() {
  const { id } = Route.useParams()
  const queryClient = useQueryClient()
  const { data, error, isPending } = useQuery(
    getOperacaoApiOperacoesOperacaoIdGetOptions({ path: { operacao_id: id } }),
  )

  const liquidar = useMutation(postLiquidarOperacaoApiOperacoesOperacaoIdLiquidarPostMutation())
  const cancelar = useMutation(postCancelarOperacaoApiOperacoesOperacaoIdCancelarPostMutation())
  const renegociar = useMutation(
    postRenegociarOperacaoApiOperacoesOperacaoIdRenegociarPostMutation(),
  )
  const inadimplente = useMutation(
    postMarcarInadimplenteApiOperacoesOperacaoIdMarcarInadimplentePostMutation(),
  )

  function invalidar() {
    queryClient.invalidateQueries({
      queryKey: getOperacaoApiOperacoesOperacaoIdGetOptions({ path: { operacao_id: id } }).queryKey,
    })
    queryClient.invalidateQueries({ queryKey: getOperacoesApiOperacoesGetQueryKey() })
    queryClient.invalidateQueries({
      queryKey: getCapitalSnapshotApiCapitalSnapshotGetOptions().queryKey,
    })
  }

  if (isPending) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid gap-4 md:grid-cols-2">
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
        </div>
        <Skeleton className="h-64" />
      </div>
    )
  }
  if (error) {
    return <p className="p-6 text-destructive">{mensagemDeErro(error)}</p>
  }
  if (!data) return null

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <Button asChild variant="ghost" size="icon" aria-label="Voltar para a lista">
          <Link to="/operacoes">
            <ArrowLeft />
          </Link>
        </Button>
        <h1 className="font-heading text-2xl font-bold tracking-tight">
          {data.tomador.razao_social}
        </h1>
        <StatusOperacaoBadge status={data.status} />
        <div className="ml-auto flex flex-wrap gap-2">
          {data.status === 'proposta' && (
            <>
              <RegistrarOperacaoDialog operacaoId={data.id} onSucesso={invalidar} />
              <TransicaoOperacaoDialog
                operacaoId={data.id}
                titulo="Cancelar proposta"
                descricao="A proposta será encerrada sem comprometer capital. Esta ação não pode ser desfeita."
                rotuloBotao="Cancelar proposta"
                rotuloConfirmar="Confirmar cancelamento"
                variant="destructive"
                mutation={cancelar}
                invalidar={invalidar}
              />
            </>
          )}
          {data.status === 'registrada' && (
            <>
              <AtivarOperacaoDialog
                operacaoId={data.id}
                valorPrincipal={String(data.valor_principal)}
                onSucesso={invalidar}
              />
              <TransicaoOperacaoDialog
                operacaoId={data.id}
                titulo="Cancelar operação registrada"
                descricao="A operação registrada será cancelada antes da ativação. Esta ação não pode ser desfeita."
                rotuloBotao="Cancelar"
                rotuloConfirmar="Confirmar cancelamento"
                variant="destructive"
                mutation={cancelar}
                invalidar={invalidar}
              />
            </>
          )}
          {data.status === 'ativa' && (
            <>
              <TransicaoOperacaoDialog
                operacaoId={data.id}
                titulo="Liquidar operação"
                descricao={`A liquidação devolve ${formatarMoeda(String(data.valor_principal))} ao capital disponível e encerra a operação. O evento é gravado no ledger imutável.`}
                rotuloBotao="Liquidar"
                rotuloConfirmar="Confirmar liquidação"
                variant="default"
                mutation={liquidar}
                invalidar={invalidar}
              />
              <TransicaoOperacaoDialog
                operacaoId={data.id}
                titulo="Renegociar operação"
                descricao="A operação sai do estado ativo para renegociada. Uma nova operação deverá formalizar as novas condições."
                rotuloBotao="Renegociar"
                rotuloConfirmar="Confirmar renegociação"
                mutation={renegociar}
                invalidar={invalidar}
              />
              <TransicaoOperacaoDialog
                operacaoId={data.id}
                titulo="Marcar inadimplência"
                descricao="A operação será marcada como inadimplente. É reversível: a regularização retorna a operação ao estado ativo."
                rotuloBotao="Inadimplência"
                rotuloConfirmar="Confirmar marcação"
                variant="destructive"
                mutation={inadimplente}
                invalidar={invalidar}
              />
            </>
          )}
          {data.status === 'inadimplente' && (
            <>
              <AtivarOperacaoDialog
                operacaoId={data.id}
                valorPrincipal={String(data.valor_principal)}
                onSucesso={invalidar}
              />
              <TransicaoOperacaoDialog
                operacaoId={data.id}
                titulo="Liquidar operação"
                descricao="Liquidação de operação inadimplente: devolve o valor ao capital disponível e encerra a operação."
                rotuloBotao="Liquidar"
                rotuloConfirmar="Confirmar liquidação"
                variant="default"
                mutation={liquidar}
                invalidar={invalidar}
              />
              <TransicaoOperacaoDialog
                operacaoId={data.id}
                titulo="Renegociar operação"
                descricao="A operação inadimplente sai para renegociada. Uma nova operação deverá formalizar as novas condições."
                rotuloBotao="Renegociar"
                rotuloConfirmar="Confirmar renegociação"
                mutation={renegociar}
                invalidar={invalidar}
              />
            </>
          )}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Condições</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <LinhaDado rotulo="Valor principal">
              <span className="font-mono tabular-nums">
                {formatarMoeda(String(data.valor_principal))}
              </span>
            </LinhaDado>
            <LinhaDado rotulo="Tipo">{data.tipo}</LinhaDado>
            <LinhaDado rotulo="Taxa de juros">
              <span className="font-mono tabular-nums">{String(data.taxa_juros_mensal)}% a.m.</span>
            </LinhaDado>
            <LinhaDado rotulo="Amortização">{data.sistema_amortizacao}</LinhaDado>
            <LinhaDado rotulo="Parcelas">{data.numero_parcelas}</LinhaDado>
            <LinhaDado rotulo="Registro externo">
              {data.registro_entidade_ref ?? <span className="text-muted-foreground">—</span>}
            </LinhaDado>
            <LinhaDado rotulo="Criada em">
              {new Date(data.created_at).toLocaleString('pt-BR')}
            </LinhaDado>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Tomador</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <LinhaDado rotulo="Razão social">
              <Link
                to="/tomadores/$id"
                params={{ id: data.tomador.id }}
                className="text-primary hover:underline"
              >
                {data.tomador.razao_social}
              </Link>
            </LinhaDado>
            <LinhaDado rotulo="CNPJ">
              <span className="font-mono tabular-nums">{data.tomador.cnpj}</span>
            </LinhaDado>
            <LinhaDado rotulo="Município">
              <span className="inline-flex items-center gap-1">
                <MapPin className="size-3.5 text-muted-foreground" aria-hidden />
                {data.tomador.municipio}/{data.tomador.uf}
              </span>
            </LinhaDado>
            <LinhaDado rotulo="Gate geográfico">
              {data.tomador.municipio_autorizado ? (
                <Badge variant="outline" className="text-success">
                  Município autorizado
                </Badge>
              ) : (
                <Badge variant="outline" className="text-destructive">
                  Não autorizado (OC002 bloqueia ativação)
                </Badge>
              )}
            </LinhaDado>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Linha do tempo</CardTitle>
          <CardDescription>
            Eventos desta operação no ledger de capital (imutável, hash-chain)
          </CardDescription>
        </CardHeader>
        <CardContent>
          {data.eventos.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nenhum evento de capital ainda — propostas e registros não movimentam o ledger; a
              ativação será o primeiro evento.
            </p>
          ) : (
            <ol className="relative space-y-4 border-l border-border pl-6">
              {data.eventos.map((evento) => (
                <li key={evento.id} className="relative">
                  <CircleDot
                    className="absolute -left-[31px] size-4 bg-background text-primary"
                    aria-hidden
                  />
                  <p className="text-sm">{narrativa(evento)}</p>
                  <p className="mt-0.5 font-mono text-xs text-muted-foreground">
                    saldo pós-evento: {formatarMoeda(String(evento.saldo_disponivel_pos))}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function LinhaDado({ rotulo, children }: { rotulo: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-muted-foreground">{rotulo}</span>
      <span className="text-right">{children}</span>
    </div>
  )
}
