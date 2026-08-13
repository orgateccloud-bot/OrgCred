import { useState, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { FileSearch } from 'lucide-react'
import { postVerificarDocumentoApiComplianceDocumentosDocumentoIdVerificarPostMutation } from '@/api/generated/@tanstack/react-query.gen'
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
import { mensagemDeErroDeEvidencia } from '@/components/identificacao/mensagens'

/**
 * Conferência bit a bit: o arquivo que a pessoa tem em mãos é o que foi
 * arquivado?
 *
 * São duas perguntas distintas e o servidor responde as duas contra o hash
 * gravado, nunca uma contra a outra:
 * - `confere`: o arquivo apresentado bate com o que foi arquivado;
 * - `storage_integro`: os bytes guardados no bucket ainda batem — é o que
 *   denuncia adulteração do arquivo GUARDADO. Nulo em evidência anterior à
 *   migration 019, que nunca teve bytes para conferir.
 */
export function VerificarDocumentoDialog({
  documentoId,
  nomeArquivo,
}: {
  documentoId: string
  nomeArquivo: string
}) {
  const [open, setOpen] = useState(false)
  const [arquivo, setArquivo] = useState<File | null>(null)
  const mutation = useMutation(
    postVerificarDocumentoApiComplianceDocumentosDocumentoIdVerificarPostMutation(),
  )

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!arquivo) return
    mutation.mutate({ path: { documento_id: documentoId }, body: { arquivo } })
  }

  const resultado = mutation.data
  const inputId = `verificar-arquivo-${documentoId}`

  /**
   * Um único caminho de fechamento.
   *
   * `setOpen(false)` direto não passa pelo `onOpenChange` do Radix, então com
   * a limpeza só ali o botão "Fechar" preservava `mutation.data`: ao reabrir,
   * o diálogo exibia de novo o resultado da conferência anterior — um
   * "Confere: é bit a bit o documento arquivado" em região viva, sem que
   * nenhum arquivo estivesse selecionado nem nenhuma conferência tivesse sido
   * feita. Afirmação de integridade não pode sobreviver ao fechamento.
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
        <Button size="sm" variant="ghost" aria-label={`Verificar ${nomeArquivo}`}>
          <FileSearch />
          Verificar
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Verificar documento</DialogTitle>
          <DialogDescription>
            Escolha o arquivo que você tem em mãos. O servidor calcula o resumo criptográfico dele e
            compara com o que foi arquivado — nada aqui é enviado ao acervo, é só conferência.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor={inputId}>Arquivo a conferir</Label>
            <Input
              id={inputId}
              type="file"
              onChange={(e) => {
                mutation.reset()
                setArquivo(e.target.files?.[0] ?? null)
              }}
            />
          </div>

          {mutation.isError && (
            <p role="alert" className="text-sm text-destructive">
              {mensagemDeErroDeEvidencia(mutation.error)}
            </p>
          )}

          {resultado && (
            <div
              role={resultado.confere ? 'status' : 'alert'}
              className="space-y-2 rounded-lg border border-border p-3 text-sm"
            >
              <p
                className={
                  resultado.confere ? 'font-medium text-success' : 'font-medium text-destructive'
                }
              >
                {resultado.confere
                  ? 'Confere: é bit a bit o documento arquivado.'
                  : 'Não confere: este arquivo NÃO é o que foi arquivado.'}
              </p>
              <p className="text-muted-foreground">
                Bytes guardados no acervo:{' '}
                {resultado.storage_integro === null ? (
                  <span>
                    não verificáveis — evidência arquivada antes do armazenamento de bytes, só o
                    resumo criptográfico existe.
                  </span>
                ) : resultado.storage_integro ? (
                  <span className="text-success">íntegros.</span>
                ) : (
                  <span className="text-destructive">
                    adulterados — o objeto no acervo não bate mais com o resumo gravado.
                  </span>
                )}
              </p>
              <dl className="space-y-1 font-mono text-xs break-all">
                <div>
                  <dt className="inline text-muted-foreground">arquivo apresentado: </dt>
                  <dd className="inline">{resultado.sha256_calculado}</dd>
                </div>
                <div>
                  <dt className="inline text-muted-foreground">documento arquivado: </dt>
                  <dd className="inline">{resultado.sha256_arquivado}</dd>
                </div>
              </dl>
            </div>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => alterarAberto(false)}>
              Fechar
            </Button>
            <Button type="submit" disabled={!arquivo || mutation.isPending}>
              {mutation.isPending ? 'Conferindo…' : 'Conferir'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
