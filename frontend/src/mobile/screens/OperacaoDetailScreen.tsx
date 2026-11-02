import { useQuery } from '@tanstack/react-query'
import { getOperacaoApiOperacoesOperacaoIdGetOptions } from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { rotuloTipo } from '@/lib/rotulos'
import { useMobileTheme } from '../MobileThemeContext'
import { useMobileApp, type SheetType } from '../MobileAppContext'
import { statusMeta } from '../theme'
import { formatarMoeda, formatarTaxa, dataHora } from '../format'
import {
  Screen,
  ScreenScroll,
  TopBar,
  Card,
  StatusPill,
  ScreenError,
  SkeletonBar,
} from '../components/kit'

/** Ação de rodapé por status, mapeada aos sheets de ciclo de vida. */
type Acao = { label: string; variant: 'primary' | 'secondary' | 'danger'; sheet: SheetType }

function acoesPorStatus(status: string): Acao[] {
  switch (status) {
    case 'proposta':
      return [
        { label: 'Registrar na entidade', variant: 'primary', sheet: 'registrar' },
        { label: 'Cancelar operação', variant: 'danger', sheet: 'cancelar' },
      ]
    case 'registrada':
      return [
        { label: 'Ativar operação', variant: 'primary', sheet: 'ativar' },
        { label: 'Cancelar operação', variant: 'danger', sheet: 'cancelar' },
      ]
    case 'ativa':
      return [
        { label: 'Liquidar operação', variant: 'primary', sheet: 'liquidar' },
        { label: 'Renegociar', variant: 'secondary', sheet: 'renegociar' },
        { label: 'Marcar inadimplência', variant: 'danger', sheet: 'marcarInadimplente' },
      ]
    case 'inadimplente':
      return [
        { label: 'Liquidar operação', variant: 'primary', sheet: 'liquidar' },
        { label: 'Renegociar', variant: 'secondary', sheet: 'renegociar' },
      ]
    case 'renegociada':
      return [{ label: 'Liquidar operação', variant: 'primary', sheet: 'liquidar' }]
    default:
      return []
  }
}

