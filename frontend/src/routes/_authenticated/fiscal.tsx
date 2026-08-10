import { useState, type FormEvent } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Calculator, Settings2, TriangleAlert } from 'lucide-react'
import { toast } from 'sonner'
import {
  getApuracoesApiFiscalApuracoesGetOptions,
  getApuracoesApiFiscalApuracoesGetQueryKey,
  getParametroVigenteApiFiscalParametrosVigenteGetOptions,
  getParametroVigenteApiFiscalParametrosVigenteGetQueryKey,
  postApurarApiFiscalApuracoesPostMutation,
  postParametroApiFiscalParametrosPostMutation,
} from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { formatarMoeda } from '@/lib/format'
import { formatarPercentual } from '@/lib/rotulos'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

export const Route = createFileRoute('/_authenticated/fiscal')({
  component: FiscalPage,
})

/** Fração (0,32) para exibição em percentual (32,00%). */
const pct = (v: string | number) => formatarPercentual(Number(v) * 100, 2)

/**
 * Apuração fiscal da receita da ESC — Lucro Presumido, trimestral.
 *
 * O IOF-crédito NÃO está aqui: segue bloqueado em parecer
 * jurídico-tributário, e nada nesta tela o antecipa.
 *
 * Nenhuma alíquota vem embutida. Sem parâmetro configurado, apurar é
 * recusado pelo banco (OC015) — devolver um número plausível calculado com
 * alíquota escolhida pelo sistema seria pior do que não devolver nada.
 */
