import { createFileRoute } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { CheckCircle2, ShieldAlert } from 'lucide-react'
import { getAuditoriaApiAuditoriaGetOptions } from '@/api/generated/@tanstack/react-query.gen'
import type { LedgerEventoOut } from '@/api/generated/types.gen'
import { mensagemDeErro } from '@/api/errors'
import { formatarMoeda } from '@/lib/format'
import { narrativa } from '@/lib/ledger'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
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

export const Route = createFileRoute('/_authenticated/auditoria')({
  component: AuditoriaPage,
})

function AuditoriaPage() {
  const { data, error, isPending } = useQuery(getAuditoriaApiAuditoriaGetOptions())
  const [mostrarTecnico, setMostrarTecnico] = useState(false)
  const [tipoFiltro, setTipoFiltro] = useState('todos')

  const tiposDisponiveis = data ? Array.from(new Set(data.eventos.map((e) => e.evento_tipo))) : []
  const eventosFiltrados = data
    ? tipoFiltro === 'todos'
      ? data.eventos
      : data.eventos.filter((e) => e.evento_tipo === tipoFiltro)
    : []

  return (
    <div className="p-6">
      <div className="flex items-center justify-between">
        <h1 className="font-heading text-2xl font-bold tracking-tight">Auditoria</h1>
        {data && <IntegridadeBadge integro={data.integro} />}
      </div>

      {isPending && (
        <div className="mt-4 space-y-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      )}
      {error && <p className="mt-4 text-destructive">{mensagemDeErro(error)}</p>}

      {data && data.eventos.length === 0 && (
        <p className="mt-4 text-muted-foreground">Nenhum evento registrado ainda.</p>
      )}

      {data && data.eventos.length > 0 && (
        <>
          <div className="mt-4 flex items-center gap-3">
            <Select value={tipoFiltro} onValueChange={setTipoFiltro}>
              <SelectTrigger className="w-56" aria-label="Filtrar por tipo de evento">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="todos">Todos os tipos</SelectItem>
                {tiposDisponiveis.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className="text-sm text-muted-foreground">
              {eventosFiltrados.length} de {data.eventos.length}
            </span>
          </div>

          <ul className="mt-4 space-y-2">
            {eventosFiltrados.map((evento) => (
              <li key={evento.id} className="rounded-lg border border-border p-3 text-sm">
                {narrativa(evento)}
              </li>
            ))}
          </ul>

          <Button
            variant="outline"
            size="sm"
            className="mt-4"
            onClick={() => setMostrarTecnico((v) => !v)}
          >
            {mostrarTecnico ? 'Ocultar' : 'Ver'} detalhes técnicos (hash-chain)
          </Button>

          {mostrarTecnico && (
            <div className="mt-4 rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Evento</TableHead>
                    <TableHead>Saldo pós-evento</TableHead>
                    <TableHead>prev_hash</TableHead>
                    <TableHead>current_hash</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.eventos.map((evento) => (
                    <TableRow key={evento.id}>
                      <TableCell className="font-mono text-xs">{evento.evento_tipo}</TableCell>
                      <TableCell className="font-mono text-xs">
                        {formatarMoeda(evento.saldo_disponivel_pos)}
                      </TableCell>
                      <TableCell className="max-w-32 truncate font-mono text-xs">
                        {evento.prev_hash ?? '—'}
                      </TableCell>
                      <TableCell className="max-w-32 truncate font-mono text-xs">
                        {evento.current_hash ?? '—'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              {data.quebras.length > 0 && (
                <div className="border-t border-border p-3">
                  <p className="text-sm font-medium text-destructive">
                    {data.quebras.length} quebra(s) detectada(s) na cadeia:
                  </p>
                  <ul className="mt-1 list-disc pl-5 text-xs text-destructive">
                    {data.quebras.map((quebra) => (
                      <li key={quebra.id}>
                        {quebra.id}: {quebra.motivo}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function IntegridadeBadge({ integro }: { integro: boolean }) {
  return integro ? (
    <Badge variant="outline" className="gap-1 text-success">
      <CheckCircle2 />
      Cadeia íntegra
    </Badge>
  ) : (
    <Badge variant="outline" className="gap-1 text-destructive">
      <ShieldAlert />
      Cadeia quebrada
    </Badge>
  )
}
