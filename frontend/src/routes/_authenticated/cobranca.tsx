import { useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlarmClock, ShieldAlert } from 'lucide-react'
import { toast } from 'sonner'
import {
  getAgingApiCobrancaAgingGetOptions,
  getAgingApiCobrancaAgingGetQueryKey,
  getOperacoesApiOperacoesGetQueryKey,
  getCapitalSnapshotApiCapitalSnapshotGetOptions,
  postProcessarAgingApiCobrancaAgingProcessarPostMutation,
} from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { formatarMoeda } from '@/lib/format'
import { rotuloFaixaAging } from '@/lib/rotulos'
import { StatusOperacaoBadge } from '@/components/status-operacao-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

export const Route = createFileRoute('/_authenticated/cobranca')({
  component: CobrancaPage,
})

/** Faixas em ordem de gravidade — a mesma da view no banco. */
const FAIXAS = ['em_dia', 'ate_30', 'de_31_a_60', 'de_61_a_90', 'acima_de_90'] as const

function classeGravidade(faixa: string): string {
  if (faixa === 'acima_de_90') return 'text-destructive'
  if (faixa === 'de_61_a_90') return 'text-warning'
  return 'text-muted-foreground'
}

function CobrancaPage() {
  const queryClient = useQueryClient()
  const { data, error, isPending } = useQuery(getAgingApiCobrancaAgingGetOptions())

  if (isPending) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-24" />
        <Skeleton className="h-64" />
      </div>
    )
  }
  if (error) return <p className="p-6 text-destructive">{mensagemDeErro(error)}</p>
  if (!data) return null

  const resumoPorFaixa = new Map(data.resumo.map((r) => [r.faixa, r]))
  const elegiveis = data.operacoes.filter(
    (o) => o.status === 'ativa' && o.dias_atraso >= data.limite_inadimplencia_dias,
  )

  function invalidar() {
    queryClient.invalidateQueries({ queryKey: getAgingApiCobrancaAgingGetQueryKey() })
    queryClient.invalidateQueries({ queryKey: getOperacoesApiOperacoesGetQueryKey() })
    queryClient.invalidateQueries({
      queryKey: getCapitalSnapshotApiCapitalSnapshotGetOptions().queryKey,
    })
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-heading text-2xl font-bold tracking-tight">Cobrança</h1>
        <div className="ml-auto">
          <ProcessarAgingDialog
            limiteDias={data.limite_inadimplencia_dias}
            elegiveis={elegiveis.length}
            onSucesso={invalidar}
          />
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {FAIXAS.map((faixa) => {
          const r = resumoPorFaixa.get(faixa)
          return (
            <Card key={faixa}>
              <CardHeader className="pb-2">
                <CardDescription>{rotuloFaixaAging(faixa)}</CardDescription>
                <CardTitle className={`font-mono text-2xl tabular-nums ${classeGravidade(faixa)}`}>
                  {r?.quantidade ?? 0}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="font-mono text-xs text-muted-foreground tabular-nums">
                  {formatarMoeda(String(r?.valor_vencido ?? 0))} vencidos
                </p>
              </CardContent>
            </Card>
          )
        })}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Operações que comprometem capital</CardTitle>
          <CardDescription>
            Atraso calculado a partir da agenda de parcelas, que é imutável desde a emissão — mais
            atrasadas primeiro, que é a ordem de prioridade da cobrança.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {data.operacoes.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nenhuma operação ativa ou inadimplente no momento.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Tomador</TableHead>
                    <TableHead>Situação</TableHead>
                    <TableHead className="text-right">Principal</TableHead>
                    <TableHead className="text-right">Atraso</TableHead>
                    <TableHead>Faixa</TableHead>
                    <TableHead className="text-right">Parcelas vencidas</TableHead>
                    <TableHead className="text-right">Valor vencido</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.operacoes.map((o) => (
                    <TableRow key={o.operacao_id}>
                      <TableCell>
                        <Link
                          to="/operacoes/$id"
                          params={{ id: o.operacao_id }}
                          className="text-primary hover:underline"
                        >
                          {o.tomador_razao_social}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <StatusOperacaoBadge status={o.status} />
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {formatarMoeda(String(o.valor_principal))}
                      </TableCell>
                      <TableCell
                        className={`text-right font-mono tabular-nums ${classeGravidade(o.faixa)}`}
                      >
                        {o.dias_atraso === 0 ? '—' : `${o.dias_atraso} d`}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className={classeGravidade(o.faixa)}>
                          {rotuloFaixaAging(o.faixa)}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {o.parcelas_vencidas}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {formatarMoeda(String(o.valor_vencido))}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

/**
 * Execução da régua automática.
 *
 * O diálogo diz quantas operações serão afetadas ANTES de confirmar, porque
 * o efeito é declarar inadimplência de tomadores reais — e a volta exige que
 * alguém confirme nominalmente a regularização, uma por uma.
 */
function ProcessarAgingDialog({
  limiteDias,
  elegiveis,
  onSucesso,
}: {
  limiteDias: number
  elegiveis: number
  onSucesso: () => void
}) {
  const [open, setOpen] = useState(false)
  const mutation = useMutation(postProcessarAgingApiCobrancaAgingProcessarPostMutation())

  return (
    <Dialog
      open={open}
      onOpenChange={(aberto) => {
        setOpen(aberto)
        if (!aberto) mutation.reset()
      }}
    >
      <DialogTrigger asChild>
        <Button variant={elegiveis > 0 ? 'default' : 'outline'}>
          <AlarmClock />
          Executar régua
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Executar régua de inadimplência</DialogTitle>
          <DialogDescription asChild>
            <div className="space-y-3">
              <p>
                Operações <strong>ativas</strong> com atraso de {limiteDias} dias ou mais passarão a{' '}
                <strong>inadimplente</strong>.{' '}
                {elegiveis === 0 ? (
                  <>Nenhuma operação se enquadra agora.</>
                ) : (
                  <>
                    <strong>{elegiveis}</strong>{' '}
                    {elegiveis === 1 ? 'operação se enquadra' : 'operações se enquadram'} agora.
                  </>
                )}
              </p>
              <p className="flex gap-2 text-sm">
                <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
                <span>
                  A régua não faz o caminho de volta. Regularizar uma operação é decisão de um
                  operador, uma por uma, e fica na trilha com o nome de quem confirmou.
                </span>
              </p>
            </div>
          </DialogDescription>
        </DialogHeader>

        {mutation.isError && (
          <p className="text-sm text-destructive">{mensagemDeErro(mutation.error)}</p>
        )}

        <DialogFooter>
          <Button
            onClick={() =>
              mutation.mutate(
                { body: { limite_dias: limiteDias } },
                {
                  onSuccess: (resultado) => {
                    onSucesso()
                    setOpen(false)
                    toast.success(
                      resultado.transicionadas === 0
                        ? 'Régua executada: nenhuma operação se enquadrou.'
                        : `${resultado.transicionadas} ${
                            resultado.transicionadas === 1
                              ? 'operação marcada'
                              : 'operações marcadas'
                          } como inadimplente.`,
                    )
                  },
                },
              )
            }
            disabled={mutation.isPending}
          >
            {mutation.isPending ? 'Executando…' : 'Confirmar execução'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
