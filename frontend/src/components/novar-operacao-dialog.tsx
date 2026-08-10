import { useState, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { postRenegociarOperacaoApiOperacoesOperacaoIdRenegociarPostMutation } from '@/api/generated/@tanstack/react-query.gen'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

/**
 * Renegociação por novação atômica.
 *
 * Não existe "só marcar como renegociada": o banco recusa (OC008). A baixa
 * da original e a criação da substituta acontecem na mesma transação, sob o
 * mesmo advisory lock do teto — do contrário haveria uma janela em que as
 * duas contam capital ao mesmo tempo, furando o Art. 5º.
 *
 * Por isso este diálogo pede as condições da nova operação, em vez de ser
 * só uma confirmação como as demais transições.
 */
export function NovarOperacaoDialog({
  operacaoId,
  valorOriginal,
  onSucesso,
}: {
  operacaoId: string
  valorOriginal: string
  onSucesso: () => void
}) {
  const [open, setOpen] = useState(false)
  const [valor, setValor] = useState('')
  const [taxa, setTaxa] = useState('')
  const [sistema, setSistema] = useState<'PRICE' | 'SAC'>('PRICE')
  const [parcelas, setParcelas] = useState('')
  const [registro, setRegistro] = useState('')

  const mutation = useMutation(postRenegociarOperacaoApiOperacoesOperacaoIdRenegociarPostMutation())

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate(
      {
        path: { operacao_id: operacaoId },
        body: {
          valor_principal: valor,
          taxa_juros_mensal: taxa,
          sistema_amortizacao: sistema,
          numero_parcelas: Number(parcelas),
          registro_entidade_ref: registro.trim() || null,
        },
      },
      {
        onSuccess: () => {
          onSucesso()
          setOpen(false)
          mutation.reset()
          toast.success('Operação renegociada', {
            description:
              'A original foi baixada e a substituta nasceu como registrada — ative-a quando houver capital.',
          })
        },
      },
    )
  }

  const valido = Number(valor) > 0 && Number(taxa) >= 0 && Number(parcelas) > 0

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) mutation.reset()
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          Renegociar
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Renegociar operação</DialogTitle>
          <DialogDescription>
            A operação atual de {formatarMoeda(valorOriginal)} será baixada e uma{' '}
            <strong>nova operação</strong> criada no lugar, na mesma transação. A substituta nasce
            como <strong>registrada</strong> e só compromete capital quando for ativada.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="novo-valor">Novo valor principal (R$)</Label>
              <Input
                id="novo-valor"
                type="number"
                min="0.01"
                step="0.01"
                required
                value={valor}
                onChange={(e) => setValor(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="nova-taxa">Nova taxa (% a.m.)</Label>
              <Input
                id="nova-taxa"
                type="number"
                min="0"
                step="0.01"
                required
                value={taxa}
                onChange={(e) => setTaxa(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="novas-parcelas">Parcelas</Label>
              <Input
                id="novas-parcelas"
                type="number"
                min="1"
                step="1"
                required
                value={parcelas}
                onChange={(e) => setParcelas(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="novo-sistema">Amortização</Label>
              <Select value={sistema} onValueChange={(v) => setSistema(v as typeof sistema)}>
                <SelectTrigger id="novo-sistema" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="PRICE">PRICE</SelectItem>
                  <SelectItem value="SAC">SAC</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="novo-registro">Referência do registro (opcional agora)</Label>
            <Input
              id="novo-registro"
              value={registro}
              onChange={(e) => setRegistro(e.target.value)}
              placeholder="pode ser informada depois, antes de ativar"
            />
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
              {mutation.isPending ? 'Renegociando…' : 'Confirmar renegociação'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
