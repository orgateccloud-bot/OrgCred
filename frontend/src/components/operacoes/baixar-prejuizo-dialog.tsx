import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Ban } from 'lucide-react'
import {
  getCapitalSnapshotApiCapitalSnapshotGetOptions,
  postBaixarPrejuizoApiOperacoesOperacaoIdBaixarPrejuizoPostMutation,
} from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { formatarMoeda } from '@/lib/format'
import { formatarPercentual } from '@/lib/rotulos'
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
 * Palavra digitada para liberar a confirmação.
 *
 * Sem acento de propósito: a comparação normaliza acentuação e caixa, mas o
 * que se pede na tela precisa ser digitável sem hesitação — o atrito aqui é
 * para forçar leitura, não para punir teclado.
 */
export const PALAVRA_CONFIRMACAO = 'PREJUIZO'

function normalizar(valor: string): string {
  return valor
    .trim()
    .toUpperCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
}

/**
 * Write-off: encerra a cobrança SEM devolver capital ao teto.
 *
 * A política decidida em 2026-08-12 (DECISOES_PENDENTES, seção 6) separa
 * quitação de perdão de dívida justamente porque as duas "encerram a
 * operação" e têm efeitos opostos sobre o teto do Art. 5º. O diálogo carrega
 * essa diferença por escrito: liquidar devolve, baixar por prejuízo não.
 *
 * Controlado por fora (`open`/`onOpenChange`) porque o caminho mais provável
 * até aqui não é o botão: é a recusa OC022 na liquidação, que oferece este
 * ato como a saída alternativa e precisa abri-lo.
 */
export function BaixarPrejuizoDialog({
  operacaoId,
  valorPrincipal,
  open,
  onOpenChange,
  onSucesso,
}: {
  operacaoId: string
  valorPrincipal: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onSucesso?: () => void
}) {
  const [confirmacao, setConfirmacao] = useState('')
  const { data: snapshot } = useQuery({
    ...getCapitalSnapshotApiCapitalSnapshotGetOptions(),
    enabled: open,
  })
  const mutation = useMutation(postBaixarPrejuizoApiOperacoesOperacaoIdBaixarPrejuizoPostMutation())

  const totalTeto = snapshot ? Number(snapshot.total) : null
  const fatiaCongelada =
    totalTeto && totalTeto > 0 ? (Number(valorPrincipal) / totalTeto) * 100 : null

  const podeConfirmar = normalizar(confirmacao) === PALAVRA_CONFIRMACAO

  function fechar(proximo: boolean) {
    onOpenChange(proximo)
    if (!proximo) {
      setConfirmacao('')
      mutation.reset()
    }
  }

  function handleConfirmar() {
    if (!podeConfirmar) return
    mutation.mutate(
      { path: { operacao_id: operacaoId } },
      {
        onSuccess: () => {
          fechar(false)
          toast.success('Operação baixada como prejuízo', {
            description: `${formatarMoeda(valorPrincipal)} seguem comprometidos — o capital não voltou ao teto.`,
          })
          onSucesso?.()
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={fechar}>
      <DialogTrigger asChild>
        <Button size="sm" variant="destructive">
          Baixar como prejuízo
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Ban className="size-5 text-destructive" aria-hidden />
            Baixar operação como prejuízo
          </DialogTitle>
          <DialogDescription>
            Isto não é uma liquidação. Você está declarando que este dinheiro{' '}
            <strong>não vai voltar</strong> e encerrando a cobrança sem pagamento.
          </DialogDescription>
        </DialogHeader>

        <ul className="space-y-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm">
          <li>
            <strong className="text-destructive">O capital não volta.</strong> Nenhum centavo é
            devolvido ao capital disponível.
          </li>
          <li>
            <strong className="text-destructive">O teto encolhe de forma permanente.</strong> O
            valor segue comprometido para sempre; só um aporte de capital recupera a capacidade de
            emprestar.
          </li>
          <li>
            <strong className="text-destructive">A operação sai da cobrança.</strong> Estado
            terminal e irreversível: não há volta para ativa, nem caminho daqui para liquidada.
          </li>
        </ul>

        <div className="space-y-2 text-sm">
          <div className="flex justify-between gap-4">
            <span className="text-muted-foreground">Valor da operação</span>
            <span className="font-mono tabular-nums">{formatarMoeda(valorPrincipal)}</span>
          </div>
          <div className="flex justify-between gap-4">
            <span className="text-muted-foreground">Devolvido ao capital disponível</span>
            <span className="font-mono tabular-nums">{formatarMoeda(0)}</span>
          </div>
          <div className="flex justify-between gap-4">
            <span className="text-muted-foreground">Fatia do teto congelada para sempre</span>
            <span className="font-mono tabular-nums">
              {fatiaCongelada !== null ? formatarPercentual(fatiaCongelada) : '—'}
            </span>
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="confirmacao-prejuizo">
            Para confirmar, digite <span className="font-mono">{PALAVRA_CONFIRMACAO}</span>
          </Label>
          <Input
            id="confirmacao-prejuizo"
            value={confirmacao}
            onChange={(e) => setConfirmacao(e.target.value)}
            autoComplete="off"
            placeholder={PALAVRA_CONFIRMACAO}
          />
        </div>

        {mutation.isError && (
          <p role="alert" className="text-sm text-destructive">
            {mensagemDeErro(mutation.error)}
          </p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => fechar(false)} disabled={mutation.isPending}>
            Cancelar
          </Button>
          <Button
            variant="destructive"
            onClick={handleConfirmar}
            disabled={!podeConfirmar || mutation.isPending}
          >
            {mutation.isPending ? 'Baixando…' : 'Confirmar baixa por prejuízo'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
