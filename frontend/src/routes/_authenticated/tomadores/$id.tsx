import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, MapPin } from 'lucide-react'
import { getTomadorApiTomadoresTomadorIdGetOptions } from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { formatarMoeda } from '@/lib/format'
import { StatusOperacaoBadge } from '@/components/status-operacao-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

export const Route = createFileRoute('/_authenticated/tomadores/$id')({
  component: TomadorDetailPage,
})

function TomadorDetailPage() {
  const { id } = Route.useParams()
  const { data, error, isPending } = useQuery(
    getTomadorApiTomadoresTomadorIdGetOptions({ path: { tomador_id: id } }),
  )

  if (isPending) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40" />
        <Skeleton className="h-48" />
      </div>
    )
  }
  if (error) return <p className="p-6 text-destructive">{mensagemDeErro(error)}</p>
  if (!data) return null

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <Button asChild variant="ghost" size="icon" aria-label="Voltar para a lista">
          <Link to="/tomadores">
            <ArrowLeft />
          </Link>
        </Button>
        <h1 className="font-heading text-2xl font-bold tracking-tight">{data.razao_social}</h1>
        {data.municipio_autorizado ? (
          <Badge variant="outline" className="text-success">
            Município autorizado
          </Badge>
        ) : (
          <Badge variant="outline" className="text-destructive">
            Não autorizado (OC002)
          </Badge>
        )}
      </div>

      <Card className="max-w-xl">
        <CardHeader>
          <CardTitle>Cadastro</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div className="flex justify-between gap-4">
            <span className="text-muted-foreground">CNPJ</span>
            <span className="font-mono tabular-nums">{data.cnpj}</span>
          </div>
          <div className="flex justify-between gap-4">
            <span className="text-muted-foreground">Porte</span>
            <span>{data.porte}</span>
          </div>
          <div className="flex justify-between gap-4">
            <span className="text-muted-foreground">Município</span>
            <span className="inline-flex items-center gap-1">
              <MapPin className="size-3.5 text-muted-foreground" aria-hidden />
              {data.municipio}/{data.uf}
            </span>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Operações do tomador</CardTitle>
        </CardHeader>
        <CardContent>
          {data.operacoes.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nenhuma operação registrada.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Tipo</TableHead>
                  <TableHead>Valor</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Criada em</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.operacoes.map((op) => (
                  <TableRow key={op.id}>
                    <TableCell>
                      <Link
                        to="/operacoes/$id"
                        params={{ id: op.id }}
                        className="text-primary hover:underline"
                      >
                        {op.tipo}
                      </Link>
                    </TableCell>
                    <TableCell className="font-mono tabular-nums">
                      {formatarMoeda(op.valor_principal)}
                    </TableCell>
                    <TableCell>
                      <StatusOperacaoBadge status={op.status} />
                    </TableCell>
                    <TableCell>{new Date(op.created_at).toLocaleString('pt-BR')}</TableCell>
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
