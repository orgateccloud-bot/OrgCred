import { useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FileUp } from 'lucide-react'
import {
  getMovimentosApiCobrancaMovimentosGetQueryKey,
  postImportarOfxApiCobrancaMovimentosImportarOfxPostMutation,
} from '@/api/generated/@tanstack/react-query.gen'
import type { ImportacaoOfxOut } from '@/api/generated/types.gen'
import {
  TAMANHO_MAXIMO_OFX_BYTES,
  mensagemDeArquivoGrandeDemais,
  mensagemDeErroDeImportacaoOfx,
} from '@/components/cobranca/mensagens'
import { RelatorioImportacaoOfx } from '@/components/cobranca/relatorio-importacao-ofx'
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
 * Importa o extrato OFX que o banco emitiu.
 *
 * O que o endpoint entrega não é conveniência de digitação: até ele, todo
 * `movimento_bancario` nascia de um formulário que aceita data, valor e
 * documento arbitrários — o invariante "nenhuma parcela paga sem movimento
 * apontado" provava que existe um registro, não que o dinheiro entrou. Aqui o
 * movimento nasce dos bytes do banco, com o sha256 desses bytes gravado ao
 * lado. O formulário manual continua existindo para o extrato que não se
 * consegue exportar, mas agora os dois são distinguíveis na leitura.
 *
 * NENHUMA PARCELA É BAIXADA pela importação. Amarrar crédito a parcela segue
 * sendo ato de gente, com nome na trilha — por isso o diálogo não promete
 * conciliação, só lastro.
 *
 * O diálogo NÃO fecha no sucesso, ao contrário de todos os outros da tela: o
 * resultado desta chamada é o relatório, e fechar em cima dele trocaria a
 * única informação que torna a importação auditável por um toast. Um toast
 * aqui seria o "importado com sucesso" seco que este componente existe para
 * não dar.
 */
export function ImportarOfxDialog() {
  const [open, setOpen] = useState(false)
  const [arquivo, setArquivo] = useState<File | null>(null)
  const [recusaLocal, setRecusaLocal] = useState<string | null>(null)
  const [relatorio, setRelatorio] = useState<ImportacaoOfxOut | null>(null)
  const queryClient = useQueryClient()
  const mutation = useMutation(postImportarOfxApiCobrancaMovimentosImportarOfxPostMutation())

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!arquivo) return

    // Recusa antes de subir: ver a nota em `TAMANHO_MAXIMO_OFX_BYTES`. O
    // servidor recusa de novo se algo passar daqui — esta guarda é economia
    // de upload, não a regra.
    if (arquivo.size > TAMANHO_MAXIMO_OFX_BYTES) {
      mutation.reset()
      setRelatorio(null)
      setRecusaLocal(mensagemDeArquivoGrandeDemais(arquivo.size))
      return
    }
    setRecusaLocal(null)

    mutation.mutate(
      { body: { arquivo } },
      {
        onSuccess: (resultado) => {
          setRelatorio(resultado)
          // Só a lista de movimentos muda. Aging e operações NÃO entram aqui:
          // a importação não baixa parcela nenhuma, e invalidá-las sugeriria
          // um efeito sobre a carteira que esta chamada não tem.
          queryClient.invalidateQueries({
            queryKey: getMovimentosApiCobrancaMovimentosGetQueryKey(),
          })
        },
      },
    )
  }

  /**
   * Um único caminho de fechamento — `setOpen(false)` direto não dispara o
   * `onOpenChange` do Radix. Sem a limpeza aqui, "Fechar" deixaria o `File`
   * vivo no estado: ao reabrir, o input aparece vazio (o conteúdo do diálogo
   * é desmontado) mas o botão continuaria habilitado e reenviaria o arquivo
   * da vez anterior. O relatório e o erro também sobreviveriam, afirmando
   * sobre uma importação que não aconteceu nesta abertura.
   */
  function alterarAberto(aberto: boolean) {
    setOpen(aberto)
    if (!aberto) {
      mutation.reset()
      setArquivo(null)
      setRecusaLocal(null)
      setRelatorio(null)
    }
  }

  /** Escolher outro arquivo apaga o veredito do anterior. */
  function escolherArquivo(escolhido: File | null) {
    setArquivo(escolhido)
    setRecusaLocal(null)
    setRelatorio(null)
    mutation.reset()
  }

  const mensagemDeFalha =
    recusaLocal ?? (mutation.isError ? mensagemDeErroDeImportacaoOfx(mutation.error) : null)

  return (
    <Dialog open={open} onOpenChange={alterarAberto}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <FileUp />
          Importar extrato OFX
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Importar extrato OFX</DialogTitle>
          <DialogDescription>
            Os créditos do arquivo viram movimentos bancários, com o resumo criptográfico dos bytes
            do banco gravado ao lado. <strong>Nenhuma parcela é baixada</strong> — a importação
            entrega o lastro; amarrar crédito a parcela continua sendo ato de um operador.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="arquivo-ofx">Arquivo do extrato (.ofx)</Label>
            {/* Sem `required`: quem valida é o botão desabilitado + a guarda do
                submit. `required` num input de arquivo só acrescentaria a bolha
                nativa do navegador, em inglês e fora do tom da tela. */}
            <Input
              id="arquivo-ofx"
              type="file"
              accept=".ofx"
              onChange={(e) => escolherArquivo(e.target.files?.[0] ?? null)}
            />
          </div>

          {mensagemDeFalha && (
            <p role="alert" className="text-sm text-destructive">
              {mensagemDeFalha}
            </p>
          )}

          {relatorio && (
            <div className="max-h-[55vh] space-y-3 overflow-y-auto">
              <RelatorioImportacaoOfx relatorio={relatorio} />
            </div>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => alterarAberto(false)}>
              {relatorio ? 'Fechar' : 'Cancelar'}
            </Button>
            <Button type="submit" disabled={!arquivo || mutation.isPending || relatorio !== null}>
              {mutation.isPending ? 'Importando…' : 'Importar'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
