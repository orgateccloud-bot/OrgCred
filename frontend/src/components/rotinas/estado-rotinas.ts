import { queryOptions } from '@tanstack/react-query'
import { client } from '@/api/client'

/**
 * Estado das rotinas periódicas — `GET /api/auditoria/rotinas` (migration 025).
 *
 * POR QUE ISTO NÃO SAI DO CLIENTE GERADO. O `frontend/src/api/generated/` é
 * produzido a partir do `/openapi.json` do backend em execução e não se edita à
 * mão; enquanto ele não for regerado, este endpoint não existe lá. A chamada
 * usa o MESMO `client` que o gerado usa (interceptors de Authorization, refresh
 * de token e tradução de erro incluídos), com a mesma forma de `queryOptions`
 * — de modo que, quando o cliente for regerado, trocar por
 * `getEstadoRotinasApiAuditoriaRotinasGetOptions()` é substituir uma linha.
 *
 * O caminho é RELATIVO ('/api/...'), como todo o resto: o `baseUrl` do cliente
 * é resolvido em `api/client.ts` e escrever host aqui quebraria produção.
 */

export type ResultadoRotina = 'sucesso' | 'falha' | 'dispensada'

export interface EstadoRotina {
  rotina: string
  /** Última vez que o cron olhou para esta rotina — inclui as dispensadas. */
  ultima_tentativa: string | null
  /** Última execução que fez o trabalho (sucesso ou falha). */
  ultima_execucao: string | null
  iniciada_em: string | null
  duracao_s: string | null
  resultado: ResultadoRotina | null
  erro: string | null
  detalhe: Record<string, unknown>
  ultimo_sucesso: string | null
  /** Nulo = nunca houve sucesso. É o caso mais grave, não o mais brando. */
  horas_desde_ultimo_sucesso: number | null
  limite_horas: number | null
  atrasada: boolean
  falhou: boolean
  nunca_executou: boolean
}

export interface EstadoRotinas {
  verificado_em: string
  saudavel: boolean
  rotinas: EstadoRotina[]
}

export const CHAVE_ESTADO_ROTINAS = ['api', 'auditoria', 'rotinas'] as const

export function estadoRotinasQueryOptions() {
  return queryOptions({
    queryKey: CHAVE_ESTADO_ROTINAS,
    queryFn: async () => {
      const { data } = await client.get<{ 200: EstadoRotinas }, unknown, true>({
        url: '/api/auditoria/rotinas',
        throwOnError: true,
      })
      return data
    },
    // A cada 5 minutos, e não a cada 20 segundos como o snapshot de capital: o
    // dado muda uma vez por dia. Um polling curto aqui gastaria requisição para
    // reconfirmar um número que só se move de madrugada — e o atraso que
    // interessa é medido em horas, então cinco minutos de defasagem não mudam
    // nenhuma decisão.
    refetchInterval: 5 * 60_000,
  })
}

/**
 * Nome de tela de cada rotina. A chave é o nome que o executor usa
 * (`app/rotinas.py`), e o valor diz O QUE ela faz — "aging" não significa nada
 * para quem opera a ESC, e o painel existe para essa pessoa.
 *
 * Nome desconhecido cai no próprio nome cru: é o que o backend faz com uma
 * rotina que está na trilha e não no executor, e esconder a linha seria pior
 * que mostrá-la feia.
 */
const ROTULOS: Record<string, string> = {
  aging: 'Régua de inadimplência',
  atipicidades: 'Varredura de atipicidade (PLD)',
  backup: 'Backup do banco',
  restore_test: 'Teste de restauração do backup',
}

export function rotuloRotina(nome: string): string {
  return ROTULOS[nome] ?? nome
}

/**
 * Quanto tempo faz que a rotina rodou com sucesso, em texto.
 *
 * Abaixo de 48h a unidade é HORA, e acima é DIA. Não é preciosismo: o limiar
 * das rotinas diárias é 36h, e "há 1 dia" arredondaria justamente a faixa em
 * que a decisão é tomada — o operador precisa distinguir 30h (normal) de 40h
 * (atrasada), e essas duas viram o mesmo "1 dia".
 */
export function descreverAtraso(horas: number | null): string {
  if (horas === null) return 'nunca executou'
  if (horas < 48) return `sem sucesso há ${Math.round(horas)}h`
  return `sem sucesso há ${Math.round(horas / 24)} dias`
}

/**
 * As rotinas que merecem aviso, na ordem em que o operador deve olhá-las.
 *
 * A ORDEM É POR TEMPO SEM SUCESSO, decrescente, com "nunca executou" no topo —
 * e não por falha primeiro. É a inversão que o problema pede: a rotina que
 * falhou já se anuncia (há uma execução vermelha, há uma mensagem de erro), e a
 * que parou de rodar não se anuncia por nada. Colocar as falhas em cima
 * empurraria para o fim da lista exatamente o caso que ninguém mais tem como
 * descobrir.
 */
export function rotinasComProblema(estado: EstadoRotinas): EstadoRotina[] {
  return estado.rotinas
    .filter((r) => r.atrasada || r.falhou)
    .sort((a, b) => {
      const horasA = a.horas_desde_ultimo_sucesso
      const horasB = b.horas_desde_ultimo_sucesso
      if (horasA === horasB) return a.rotina.localeCompare(b.rotina)
      if (horasA === null) return -1
      if (horasB === null) return 1
      return horasB - horasA
    })
}
