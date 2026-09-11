import { useQuery } from '@tanstack/react-query'
import { getAgingApiCobrancaAgingGetOptions } from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { useMobileTheme } from '../MobileThemeContext'
import { useMobileApp } from '../MobileAppContext'
import { formatarMoeda } from '../format'
import {
  Screen,
  ScreenScroll,
  HEADER_TOP,
  Card,
  EmptyState,
  ScreenError,
  SkeletonBar,
} from '../components/kit'

/**
 * Tela Cobrança — aging por operação (não parcela avulsa: é o que a API real
 * expõe). "Em atraso" lista as operações com valor vencido; tocar abre a
 * operação, onde vive a agenda e a baixa (que concilia contra movimento real).
 */
const num = (v: string | number | null | undefined) => Number(v ?? 0) || 0

export function CobrancaScreen() {
  const t = useMobileTheme()
  const app = useMobileApp()
  const { data, isPending, error } = useQuery(getAgingApiCobrancaAgingGetOptions())

  const atrasadas = (data?.operacoes ?? []).filter((o) => num(o.valor_vencido) > 0)
  const resumo = (data?.resumo ?? []).filter((r) => num(r.valor_vencido) > 0 || r.quantidade > 0)

  return (
    <Screen label="Cobrança">
      <div style={{ flex: 'none', padding: `${HEADER_TOP} 20px 12px` }}>
        <span style={{ font: `700 20px ${t.fd}`, color: t.text }}>Cobrança</span>
        <div style={{ font: `500 11.5px ${t.fb}`, color: t.sub2, marginTop: 2 }}>
          {atrasadas.length} em atraso
        </div>
      </div>

      <ScreenScroll style={{ padding: '4px 20px 28px', gap: 18 }}>
        {error && <ScreenError mensagem={mensagemDeErro(error)} />}
        {isPending &&
          !data &&
          Array.from({ length: 3 }).map((_, i) => (
            <SkeletonBar key={i} height={66} style={{ borderRadius: 14 }} />
          ))}

        {data && atrasadas.length === 0 && (
          <EmptyState
            icon="calendar-clock"
            titulo="Nada em atraso"
            descricao="As operações com parcelas vencidas aparecem aqui."
          />
        )}

        {atrasadas.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
            <span
              style={{
                font: `700 11px ${t.fb}`,
                letterSpacing: '.1em',
                textTransform: 'uppercase',
                color: t.neg,
              }}
            >
              Em atraso
            </span>
            {atrasadas.map((o) => (
              <div
                key={o.operacao_id}
                onClick={() => app.openOpDetail(o.operacao_id)}
                style={{
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  padding: '13px 14px',
                  background: t.negBg,
                  border: `1px solid ${t.negBorder}`,
                  borderRadius: 14,
                }}
              >
                <span
                  style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 2 }}
                >
                  <span style={{ font: `700 13px ${t.fb}`, color: t.text }}>
                    {o.tomador_razao_social}
                  </span>
                  <span style={{ font: `500 11px ${t.fb}`, color: t.negSoft }}>
                    {o.parcelas_vencidas} parcela(s) · {o.dias_atraso} dias · {o.faixa}
                  </span>
                </span>
                <span
                  style={{
                    font: "600 13.5px 'JetBrains Mono Variable',monospace",
                    color: t.text,
                    flex: 'none',
                  }}
                >
                  {formatarMoeda(o.valor_vencido)}
                </span>
              </div>
            ))}
          </div>
        )}

        {resumo.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
            <span
              style={{
                font: `700 11px ${t.fb}`,
                letterSpacing: '.1em',
                textTransform: 'uppercase',
                color: t.sub2,
              }}
            >
              Resumo por faixa
            </span>
            <Card style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {resumo.map((r) => (
                <span
                  key={r.faixa}
                  style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                >
                  <span style={{ font: `600 12px ${t.fb}`, color: t.sub }}>
                    {r.faixa} · {r.quantidade}
                  </span>
                  <span
                    style={{
                      font: "600 12.5px 'JetBrains Mono Variable',monospace",
                      color: t.text,
                    }}
                  >
                    {formatarMoeda(r.valor_vencido)}
                  </span>
                </span>
              ))}
            </Card>
          </div>
        )}
      </ScreenScroll>
    </Screen>
  )
}
