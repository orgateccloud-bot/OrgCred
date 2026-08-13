import { useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { postLiquidarOperacaoApiOperacoesOperacaoIdLiquidarPostMutation } from '@/api/generated/@tanstack/react-query.gen'
import { ApiError, mensagemDeErro } from '@/api/errors'
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

/**
 * Quitação: encerra a operação DEVOLVENDO o capital ao teto.
 *
 * Por isso o banco exige a prova (migration 017): toda parcela paga contra
 * um movimento bancário. Faltando uma, a recusa é OC022 — e recusa que só
 * vira toast é recusa sem saída, porque as duas ações possíveis a partir
 * dali estão em lugares diferentes da tela. Este diálogo trata OC022 como
 * conteúdo, não como erro genérico: fica aberto, explica o que falta e
 * oferece o caminho alternativo (write-off) no próprio painel.
 */
export function LiquidarOperacaoDialog({
  operacaoId,
  valorPrincipal,
  open,
  onOpenChange,
  onSucesso,
  onEscolherPrejuizo,
}: {
  operacaoId: string
  valorPrincipal: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onSucesso?: () => void
  /** Fecha esta confirmação e abre a baixa por prejuízo. */
  onEscolherPrejuizo: () => void
}) {
  const mutation = useMutation(postLiquidarOperacaoApiOperacoesOperacaoIdLiquidarPostMutation())

  const erro = mutation.error
  const semQuitacao = erro instanceof ApiError && erro.codigo === 'OC022'

  // Zerado na ABERTURA, não só no fechamento, porque quem fecha este diálogo
  // nem sempre é ele: ao escolher o write-off pelo painel OC022, é o pai que
  // troca um diálogo pelo outro e `fechar` nunca roda. Sem isto, reabrir a
  // liquidação exibe a recusa da tentativa anterior como se fosse desta —
  // inclusive depois de o operador ter ido baixar as parcelas que faltavam,
  // dizendo "bloqueada" para uma liquidação que agora passaria.
  const { reset } = mutation
  useEffect(() => {
    if (open) reset()
  }, [open, reset])

  function fechar(proximo: boolean) {
    onOpenChange(proximo)
    if (!proximo) mutation.reset()
  }

  function handleConfirmar() {
    mutation.mutate(
      { path: { operacao_id: operacaoId } },
      {
        onSuccess: () => {
          fechar(false)
          toast.success('Operação liquidada', {
            description: `${formatarMoeda(valorPrincipal)} voltam ao capital disponível.`,
          })
          onSucesso?.()
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={fechar}>
      <DialogTrigger asChild>
        <Button size="sm">Liquidar</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Liquidar operação</DialogTitle>
          <DialogDescription>
            A liquidação é a quitação: devolve {formatarMoeda(valorPrincipal)} ao capital disponível
            e encerra a operação. O evento é gravado no ledger imutável.
          </DialogDescription>
        </DialogHeader>

        <p className="text-sm text-muted-foreground">
          Só é aceita com a prova de que o dinheiro voltou — todas as parcelas baixadas contra
          movimento bancário.
        </p>

        {semQuitacao && (
          <div
            role="alert"
            className="space-y-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-sm"
          >
            <p className="font-medium">Liquidação bloqueada: faltam parcelas com lastro bancário</p>
            <p className="text-muted-foreground">
              Quitação devolve capital ao teto (Art. 5º, LC 167/2019) e por isso exige cada parcela
              paga contra um movimento bancário. Enquanto faltar uma, o banco recusa (OC022).
            </p>
            <p className="text-muted-foreground">
              Há dois caminhos: dar baixa nas parcelas pendentes na seção{' '}
              <strong>Agenda de parcelas</strong>, se o pagamento existiu; ou, se o dinheiro não vai
              voltar, encerrar a cobrança pela baixa como prejuízo — que{' '}
              <strong>não devolve capital</strong> e encolhe o teto de forma permanente.
            </p>
            <Button size="sm" variant="destructive" onClick={onEscolherPrejuizo}>
              Baixar como prejuízo
            </Button>
          </div>
        )}

        {mutation.isError && !semQuitacao && (
          <p role="alert" className="text-sm text-destructive">
            {mensagemDeErro(mutation.error)}
          </p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => fechar(false)} disabled={mutation.isPending}>
            Cancelar
          </Button>
          <Button onClick={handleConfirmar} disabled={mutation.isPending}>
            {mutation.isPending ? 'Liquidando…' : 'Confirmar liquidação'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
