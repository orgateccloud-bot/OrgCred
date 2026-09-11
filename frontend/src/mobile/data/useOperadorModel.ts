import { useQuery } from '@tanstack/react-query'
import {
  getAuditoriaApiAuditoriaGetOptions,
  getCapitalSnapshotApiCapitalSnapshotGetOptions,
  getAgingApiCobrancaAgingGetOptions,
  getMeApiMeGetOptions,
  getOperacoesApiOperacoesGetOptions,
} from '@/api/generated/@tanstack/react-query.gen'
import type { MobileIconName } from '../icons'
import type { ToneKey } from '../theme'

/**
 * Modelo derivado do app mobile operador — o "renderVals" do design, porém
 * alimentado pela API real (O BANCO DECIDE, não o cliente).
 *
 * Cobre o que a HOME e a navegação precisam: capital (teto/comprometido/
 * disponível), contagem de operações, integridade da cadeia, aging (atraso),
 * ledger decorado e papel do usuário. As telas de LISTA (Operações, Tomadores,
 * Cobrança) buscam por conta própria via hooks gerados — o cache do react-query
 * é compartilhado, então não há busca duplicada.
 *
 * Nada de cor de tema aqui: devolvemos `nivelUtilizacao` e nomes de `tone`; a
 * tela resolve para os tokens do tema ativo. Assim o modelo é independente do
 * tema escolhido.
 */

export type NivelUtilizacao = 'zero' | 'ok' | 'warn' | 'danger'

export interface LedgerCard {
  id: string
  titulo: string
  detalhe: string
  valorFmt: string | null
  icon: MobileIconName
  tone: ToneKey
  quebrado?: boolean
}

export interface NotifItem {
  id: string
  icon: MobileIconName
  tone: ToneKey
  titulo: string
  detalhe: string
}

const num = (v: string | number | null | undefined): number => Number(v ?? 0) || 0

const fmt = (v: number) => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })

/** evento_tipo do ledger → rótulo, ícone, tom e sinal do valor. */
function decorarEvento(tipo: string): {
  titulo: string
  icon: MobileIconName
  tone: ToneKey
  sinal: '+' | '-' | null
} {
  switch (tipo) {
    case 'ativacao_operacao':
      return { titulo: 'Ativação de operação', icon: 'check-circle-2', tone: 'neutral', sinal: '-' }
    case 'liquidacao':
      return {
        titulo: 'Liquidação de operação',
        icon: 'arrow-down-left',
        tone: 'positive',
        sinal: '+',
      }
    case 'constituicao':
    case 'constituicao_capital':
      return { titulo: 'Constituição de capital', icon: 'landmark', tone: 'cyan', sinal: '+' }
    case 'reducao':
    case 'reducao_capital':
      return { titulo: 'Redução de capital', icon: 'landmark', tone: 'cyan', sinal: '-' }
    case 'baixa_prejuizo':
      return { titulo: 'Baixa a prejuízo', icon: 'shield-x', tone: 'negative', sinal: null }
    default:
      return {
        titulo: tipo.charAt(0).toUpperCase() + tipo.slice(1).replace(/_/g, ' '),
        icon: 'file-text',
        tone: 'muted',
        sinal: null,
      }
  }
}

function dataHoraCurta(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const dia = d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' }).replace('.', '')
  const hora = d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
  return `${dia}, ${hora}`
}

export interface OperadorModel {
  teto: number
  comprometido: number
  disponivel: number
  tetoFmt: string
  comprometidoFmt: string
  disponivelFmt: string
  tetoZerado: boolean
  utilPct: number
  utilPctLabel: string
  nivelUtilizacao: NivelUtilizacao
  anelOffset: number

  opsAtivasCount: number
  opsTotalCount: number

  cadeiaIntegra: boolean

  atrasadasCount: number
  atrasoSum: number
  atrasoSumFmt: string

  ledger: LedgerCard[]
  notificacoes: NotifItem[]

  papel: string
  isAdmin: boolean
  papelLabel: string
  nomeUsuario: string
}

export interface UseOperadorModel {
  isLoading: boolean
  error: unknown
  model: OperadorModel | null
  refetchAll: () => void
}

const CIRCUNFERENCIA = 327 // 2πr, r=52 — igual ao SVG do design

