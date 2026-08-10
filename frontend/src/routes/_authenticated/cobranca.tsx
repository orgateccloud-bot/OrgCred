import { useState, type FormEvent } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlarmClock, Landmark, ShieldAlert } from 'lucide-react'
import { toast } from 'sonner'
import {
  getAgingApiCobrancaAgingGetOptions,
  getAgingApiCobrancaAgingGetQueryKey,
  getMovimentosApiCobrancaMovimentosGetOptions,
  getMovimentosApiCobrancaMovimentosGetQueryKey,
  getOperacoesApiOperacoesGetQueryKey,
  getCapitalSnapshotApiCapitalSnapshotGetOptions,
  postMovimentoApiCobrancaMovimentosPostMutation,
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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

      <MovimentosBancarios />

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

/**
 * Extrato bancário registrado.
 *
 * É a fonte de lastro das baixas: nenhuma parcela pode ser dada por paga
 * sem apontar para uma destas linhas (OC011). O documento é único, então
 * reimportar o mesmo extrato — rotina na operação real — não duplica
 * crédito nem permite baixar duas parcelas com o mesmo dinheiro.
 */
function MovimentosBancarios() {
  const queryClient = useQueryClient()
  const { data, error, isPending } = useQuery(getMovimentosApiCobrancaMovimentosGetOptions())

  function invalidar() {
    queryClient.invalidateQueries({ queryKey: getMovimentosApiCobrancaMovimentosGetQueryKey() })
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div className="space-y-1.5">
          <CardTitle>Extrato bancário</CardTitle>
          <CardDescription>
            Lastro das baixas. Nenhuma parcela é dada por paga sem apontar para uma destas linhas —
            o documento é único, então reimportar o mesmo extrato não duplica crédito.
          </CardDescription>
        </div>
        <RegistrarMovimentoDialog onSucesso={invalidar} />
      </CardHeader>
      <CardContent>
        {isPending && <Skeleton className="h-24" />}
        {error && <p className="text-sm text-destructive">{mensagemDeErro(error)}</p>}
        {data && data.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Nenhum movimento registrado. Registre as linhas do extrato antes de baixar parcelas.
          </p>
        )}
        {data && data.length > 0 && (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Data</TableHead>
                  <TableHead className="text-right">Valor</TableHead>
                  <TableHead>Documento</TableHead>
                  <TableHead>Descrição</TableHead>
                  <TableHead>Situação</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((m) => (
                  <TableRow key={m.id}>
                    <TableCell className="tabular-nums">
                      {new Date(`${m.data_movimento}T00:00:00`).toLocaleDateString('pt-BR')}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {formatarMoeda(String(m.valor))}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{m.documento}</TableCell>
                    <TableCell className="text-muted-foreground">{m.descricao ?? '—'}</TableCell>
                    <TableCell>
                      {m.conciliado ? (
                        <Badge variant="outline" className="text-success">
                          Conciliado
                        </Badge>
                      ) : (
                        <Badge variant="outline">Disponível</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function RegistrarMovimentoDialog({ onSucesso }: { onSucesso: () => void }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState(new Date().toISOString().slice(0, 10))
  const [valor, setValor] = useState('')
  const [documento, setDocumento] = useState('')
  const [descricao, setDescricao] = useState('')

  const mutation = useMutation(postMovimentoApiCobrancaMovimentosPostMutation())

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate(
      {
        body: {
          data_movimento: data,
          valor,
          documento: documento.trim(),
          descricao: descricao.trim() || null,
        },
      },
      {
        onSuccess: () => {
          onSucesso()
          setOpen(false)
          mutation.reset()
          setValor('')
          setDocumento('')
          setDescricao('')
          toast.success('Movimento registrado.')
        },
      },
    )
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(aberto) => {
        setOpen(aberto)
        if (!aberto) mutation.reset()
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Landmark />
          Registrar movimento
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Registrar movimento bancário</DialogTitle>
          <DialogDescription>
            Uma linha do extrato. O <strong>documento</strong> é o identificador dela no banco
            (FITID, no OFX) e é único — é o que impede o mesmo crédito de baixar duas parcelas.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="mov-data">Data</Label>
              <Input
                id="mov-data"
                type="date"
                required
                value={data}
                onChange={(e) => setData(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="mov-valor">Valor (R$)</Label>
              <Input
                id="mov-valor"
                type="number"
                min="0.01"
                step="0.01"
                required
                value={valor}
                onChange={(e) => setValor(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="mov-documento">Documento</Label>
            <Input
              id="mov-documento"
              required
              value={documento}
              onChange={(e) => setDocumento(e.target.value)}
              placeholder="FITID ou identificador da linha no extrato"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="mov-descricao">Descrição (opcional)</Label>
            <Input
              id="mov-descricao"
              value={descricao}
              onChange={(e) => setDescricao(e.target.value)}
            />
          </div>

          {mutation.isError && (
            <p className="text-sm text-destructive">{mensagemDeErro(mutation.error)}</p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={!valor || !documento.trim() || mutation.isPending}>
              {mutation.isPending ? 'Registrando…' : 'Registrar'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
