import { AlertTriangle, CheckCircle2, Clock } from 'lucide-react'
import type { ParcelaPortalOut } from '@/api/generated/types.gen'
import { formatarDataIso } from '@/components/identificacao/mensagens'
import { diasDeAtraso } from '@/lib/parcelas'
import { formatarMoeda } from '@/lib/format'
import { cn } from '@/lib/utils'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

/**
 * A agenda de parcelas do portal em DUAS formas do mesmo dado: cartões
 * empilhados no celular, tabela do sm para cima.
 *
 * Não é a tabela com overflow-x: uma agenda de 24 linhas rolando de lado num
 * celular esconde exatamente a coluna que o tomador procura (situação). O
 * cartão põe vencimento, valor e situação na mesma dobra, sem rolagem
 * horizontal. As duas formas leem os MESMOS campos — divergir uma da outra é
 * impossível por construção.
 */
export function ListaParcelas({ parcelas, hoje }: { parcelas: ParcelaPortalOut[]; hoje?: Date }) {
  return (
    <>
      {/* Celular: cartões */}
      <ul className="space-y-2 sm:hidden">
        {parcelas.map((p) => (
          <li
            key={p.numero}
            className="flex items-center justify-between gap-3 rounded-lg border border-border p-3"
          >
            <div>
              <p className="text-sm font-medium">Parcela {p.numero}</p>
              <p className="text-sm text-muted-foreground tabular-nums">
                {formatarDataIso(p.vencimento)}
              </p>
            </div>
            <div className="text-right">
              <p className="font-mono text-sm font-medium tabular-nums">
                {formatarMoeda(p.valor_total)}
              </p>
              <SituacaoParcela parcela={p} hoje={hoje} />
            </div>
          </li>
        ))}
      </ul>

      {/* Telas maiores: tabela */}
      <div className="hidden overflow-x-auto rounded-lg border border-border sm:block">
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
            {parcelas.map((p) => (
              <TableRow key={p.numero}>
                <TableCell className="tabular-nums">{p.numero}</TableCell>
                <TableCell className="tabular-nums">{formatarDataIso(p.vencimento)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {formatarMoeda(p.valor_total)}
                </TableCell>
                <TableCell>
                  <SituacaoParcela parcela={p} hoje={hoje} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  )
}

/**
 * Paga (com a data em que a ESC deu por paga) / em atraso (com ícone e cor de
 * alerta) / em aberto. Ícone + texto sempre juntos: cor sozinha não comunica.
 */
function SituacaoParcela({ parcela, hoje }: { parcela: ParcelaPortalOut; hoje?: Date }) {
  if (parcela.status === 'paga') {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm text-success">
        <CheckCircle2 className="size-4 shrink-0" aria-hidden />
        Paga{parcela.pago_em ? ` em ${formatarDataIso(parcela.pago_em)}` : ''}
      </span>
    )
  }

  const atraso = diasDeAtraso(parcela.vencimento, hoje)
  const emAtraso = atraso > 0
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 text-sm',
        emAtraso ? 'text-destructive' : 'text-muted-foreground',
      )}
    >
      {emAtraso ? (
        <AlertTriangle className="size-4 shrink-0" aria-hidden />
      ) : (
        <Clock className="size-4 shrink-0" aria-hidden />
      )}
      {emAtraso ? 'Em atraso' : 'Em aberto'}
    </span>
  )
}
