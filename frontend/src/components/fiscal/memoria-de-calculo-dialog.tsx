import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ClipboardCopy, Download, ListTree, TriangleAlert } from 'lucide-react'
import { mensagemDeErro } from '@/api/errors'
import { formatarMoeda } from '@/lib/format'
import { formatarPercentual } from '@/lib/rotulos'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { buscarMemoriaDeCalculo } from '@/components/fiscal/memoria-api'
import {
  memoriaComoCsv,
  memoriaComoTexto,
  memoriaQueryKey,
  nomeDoArquivo,
  rotuloPeriodo,
  rotuloRegime,
  type LinhaMemoria,
  type MemoriaCalculo,
} from '@/components/fiscal/memoria'

/** Fração (0,32) para exibição em percentual (32,00%). */
const pct = (v: string) => formatarPercentual(Number(v) * 100, 2)

/**
 * Memória de cálculo de uma apuração.
 *
 * A apuração é imutável (OC016) e o contador recebe números prontos. Sem a
 * derivação à vista, ele não tem como conferir de onde eles saíram — e é este
 * o documento que alguém vai ter que defender. Cada tributo aparece com o
 * caminho inteiro: receita considerada, base (com a presunção, quando há),
 * alíquota e valor.
 *
 * Nada aqui recalcula nada: a aritmética é do banco e a conferência dela é do
 * backend, que devolve o recalculado ao lado do gravado. Refazer a conta em
 * JavaScript com float seria trocar a fonte da verdade por outra pior.
 */
