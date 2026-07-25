import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Banknote, PiggyBank, ShieldAlert, Vault, Wallet } from 'lucide-react'
import { Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, XAxis, YAxis } from 'recharts'
import {
  getAuditoriaApiAuditoriaGetOptions,
  getCapitalSnapshotApiCapitalSnapshotGetOptions,
  getOperacoesApiOperacoesGetOptions,
} from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { formatarMoeda } from '@/lib/format'
import { narrativa } from '@/lib/ledger'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { Skeleton } from '@/components/ui/skeleton'

export const Route = createFileRoute('/_authenticated/')({
  component: DashboardPage,
})

function DashboardPage() {
  const snapshot = useQuery({
    ...getCapitalSnapshotApiCapitalSnapshotGetOptions(),
    refetchInterval: 20_000,
  })
  const operacoes = useQuery(getOperacoesApiOperacoesGetOptions())
  const auditoria = useQuery(getAuditoriaApiAuditoriaGetOptions())

  const carregando = snapshot.isPending || operacoes.isPending || auditoria.isPending
  const erro = snapshot.error ?? operacoes.error ?? auditoria.error

  if (carregando) {
    return (
      <div className="grid gap-4 p-6 md:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-28 w-full" />
        ))}
        <Skeleton className="h-72 md:col-span-2 xl:col-span-3" />
        <Skeleton className="h-72" />
      </div>
    )
  }

  if (erro) {
    return <p className="p-6 text-destructive">{mensagemDeErro(erro)}</p>
  }
  if (!snapshot.data || !operacoes.data || !auditoria.data) return null

  const total = Number(snapshot.data.total)
  const comprometido = Number(snapshot.data.comprometido)
  const utilizacaoPct = total > 0 ? Math.min(100, (comprometido / total) * 100) : 0
  const ativas = operacoes.data.filter((op) => op.status === 'ativa')

  return (
    <div className="space-y-6 p-6">
      {total === 0 && (
        <BannerCritico
          icone={AlertTriangle}
          titulo="Teto de capital em R$ 0,00"
          descricao="O capital social ainda não foi integralizado (LC 167/2019, art. 2º). Nenhuma operação pode ser ativada até o registro do aporte."
        />
      )}
      {!auditoria.data.integro && (
        <BannerCritico
          icone={ShieldAlert}
          titulo="Cadeia de auditoria quebrada"
          descricao="A verificação de integridade do ledger detectou inconsistência na hash-chain. Trate como incidente: nenhum número abaixo é confiável até apuração."
          to="/auditoria"
        />
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          icone={Wallet}
          rotulo="Capital disponível"
          valor={formatarMoeda(snapshot.data.disponivel)}
          destaque
        />
        <KpiCard
          icone={PiggyBank}
          rotulo="Comprometido"
          valor={formatarMoeda(snapshot.data.comprometido)}
          detalhe={`${utilizacaoPct.toFixed(1)}% do teto`}
          progresso={utilizacaoPct}
        />
        <KpiCard
          icone={Vault}
          rotulo="Teto de capital"
          valor={formatarMoeda(snapshot.data.total)}
        />
        <KpiCard
          icone={Banknote}
          rotulo="Operações ativas"
          valor={String(ativas.length)}
          detalhe={`${operacoes.data.length} no total`}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <EvolucaoSaldoCard eventos={auditoria.data.eventos} className="xl:col-span-2" />
        <ComposicaoPorTipoCard operacoes={ativas} />
      </div>

      <AtividadeRecenteCard eventos={auditoria.data.eventos} />
    </div>
  )
}

function BannerCritico({
  icone: Icone,
  titulo,
  descricao,
  to,
}: {
  icone: typeof AlertTriangle
  titulo: string
  descricao: string
  to?: string
}) {
  const conteudo = (
    <div className="flex items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4">
      <Icone className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden />
      <div>
        <p className="font-medium text-destructive">{titulo}</p>
        <p className="mt-0.5 text-sm text-muted-foreground">{descricao}</p>
      </div>
    </div>
  )
  return to ? <Link to={to}>{conteudo}</Link> : conteudo
}

function KpiCard({
  icone: Icone,
  rotulo,
  valor,
  detalhe,
  progresso,
  destaque = false,
}: {
  icone: typeof Wallet
  rotulo: string
  valor: string
  detalhe?: string
  progresso?: number
  destaque?: boolean
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardDescription>{rotulo}</CardDescription>
        <Icone className="size-4 text-muted-foreground" aria-hidden />
      </CardHeader>
      <CardContent>
        <p
          className={`font-mono text-2xl font-semibold tabular-nums ${destaque ? 'text-primary' : ''}`}
        >
          {valor}
        </p>
        {detalhe && <p className="mt-1 text-xs text-muted-foreground">{detalhe}</p>}
        {progresso !== undefined && (
          <div
            className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-valuenow={Math.round(progresso)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Utilização do teto de capital"
          >
            <div
              className="h-full rounded-full bg-primary transition-[width]"
              style={{ width: `${progresso}%` }}
            />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

const configSaldo = {
  saldo: { label: 'Saldo disponível', color: 'var(--chart-1)' },
} satisfies ChartConfig

function EvolucaoSaldoCard({
  eventos,
  className,
}: {
  eventos: Array<{ created_at: string; saldo_disponivel_pos: string }>
  className?: string
}) {
  // Ledger vem do backend em ordem de cadeia (mais recente primeiro ou não —
  // ordenar por data garante o eixo X correto independente disso).
  const serie = [...eventos]
    .sort((a, b) => a.created_at.localeCompare(b.created_at))
    .map((e) => ({
      quando: new Date(e.created_at).toLocaleDateString('pt-BR', {
        day: '2-digit',
        month: '2-digit',
      }),
      saldo: Number(e.saldo_disponivel_pos),
    }))

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Evolução do saldo disponível</CardTitle>
        <CardDescription>Reconstruída do ledger de capital (hash-chain)</CardDescription>
      </CardHeader>
      <CardContent>
        {serie.length < 2 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            Ainda não há eventos suficientes no ledger para desenhar a série.
          </p>
        ) : (
          <ChartContainer config={configSaldo} className="h-64 w-full">
            <AreaChart data={serie} margin={{ left: 12, right: 12 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="quando" tickLine={false} axisLine={false} tickMargin={8} />
              <YAxis
                tickLine={false}
                axisLine={false}
                tickMargin={8}
                width={80}
                tickFormatter={(v: number) =>
                  v.toLocaleString('pt-BR', {
                    notation: 'compact',
                    style: 'currency',
                    currency: 'BRL',
                  })
                }
              />
              <ChartTooltip
                content={
                  <ChartTooltipContent formatter={(value) => formatarMoeda(String(value))} />
                }
              />
              <Area
                dataKey="saldo"
                type="monotone"
                fill="var(--color-saldo)"
                fillOpacity={0.15}
                stroke="var(--color-saldo)"
                strokeWidth={2}
              />
            </AreaChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  )
}

const CORES_TIPO = [
  'var(--chart-1)',
  'var(--chart-2)',
  'var(--chart-3)',
  'var(--chart-4)',
  'var(--chart-5)',
]

function ComposicaoPorTipoCard({
  operacoes,
}: {
  operacoes: Array<{ tipo: string; valor_principal: string }>
}) {
  const porTipo = new Map<string, number>()
  for (const op of operacoes) {
    porTipo.set(op.tipo, (porTipo.get(op.tipo) ?? 0) + Number(op.valor_principal))
  }
  const dados = [...porTipo.entries()].map(([tipo, valor]) => ({ tipo, valor }))
  const config = Object.fromEntries(
    dados.map((d, i) => [d.tipo, { label: d.tipo, color: CORES_TIPO[i % CORES_TIPO.length] }]),
  ) satisfies ChartConfig

  return (
    <Card>
      <CardHeader>
        <CardTitle>Comprometido por tipo</CardTitle>
        <CardDescription>Somente operações ativas</CardDescription>
      </CardHeader>
      <CardContent>
        {dados.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            Nenhuma operação ativa no momento.
          </p>
        ) : (
          <ChartContainer config={config} className="mx-auto h-64 w-full">
            <PieChart>
              <ChartTooltip
                content={
                  <ChartTooltipContent formatter={(value) => formatarMoeda(String(value))} />
                }
              />
              <Pie data={dados} dataKey="valor" nameKey="tipo" innerRadius={55} strokeWidth={2}>
                {dados.map((d, i) => (
                  <Cell key={d.tipo} fill={CORES_TIPO[i % CORES_TIPO.length]} />
                ))}
              </Pie>
            </PieChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  )
}

function AtividadeRecenteCard({ eventos }: { eventos: Array<Parameters<typeof narrativa>[0]> }) {
  const recentes = [...eventos].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 5)

  return (
    <Card>
      <CardHeader>
        <CardTitle>Atividade recente</CardTitle>
        <CardDescription>Últimos eventos do ledger de capital</CardDescription>
      </CardHeader>
      <CardContent>
        {recentes.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nenhum evento registrado ainda.</p>
        ) : (
          <ul className="space-y-2">
            {recentes.map((evento) => (
              <li key={evento.id} className="rounded-lg border border-border p-3 text-sm">
                {narrativa(evento)}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
