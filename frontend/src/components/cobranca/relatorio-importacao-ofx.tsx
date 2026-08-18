import { AlertTriangle, CalendarRange, CheckCircle2, Landmark } from 'lucide-react'
import type { ImportacaoOfxOut } from '@/api/generated/types.gen'
// Reuso deliberado: `formatarDataIso` não passa por `new Date()`, que em fuso
// negativo devolveria o dia anterior para uma data 'YYYY-MM-DD'. Num período
// de extrato, um dia a menos na borda é exatamente o engano que este bloco
// existe para revelar. `hashAbreviado` corta o sha256 no mesmo ponto usado na
// evidência de identificação, para o operador conferir de olho sempre igual.
import { formatarDataIso, hashAbreviado } from '@/components/identificacao/mensagens'
import { Badge } from '@/components/ui/badge'

/**
 * Um destino possível para uma linha do extrato.
 *
 * O texto não é decoração: `ja_registrados` e `repetidos_no_arquivo` viram
 * ambos "não criado" e significam coisas opostas — reimportação normal contra
 * anomalia do arquivo do banco. Quem não leu `capital_engine` não tem como
 * inferir isso de um número solto.
 */
interface Destino {
  chave: string
  rotulo: string
  quantidade: number
  explicacao: string
  /** Destaque de anomalia: o número não deveria existir e alguém precisa olhar. */
  anomalia?: boolean
}

function destinos(relatorio: ImportacaoOfxOut): Destino[] {
  return [
    {
      chave: 'criados',
      rotulo: 'Movimentos criados',
      quantidade: relatorio.criados,
      explicacao:
        'Créditos novos. Já estão na lista de movimentos e podem lastrear a baixa de parcelas.',
    },
    {
      chave: 'ja_registrados',
      rotulo: 'Já registrados',
      quantidade: relatorio.ja_registrados,
      explicacao:
        'Créditos que o sistema já tinha: este extrato, ou outro que continha as mesmas linhas, ' +
        'foi importado antes. Não é erro — o identificador do banco (FITID) é único, então ' +
        'reimportar não duplica crédito nem permite baixar duas parcelas com o mesmo dinheiro.',
    },
    {
      chave: 'repetidos_no_arquivo',
      rotulo: 'Repetidos dentro do arquivo',
      quantidade: relatorio.repetidos_no_arquivo,
      anomalia: relatorio.repetidos_no_arquivo > 0,
      explicacao:
        'O próprio arquivo do banco trouxe o mesmo FITID mais de uma vez. Isso é anomalia DO ' +
        'ARQUIVO, não do sistema: só a primeira ocorrência foi considerada. Confira no extrato ' +
        'se são de fato a mesma transação antes de usar este arquivo como prova.',
    },
    {
      chave: 'debitos_ignorados',
      rotulo: 'Débitos ignorados',
      quantidade: relatorio.debitos_ignorados,
      explicacao:
        'Saídas da conta. Só crédito vira movimento bancário — débito não baixa parcela —, e por ' +
        'isso eles são contados aqui em vez de desaparecerem em silêncio.',
    },
  ]
}

/**
 * O relatório da importação.
 *
 * Este bloco é o produto do endpoint, não o rodapé dele. "Importado com
 * sucesso" descartaria a única informação que torna a importação auditável:
 * `lidas` fecha com a soma dos quatro destinos, e é essa aritmética — exibida
 * por extenso, com os quatro parcelas somando à vista — que permite ao
 * operador afirmar que nenhuma linha do extrato dele se perdeu no caminho.
 *
 * Período e contas ficam no topo porque o engano mais provável aqui não é
 * técnico: é importar o mês errado ou a conta errada, e nesse caso todos os
 * números abaixo estarão certos para o arquivo errado.
 */
