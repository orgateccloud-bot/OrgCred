import { useQuery } from '@tanstack/react-query'
import { getTomadorApiTomadoresTomadorIdGetOptions } from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { rotuloTipo } from '@/lib/rotulos'
import { useMobileTheme } from '../MobileThemeContext'
import { useMobileApp } from '../MobileAppContext'
import { statusMeta } from '../theme'
import { formatarMoeda } from '../format'
import {
  Screen,
  ScreenScroll,
  TopBar,
  Card,
  StatusPill,
  ScreenError,
  SkeletonBar,
} from '../components/kit'

/** Tela Tomador — detalhe. Design `data-screen-label="Tomador — detalhe"`. */
export function TomadorDetailScreen() {
  const t = useMobileTheme()
  const app = useMobileApp()
  const id = app.tomSelectedId ?? ''
  const { data, isPending, error } = useQuery(
    getTomadorApiTomadoresTomadorIdGetOptions({ path: { tomador_id: id } }),
  )

  return (
    <Screen label="Tomador — detalhe">
      <TopBar onBack={app.backToTomList} title={data?.razao_social ?? '…'} />

      <ScreenScroll style={{ padding: '4px 20px 20px', gap: 16 }}>
        {error && <ScreenError mensagem={mensagemDeErro(error)} />}
        {isPending && !data && (
          <>
            <SkeletonBar height={120} style={{ borderRadius: 16 }} />
            <SkeletonBar height={90} style={{ borderRadius: 16 }} />
          </>
        )}

        {data && (
          <>
            <Card style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <LinhaTom label="CNPJ" mono t={t} valor={data.cnpj} />
              <LinhaTom label="Porte" t={t} valor={data.porte} />
              <LinhaTom label="Município" t={t} valor={`${data.municipio}/${data.uf}`} />
              <span
                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
              >
                <span style={{ font: `500 12px ${t.fb}`, color: t.sub2 }}>Área autorizada</span>
                {data.municipio_autorizado ? (
                  <span
                    style={{
                      display: 'inline-flex',
                      background: t.posBg,
                      color: t.pos,
                      borderRadius: 999,
                      padding: '3px 10px',
                      font: `700 10.5px ${t.fb}`,
                    }}
                  >
                    Autorizado
                  </span>
                ) : (
                  <span
                    style={{
                      display: 'inline-flex',
                      background: t.negBg,
                      color: t.neg,
                      borderRadius: 999,
                      padding: '3px 10px',
                      font: `700 10.5px ${t.fb}`,
                    }}
                  >
                    Fora da área (OC002)
                  </span>
                )}
              </span>
            </Card>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div
                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
              >
                <span style={{ font: `700 13.5px ${t.fd}`, color: t.text }}>Operações</span>
                <button
                  type="button"
                  onClick={() => app.abrirNovaOp(data.id)}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: t.accentText,
                    font: `700 12px ${t.fb}`,
                    cursor: 'pointer',
                    padding: 0,
                  }}
                >
                  + Nova
                </button>
              </div>

              {data.operacoes.map((op) => {
                const sm = statusMeta(t, op.status)
                return (
                  <Card
                    key={op.id}
                    onClick={() => app.openOpDetail(op.id)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 10,
                      padding: '12px 13px',
                      borderRadius: 13,
                    }}
                  >
                    <span
                      style={{
                        flex: 1,
                        minWidth: 0,
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 1,
                      }}
                    >
                      <span style={{ font: `600 12.5px ${t.fb}`, color: t.text }}>
                        {rotuloTipo(op.tipo)}
                      </span>
                      <span
                        style={{
                          font: "500 11px 'JetBrains Mono Variable',monospace",
                          color: t.sub2,
                        }}
                      >
                        {formatarMoeda(op.valor_principal)}
                      </span>
                    </span>
                    <StatusPill label={sm.label} bg={sm.bg} fg={sm.fg} />
                  </Card>
                )
              })}
              {data.operacoes.length === 0 && (
                <span style={{ font: `500 12px ${t.fb}`, color: t.muted, padding: '8px 0' }}>
                  Nenhuma operação ainda.
                </span>
              )}
            </div>
          </>
        )}
      </ScreenScroll>
    </Screen>
  )
}

function LinhaTom({
  label,
  valor,
  mono,
  t,
}: {
  label: string
  valor: string
  mono?: boolean
  t: ReturnType<typeof useMobileTheme>
}) {
  return (
    <span style={{ display: 'flex', justifyContent: 'space-between' }}>
      <span style={{ font: `500 12px ${t.fb}`, color: t.sub2 }}>{label}</span>
      <span
        style={{
          font: `600 12.5px ${mono ? "'JetBrains Mono Variable',monospace" : t.fb}`,
          color: t.text,
        }}
      >
        {valor}
      </span>
    </span>
  )
}
