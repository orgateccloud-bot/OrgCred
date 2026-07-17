import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from '@tanstack/react-table'
import { useState } from 'react'
import { getOperacoesOperacoesGetOptions } from '@/api/generated/@tanstack/react-query.gen'
import type { OperacaoListItemOut } from '@/api/generated/types.gen'
import { mensagemDeErro } from '@/api/errors'
import { formatarMoeda } from '@/lib/format'
import { StatusOperacaoBadge } from '@/components/status-operacao-badge'
import { AtivarOperacaoDialog } from '@/components/ativar-operacao-dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

export const Route = createFileRoute('/_authenticated/operacoes/')({
  component: OperacoesListPage,
})

const columnHelper = createColumnHelper<OperacaoListItemOut>()

const columns = [
  columnHelper.accessor('tomador_razao_social', { header: 'Tomador' }),
  columnHelper.accessor('tipo', { header: 'Tipo' }),
  columnHelper.accessor('valor_principal', {
    header: 'Valor',
    cell: (info) => formatarMoeda(info.getValue()),
  }),
  columnHelper.accessor('numero_parcelas', { header: 'Parcelas' }),
  columnHelper.accessor('status', {
    header: 'Status',
    cell: (info) => <StatusOperacaoBadge status={info.getValue()} />,
  }),
  columnHelper.accessor('created_at', {
    header: 'Criada em',
    cell: (info) => new Date(info.getValue()).toLocaleString('pt-BR'),
  }),
  columnHelper.display({
    id: 'acoes',
    header: '',
    cell: (info) =>
      info.row.original.status === 'registrada' ? (
        <AtivarOperacaoDialog
          operacaoId={info.row.original.id}
          valorPrincipal={info.row.original.valor_principal}
        />
      ) : null,
  }),
]

function OperacoesListPage() {
  const { data, error, isPending } = useQuery(getOperacoesOperacoesGetOptions())
  const [sorting, setSorting] = useState<SortingState>([{ id: 'created_at', desc: true }])

  const table = useReactTable({
    data: data ?? [],
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold">Operações</h1>

      {isPending && <p className="mt-4 text-muted-foreground">Carregando…</p>}
      {error && <p className="mt-4 text-destructive">{mensagemDeErro(error)}</p>}

      {data && data.length === 0 && (
        <p className="mt-4 text-muted-foreground">Nenhuma operação cadastrada.</p>
      )}

      {data && data.length > 0 && (
        <div className="mt-4 rounded-lg border border-border">
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <TableHead
                      key={header.id}
                      className="cursor-pointer select-none"
                      onClick={header.column.getToggleSortingHandler()}
                    >
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {{ asc: ' ▲', desc: ' ▼' }[header.column.getIsSorted() as string] ?? ''}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {cell.column.id === 'tomador_razao_social' ? (
                        <Link
                          to="/operacoes/$id"
                          params={{ id: row.original.id }}
                          className="text-primary hover:underline"
                        >
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </Link>
                      ) : (
                        flexRender(cell.column.columnDef.cell, cell.getContext())
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
