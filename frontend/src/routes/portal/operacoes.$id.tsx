import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeft, FileCheck2 } from 'lucide-react'
import {
  getContratoApiPortalOperacoesOperacaoIdContratoGetOptions,
  getOperacoesApiPortalOperacoesGetOptions,
  getParcelasApiPortalOperacoesOperacaoIdParcelasGetOptions,
} from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { formatarDataIso, hashAbreviado } from '@/components/identificacao/mensagens'
import { ListaParcelas } from '@/components/portal/lista-parcelas'
import { ProgressoParcelas } from '@/components/portal/progresso-parcelas'
import { ProximaParcelaCard } from '@/components/portal/proxima-parcela'
import { StatusOperacaoBadge } from '@/components/status-operacao-badge'
import { Skeleton } from '@/components/ui/skeleton'
import { formatarMoeda } from '@/lib/format'
import { proximaParcelaEmAberto } from '@/lib/parcelas'
import { formatarPercentual, rotuloTipo } from '@/lib/rotulos'

export const Route = createFileRoute('/portal/operacoes/$id')({
  component: OperacaoDoTomador,
})

function OperacaoDoTomador() {
  const { id } = Route.useParams()
  // A MESMA lista da home, não um GET /operacoes/{id} que não existe no
  // portal: o React Query serve do cache quando o tomador veio da home, e um
  // acesso direto por URL busca a lista inteira — que é dele, e é pequena.
  const operacoes = useQuery(getOperacoesApiPortalOperacoesGetOptions())
  const agenda = useQuery(
    getParcelasApiPortalOperacoesOperacaoIdParcelasGetOptions({ path: { operacao_id: id } }),
  )
  const contrato = useQuery(
    getContratoApiPortalOperacoesOperacaoIdContratoGetOptions({ path: { operacao_id: id } }),
  )

  const operacao = operacoes.data?.find((op) => op.id === id)
  const proxima = agenda.data ? proximaParcelaEmAberto(agenda.data.parcelas) : null

  return (
    <div className="space-y-6">
      <Link
        to="/portal"
        className="inline-flex min-h-11 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        Voltar
      </Link>

      {/* ---- Resumo: o que é esta operação -------------------------------- */}
      <section>
        {operacoes.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : operacao ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold">{rotuloTipo(operacao.tipo)}</h1>
              <StatusOperacaoBadge status={operacao.status} />
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              {formatarMoeda(operacao.valor_principal)} · juros de{' '}
              {formatarPercentual(Number(operacao.taxa_juros_mensal))} a.m. ·{' '}
              {operacao.sistema_amortizacao} · {operacao.numero_parcelas} parcelas
            </p>
            <div className="mt-3 space-y-1.5">
              <ProgressoParcelas pagas={operacao.parcelas_pagas} total={operacao.numero_parcelas} />
              <div className="flex items-baseline justify-between text-sm">
                <span className="text-muted-foreground">
                  {operacao.parcelas_pagas}/{operacao.numero_parcelas} pagas
                </span>
                <span>
                  Em aberto:{' '}
                  <strong className="font-mono tabular-nums">
                    {formatarMoeda(operacao.saldo_em_aberto)}
                  </strong>
                </span>
              </div>
            </div>
          </>
        ) : (
          // A lista carregou e a operação não está nela: para o tomador, ela
          // não existe (mesma resposta do backend, 404 — nunca 403).
          <h1 className="text-xl font-semibold">Agenda de pagamento</h1>
        )}
      </section>

      {/* ---- Próxima parcela: o número que ele veio ver ------------------- */}
      {proxima && <ProximaParcelaCard parcela={proxima} />}

      {/* ---- Agenda completa ---------------------------------------------- */}
      <section className="space-y-3">
        <h2 className="text-sm font-medium text-muted-foreground">Agenda de pagamento</h2>

        {agenda.isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : agenda.isError ? (
          <p
            role="alert"
            className="flex gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm"
          >
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
            {mensagemDeErro(agenda.error)}
          </p>
        ) : !agenda.data || agenda.data.parcelas.length === 0 ? (
          <p className="rounded-lg border border-border p-6 text-sm text-muted-foreground">
            Esta operação ainda não teve a agenda de parcelas emitida.
          </p>
        ) : (
          <>
            <ListaParcelas parcelas={agenda.data.parcelas} />
            <p className="text-right text-sm">
              Total da agenda:{' '}
              <strong className="font-mono tabular-nums">
                {formatarMoeda(agenda.data.total_geral)}
              </strong>
            </p>
          </>
        )}
      </section>

      {/* ---- Contrato: a prova, não o corpo (ver app/routers/portal.py) --- */}
      <section className="space-y-3">
        <h2 className="text-sm font-medium text-muted-foreground">Contrato</h2>
        {contrato.isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : contrato.data ? (
          <div className="space-y-2 rounded-lg border border-border p-4 text-sm">
            <p className="flex items-center gap-2 font-medium">
              <FileCheck2 className="size-4 text-primary" aria-hidden />
              Instrumento emitido (versão {contrato.data.versao})
            </p>
            <p className="text-muted-foreground">
              Emitido em {formatarDataIso(contrato.data.emitido_em)}. Confira que a via que você
              recebeu tem esta mesma impressão digital:
            </p>
            {/* O sha256 é a prova de que a via do tomador é a que a ESC emitiu.
                Abreviado no mesmo ponto usado na evidência de identificação,
                para o operador conferir de olho sempre no mesmo lugar. O título
                traz o hash inteiro para conferência exata. */}
            <p
              className="font-mono text-xs break-all text-muted-foreground"
              title={contrato.data.sha256}
            >
              {hashAbreviado(contrato.data.sha256)}
            </p>
          </div>
        ) : (
          <p className="rounded-lg border border-border p-4 text-sm text-muted-foreground">
            O contrato desta operação ainda não foi emitido.
          </p>
        )}
      </section>
    </div>
  )
}
