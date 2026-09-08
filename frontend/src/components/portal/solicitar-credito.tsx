import { useState } from 'react'
import { Copy, HandCoins, Mail } from 'lucide-react'
import { toast } from 'sonner'
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
import { montarSolicitacao } from '@/lib/solicitacao'

const OPCOES_PARCELAS = ['6', '12', '18', '24'] as const

/**
 * Solicitação de novo crédito — SEM gravar nada no banco, de propósito.
 *
 * O portal não tem verbo de escrita (app/routers/portal.py), e crédito não
 * nasce de formulário: nasce de análise. O diálogo compõe a mensagem, mostra
 * exatamente o que será enviado, e entrega pelos canais que já existem —
 * e-mail (se VITE_ESC_EMAIL estiver configurado no build) ou cópia para o
 * canal que a empresa usa com a ESC. Um botão "Enviar" que fingisse
 * persistir seria o defeito que a migration 019 matou no arquivamento.
 */
export function SolicitarCredito({ razaoSocial, cnpj }: { razaoSocial: string; cnpj: string }) {
  const [open, setOpen] = useState(false)
  const [valor, setValor] = useState('')
  const [parcelas, setParcelas] = useState<string>('12')
  const [finalidade, setFinalidade] = useState('')

  const emailEsc = (import.meta.env.VITE_ESC_EMAIL as string | undefined)?.trim()
  const texto = montarSolicitacao({ razaoSocial, cnpj, valor, parcelas, finalidade })
  const preenchido = valor.trim().length > 0 && finalidade.trim().length > 0

  async function copiar() {
    try {
      await navigator.clipboard.writeText(texto)
      toast.success('Solicitação copiada', {
        description: 'Cole no canal que a sua empresa usa com a ESC.',
      })
    } catch {
      toast.error('Não foi possível copiar automaticamente. Selecione o texto e copie.')
    }
  }

  function alterarAberto(aberto: boolean) {
    setOpen(aberto)
    if (!aberto) {
      setValor('')
      setParcelas('12')
      setFinalidade('')
    }
  }

  return (
    <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card p-4">
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 font-medium">
          <HandCoins className="size-4 text-primary" aria-hidden />
          Precisa de mais crédito?
        </h2>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Monte a solicitação aqui; a equipe da ESC analisa e retorna.
        </p>
      </div>

      <Dialog open={open} onOpenChange={alterarAberto}>
        <DialogTrigger asChild>
          <Button size="sm">Solicitar crédito</Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Solicitar novo crédito</DialogTitle>
            <DialogDescription>
              A solicitação vai para a análise da equipe da ESC —{' '}
              <strong>nenhum crédito nasce aprovado automaticamente</strong>. Você verá abaixo
              exatamente o que será enviado.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="solicitacao-valor">Valor pretendido (R$)</Label>
                <Input
                  id="solicitacao-valor"
                  inputMode="decimal"
                  placeholder="20.000,00"
                  value={valor}
                  onChange={(e) => setValor(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="solicitacao-parcelas">Parcelas</Label>
                <Select value={parcelas} onValueChange={setParcelas}>
                  <SelectTrigger id="solicitacao-parcelas" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {OPCOES_PARCELAS.map((n) => (
                      <SelectItem key={n} value={n}>
                        {n} parcelas
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="solicitacao-finalidade">Finalidade</Label>
              <Input
                id="solicitacao-finalidade"
                placeholder="Ex.: reforma do forno, capital de giro…"
                value={finalidade}
                onChange={(e) => setFinalidade(e.target.value)}
              />
            </div>

            {preenchido && (
              <pre className="max-h-40 overflow-y-auto rounded-lg border border-border bg-muted p-3 font-mono text-xs whitespace-pre-wrap text-muted-foreground">
                {texto}
              </pre>
            )}

            <DialogFooter className="gap-2">
              <Button type="button" variant="outline" disabled={!preenchido} onClick={copiar}>
                <Copy aria-hidden />
                Copiar
              </Button>
              {emailEsc && (
                <Button asChild disabled={!preenchido}>
                  <a
                    href={`mailto:${emailEsc}?subject=${encodeURIComponent(
                      `Solicitação de crédito — ${razaoSocial}`,
                    )}&body=${encodeURIComponent(texto)}`}
                  >
                    <Mail aria-hidden />
                    Enviar por e-mail
                  </a>
                </Button>
              )}
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  )
}
