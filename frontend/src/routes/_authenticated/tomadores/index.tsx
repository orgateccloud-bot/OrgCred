import { useState, type FormEvent } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, Plus } from 'lucide-react'
import { toast } from 'sonner'
import {
  getTomadoresApiTomadoresGetOptions,
  getTomadoresApiTomadoresGetQueryKey,
  patchAutorizacaoApiTomadoresTomadorIdAutorizacaoPatchMutation,
  postCriarTomadorApiTomadoresPostMutation,
} from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { useAppStore } from '@/stores/useAppStore'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
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

export const Route = createFileRoute('/_authenticated/tomadores/')({
  component: TomadoresPage,
})

function TomadoresPage() {
  const { data, error, isPending } = useQuery(getTomadoresApiTomadoresGetOptions())
  const papel = useAppStore((state) => state.usuario?.papel)
  const queryClient = useQueryClient()
  const autorizar = useMutation(patchAutorizacaoApiTomadoresTomadorIdAutorizacaoPatchMutation())

  function alternarAutorizacao(tomadorId: string, atual: boolean) {
    autorizar.mutate(
      { path: { tomador_id: tomadorId }, body: { municipio_autorizado: !atual } },
      {
        onSuccess: () => {
          queryClient.invalidateQueries({ queryKey: getTomadoresApiTomadoresGetQueryKey() })
          toast.success(!atual ? 'Município autorizado' : 'Autorização revogada')
        },
        onError: (err) => toast.error('Falha na autorização', { description: mensagemDeErro(err) }),
      },
    )
  }

  return (
    <div className="p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Tomadores</h1>
        <CriarTomadorDialog />
      </div>

      {isPending && (
        <div className="mt-4 space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      )}
      {error && <p className="mt-4 text-destructive">{mensagemDeErro(error)}</p>}

      {data && data.length === 0 && (
        <div className="mt-10 flex flex-col items-center gap-3 text-center">
          <Building2 className="size-8 text-muted-foreground" aria-hidden />
          <p className="text-muted-foreground">
            Nenhum tomador cadastrado — o cadastro é pré-requisito para criar operações.
          </p>
        </div>
      )}

      {data && data.length > 0 && (
        <div className="mt-4 rounded-lg border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Razão social</TableHead>
                <TableHead>CNPJ</TableHead>
                <TableHead>Porte</TableHead>
                <TableHead>Município</TableHead>
                <TableHead>Gate geográfico</TableHead>
                {papel === 'admin' && <TableHead />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((t) => (
                <TableRow key={t.id}>
                  <TableCell>
                    <Link
                      to="/tomadores/$id"
                      params={{ id: t.id }}
                      className="text-primary hover:underline"
                    >
                      {t.razao_social}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono tabular-nums">{t.cnpj}</TableCell>
                  <TableCell>{t.porte}</TableCell>
                  <TableCell>
                    {t.municipio}/{t.uf}
                  </TableCell>
                  <TableCell>
                    {t.municipio_autorizado ? (
                      <Badge variant="outline" className="text-emerald-600 dark:text-emerald-400">
                        Autorizado
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="text-muted-foreground">
                        Não autorizado
                      </Badge>
                    )}
                  </TableCell>
                  {papel === 'admin' && (
                    <TableCell>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={autorizar.isPending}
                        onClick={() => alternarAutorizacao(t.id, t.municipio_autorizado)}
                      >
                        {t.municipio_autorizado ? 'Revogar' : 'Autorizar'}
                      </Button>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}

function CriarTomadorDialog() {
  const queryClient = useQueryClient()
  const mutation = useMutation(postCriarTomadorApiTomadoresPostMutation())
  const [open, setOpen] = useState(false)
  const [cnpj, setCnpj] = useState('')
  const [razaoSocial, setRazaoSocial] = useState('')
  const [porte, setPorte] = useState<'ME' | 'EPP'>('ME')
  const [municipio, setMunicipio] = useState('')
  const [uf, setUf] = useState('')

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate(
      {
        body: {
          cnpj: cnpj.replace(/\D/g, ''),
          razao_social: razaoSocial.trim(),
          porte,
          municipio: municipio.trim(),
          uf: uf.trim().toUpperCase(),
        },
      },
      {
        onSuccess: () => {
          queryClient.invalidateQueries({ queryKey: getTomadoresApiTomadoresGetQueryKey() })
          setOpen(false)
          setCnpj('')
          setRazaoSocial('')
          setMunicipio('')
          setUf('')
          mutation.reset()
          toast.success('Tomador cadastrado', {
            description:
              'O município nasce como não autorizado — a liberação do gate geográfico é ato de admin.',
          })
        },
      },
    )
  }

  const valido =
    cnpj.replace(/\D/g, '').length === 14 &&
    razaoSocial.trim() &&
    municipio.trim() &&
    /^[A-Za-z]{2}$/.test(uf.trim())

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) mutation.reset()
      }}
    >
      <DialogTrigger asChild>
        <Button>
          <Plus />
          Novo tomador
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Cadastrar tomador</DialogTitle>
          <DialogDescription>
            Somente ME/EPP podem tomar crédito de ESC (LC 167/2019). O gate geográfico (OC002)
            permanece bloqueado até autorização explícita de um admin.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="razao">Razão social</Label>
            <Input
              id="razao"
              required
              value={razaoSocial}
              onChange={(e) => setRazaoSocial(e.target.value)}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="cnpj">CNPJ (14 dígitos)</Label>
              <Input
                id="cnpj"
                required
                inputMode="numeric"
                value={cnpj}
                onChange={(e) => setCnpj(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="porte">Porte</Label>
              <Select value={porte} onValueChange={(v) => setPorte(v as typeof porte)}>
                <SelectTrigger id="porte" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ME">ME — Microempresa</SelectItem>
                  <SelectItem value="EPP">EPP — Pequeno porte</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="municipio">Município</Label>
              <Input
                id="municipio"
                required
                value={municipio}
                onChange={(e) => setMunicipio(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="uf">UF</Label>
              <Input
                id="uf"
                required
                maxLength={2}
                value={uf}
                onChange={(e) => setUf(e.target.value)}
              />
            </div>
          </div>

          {mutation.isError && (
            <p className="text-sm text-destructive">{mensagemDeErro(mutation.error)}</p>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={mutation.isPending}
            >
              Cancelar
            </Button>
            <Button type="submit" disabled={!valido || mutation.isPending}>
              {mutation.isPending ? 'Cadastrando…' : 'Cadastrar'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