export function RelatorioImportacaoOfx({ relatorio }: { relatorio: ImportacaoOfxOut }) {
  const linhas = destinos(relatorio)
  const soma = linhas.reduce((total, destino) => total + destino.quantidade, 0)
  const fecha = soma === relatorio.lidas
  const parcelasSomadas = linhas.map((d) => d.quantidade).join(' + ')

  return (
    <div className="space-y-4">
      <div className="space-y-2 rounded-lg border border-border p-3 text-sm">
        <p className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-medium">{relatorio.arquivo}</span>
          <span
            className="font-mono text-xs text-muted-foreground"
            title={relatorio.arquivo_sha256}
          >
            {hashAbreviado(relatorio.arquivo_sha256)}
          </span>
        </p>
        <p className="flex gap-2 text-muted-foreground">
          <CalendarRange className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            {relatorio.periodo_inicio && relatorio.periodo_fim ? (
              <>
                Período do extrato:{' '}
                <strong className="text-foreground tabular-nums">
                  {formatarDataIso(relatorio.periodo_inicio)}
                </strong>{' '}
                a{' '}
                <strong className="text-foreground tabular-nums">
                  {formatarDataIso(relatorio.periodo_fim)}
                </strong>
                . Se não é o período que você queria, o arquivo está errado — nenhuma parcela foi
                baixada, então basta importar o correto.
              </>
            ) : (
              <>O arquivo não trouxe transação nenhuma, então não há período a conferir.</>
            )}
          </span>
        </p>
        <p className="flex gap-2 text-muted-foreground">
          <Landmark className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span className="flex flex-wrap items-center gap-1.5">
            {relatorio.contas.length > 0 ? (
              <>
                <span>{relatorio.contas.length === 1 ? 'Conta:' : 'Contas:'}</span>
                {relatorio.contas.map((conta) => (
                  <Badge key={conta} variant="outline" className="font-mono">
                    {conta}
                  </Badge>
                ))}
              </>
            ) : (
              <span>O arquivo não identificou a conta de origem.</span>
            )}
          </span>
        </p>
      </div>

      <div className="space-y-2">
        <p className="text-sm">
          <strong className="tabular-nums">{relatorio.lidas}</strong>{' '}
          {relatorio.lidas === 1 ? 'linha lida' : 'linhas lidas'} no arquivo, com{' '}
          <strong className="tabular-nums">{relatorio.creditos}</strong>{' '}
          {relatorio.creditos === 1 ? 'crédito' : 'créditos'}. Cada linha teve um destino:
        </p>

        <ul className="space-y-2">
          {linhas.map((destino) => (
            <li
              key={destino.chave}
              // `data-anomalia` não é gancho de teste decorativo: é a única
              // afirmação legível de que ESTE destino está ou não sinalizado.
              // A moldura e o ícone são cor — e o ponto do relatório é que
              // reimportação (`ja_registrados`) NUNCA seja pintada como falha,
              // enquanto FITID repetido pelo banco sempre seja. Sem o atributo,
              // trocar um pelo outro não muda nada que se possa checar.
              data-anomalia={destino.anomalia ? 'sim' : 'nao'}
              className={`rounded-lg border p-3 text-sm ${
                destino.anomalia ? 'border-warning/40 bg-warning/5' : 'border-border'
              }`}
            >
              <p className="flex items-baseline justify-between gap-3">
                <span className="flex items-center gap-1.5 font-medium">
                  {destino.anomalia && (
                    <AlertTriangle className="size-4 shrink-0 text-warning" aria-hidden />
                  )}
                  {destino.rotulo}
                </span>
                <span className="font-mono text-base tabular-nums">{destino.quantidade}</span>
              </p>
              <p className="mt-1 text-muted-foreground">{destino.explicacao}</p>
            </li>
          ))}
        </ul>
      </div>

      {relatorio.lidas === 0 ? (
        /*
         * Arquivo VÁLIDO e VAZIO — 200, não erro: `ler_ofx` só recusa bytes
         * vazios e OFX malformado, então um extrato sem nenhuma `<STMTTRN>`
         * (mês sem movimento, ou exportação com o filtro de datas errado)
         * chega aqui com todos os contadores zerados.
         *
         * Zero fecha com zero, e a versão anterior deste bloco respondia a
         * isso com o selo verde "Nenhuma linha do extrato se perdeu" — a
         * frase certa para o caso errado. Nenhuma linha se perdeu porque
         * nenhuma linha existia: a aritmética não afirma nada aqui, e a
         * conferência que revelaria a exportação errada — o período — é
         * justamente a que some, porque um arquivo sem transação não tem
         * período. Um verde nesse ponto ensina o operador a dar por importado
         * um mês em que nada entrou.
         */
        <p
          role="status"
          className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-sm"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <span>
            <strong>Não há o que conferir:</strong> o arquivo é um OFX válido, mas não trouxe
            nenhuma transação, e <strong>nenhum movimento foi criado</strong>. Extrato vazio quase
            sempre é exportação do período errado ou de conta sem movimento — confira no banco antes
            de dar o mês por importado.
          </span>
        </p>
      ) : fecha ? (
        <p
          role="status"
          className="flex gap-2 rounded-lg border border-success/40 bg-success/5 p-3 text-sm"
        >
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
          <span>
            <strong>Conferência fecha:</strong>{' '}
            <span className="font-mono tabular-nums">
              {parcelasSomadas} = {soma}
            </span>
            , igual às {relatorio.lidas} {relatorio.lidas === 1 ? 'linha lida' : 'linhas lidas'} do
            arquivo. Nenhuma linha do extrato se perdeu.
          </span>
        </p>
      ) : (
        <p
          role="alert"
          className="flex gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
          <span>
            <strong>Conferência NÃO fecha:</strong> os destinos somam{' '}
            <span className="font-mono tabular-nums">{soma}</span>, mas o arquivo tinha{' '}
            <span className="font-mono tabular-nums">{relatorio.lidas}</span>{' '}
            {relatorio.lidas === 1 ? 'linha' : 'linhas'}. Há {Math.abs(relatorio.lidas - soma)} sem
            destino explicado — não use esta importação como prova sem conferir o extrato original.
          </span>
        </p>
      )}
    </div>
  )
}
