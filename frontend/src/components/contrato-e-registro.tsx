import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, Landmark, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'
import {
  getContratoApiContratosOperacoesOperacaoIdContratoGetOptions,
  getContratoApiContratosOperacoesOperacaoIdContratoGetQueryKey,
  getRegistrosApiContratosOperacoesOperacaoIdRegistrosGetOptions,
  getRegistrosApiContratosOperacoesOperacaoIdRegistrosGetQueryKey,
  postAbrirRegistroApiContratosOperacoesOperacaoIdRegistrosPostMutation,
  postConfirmarRegistroApiContratosRegistrosRegistroIdConfirmarPostMutation,
  postEmitirContratoApiContratosOperacoesOperacaoIdContratoPostMutation,
  postRejeitarRegistroApiContratosRegistrosRegistroIdRejeitarPostMutation,
} from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Skeleton } from '@/components/ui/skeleton'

/**
 * Instrumento contratual e registro em entidade registradora.
 *
 * O registro aqui é entidade de primeira classe — entidade, protocolo,
 * status. O campo `registro_entidade_ref` da operação continua existindo e
 * continua sendo texto livre; é justamente o que esta seção substitui.
 *
 * O gate de ativação por registro confirmado está LIGADO desde a migration
 * 013: sem um registro confirmado aqui, a operação não ativa (OC004).
 */
