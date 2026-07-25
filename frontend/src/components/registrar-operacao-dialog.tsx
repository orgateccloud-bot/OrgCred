import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { postRegistrarOperacaoApiOperacoesOperacaoIdRegistrarPostMutation } from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
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

/**
 * proposta -> registrada. A referência do registro na entidade registradora
 * é obrigatória aqui porque o trigger OC004 exige tê-la para a futura
 * ativação (Art. 5º §3º, LC 167/2019).
 */
export function RegistrarOperacaoDialog({
  operacaoId,
  onSucesso,
}: {
  operacaoId: string
  onSucesso: () => void
}) {
  const [open, setOpen] = useState(false)
  const [referencia, setReferencia] = useState('')
  const mutation = useMutation(postRegistrarOperacaoApiOperacoesOperacaoIdRegistrarPostMutation())

  function handleConfirmar() {
    mutation.mutate(
      {
        path: { operacao_id: operacaoId },
        body: { registro_entidade_ref: referencia.trim() },
      },
      {
        onSuccess: () => {
          onSucesso()
          setOpen(false)
          setReferencia('')
          mutation.reset()
          toast.success('Operação registrada', {
            description: 'Pronta para ativação quando houver capital disponível.',
          })
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
        <Button size="sm">Registrar</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Registrar operação</DialogTitle>
          <DialogDescription>
            Informe a referência do registro na entidade registradora. Sem ela, a ativação será
            bloqueada pelo banco (OC004 — Art. 5º §3º, LC 167/2019).
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <Label htmlFor="registro-ref">Referência do registro</Label>
          <Input
            id="registro-ref"
            value={referencia}
            onChange={(event) => setReferencia(event.target.value)}
            placeholder="ex.: B3-REG-2026-000123"
          />
        </div>

        {mutation.isError && (
          <p className="text-sm text-destructive">{mensagemDeErro(mutation.error)}</p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={mutation.isPending}>
            Cancelar
          </Button>
          <Button
            onClick={handleConfirmar}
            disabled={mutation.isPending || referencia.trim().length === 0}
          >
            {mutation.isPending ? 'Registrando…' : 'Confirmar registro'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
