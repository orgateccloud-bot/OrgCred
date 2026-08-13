import { useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Upload } from 'lucide-react'
import { toast } from 'sonner'
import {
  getDocumentosApiComplianceTomadoresTomadorIdDocumentosGetQueryKey,
  getPendenciasIdentificacaoApiComplianceIdentificacaoPendenciasGetQueryKey,
  postDocumentoApiComplianceTomadoresTomadorIdDocumentosPostMutation,
} from '@/api/generated/@tanstack/react-query.gen'
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
import {
  TIPOS_DOCUMENTO,
  mensagemDeErroDeEvidencia,
  type TipoDocumento,
} from '@/components/identificacao/mensagens'

/**
 * Arquiva a evidência de identificação enviando os BYTES do arquivo.
 *
 * O cliente NÃO manda hash: desde a migration 019 o sha256 é calculado no
 * servidor sobre o que chegou. Um campo de hash aqui seria exatamente o
 * buraco que aquela migration fechou — qualquer pessoa capaz de digitar 64
 * caracteres hexadecimais satisfazia o gate OC019 sem arquivar nada.
 */
export function ArquivarDocumentoDialog({ tomadorId }: { tomadorId: string }) {
  const [open, setOpen] = useState(false)
  const [tipo, setTipo] = useState<TipoDocumento>('contrato_social')
  const [arquivo, setArquivo] = useState<File | null>(null)
  const queryClient = useQueryClient()
  const mutation = useMutation(postDocumentoApiComplianceTomadoresTomadorIdDocumentosPostMutation())

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!arquivo) return
    mutation.mutate(
      { path: { tomador_id: tomadorId }, body: { tipo, arquivo } },
      {
        onSuccess: () => {
          queryClient.invalidateQueries({
            queryKey: getDocumentosApiComplianceTomadoresTomadorIdDocumentosGetQueryKey({
              path: { tomador_id: tomadorId },
            }),
          })
          // O tomador acaba de sair da lista de pendências de identificação —
          // deixá-la em cache mostraria como bloqueado quem já não está.
          queryClient.invalidateQueries({
            queryKey: getPendenciasIdentificacaoApiComplianceIdentificacaoPendenciasGetQueryKey(),
          })
          alterarAberto(false)
          toast.success('Evidência de identificação arquivada.')
        },
      },
    )
  }

  /**
   * Um único caminho de fechamento.
   *
   * `setOpen(false)` direto NÃO dispara `onOpenChange` do Radix (só as saídas
   * internas — Esc, overlay, botão X — passam por lá). Com a limpeza só no
   * `onOpenChange`, "Cancelar" deixava o `File` escolhido vivo no estado: ao
   * reabrir, o input aparecia vazio (o conteúdo do diálogo é desmontado) mas
   * o botão "Arquivar" continuava habilitado e enviaria o arquivo da vez
   * anterior — evidência arquivada sem que ninguém a tenha escolhido daquela
   * vez. O erro anterior também sobrevivia, anunciado de novo por role="alert"
   * antes de qualquer envio.
   */
  function alterarAberto(aberto: boolean) {
    setOpen(aberto)
    if (!aberto) {
      mutation.reset()
      setArquivo(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={alterarAberto}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <Upload />
          Arquivar documento
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Arquivar documento de identificação</DialogTitle>
          <DialogDescription>
            O arquivo é enviado inteiro e guardado; o{' '}
            <strong>resumo criptográfico é calculado pelo servidor</strong>, não informado aqui. A
            guarda é de 5 anos (Lei 9.613/98, art. 10, III) e o prazo fica gravado no momento do
            arquivamento.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="tipo-documento">Tipo de documento</Label>
            <Select value={tipo} onValueChange={(v) => setTipo(v as TipoDocumento)}>
              <SelectTrigger id="tipo-documento" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TIPOS_DOCUMENTO.map((t) => (
                  <SelectItem key={t.valor} value={t.valor}>
                    {t.rotulo}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="arquivo-documento">Arquivo</Label>
            {/* Sem `required`: quem valida é o botão desabilitado + a guarda
                do submit. `required` num input de arquivo só acrescentaria a
                bolha nativa do navegador, em inglês e fora do tom da tela. */}
            <Input
              id="arquivo-documento"
              type="file"
              onChange={(e) => setArquivo(e.target.files?.[0] ?? null)}
            />
          </div>

          {mutation.isError && (
            <p role="alert" className="text-sm text-destructive">
              {mensagemDeErroDeEvidencia(mutation.error)}
            </p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => alterarAberto(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={!arquivo || mutation.isPending}>
              {mutation.isPending ? 'Arquivando…' : 'Arquivar'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
