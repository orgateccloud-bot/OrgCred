import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from '@tanstack/react-table'
import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, ArrowUpDown, Inbox, Plus, Search } from 'lucide-react'
import { getOperacoesApiOperacoesGetOptions } from '@/api/generated/@tanstack/react-query.gen'
import type { OperacaoListItemOut } from '@/api/generated/types.gen'
import { mensagemDeErro } from '@/api/errors'
import { formatarMoeda } from '@/lib/format'
import { StatusOperacaoBadge } from '@/components/status-operacao-badge'
import { AtivarOperacaoDialog } from '@/components/ativar-operacao-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
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

export const Route = createFileRoute('/_authenticated/operacoes/')({
  component: OperacoesListPage,
})

const STATUS_OPCOES = [
  'proposta',
  'registrada',
  'ativa',
  'liquidada',
  'inadimplente',
  'renegociada',
  'cancelada',
] as const

const columnHelper = createColumnHelper<OperacaoListItemOut>()

const columns = [
  columnHelper.accessor('tomador_razao_social', { header: 'Tomador' }),
  columnHelper.accessor('tipo', { header: 'Tipo' }),
  columnHelper.accessor('valor_principal', {
    header: 'Valor',
    cell: (info) => (
      <span className="font-mono tabular-nums">{formatarMoeda(info.getValue())}</span>
    ),
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
  const { data, error, isPending } = useQuery(getOperacoesApiOperacoesGetOptions())
  const [sorting, setSorting] = useState<SortingState>([{ id: 'created_at', desc: true }])
  const [busca, setBusca] = useState('')
  const [statusFiltro, setStatusFiltro] = useState<string>('todos')

  const filtradas = useMemo(() => {
    let rows = data ?? []
    if (statusFiltro !== 'todos') rows = rows.filter((op) => op.status === statusFiltro)
    if (busca.trim()) {
      const q = busca.trim().toLowerCase()
      rows = rows.filter((op) => op.tomador_razao_social.toLowerCase().includes(q))
    }
    return rows
  }, [data, busca, statusFiltro])

  const table = useReactTable({
    data: filtradas,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  })

  return (
    <div className="p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Operações</h1>
        <Button asChild>
          <Link to="/operacoes/nova">
            <Plus />
            Nova operação
          </Link>
        </Button>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <div className="relative">
          <Search
            className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            placeholder="Buscar por tomador…"
            aria-label="Buscar por tomador"
            value={busca}
            onChange={(event) => setBusca(event.target.value)}
            className="w-64 pl-8"
          />
        </div>
        <Select value={statusFiltro} onValueChange={setStatusFiltro}>
          <SelectTrigger className="w-44" aria-label="Filtrar por status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="todos">Todos os status</SelectItem>
            {STATUS_OPCOES.map((s) => (
              <SelectItem key={s} value={s}>
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {data && (
          <span className="text-sm text-muted-foreground">
            {filtradas.length} de {data.length}
          </span>
        )}
      </div>

      {isPending && (
        <div className="mt-4 space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      )}
      {error && <p className="mt-4 text-destructive">{mensagemDeErro(error)}</p>}

      {data && data.length === 0 && (
        <div className="mt-10 flex flex-col items-center gap-3 text-center">
          <Inbox className="size-8 text-muted-foreground" aria-hidden />
          <p className="text-muted-foreground">Nenhuma operação cadastrada ainda.</p>
          <Button asChild variant="outline">
            <Link to="/operacoes/nova">Criar a primeira operação</Link>
          </Button>
        </div>
      )}

      {data && data.length > 0 && (
        <div className="mt-4 rounded-lg border border-border">
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => {
                    const dir = header.column.getIsSorted()
                    const podeOrdenar = header.column.getCanSort()
                    return (
                      <TableHead
                        key={header.id}
                        aria-sort={
                          dir === 'asc' ? 'ascending' : dir === 'desc' ? 'descending' : 'none'
                        }
                      >
                        {podeOrdenar ? (
                          <button
                            type="button"
                            className="inline-flex items-center gap-1 select-none"
                            onClick={header.column.getToggleSortingHandler()}
                          >
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {dir === 'asc' ? (
                              <ArrowUp className="size-3.5" aria-hidden />
                            ) : dir === 'desc' ? (
                              <ArrowDown className="size-3.5" aria-hidden />
                            ) : (
                              <ArrowUpDown className="size-3.5 opacity-40" aria-hidden />
                            )}
                          </button>
                        ) : (
                          flexRender(header.column.columnDef.header, header.getContext())
                        )}
                      </TableHead>
                    )
                  })}
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
              {table.getRowModel().rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={columns.length} className="text-center text-muted-foreground">
                    Nenhuma operação corresponde aos filtros.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
