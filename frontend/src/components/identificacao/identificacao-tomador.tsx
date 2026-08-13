import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, ShieldAlert } from 'lucide-react'
import { getDocumentosApiComplianceTomadoresTomadorIdDocumentosGetOptions } from '@/api/generated/@tanstack/react-query.gen'
import { getConteudoDocumentoApiComplianceDocumentosDocumentoIdConteudoGet } from '@/api/generated/sdk.gen'
import type { DocumentoOut } from '@/api/generated/types.gen'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ArquivarDocumentoDialog } from '@/components/identificacao/arquivar-documento-dialog'
import { VerificarDocumentoDialog } from '@/components/identificacao/verificar-documento-dialog'
import {
  formatarDataIso,
  hashAbreviado,
  mensagemDeErroDeEvidencia,
  rotuloTipoDocumento,
} from '@/components/identificacao/mensagens'

/**
 * Identificação do tomador — a evidência que destrava a ativação.
 *
 * O gate OC019 (Lei 9.613/98, art. 10, I) recusa ativar operação de tomador
 * sem evidência arquivada, e a mensagem daquele erro manda "arquivar o
 * documento na ficha do tomador". Esta seção É esse lugar: sem ela, a
 * instrução apontava para uma tela que não existia e todo tomador cadastrado
 * pela interface nascia com as operações travadas.
 */
export function IdentificacaoTomador({ tomadorId }: { tomadorId: string }) {
  const documentos = useQuery(
    getDocumentosApiComplianceTomadoresTomadorIdDocumentosGetOptions({
      path: { tomador_id: tomadorId },
    }),
  )

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div className="space-y-1.5">
          <CardTitle>Identificação</CardTitle>
          <CardDescription>
            Evidência de identificação do cliente (Lei 9.613/98, art. 10, I), guardada por 5 anos. O
            arquivo é enviado inteiro e o resumo criptográfico é calculado pelo servidor — o cliente
            não informa hash.
          </CardDescription>
        </div>
        <ArquivarDocumentoDialog tomadorId={tomadorId} />
      </CardHeader>
      <CardContent className="space-y-3">
        {documentos.isPending && <Skeleton className="h-24" />}

        {documentos.error && (
          <p role="alert" className="text-sm text-destructive">
            {mensagemDeErroDeEvidencia(documentos.error)}
          </p>
        )}

        {documentos.data?.length === 0 && (
          <div className="flex gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm">
            <ShieldAlert className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
            <div className="space-y-1">
              <p className="font-medium">Nenhuma evidência de identificação arquivada.</p>
              <p className="text-muted-foreground">
                Enquanto não houver um documento aqui,{' '}
                <strong className="text-foreground">
                  nenhuma operação deste tomador poderá ser ativada
                </strong>{' '}
                — o banco recusa a ativação com o código OC019. Arquive o documento para destravar.
              </p>
            </div>
          </div>
        )}

        {documentos.data && documentos.data.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Documento</TableHead>
                <TableHead>Arquivado em</TableHead>
                <TableHead>Guarda até</TableHead>
                <TableHead>Resumo (SHA-256)</TableHead>
                <TableHead className="text-right">Conferência</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {documentos.data.map((doc) => (
                <LinhaDocumento key={doc.id} documento={doc} />
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

function LinhaDocumento({ documento }: { documento: DocumentoOut }) {
  const [baixando, setBaixando] = useState(false)
  const [erroDownload, setErroDownload] = useState<string | null>(null)

  async function baixar() {
    setBaixando(true)
    setErroDownload(null)
    try {
      const { data } = await getConteudoDocumentoApiComplianceDocumentosDocumentoIdConteudoGet({
        path: { documento_id: documento.id },
        parseAs: 'blob',
        throwOnError: true,
      })
      // Não navegamos para a URL da API: o download precisa do Authorization
      // da sessão, que um <a href> não carrega. Buscamos os bytes e
      // entregamos o blob local com o nome registrado.
      const url = URL.createObjectURL(data as Blob)
      const link = document.createElement('a')
      link.href = url
      link.download = documento.nome_arquivo
      // Âncora ligada ao documento e revogação adiada: um <a> desconectado
      // não dispara download no Firefox, e revogar o objectURL na mesma volta
      // do event loop aborta a gravação de arquivos grandes no Chromium. Nos
      // dois casos o download falharia em silêncio — sem exceção para o catch
      // pegar, o operador ficaria olhando um botão que não faz nada.
      document.body.appendChild(link)
      link.click()
      link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (erro) {
      setErroDownload(mensagemDeErroDeEvidencia(erro))
    } finally {
      setBaixando(false)
    }
  }

  return (
    <TableRow>
      <TableCell>
        <div className="space-y-0.5">
          <p className="font-medium">{rotuloTipoDocumento(documento.tipo)}</p>
          <p className="text-xs break-all text-muted-foreground">{documento.nome_arquivo}</p>
          {documento.storage_objeto === null && (
            <Badge variant="outline" className="text-destructive">
              Sem arquivo guardado
            </Badge>
          )}
          {erroDownload && (
            <p role="alert" className="text-xs text-destructive">
              {erroDownload}
            </p>
          )}
        </div>
      </TableCell>
      <TableCell className="tabular-nums">
        {new Date(documento.arquivado_em).toLocaleDateString('pt-BR')}
      </TableCell>
      <TableCell className="tabular-nums">{formatarDataIso(documento.retencao_ate)}</TableCell>
      <TableCell className="font-mono text-xs" title={documento.sha256}>
        {hashAbreviado(documento.sha256)}
      </TableCell>
      <TableCell>
        <div className="flex justify-end gap-1">
          <Button
            size="sm"
            variant="ghost"
            onClick={baixar}
            disabled={baixando || documento.storage_objeto === null}
            aria-label={`Baixar ${documento.nome_arquivo}`}
          >
            <Download />
            {baixando ? 'Baixando…' : 'Baixar'}
          </Button>
          <VerificarDocumentoDialog
            documentoId={documento.id}
            nomeArquivo={documento.nome_arquivo}
          />
        </div>
      </TableCell>
    </TableRow>
  )
}
