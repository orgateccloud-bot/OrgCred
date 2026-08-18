import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Landmark } from 'lucide-react'
import { toast } from 'sonner'
import {
  getMovimentosApiCobrancaMovimentosGetOptions,
  getMovimentosApiCobrancaMovimentosGetQueryKey,
  postMovimentoApiCobrancaMovimentosPostMutation,
} from '@/api/generated/@tanstack/react-query.gen'
import type { MovimentoOut } from '@/api/generated/types.gen'
import { mensagemDeErro } from '@/api/errors'
import { formatarMoeda } from '@/lib/format'
import { ImportarOfxDialog } from '@/components/cobranca/importar-ofx-dialog'
import { rotuloOrigemMovimento } from '@/components/cobranca/mensagens'
import { hashAbreviado } from '@/components/identificacao/mensagens'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

/**
 * De onde a linha veio — e não "quem a cadastrou".
 *
 * A distinção é a defesa inteira de uma ESC que se apoia na rastreabilidade
 * do fluxo financeiro: o movimento importado nasce dos bytes que o banco
 * emitiu e carrega o sha256 desses bytes; o digitado é alguém informando
 * data, valor e documento à mão, e prova apenas que o registro existe. Quem
 * audita precisa separar os dois sem abrir o código — proveniência que a tela
 * não mostra não é proveniência.
 */
function ProvenienciaMovimento({ movimento }: { movimento: MovimentoOut }) {
  const deArquivo = movimento.origem === 'ofx'

  return (
    <div className="space-y-1">
      <Badge variant={deArquivo ? 'secondary' : 'outline'}>
        {rotuloOrigemMovimento(movimento.origem)}
      </Badge>
      {movimento.conta_origem && (
        <p className="font-mono text-xs text-muted-foreground">Conta {movimento.conta_origem}</p>
      )}
      {movimento.arquivo_sha256 && (
        <p
          className="font-mono text-xs text-muted-foreground"
          title={`Resumo do arquivo importado: ${movimento.arquivo_sha256}`}
        >
          {hashAbreviado(movimento.arquivo_sha256)}
        </p>
      )}
      {!deArquivo && <p className="text-xs text-muted-foreground">Sem arquivo do banco por trás</p>}
    </div>
  )
}

/**
 * Extrato bancário registrado.
 *
 * É a fonte de lastro das baixas: nenhuma parcela pode ser dada por paga
 * sem apontar para uma destas linhas (OC011). O documento é único, então
 * reimportar o mesmo extrato — rotina na operação real — não duplica
 * crédito nem permite baixar duas parcelas com o mesmo dinheiro.
 */
export function MovimentosBancarios() {
  const queryClient = useQueryClient()
  const { data, error, isPending } = useQuery(getMovimentosApiCobrancaMovimentosGetOptions())

  function invalidar() {
    queryClient.invalidateQueries({ queryKey: getMovimentosApiCobrancaMovimentosGetQueryKey() })
  }

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-4">
        <div className="space-y-1.5">
          <CardTitle>Extrato bancário</CardTitle>
          <CardDescription>
            Lastro das baixas. Nenhuma parcela é dada por paga sem apontar para uma destas linhas —
            o documento é único, então reimportar o mesmo extrato não duplica crédito. A coluna{' '}
            <strong>Origem</strong> diz como a linha entrou: importada do arquivo que o banco
            emitiu, com o resumo criptográfico dos bytes ao lado, ou digitada à mão.
          </CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          <ImportarOfxDialog />
          <RegistrarMovimentoDialog onSucesso={invalidar} />
        </div>
      </CardHeader>
      <CardContent>
        {isPending && <Skeleton className="h-24" />}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {mensagemDeErro(error)}
          </p>
        )}
        {data && data.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Nenhum movimento registrado. Importe o extrato do banco — ou registre as linhas à mão —
            antes de baixar parcelas.
          </p>
        )}
        {data && data.length > 0 && (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Data</TableHead>
                  <TableHead className="text-right">Valor</TableHead>
                  <TableHead>Documento</TableHead>
                  <TableHead>Descrição</TableHead>
                  <TableHead>Origem</TableHead>
                  <TableHead>Situação</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((m) => (
                  <TableRow key={m.id}>
                    <TableCell className="tabular-nums">
                      {new Date(`${m.data_movimento}T00:00:00`).toLocaleDateString('pt-BR')}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {formatarMoeda(String(m.valor))}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{m.documento}</TableCell>
                    <TableCell className="text-muted-foreground">{m.descricao ?? '—'}</TableCell>
                    <TableCell>
                      <ProvenienciaMovimento movimento={m} />
                    </TableCell>
                    <TableCell>
                      {m.conciliado ? (
                        <Badge variant="outline" className="text-success">
                          Conciliado
                        </Badge>
                      ) : (
                        <Badge variant="outline">Disponível</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function RegistrarMovimentoDialog({ onSucesso }: { onSucesso: () => void }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState(new Date().toISOString().slice(0, 10))
  const [valor, setValor] = useState('')
  const [documento, setDocumento] = useState('')
  const [descricao, setDescricao] = useState('')

  const mutation = useMutation(postMovimentoApiCobrancaMovimentosPostMutation())

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate(
      {
        body: {
          data_movimento: data,
          valor,
          documento: documento.trim(),
          descricao: descricao.trim() || null,
        },
      },
      {
        onSuccess: () => {
          onSucesso()
          setOpen(false)
          mutation.reset()
          setValor('')
          setDocumento('')
          setDescricao('')
          toast.success('Movimento registrado.')
        },
      },
    )
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(aberto) => {
        setOpen(aberto)
        if (!aberto) mutation.reset()
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Landmark />
          Registrar movimento
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Registrar movimento bancário</DialogTitle>
          <DialogDescription>
            Uma linha do extrato. O <strong>documento</strong> é o identificador dela no banco
            (FITID, no OFX) e é único — é o que impede o mesmo crédito de baixar duas parcelas.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="mov-data">Data</Label>
              <Input
                id="mov-data"
                type="date"
                required
                value={data}
                onChange={(e) => setData(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="mov-valor">Valor (R$)</Label>
              <Input
                id="mov-valor"
                type="number"
                min="0.01"
                step="0.01"
                required
                value={valor}
                onChange={(e) => setValor(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="mov-documento">Documento</Label>
            <Input
              id="mov-documento"
              required
              value={documento}
              onChange={(e) => setDocumento(e.target.value)}
              placeholder="FITID ou identificador da linha no extrato"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="mov-descricao">Descrição (opcional)</Label>
            <Input
              id="mov-descricao"
              value={descricao}
              onChange={(e) => setDescricao(e.target.value)}
            />
          </div>

          {mutation.isError && (
            <p role="alert" className="text-sm text-destructive">
              {mensagemDeErro(mutation.error)}
            </p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={!valor || !documento.trim() || mutation.isPending}>
              {mutation.isPending ? 'Registrando…' : 'Registrar'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