export function useOperadorModel(): UseOperadorModel {
  const snapshot = useQuery({
    ...getCapitalSnapshotApiCapitalSnapshotGetOptions(),
    refetchInterval: 20_000,
  })
  const operacoes = useQuery(getOperacoesApiOperacoesGetOptions())
  const auditoria = useQuery(getAuditoriaApiAuditoriaGetOptions())
  const aging = useQuery(getAgingApiCobrancaAgingGetOptions())
  const me = useQuery(getMeApiMeGetOptions())

  const isLoading =
    snapshot.isPending || operacoes.isPending || auditoria.isPending || aging.isPending
  // `me` não bloqueia: sem ele o app assume "operador" (menos privilégio) e
  // segue — o backend continua sendo a autoridade de papel a cada request.
  const error = snapshot.error ?? operacoes.error ?? auditoria.error ?? aging.error

  const refetchAll = () => {
    void snapshot.refetch()
    void operacoes.refetch()
    void auditoria.refetch()
    void aging.refetch()
  }

  let model: OperadorModel | null = null
  if (snapshot.data && operacoes.data && auditoria.data && aging.data) {
    const teto = num(snapshot.data.total)
    const comprometido = num(snapshot.data.comprometido)
    const disponivel = num(snapshot.data.disponivel)
    const tetoZerado = teto <= 0
    const utilPct = tetoZerado ? 0 : Math.min(100, Math.round((comprometido / teto) * 100))
    const nivelUtilizacao: NivelUtilizacao = tetoZerado
      ? 'zero'
      : utilPct >= 90
        ? 'danger'
        : utilPct >= 70
          ? 'warn'
          : 'ok'

    const opsAtivasCount = operacoes.data.filter((o) => o.status === 'ativa').length

    const atrasadas = aging.data.operacoes.filter((o) => num(o.valor_vencido) > 0)
    const atrasoSum = atrasadas.reduce((a, o) => a + num(o.valor_vencido), 0)

    const cadeiaIntegra = auditoria.data.integro

    const ledger: LedgerCard[] = auditoria.data.eventos.slice(0, 40).map((e) => {
      const d = decorarEvento(e.evento_tipo)
      const valor = num(e.valor)
      return {
        id: e.id,
        titulo: d.titulo,
        detalhe: `${dataHoraCurta(e.created_at)} · ${e.usuario_nome ?? 'Sistema'}`,
        valorFmt: d.sinal && valor ? `${d.sinal} ${fmt(valor)}` : null,
        icon: d.icon,
        tone: d.tone,
      }
    })

    const notificacoes: NotifItem[] = []
    if (tetoZerado)
      notificacoes.push({
        id: 'n-teto',
        icon: 'alert-triangle',
        tone: 'negative',
        titulo: 'Teto de capital em R$ 0,00',
        detalhe: 'Nenhuma operação pode ser ativada até a integralização.',
      })
    if (!cadeiaIntegra)
      notificacoes.push({
        id: 'n-cadeia',
        icon: 'alert-octagon',
        tone: 'negative',
        titulo: 'Quebra na cadeia de auditoria',
        detalhe: 'Hash registrado não confere — investigar imediatamente.',
      })
    if (atrasadas.length)
      notificacoes.push({
        id: 'n-atraso',
        icon: 'alarm-clock',
        tone: 'negative',
        titulo: `${atrasadas.length} operação(ões) em atraso`,
        detalhe: `${fmt(atrasoSum)} vencido aguardando recebimento.`,
      })
    if (ledger[0])
      notificacoes.push({
        id: `n-ledger-${ledger[0].id}`,
        icon: ledger[0].icon,
        tone: ledger[0].tone,
        titulo: ledger[0].titulo,
        detalhe: ledger[0].detalhe,
      })

    const papel = me.data?.papel ?? 'operador'
    const isAdmin = papel === 'admin'

    model = {
      teto,
      comprometido,
      disponivel,
      tetoFmt: fmt(teto),
      comprometidoFmt: fmt(comprometido),
      disponivelFmt: fmt(disponivel),
      tetoZerado,
      utilPct,
      utilPctLabel: tetoZerado ? '—' : `${utilPct}%`,
      nivelUtilizacao,
      anelOffset: CIRCUNFERENCIA - (CIRCUNFERENCIA * utilPct) / 100,
      opsAtivasCount,
      opsTotalCount: operacoes.data.length,
      cadeiaIntegra,
      atrasadasCount: atrasadas.length,
      atrasoSum,
      atrasoSumFmt: fmt(atrasoSum),
      ledger,
      notificacoes,
      papel,
      isAdmin,
      papelLabel: isAdmin ? 'Administrador' : 'Operador',
      nomeUsuario: me.data?.nome ?? 'Operador',
    }
  }

  return { isLoading, error, model, refetchAll }
}
