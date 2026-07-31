import { useState, type FormEvent } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Landmark, ShieldAlert } from 'lucide-react'
import { toast } from 'sonner'
import {
  getCapitalEventosApiCapitalEventosGetOptions,
  getCapitalEventosApiCapitalEventosGetQueryKey,
  getCapitalSnapshotApiCapitalSnapshotGetOptions,
  postCapitalEventoApiCapitalEventosPostMutation,
} from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { formatarMoeda } from '@/lib/format'
import { useAppStore } from '@/stores/useAppStore'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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

export const Route = createFileRoute('/_authenticated/capital')({
  component: CapitalPage,
})

function CapitalPage() {
  const snapshot = useQuery(getCapitalSnapshotApiCapitalSnapshotGetOptions())
  const eventos = useQuery(getCapitalEventosApiCapitalEventosGetOptions())
  const papel = useAppStore((state) => state.usuario?.papel)
  const ehAdmin = papel === 'admin'

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center gap-3">
        <Landmark className="size-6 text-primary" aria-hidden />
        <h1 className="font-heading text-2xl font-bold tracking-tight">Capital social</h1>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <ResumoCard rotulo="Teto (capital social)" valor={snapshot.data?.total} destaque />
        <ResumoCard rotulo="Comprometido" valor={snapshot.data?.comprometido} />
        <ResumoCard rotulo="Disponível" valor={snapshot.data?.disponivel} />
      </div>

      {ehAdmin ? (
        <RegistrarEventoCard />
      ) : (
        <div className="flex items-start gap-3 rounded-lg border border-border p-4 text-sm text-muted-foreground">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          Registrar aportes ou reduções de capital é ação restrita a administradores. Você tem
          acesso apenas de leitura a esta tela.
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Histórico de eventos</CardTitle>
          <CardDescription>
            A soma (constituições menos reduções) é o teto legal da ESC (Art. 5º, LC 167/2019).
          </CardDescription>
        </CardHeader>
        <CardContent>
          {eventos.isPending && <Skeleton className="h-24 w-full" />}
          {eventos.error && <p className="text-destructive">{mensagemDeErro(eventos.error)}</p>}
          {eventos.data && eventos.data.length === 0 && (
            <p className="text-sm text-muted-foreground">
              Nenhum evento de capital ainda. Enquanto o capital não for integralizado, o teto é R$
              0,00 e nenhuma operação pode ser ativada.
            </p>
          )}
          {eventos.data && eventos.data.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Evento</TableHead>
                  <TableHead>Valor</TableHead>
                  <TableHead>Data</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {eventos.data.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="capitalize">{e.tipo_evento}</TableCell>
                    <TableCell className="font-mono tabular-nums">
                      {e.tipo_evento === 'reducao' ? '−' : '+'}
                      {formatarMoeda(e.valor)}
                    </TableCell>
                    <TableCell>{new Date(e.created_at).toLocaleString('pt-BR')}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function ResumoCard({
  rotulo,
  valor,
  destaque = false,
}: {
  rotulo: string
  valor?: string
  destaque?: boolean
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{rotulo}</CardDescription>
      </CardHeader>
      <CardContent>
        {valor === undefined ? (
          <Skeleton className="h-8 w-32" />
        ) : (
          <p
            className={`font-mono text-2xl font-semibold tabular-nums ${destaque ? 'text-primary' : ''}`}
          >
            {formatarMoeda(valor)}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function RegistrarEventoCard() {
  const queryClient = useQueryClient()
  const mutation = useMutation(postCapitalEventoApiCapitalEventosPostMutation())
  const [tipo, setTipo] = useState<'constituicao' | 'reducao'>('constituicao')
  const [valor, setValor] = useState('')

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate(
      { body: { tipo_evento: tipo, valor } },
      {
        onSuccess: () => {
          queryClient.invalidateQueries({
            queryKey: getCapitalEventosApiCapitalEventosGetQueryKey(),
          })
          queryClient.invalidateQueries({
            queryKey: getCapitalSnapshotApiCapitalSnapshotGetOptions().queryKey,
          })
          setValor('')
          mutation.reset()
          toast.success('Evento de capital registrado')
        },
        onError: (err) => toast.error('Registro recusado', { description: mensagemDeErro(err) }),
      },
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Registrar evento</CardTitle>
        <CardDescription>
          Aporte (constituição) aumenta o teto; redução diminui — o banco recusa reduções que deixem
          o capital abaixo do comprometido (OC005).
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
          <div className="space-y-2">
            <Label htmlFor="tipo-evento">Tipo</Label>
            <Select value={tipo} onValueChange={(v) => setTipo(v as typeof tipo)}>
              <SelectTrigger id="tipo-evento" className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="constituicao">Constituição / aporte</SelectItem>
                <SelectItem value="reducao">Redução</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="valor-evento">Valor (R$)</Label>
            <Input
              id="valor-evento"
              type="number"
              min="0.01"
              step="0.01"
              required
              value={valor}
              onChange={(e) => setValor(e.target.value)}
              className="w-48"
            />
          </div>
          <Button type="submit" disabled={mutation.isPending || Number(valor) <= 0}>
            {mutation.isPending ? 'Registrando…' : 'Registrar'}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
