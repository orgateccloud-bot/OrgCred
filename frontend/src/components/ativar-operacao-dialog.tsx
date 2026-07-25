import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  getCapitalSnapshotApiCapitalSnapshotGetOptions,
  getOperacoesApiOperacoesGetQueryKey,
  postAtivarOperacaoApiOperacoesOperacaoIdAtivarPostMutation,
} from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { formatarMoeda } from '@/lib/format'
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

export function AtivarOperacaoDialog({
  operacaoId,
  valorPrincipal,
  onSucesso,
}: {
  operacaoId: string
  valorPrincipal: string
  onSucesso?: () => void
}) {
  const [open, setOpen] = useState(false)
  const queryClient = useQueryClient()
  const { data: snapshot } = useQuery(getCapitalSnapshotApiCapitalSnapshotGetOptions())
  const mutation = useMutation(postAtivarOperacaoApiOperacoesOperacaoIdAtivarPostMutation())

  const totalTeto = snapshot ? Number(snapshot.total) : null
  const comprometidoAtual = snapshot ? Number(snapshot.comprometido) : null
  const percentualResultante =
    totalTeto && totalTeto > 0 && comprometidoAtual !== null
      ? ((comprometidoAtual + Number(valorPrincipal)) / totalTeto) * 100
      : null

  function handleConfirmar() {
    mutation.mutate(
      { path: { operacao_id: operacaoId } },
      {
        onSuccess: () => {
          queryClient.invalidateQueries({ queryKey: getOperacoesApiOperacoesGetQueryKey() })
          queryClient.invalidateQueries({
            queryKey: getCapitalSnapshotApiCapitalSnapshotGetOptions().queryKey,
          })
          setOpen(false)
          mutation.reset()
          toast.success('Operação ativada', {
            description: `${formatarMoeda(valorPrincipal)} passam a comprometer o capital da ESC.`,
          })
          onSucesso?.()
        },
      },
    )
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) mutation.reset()
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="secondary">
          Ativar
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Confirmar ativação de operação</DialogTitle>
          <DialogDescription>
            Esta ação é <strong>irreversível</strong>: uma vez ativada, a operação passa a
            comprometer o capital disponível da ESC e não pode ser desfeita — apenas liquidada ou
            renegociada no futuro.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Valor da operação</span>
            <span className="font-mono">{formatarMoeda(valorPrincipal)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Teto comprometido após ativação</span>
            <span className="font-mono">
              {percentualResultante !== null ? `${percentualResultante.toFixed(1)}%` : '—'}
            </span>
          </div>
        </div>

        {mutation.isError && (
          <p className="text-sm text-destructive">{mensagemDeErro(mutation.error)}</p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={mutation.isPending}>
            Cancelar
          </Button>
          <Button onClick={handleConfirmar} disabled={mutation.isPending}>
            {mutation.isPending ? 'Ativando…' : 'Confirmar ativação'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
