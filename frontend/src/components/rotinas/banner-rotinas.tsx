import { AlertTriangle } from 'lucide-react'
import {
  descreverAtraso,
  rotinasComProblema,
  rotuloRotina,
  type EstadoRotina,
  type EstadoRotinas,
} from './estado-rotinas'

/**
 * Aviso no dashboard quando alguma rotina periódica está ATRASADA ou FALHOU na
 * última execução.
 *
 * POR QUE ELE EXISTE. As quatro rotinas (régua de inadimplência, varredura de
 * PLD, backup e teste de restauração) rodam num serviço de cron, e até a
 * migration 025 o app não tinha como saber se elas rodaram. A detecção de
 * incidente dependia de alguém abrir o painel do provedor — e o pior modo de
 * falha delas nem chega lá: uma rotina que PARA DE SER AGENDADA não produz
 * execução vermelha nenhuma. Ela simplesmente deixa de acontecer.
 *
 * O QUE ELE MOSTRA, e por que o tempo vem antes do erro: para cada rotina com
 * problema, HÁ QUANTO TEMPO ela não roda com sucesso. Uma rotina que nunca
 * falhou e parou há nove dias é o caso perigoso justamente porque não há falha
 * para ver, e a mensagem de erro — quando existe — é a parte que o operador já
 * teria de outras formas.
 *
 * QUANDO ELE SOME: quando as quatro voltarem a ter sucesso recente. É o backend
 * que decide isso (`saudavel`), contra os limiares declarados junto com as
 * rotinas (`app/rotinas.py`, LIMITE_ATRASO_HORAS): 36h para as diárias — 24h
 * dispararia por construção a cada jitter do agendador — e 45 dias para o teste
 * mensal de restauração, cuja distância legítima entre duas execuções passa de
 * 31 dias. A régua NÃO é reimplementada aqui: duas cópias do limiar
 * divergiriam, e a tela passaria a afirmar uma pontualidade que ninguém pratica.
 *
 * `role="status"` e não `role="alert"`: o aviso chega junto com o carregamento
 * da página, e `alert` interromperia a leitura da tela inteira toda vez. Região
 * viva, anunciada quando o leitor de tela chegar nela.
 */
export function BannerRotinas({ estado }: { estado?: EstadoRotinas }) {
  if (!estado || estado.saudavel) return null

  const problemas = rotinasComProblema(estado)
  // Defesa contra um `saudavel: false` sem nenhuma rotina listada: um banner
  // vazio afirmando que algo está errado é pior que banner nenhum.
  if (problemas.length === 0) return null

  return (
    <div
      role="status"
      className="flex items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4"
    >
      <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden />
      <div className="space-y-2">
        <p className="font-medium text-destructive">
          {problemas.length === 1
            ? 'Uma rotina periódica não está em dia'
            : `${problemas.length} rotinas periódicas não estão em dia`}
        </p>
        <p className="text-sm text-muted-foreground">
          Enquanto elas não rodarem, a inadimplência é declarada com atraso, a varredura de PLD não
          detecta nada novo e o backup do dia pode não existir. Verifique o serviço de rotinas.
        </p>
        <ul className="space-y-1.5">
          {problemas.map((rotina) => (
            <LinhaRotina key={rotina.rotina} rotina={rotina} />
          ))}
        </ul>
      </div>
    </div>
  )
}

function LinhaRotina({ rotina }: { rotina: EstadoRotina }) {
  return (
    <li className="text-sm">
      <span className="font-medium">{rotuloRotina(rotina.rotina)}</span>
      <span className="text-muted-foreground">
        {' — '}
        {descreverAtraso(rotina.horas_desde_ultimo_sucesso)}
        {rotina.limite_horas !== null && rotina.atrasada && (
          <> (limite: {formatarLimite(rotina.limite_horas)})</>
        )}
      </span>
      {/* O erro entra DEPOIS do tempo e só quando existe. Ele é o detalhe que
          explica uma falha; o tempo é o que denuncia a ausência de execução,
          que é o caso sem nenhum outro sinal. */}
      {rotina.falhou && rotina.erro && (
        <p className="mt-0.5 font-mono text-xs break-words text-muted-foreground">{rotina.erro}</p>
      )}
    </li>
  )
}

/** Horas viram dias a partir de 48h — mesma régua de `descreverAtraso`. */
function formatarLimite(horas: number): string {
  return horas < 48 ? `${horas}h` : `${Math.round(horas / 24)} dias`
}