function FiscalPage() {
  const queryClient = useQueryClient()
  const parametro = useQuery(getParametroVigenteApiFiscalParametrosVigenteGetOptions())
  const apuracoes = useQuery(getApuracoesApiFiscalApuracoesGetOptions())

  const configurado = !!parametro.data

  function invalidar() {
    queryClient.invalidateQueries({
      queryKey: getParametroVigenteApiFiscalParametrosVigenteGetQueryKey(),
    })
    queryClient.invalidateQueries({ queryKey: getApuracoesApiFiscalApuracoesGetQueryKey() })
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-heading text-2xl font-bold tracking-tight">Fiscal</h1>
        <div className="ml-auto flex gap-2">
          <ParametroDialog onSucesso={invalidar} />
          <ApurarDialog habilitado={configurado} onSucesso={invalidar} />
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Parâmetros vigentes</CardTitle>
          <CardDescription>
            Regime <strong>Lucro Presumido</strong>, apuração trimestral. Percentuais de presunção e
            alíquotas são matéria tributária e vêm daqui, não do código — uma apuração passada
            continua reproduzível porque os parâmetros usados ficam congelados dentro dela.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {parametro.isPending && <Skeleton className="h-24" />}
          {parametro.error && (
            <p className="text-sm text-destructive">{mensagemDeErro(parametro.error)}</p>
          )}
          {parametro.isSuccess && !configurado && (
            <p className="flex gap-2 text-sm">
              <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
              <span>
                Nenhum parâmetro configurado. A apuração fica bloqueada até que o contador informe
                presunção e alíquotas — o sistema não assume valores.
              </span>
            </p>
          )}
          {parametro.data && (
            <dl className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
              <Item rotulo="Vigente desde">
                {new Date(`${parametro.data.vigencia_inicio}T00:00:00`).toLocaleDateString('pt-BR')}
              </Item>
              <Item rotulo="Reconhecimento">
                {parametro.data.regime_reconhecimento === 'caixa' ? 'Caixa' : 'Competência'}
              </Item>
              <Item rotulo="Presunção IRPJ">{pct(parametro.data.percentual_presuncao_irpj)}</Item>
              <Item rotulo="Presunção CSLL">{pct(parametro.data.percentual_presuncao_csll)}</Item>
              <Item rotulo="IRPJ">{pct(parametro.data.aliquota_irpj)}</Item>
              <Item rotulo="CSLL">{pct(parametro.data.aliquota_csll)}</Item>
              <Item rotulo="Adicional IRPJ">
                {pct(parametro.data.adicional_irpj_aliquota)} acima de{' '}
                {formatarMoeda(String(parametro.data.adicional_irpj_limite))}
              </Item>
              <Item rotulo="PIS">{pct(parametro.data.aliquota_pis)}</Item>
              <Item rotulo="COFINS">{pct(parametro.data.aliquota_cofins)}</Item>
            </dl>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Apurações trimestrais</CardTitle>
          <CardDescription>
            A base é a <strong>receita de juros</strong>, tirada da agenda de parcelas — nunca a
            amortização, que devolve principal e não é resultado. Reapurar grava uma nova versão em
            vez de sobrescrever.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {apuracoes.isPending && <Skeleton className="h-24" />}
          {apuracoes.error && (
            <p className="text-sm text-destructive">{mensagemDeErro(apuracoes.error)}</p>
          )}
          {apuracoes.data && apuracoes.data.length === 0 && (
            <p className="text-sm text-muted-foreground">Nenhum trimestre apurado ainda.</p>
          )}
          {apuracoes.data && apuracoes.data.length > 0 && (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Período</TableHead>
                    <TableHead className="text-right">Receita de juros</TableHead>
                    <TableHead className="text-right">IRPJ</TableHead>
                    <TableHead className="text-right">Adicional</TableHead>
                    <TableHead className="text-right">CSLL</TableHead>
                    <TableHead className="text-right">PIS</TableHead>
                    <TableHead className="text-right">COFINS</TableHead>
                    <TableHead className="text-right">Total</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {apuracoes.data.map((a) => (
                    <TableRow key={a.id}>
                      <TableCell className="tabular-nums">
                        {a.trimestre}º tri/{a.ano}
                        {a.versao > 1 && (
                          <span className="ml-1 text-xs text-muted-foreground">
                            (retificada, v{a.versao})
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {formatarMoeda(String(a.receita_juros))}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {formatarMoeda(String(a.irpj))}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {formatarMoeda(String(a.adicional_irpj))}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {formatarMoeda(String(a.csll))}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {formatarMoeda(String(a.pis))}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {formatarMoeda(String(a.cofins))}
                      </TableCell>
                      <TableCell className="text-right font-mono font-medium tabular-nums">
                        {formatarMoeda(String(a.total_tributos))}
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

function Item({ rotulo, children }: { rotulo: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-border/50 py-1">
      <dt className="text-muted-foreground">{rotulo}</dt>
      <dd className="text-right font-mono tabular-nums">{children}</dd>
    </div>
  )
}

const CAMPOS = [
  { chave: 'percentual_presuncao_irpj', rotulo: 'Presunção IRPJ' },
  { chave: 'percentual_presuncao_csll', rotulo: 'Presunção CSLL' },
  { chave: 'aliquota_irpj', rotulo: 'Alíquota IRPJ' },
  { chave: 'aliquota_csll', rotulo: 'Alíquota CSLL' },
  { chave: 'adicional_irpj_aliquota', rotulo: 'Adicional IRPJ' },
  { chave: 'aliquota_pis', rotulo: 'Alíquota PIS' },
  { chave: 'aliquota_cofins', rotulo: 'Alíquota COFINS' },
] as const

function ParametroDialog({ onSucesso }: { onSucesso: () => void }) {
  const [open, setOpen] = useState(false)
  const [vigencia, setVigencia] = useState(new Date().toISOString().slice(0, 10))
  const [regime, setRegime] = useState<'caixa' | 'competencia'>('competencia')
  const [limite, setLimite] = useState('')
  const [valores, setValores] = useState<Record<string, string>>({})

  const mutation = useMutation(postParametroApiFiscalParametrosPostMutation())

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate(
      {
        body: {
          vigencia_inicio: vigencia,
          regime_reconhecimento: regime,
          adicional_irpj_limite: limite,
          ...Object.fromEntries(CAMPOS.map((c) => [c.chave, valores[c.chave] ?? '0'])),
        } as never,
      },
      {
        onSuccess: () => {
          onSucesso()
          setOpen(false)
          mutation.reset()
          toast.success('Parâmetros registrados.')
        },
      },
    )
  }

  const completo = CAMPOS.every((c) => valores[c.chave] !== undefined && valores[c.chave] !== '')

  return (
    <Dialog
      open={open}
      onOpenChange={(aberto) => {
        setOpen(aberto)
        if (!aberto) mutation.reset()
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline">
          <Settings2 />
          Configurar parâmetros
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Parâmetros fiscais</DialogTitle>
          <DialogDescription>
            Percentuais em <strong>fração</strong>: 0,32 para 32%. A API recusa valores acima de 1 —
            aceitar &quot;32&quot; e &quot;0,32&quot; no mesmo campo é como se escreve um erro de
            duas ordens de grandeza numa base tributária.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="vigencia">Vigente a partir de</Label>
              <Input
                id="vigencia"
                type="date"
                required
                value={vigencia}
                onChange={(e) => setVigencia(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="regime">Reconhecimento da receita</Label>
              <Select value={regime} onValueChange={(v) => setRegime(v as typeof regime)}>
                <SelectTrigger id="regime" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="competencia">Competência (vencimento)</SelectItem>
                  <SelectItem value="caixa">Caixa (data da baixa)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {CAMPOS.map((campo) => (
              <div key={campo.chave} className="space-y-2">
                <Label htmlFor={campo.chave}>{campo.rotulo}</Label>
                <Input
                  id={campo.chave}
                  type="number"
                  min="0"
                  max="1"
                  step="0.0001"
                  required
                  value={valores[campo.chave] ?? ''}
                  onChange={(e) =>
                    setValores((atual) => ({ ...atual, [campo.chave]: e.target.value }))
                  }
                />
              </div>
            ))}

            <div className="space-y-2">
              <Label htmlFor="limite">Limite do adicional (R$ por trimestre)</Label>
              <Input
                id="limite"
                type="number"
                min="0"
                step="0.01"
                required
                value={limite}
                onChange={(e) => setLimite(e.target.value)}
              />
            </div>
          </div>

          {mutation.isError && (
            <p className="text-sm text-destructive">{mensagemDeErro(mutation.error)}</p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={!completo || !limite || mutation.isPending}>
              {mutation.isPending ? 'Salvando…' : 'Salvar parâmetros'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function ApurarDialog({ habilitado, onSucesso }: { habilitado: boolean; onSucesso: () => void }) {
  const [open, setOpen] = useState(false)
  const agora = new Date()
  const [ano, setAno] = useState(String(agora.getFullYear()))
  const [trimestre, setTrimestre] = useState(String(Math.floor(agora.getMonth() / 3) + 1))

  const mutation = useMutation(postApurarApiFiscalApuracoesPostMutation())

  return (
    <Dialog
      open={open}
      onOpenChange={(aberto) => {
        setOpen(aberto)
        if (!aberto) mutation.reset()
      }}
    >
      <DialogTrigger asChild>
        <Button disabled={!habilitado} title={habilitado ? undefined : 'Configure os parâmetros'}>
          <Calculator />
          Apurar trimestre
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Apurar trimestre</DialogTitle>
          <DialogDescription>
            Reapurar um trimestre já apurado grava uma <strong>nova versão</strong> — a anterior
            permanece, porque editar uma apuração apagaria o que já foi declarado.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="ano">Ano</Label>
            <Input id="ano" type="number" value={ano} onChange={(e) => setAno(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="trimestre">Trimestre</Label>
            <Select value={trimestre} onValueChange={setTrimestre}>
              <SelectTrigger id="trimestre" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {['1', '2', '3', '4'].map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}º trimestre
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {mutation.isError && (
          <p className="text-sm text-destructive">{mensagemDeErro(mutation.error)}</p>
        )}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => setOpen(false)}>
            Cancelar
          </Button>
          <Button
            disabled={mutation.isPending}
            onClick={() =>
              mutation.mutate(
                { body: { ano: Number(ano), trimestre: Number(trimestre) } },
                {
                  onSuccess: (resultado) => {
                    onSucesso()
                    setOpen(false)
                    toast.success(
                      `${resultado.trimestre}º tri/${resultado.ano} apurado: ${formatarMoeda(
                        String(resultado.total_tributos),
                      )} em tributos.`,
                    )
                  },
                },
              )
            }
          >
            {mutation.isPending ? 'Apurando…' : 'Apurar'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