export function OperacaoDetailScreen() {
  const t = useMobileTheme()
  const app = useMobileApp()
  const opId = app.opSelectedId ?? ''
  const { data, isPending, error } = useQuery(
    getOperacaoApiOperacoesOperacaoIdGetOptions({ path: { operacao_id: opId } }),
  )

  const sm = data ? statusMeta(t, data.status) : null
  const acoes = data ? acoesPorStatus(data.status) : []

  const estiloAcao = (v: Acao['variant']) => {
    if (v === 'primary') return { background: t.grad, color: t.gradFg, border: 'none' }
    if (v === 'danger')
      return { background: t.negBg, color: t.neg, border: `1px solid ${t.negBorder}` }
    return { background: t.surface, color: t.text, border: `1px solid ${t.border2}` }
  }

  return (
    <Screen label="Operação — detalhe">
      <TopBar
        onBack={app.backToOpList}
        title={data?.tomador.razao_social ?? '…'}
        subtitle={data ? rotuloTipo(data.tipo) : undefined}
        trailing={sm ? <StatusPill label={sm.label} bg={sm.bg} fg={sm.fg} /> : undefined}
      />

      <ScreenScroll style={{ padding: '4px 20px 20px', gap: 14 }}>
        {error && <ScreenError mensagem={mensagemDeErro(error)} />}
        {isPending && !data && (
          <>
            <SkeletonBar height={120} style={{ borderRadius: 16 }} />
            <SkeletonBar height={140} style={{ borderRadius: 16 }} />
          </>
        )}

        {data && (
          <>
            <Card style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <Dado label="Principal" valor={formatarMoeda(data.valor_principal)} mono t={t} />
              <Dado label="Taxa a.m." valor={formatarTaxa(data.taxa_juros_mensal)} mono t={t} />
              <Dado label="Parcelas" valor={`${data.numero_parcelas}x`} mono t={t} />
              <Dado
                label="Registro"
                valor={data.registro_entidade_ref ?? 'Pendente'}
                mono
                cor={data.registro_entidade_ref ? t.accentText : t.muted}
                t={t}
              />
              <span
                style={{ display: 'flex', flexDirection: 'column', gap: 2, gridColumn: 'span 2' }}
              >
                <span style={{ font: `500 10.5px ${t.fb}`, color: t.sub2 }}>Tomador</span>
                <span style={{ font: `600 12.5px ${t.fb}`, color: t.text }}>
                  {data.tomador.cnpj} · {data.tomador.municipio}/{data.tomador.uf}
                  {!data.tomador.municipio_autorizado && (
                    <span style={{ color: t.neg }}> · fora da área (OC002)</span>
                  )}
                </span>
              </span>
            </Card>

            {/* Linha do tempo — transições de estado (trilha com autor). */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span style={{ font: `700 13.5px ${t.fd}`, color: t.text, marginBottom: 8 }}>
                Linha do tempo
              </span>
              {data.eventos_estado.map((ev, i) => {
                const ultimo = i === data.eventos_estado.length - 1
                const de = ev.status_anterior ? statusMeta(t, ev.status_anterior).label : null
                const para = statusMeta(t, ev.status_novo).label
                return (
                  <div key={ev.id} style={{ display: 'flex', gap: 11 }}>
                    <span
                      style={{
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        flex: 'none',
                      }}
                    >
                      <span
                        style={{
                          width: 9,
                          height: 9,
                          borderRadius: 999,
                          background: t.accent,
                          marginTop: 4,
                        }}
                      />
                      {!ultimo && (
                        <span style={{ width: 1, flex: 1, background: t.border2, minHeight: 18 }} />
                      )}
                    </span>
                    <span
                      style={{
                        flex: 1,
                        paddingBottom: 16,
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 1,
                      }}
                    >
                      <span style={{ font: `600 12.5px ${t.fb}`, color: t.text }}>
                        {de ? `${de} → ${para}` : `Criada como ${para}`}
                      </span>
                      <span style={{ font: `500 11px ${t.fb}`, color: t.sub2 }}>
                        {dataHora(ev.created_at)} ·{' '}
                        {ev.origem === 'sistema' ? 'Sistema' : (ev.usuario_nome ?? 'operador')}
                        {ev.dias_atraso ? ` · ${ev.dias_atraso} dias de atraso` : ''}
                      </span>
                    </span>
                  </div>
                )
              })}
            </div>
          </>
        )}
      </ScreenScroll>

      {/* Ações de ciclo de vida (abrem o sheet). */}
      {data && acoes.length > 0 && (
        <div
          style={{
            flex: 'none',
            padding: '12px 20px 22px',
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
            borderTop: `1px solid ${t.border}`,
          }}
        >
          {acoes.map((a) => {
            const s = estiloAcao(a.variant)
            return (
              <button
                key={a.sheet}
                type="button"
                onClick={() => app.openSheet(a.sheet, data.id)}
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  borderRadius: 13,
                  padding: 13,
                  font: `700 14px ${t.fb}`,
                  cursor: 'pointer',
                  ...s,
                }}
              >
                {a.label}
              </button>
            )
          })}
        </div>
      )}
    </Screen>
  )
}

function Dado({
  label,
  valor,
  mono,
  cor,
  t,
}: {
  label: string
  valor: string
  mono?: boolean
  cor?: string
  t: ReturnType<typeof useMobileTheme>
}) {
  return (
    <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span style={{ font: `500 10.5px ${t.fb}`, color: t.sub2 }}>{label}</span>
      <span
        style={{
          font: `600 ${mono ? 15 : 13}px ${mono ? "'JetBrains Mono Variable',monospace" : t.fb}`,
          color: cor ?? t.text,
        }}
      >
        {valor}
      </span>
    </span>
  )
}