export function ContratoERegistro({ operacaoId }: { operacaoId: string }) {
  const queryClient = useQueryClient()
  const contrato = useQuery(
    getContratoApiContratosOperacoesOperacaoIdContratoGetOptions({
      path: { operacao_id: operacaoId },
    }),
  )
  const registros = useQuery(
    getRegistrosApiContratosOperacoesOperacaoIdRegistrosGetOptions({
      path: { operacao_id: operacaoId },
    }),
  )
  const emitir = useMutation(
    postEmitirContratoApiContratosOperacoesOperacaoIdContratoPostMutation(),
  )

  function invalidarContrato() {
    queryClient.invalidateQueries({
      queryKey: getContratoApiContratosOperacoesOperacaoIdContratoGetQueryKey({
        path: { operacao_id: operacaoId },
      }),
    })
  }

  function invalidarRegistros() {
    queryClient.invalidateQueries({
      queryKey: getRegistrosApiContratosOperacoesOperacaoIdRegistrosGetQueryKey({
        path: { operacao_id: operacaoId },
      }),
    })
  }

  const confirmado = (registros.data ?? []).some((r) => r.status === 'confirmado')

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div className="space-y-1.5">
            <CardTitle>Instrumento contratual</CardTitle>
            <CardDescription>
              Contrato de Empréstimo ESC gerado a partir das condições e da agenda. Reemitir cria
              uma nova versão — a anterior permanece, porque o tomador tem uma via dela.
            </CardDescription>
          </div>
          <Button
            size="sm"
            variant="outline"
            disabled={emitir.isPending}
            onClick={() =>
              emitir.mutate(
                { path: { operacao_id: operacaoId } },
                {
                  onSuccess: (c) => {
                    invalidarContrato()
                    toast.success(`Contrato emitido (versão ${c.versao}).`)
                  },
                },
              )
            }
          >
            <FileText />
            {contrato.data ? 'Reemitir' : 'Emitir'}
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {contrato.isPending && <Skeleton className="h-32" />}
          {contrato.error && (
            <p className="text-sm text-destructive">{mensagemDeErro(contrato.error)}</p>
          )}
          {emitir.isError && (
            <p className="text-sm text-destructive">{mensagemDeErro(emitir.error)}</p>
          )}
          {contrato.isSuccess && !contrato.data && !emitir.isError && (
            <p className="text-sm text-muted-foreground">Nenhum instrumento emitido ainda.</p>
          )}
          {contrato.data && (
            <>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge variant="outline">versão {contrato.data.versao}</Badge>
                <span className="text-muted-foreground">
                  emitido em {new Date(contrato.data.emitido_em).toLocaleString('pt-BR')}
                </span>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">
                  Resumo criptográfico (SHA-256), calculado pelo banco:
                </p>
                <p className="font-mono text-xs break-all">{contrato.data.sha256}</p>
              </div>
              <pre className="max-h-80 overflow-auto rounded-lg bg-muted/40 p-3 font-mono text-xs whitespace-pre">
                {contrato.data.corpo}
              </pre>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div className="space-y-1.5">
            <CardTitle>Registro em entidade registradora</CardTitle>
            <CardDescription>
              Exigência do art. 5º, §3º, da LC 167/2019. Confirmar exige o número de protocolo — e é
              estado definitivo.
            </CardDescription>
          </div>
          {!confirmado && (
            <AbrirRegistroDialog operacaoId={operacaoId} onSucesso={invalidarRegistros} />
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          {registros.isPending && <Skeleton className="h-24" />}
          {registros.error && (
            <p className="text-sm text-destructive">{mensagemDeErro(registros.error)}</p>
          )}
          {registros.data && registros.data.length === 0 && (
            <p className="text-sm text-muted-foreground">
              Nenhuma tentativa de registro. A operação <strong>não poderá ser ativada</strong> até
              haver um registro confirmado, com protocolo.
            </p>
          )}
          {registros.data?.map((r) => (
            <div key={r.id} className="space-y-2 rounded-lg border border-border p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{r.entidade}</span>
                <StatusRegistroBadge status={r.status} />
                <span className="ml-auto text-xs text-muted-foreground">
                  {new Date(r.enviado_em).toLocaleDateString('pt-BR')}
                </span>
              </div>
              {r.protocolo && (
                <p className="font-mono text-xs">
                  protocolo: <span className="text-foreground">{r.protocolo}</span>
                </p>
              )}
              {r.motivo_rejeicao && (
                <p className="text-xs text-destructive">motivo: {r.motivo_rejeicao}</p>
              )}
              {r.status === 'pendente' && (
                <div className="flex gap-2 pt-1">
                  <ConfirmarRegistroDialog registroId={r.id} onSucesso={invalidarRegistros} />
                  <RejeitarRegistroDialog registroId={r.id} onSucesso={invalidarRegistros} />
                </div>
              )}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

function StatusRegistroBadge({ status }: { status: string }) {
  if (status === 'confirmado') {
    return (
      <Badge variant="outline" className="text-success">
        Confirmado
      </Badge>
    )
  }
  if (status === 'rejeitado') {
    return (
      <Badge variant="outline" className="text-destructive">
        Rejeitado
      </Badge>
    )
  }
  return <Badge variant="outline">Pendente</Badge>
}

function AbrirRegistroDialog({
  operacaoId,
  onSucesso,
}: {
  operacaoId: string
  onSucesso: () => void
}) {
  const [open, setOpen] = useState(false)
  const [entidade, setEntidade] = useState('')
  const mutation = useMutation(
    postAbrirRegistroApiContratosOperacoesOperacaoIdRegistrosPostMutation(),
  )

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate(
      { path: { operacao_id: operacaoId }, body: { entidade: entidade.trim() } },
      {
        onSuccess: () => {
          onSucesso()
          setOpen(false)
          mutation.reset()
          setEntidade('')
          toast.success('Registro aberto como pendente.')
        },
      },
    )
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(aberto) => {
        setOpen(aberto)
        if (!aberto) mutation.reset()
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <Landmark />
          Abrir registro
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Abrir registro</DialogTitle>
          <DialogDescription>
            O envio à entidade é <strong>manual</strong> hoje: não há integração porque a
            registradora ainda não foi escolhida. Este passo registra a tentativa; a confirmação vem
            depois, com o protocolo devolvido por ela.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="entidade">Entidade registradora</Label>
            <Input
              id="entidade"
              required
              value={entidade}
              onChange={(e) => setEntidade(e.target.value)}
              placeholder="CRDC, Núclea, SPC Grafeno, B3, CERC…"
            />
          </div>

          {mutation.isError && (
            <p className="text-sm text-destructive">{mensagemDeErro(mutation.error)}</p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={!entidade.trim() || mutation.isPending}>
              {mutation.isPending ? 'Abrindo…' : 'Abrir'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function ConfirmarRegistroDialog({
  registroId,
  onSucesso,
}: {
  registroId: string
  onSucesso: () => void
}) {
  const [open, setOpen] = useState(false)
  const [protocolo, setProtocolo] = useState('')
  const mutation = useMutation(
    postConfirmarRegistroApiContratosRegistrosRegistroIdConfirmarPostMutation(),
  )

  return (
    <Dialog
      open={open}
      onOpenChange={(aberto) => {
        setOpen(aberto)
        if (!aberto) mutation.reset()
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm">
          <ShieldCheck />
          Confirmar
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Confirmar registro</DialogTitle>
          <DialogDescription>
            O protocolo é <strong>obrigatório</strong>: registro confirmado sem número é
            indistinguível de alguém marcando a caixinha. A confirmação é{' '}
            <strong>definitiva</strong> — reverter apagaria a prova de que a operação existe
            legalmente.
          </DialogDescription>
        </DialogHeader>

        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            mutation.mutate(
              { path: { registro_id: registroId }, body: { protocolo: protocolo.trim() } },
              {
                onSuccess: () => {
                  onSucesso()
                  setOpen(false)
                  mutation.reset()
                  toast.success('Registro confirmado.')
                },
              },
            )
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="protocolo">Protocolo devolvido pela entidade</Label>
            <Input
              id="protocolo"
              required
              value={protocolo}
              onChange={(e) => setProtocolo(e.target.value)}
            />
          </div>

          {mutation.isError && (
            <p className="text-sm text-destructive">{mensagemDeErro(mutation.error)}</p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={!protocolo.trim() || mutation.isPending}>
              {mutation.isPending ? 'Confirmando…' : 'Confirmar registro'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function RejeitarRegistroDialog({
  registroId,
  onSucesso,
}: {
  registroId: string
  onSucesso: () => void
}) {
  const [open, setOpen] = useState(false)
  const [motivo, setMotivo] = useState('')
  const mutation = useMutation(
    postRejeitarRegistroApiContratosRegistrosRegistroIdRejeitarPostMutation(),
  )

  return (
    <Dialog
      open={open}
      onOpenChange={(aberto) => {
        setOpen(aberto)
        if (!aberto) mutation.reset()
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          Rejeitar
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rejeitar registro</DialogTitle>
          <DialogDescription>
            O motivo é obrigatório — sem ele, a próxima tentativa repete o mesmo erro. Rejeitar
            encerra esta tentativa, não a operação: uma nova pode ser aberta.
          </DialogDescription>
        </DialogHeader>

        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            mutation.mutate(
              { path: { registro_id: registroId }, body: { motivo: motivo.trim() } },
              {
                onSuccess: () => {
                  onSucesso()
                  setOpen(false)
                  mutation.reset()
                  toast.success('Registro rejeitado.')
                },
              },
            )
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="motivo">Motivo da rejeição</Label>
            <Input
              id="motivo"
              required
              value={motivo}
              onChange={(e) => setMotivo(e.target.value)}
            />
          </div>

          {mutation.isError && (
            <p className="text-sm text-destructive">{mensagemDeErro(mutation.error)}</p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancelar
            </Button>
            <Button
              type="submit"
              variant="destructive"
              disabled={!motivo.trim() || mutation.isPending}
            >
              {mutation.isPending ? 'Rejeitando…' : 'Rejeitar'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