export function MemoriaDeCalculoDialog({
  apuracaoId,
  rotulo,
}: {
  apuracaoId: string
  rotulo: string
}) {
  const [open, setOpen] = useState(false)
  const memoria = useQuery({
    queryKey: memoriaQueryKey(apuracaoId),
    queryFn: () => buscarMemoriaDeCalculo(apuracaoId),
    // Só busca quando alguém abre: a lista de apurações não precisa carregar a
    // memória de todos os trimestres para desenhar um botão.
    enabled: open,
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" aria-label={`Memória de cálculo — ${rotulo}`}>
          <ListTree />
          Memória
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>Memória de cálculo</DialogTitle>
          <DialogDescription>
            Recalculada a partir dos parâmetros congelados dentro da própria apuração — não do
            parâmetro vigente hoje. É o que torna o número conferível linha a linha, mesmo anos
            depois.
          </DialogDescription>
        </DialogHeader>

        {memoria.isPending && <Skeleton className="h-64" />}
        {memoria.error && (
          <p role="alert" className="text-sm text-destructive">
            {mensagemDeErro(memoria.error)}
          </p>
        )}
        {memoria.data && <CorpoDaMemoria memoria={memoria.data} />}
      </DialogContent>
    </Dialog>
  )
}

function CorpoDaMemoria({ memoria }: { memoria: MemoriaCalculo }) {
  return (
    <div className="space-y-4">
      <dl className="grid gap-x-8 gap-y-1 text-sm sm:grid-cols-2">
        <Linha rotulo="Período">{rotuloPeriodo(memoria)}</Linha>
        <Linha rotulo="Reconhecimento">{rotuloRegime(memoria.regime_reconhecimento)}</Linha>
        <Linha rotulo="Receita de juros">{formatarMoeda(memoria.receita_juros)}</Linha>
        <Linha rotulo="Mora e multa recebidas">{formatarMoeda(memoria.receita_demais)}</Linha>
        <Linha rotulo="Receita total tributada">
          <strong>{formatarMoeda(memoria.receita_total)}</strong>
        </Linha>
      </dl>

      {!memoria.confere && <AvisoDivergencia memoria={memoria} />}

      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Tributo</TableHead>
              <TableHead className="text-right">Receita considerada</TableHead>
              <TableHead className="text-right">Presunção</TableHead>
              <TableHead className="text-right">Base de cálculo</TableHead>
              <TableHead className="text-right">Alíquota</TableHead>
              <TableHead className="text-right">Valor</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {memoria.linhas.map((linha) => (
              <LinhaDeTributo key={linha.chave} linha={linha} />
            ))}
            <TableRow>
              <TableCell className="font-medium">Total de tributos</TableCell>
              <TableCell colSpan={4} />
              <TableCell className="text-right font-mono font-medium tabular-nums">
                {formatarMoeda(memoria.total_tributos)}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>

      <BotoesDeSaida memoria={memoria} />
    </div>
  )
}

function LinhaDeTributo({ linha }: { linha: LinhaMemoria }) {
  // Limite e excedente à vista só no adicional: é a linha que mais gera
  // dúvida, e sem eles "R$ 0,00" parece esquecimento em vez de "a base não
  // chegou ao limite do trimestre".
  const temLimite = linha.limite !== null && linha.excedente !== null
  const excedeu = temLimite && Number(linha.excedente) > 0

  return (
    <TableRow>
      <TableCell className="align-top">
        <div className="space-y-1">
          <p className="font-medium">{linha.tributo}</p>
          {temLimite && (
            <p className="text-xs text-muted-foreground">
              {excedeu ? (
                <>
                  Base {formatarMoeda(linha.base_calculo)} − limite{' '}
                  {formatarMoeda(linha.limite as string)} = excedente{' '}
                  <span className="font-mono tabular-nums">
                    {formatarMoeda(linha.excedente as string)}
                  </span>
                  . O adicional incide só sobre o excedente.
                </>
              ) : (
                <>
                  Base {formatarMoeda(linha.base_calculo)} abaixo do limite de{' '}
                  {formatarMoeda(linha.limite as string)} no trimestre: excedente zero, o adicional
                  não incide.
                </>
              )}
            </p>
          )}
          {!linha.confere && (
            <p className="text-xs text-destructive">
              Gravado: {formatarMoeda(linha.valor_gravado)}
            </p>
          )}
        </div>
      </TableCell>
      <TableCell className="text-right align-top font-mono tabular-nums">
        {formatarMoeda(linha.receita_considerada)}
      </TableCell>
      <TableCell className="text-right align-top font-mono tabular-nums">
        {linha.percentual_presuncao === null ? (
          <span className="text-muted-foreground" title="Cumulativo: incide sobre a receita">
            —
          </span>
        ) : (
          pct(linha.percentual_presuncao)
        )}
      </TableCell>
      <TableCell className="text-right align-top font-mono tabular-nums">
        {excedeu ? formatarMoeda(linha.excedente as string) : formatarMoeda(linha.base_calculo)}
      </TableCell>
      <TableCell className="text-right align-top font-mono tabular-nums">
        {pct(linha.aliquota)}
      </TableCell>
      <TableCell className="text-right align-top font-mono tabular-nums">
        {formatarMoeda(linha.valor)}
        {!linha.confere && (
          <Badge variant="destructive" className="ml-2">
            Diverge
          </Badge>
        )}
      </TableCell>
    </TableRow>
  )
}

/**
 * O aviso que existe porque a apuração é imutável.
 *
 * Recalcular a partir do snapshot só pode discordar do gravado se a fórmula
 * mudou depois de a apuração existir. OC016 impede corrigir a linha, então
 * esconder isso deixaria uma declaração errada com aparência de auditada — a
 * única providência possível é retificar o trimestre, e para isso é preciso
 * enxergar o problema.
 */
function AvisoDivergencia({ memoria }: { memoria: MemoriaCalculo }) {
  return (
    <div
      role="alert"
      className="flex gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4"
    >
      <TriangleAlert className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden />
      <div className="space-y-2">
        <p className="font-medium text-destructive">O recálculo não reproduz os valores gravados</p>
        <p className="text-sm text-muted-foreground">
          Refazendo as contas com os mesmos percentuais e alíquotas que estão congelados dentro
          desta apuração, o resultado é outro — o que só acontece se a fórmula de apuração mudou
          depois que este trimestre foi gravado. A apuração não pode ser editada; a correção se faz
          apurando o trimestre de novo, o que grava uma versão retificadora.
        </p>
        <ul className="space-y-1 text-sm">
          {memoria.divergencias.map((d) => (
            <li key={d.campo} className="font-mono tabular-nums">
              <span className="font-sans">{d.rotulo}:</span> recalculado{' '}
              {formatarMoeda(d.calculado)}, gravado {formatarMoeda(d.gravado)}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

/**
 * As duas saídas para fora da tela.
 *
 * O destino real deste dado é o escritório de contabilidade: texto para colar
 * em e-mail ou parecer, CSV para abrir na planilha onde a conferência de fato
 * acontece.
 */
function BotoesDeSaida({ memoria }: { memoria: MemoriaCalculo }) {
  const [aviso, setAviso] = useState<string | null>(null)

  async function copiar() {
    try {
      await navigator.clipboard.writeText(memoriaComoTexto(memoria))
      setAviso('Memória copiada para a área de transferência.')
    } catch {
      // Área de transferência negada (permissão, contexto não seguro) é
      // silenciosa por natureza: sem esta mensagem o contador clicaria, colaria
      // o conteúdo antigo e não saberia por quê.
      setAviso('Não foi possível copiar. Use o download em CSV.')
    }
  }

  function baixar() {
    // BOM antes do conteúdo: sem ele o Excel em pt-BR abre o CSV em Latin-1 e
    // "Apuração" vira "ApuraÃ§Ã£o" na primeira coluna do documento fiscal.
    const blob = new Blob(['﻿', memoriaComoCsv(memoria)], {
      type: 'text/csv;charset=utf-8',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = nomeDoArquivo(memoria)
    // Âncora ligada ao documento antes do clique e revogação adiada: um <a>
    // desconectado não dispara download no Firefox, e revogar na mesma volta do
    // event loop aborta a gravação no Chromium — nos dois casos falharia em
    // silêncio. Mesmo cuidado do download de evidência (identificação).
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
    setAviso('Arquivo gerado.')
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button type="button" variant="outline" size="sm" onClick={copiar}>
        <ClipboardCopy />
        Copiar memória
      </Button>
      <Button type="button" variant="outline" size="sm" onClick={baixar}>
        <Download />
        Baixar CSV
      </Button>
      <p role="status" className="text-xs text-muted-foreground">
        {aviso}
      </p>
    </div>
  )
}

function Linha({ rotulo, children }: { rotulo: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-border/50 py-1">
      <dt className="text-muted-foreground">{rotulo}</dt>
      <dd className="text-right font-mono tabular-nums">{children}</dd>
    </div>
  )
}
