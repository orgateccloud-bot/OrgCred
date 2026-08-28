import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeft, CheckCircle2, Clock, FileCheck2 } from 'lucide-react'
import {
  getContratoApiPortalOperacoesOperacaoIdContratoGetOptions,
  getParcelasApiPortalOperacoesOperacaoIdParcelasGetOptions,
} from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { formatarDataIso, hashAbreviado } from '@/components/identificacao/mensagens'
import { formatarMoeda } from '@/lib/format'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

export const Route = createFileRoute('/portal/operacoes/$id')({
  component: OperacaoDoTomador,
})

function OperacaoDoTomador() {
  const { id } = Route.useParams()
  const agenda = useQuery(
    getParcelasApiPortalOperacoesOperacaoIdParcelasGetOptions({ path: { operacao_id: id } }),
  )
  const contrato = useQuery(
    getContratoApiPortalOperacoesOperacaoIdContratoGetOptions({ path: { operacao_id: id } }),
  )

  return (
    <div className="space-y-6">
      <Link
        to="/portal"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        Voltar
      </Link>

      <section className="space-y-3">
        <h1 className="text-xl font-semibold">Agenda de pagamento</h1>

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
            <div className="overflow-x-auto rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-16">Parcela</TableHead>
                    <TableHead>Vencimento</TableHead>
                    <TableHead className="text-right">Valor</TableHead>
                    <TableHead>Situação</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {agenda.data.parcelas.map((p) => (
                    <TableRow key={p.numero}>
                      <TableCell className="tabular-nums">{p.numero}</TableCell>
                      <TableCell className="tabular-nums">
                        {formatarDataIso(p.vencimento)}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {formatarMoeda(p.valor_total)}
                      </TableCell>
                      <TableCell>
                        {p.status === 'paga' ? (
                          <span className="inline-flex items-center gap-1.5 text-sm text-success">
                            <CheckCircle2 className="size-4" aria-hidden />
                            Paga
                            {p.pago_em ? ` em ${formatarDataIso(p.pago_em)}` : ''}
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
                            <Clock className="size-4" aria-hidden />
                            Em aberto
                          </span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <p className="text-right text-sm">
              Total da agenda:{' '}
              <strong className="font-mono tabular-nums">
                {formatarMoeda(agenda.data.total_geral)}
              </strong>
            </p>
          </>
        )}
      </section>

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
