import { useQuery } from '@tanstack/react-query'
import { getParcelasApiOperacoesOperacaoIdParcelasGetOptions } from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { formatarMoeda } from '@/lib/format'
import { BaixarParcelaDialog } from '@/components/baixar-parcela-dialog'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

/**
 * Agenda de amortização emitida na ativação.
 *
 * Os valores vêm calculados e somados pelo banco (`fn_gerar_parcelas`), não
 * recalculados aqui: a régua de arredondamento — resíduo na última parcela,
 * para que a soma feche exatamente no principal — mora numa camada só. Se a
 * tela refizesse a conta, bastaria um `toFixed` diferente para mostrar um
 * total que não é o que se cobra.
 */
export function AgendaParcelas({
  operacaoId,
  onBaixa,
}: {
  operacaoId: string
  onBaixa: () => void
}) {
  const { data, error, isPending } = useQuery(
    getParcelasApiOperacoesOperacaoIdParcelasGetOptions({ path: { operacao_id: operacaoId } }),
  )

  return (
    <Card>
      <CardHeader>
        <CardTitle>Agenda de parcelas</CardTitle>
        <CardDescription>
          Emitida pelo banco na ativação e imutável desde então — valores e vencimentos não podem
          ser alterados (OC009). Só a baixa de recebimento muda o status.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isPending && <Skeleton className="h-48" />}
        {error && <p className="text-sm text-destructive">{mensagemDeErro(error)}</p>}
        {data && data.parcelas.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Nenhuma parcela ainda — a agenda é emitida no momento da ativação.
          </p>
        )}
        {data && data.parcelas.length > 0 && (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">#</TableHead>
                  <TableHead>Vencimento</TableHead>
                  <TableHead className="text-right">Amortização</TableHead>
                  <TableHead className="text-right">Juros</TableHead>
                  <TableHead className="text-right">Parcela</TableHead>
                  <TableHead className="text-right">Saldo devedor</TableHead>
                  <TableHead>Situação</TableHead>
                  <TableHead className="text-right">Baixa</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.parcelas.map((p) => (
                  <TableRow key={p.numero}>
                    <TableCell className="font-mono tabular-nums">{p.numero}</TableCell>
                    <TableCell className="tabular-nums">
                      {new Date(`${p.vencimento}T00:00:00`).toLocaleDateString('pt-BR')}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {formatarMoeda(String(p.valor_amortizacao))}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {formatarMoeda(String(p.valor_juros))}
                    </TableCell>
                    <TableCell className="text-right font-mono font-medium tabular-nums">
                      {formatarMoeda(String(p.valor_total))}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums text-muted-foreground">
                      {formatarMoeda(String(p.saldo_devedor_pos))}
                    </TableCell>
                    <TableCell>
                      {p.status === 'aberta' ? (
                        <Badge variant="outline">Em aberto</Badge>
                      ) : (
                        <Badge variant="outline" className="text-success">
                          Paga
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {p.status === 'aberta' ? (
                        <BaixarParcelaDialog
                          parcelaId={p.id}
                          numero={p.numero}
                          valorTotal={String(p.valor_total)}
                          onSucesso={onBaixa}
                        />
                      ) : (
                        // O documento do extrato fica visível: baixa sem
                        // origem exibida é indistinguível de um "marcar como
                        // pago" sem lastro.
                        <span className="font-mono text-xs text-muted-foreground">
                          {p.movimento_documento ?? '—'}
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
              <TableFooter>
                <TableRow>
                  <TableCell colSpan={2}>Totais ({data.sistema_amortizacao})</TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {formatarMoeda(String(data.total_amortizacao))}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {formatarMoeda(String(data.total_juros))}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {formatarMoeda(String(data.total_geral))}
                  </TableCell>
                  <TableCell colSpan={3} />
                </TableRow>
              </TableFooter>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
