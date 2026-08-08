import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  getMovimentosApiCobrancaMovimentosGetOptions,
  postBaixarParcelaApiCobrancaParcelasParcelaIdBaixarPostMutation,
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
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

/**
 * Baixa de recebimento contra uma linha de extrato.
 *
 * Não existe "marcar como pago": o banco recusa (OC011). Sem lastro, a
 * régua de inadimplência pararia de ver o atraso de uma dívida que continua
 * em aberto — a carteira pareceria saudável sem nada registrar a mentira.
 *
 * A lista só oferece movimentos AINDA NÃO conciliados e com valor
 * suficiente: oferecer o que o banco vai recusar transforma uma regra clara
 * num erro genérico depois do clique.
 */
export function BaixarParcelaDialog({
  parcelaId,
  numero,
  valorTotal,
  onSucesso,
}: {
  parcelaId: string
  numero: number
  valorTotal: string
  onSucesso: () => void
}) {
  const [open, setOpen] = useState(false)
  const [movimentoId, setMovimentoId] = useState('')

  const { data: movimentos } = useQuery({
    ...getMovimentosApiCobrancaMovimentosGetOptions({ query: { apenas_disponiveis: true } }),
    enabled: open,
  })
  const mutation = useMutation(postBaixarParcelaApiCobrancaParcelasParcelaIdBaixarPostMutation())

  const elegiveis = (movimentos ?? []).filter((m) => Number(m.valor) >= Number(valorTotal))

  return (
    <Dialog
      open={open}
      onOpenChange={(aberto) => {
        setOpen(aberto)
        if (!aberto) {
          mutation.reset()
          setMovimentoId('')
        }
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          Baixar
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Baixar parcela {numero}</DialogTitle>
          <DialogDescription>
            A parcela de <strong>{formatarMoeda(valorTotal)}</strong> será dada por paga contra a
            linha de extrato escolhida. A baixa é <strong>definitiva</strong> — não há estorno: uma
            baixa errada se corrige com um lançamento de correção no próprio banco.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <Label htmlFor="movimento">Movimento bancário</Label>
          {elegiveis.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nenhum movimento disponível cobre {formatarMoeda(valorTotal)}. Registre a linha de
              extrato em <strong>Cobrança</strong> antes de baixar.
            </p>
          ) : (
            <Select value={movimentoId} onValueChange={setMovimentoId}>
              <SelectTrigger id="movimento" className="w-full">
                <SelectValue placeholder="Selecione a linha do extrato" />
              </SelectTrigger>
              <SelectContent>
                {elegiveis.map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    {new Date(`${m.data_movimento}T00:00:00`).toLocaleDateString('pt-BR')} ·{' '}
                    {formatarMoeda(String(m.valor))} · {m.documento}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>

        {mutation.isError && (
          <p className="text-sm text-destructive">{mensagemDeErro(mutation.error)}</p>
        )}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => setOpen(false)}>
            Cancelar
          </Button>
          <Button
            disabled={!movimentoId || mutation.isPending}
            onClick={() =>
              mutation.mutate(
                { path: { parcela_id: parcelaId }, body: { movimento_id: movimentoId } },
                {
                  onSuccess: () => {
                    onSucesso()
                    setOpen(false)
                    toast.success(`Parcela ${numero} baixada.`)
                  },
                },
              )
            }
          >
            {mutation.isPending ? 'Baixando…' : 'Confirmar baixa'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
