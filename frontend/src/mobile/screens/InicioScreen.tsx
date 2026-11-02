import { useMobileTheme } from '../MobileThemeContext'
import { useMobileApp } from '../MobileAppContext'
import { useOperadorModel, type NivelUtilizacao } from '../data/useOperadorModel'
import { Icon } from '../icons'
import { toneColors } from '../theme'
import { Screen, ScreenScroll, HEADER_TOP, Card, ScreenError, SkeletonBar } from '../components/kit'

/**
 * Tela Início — o "dia do operador": capital disponível (anel de utilização do
 * teto), alertas do banco, KPIs e a atividade recente do ledger. Fiel ao design
 * `data-screen-label="Início"`, alimentada por `useOperadorModel` (API real).
 */
export function InicioScreen() {
  const t = useMobileTheme()
  const app = useMobileApp()
  const { model, isLoading, error } = useOperadorModel()

  const anelPorNivel: Record<NivelUtilizacao, string> = {
    ok: t.ringOk,
    warn: t.ringWarn,
    danger: t.ringDanger,
    zero: t.ringZero,
  }
  const glowPorNivel: Record<NivelUtilizacao, string> = {
    ok: t.glowOk,
    warn: t.glowWarn,
    danger: t.glowDanger,
    zero: t.glowZero,
  }

  return (
    <Screen label="Início">
      {/* Cabeçalho: esfera + saudação + sino de notificações. */}
      <div
        style={{
          flex: 'none',
          paddingTop: HEADER_TOP,
          padding: `${HEADER_TOP} 20px 14px`,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <span
          style={{
            width: 38,
            height: 38,
            borderRadius: 11,
            background: '#eef4fa',
            border: `1px solid ${t.border}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flex: 'none',
            overflow: 'hidden',
          }}
        >
          <img
            src="/mobile/orgatec-sphere.png"
            alt=""
            style={{ width: 26, height: 26, objectFit: 'contain' }}
          />
        </span>
        <span style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0, flex: 1 }}>
          <span style={{ font: `700 17px ${t.fd}`, color: t.text }}>
            Olá, {model?.nomeUsuario ?? '…'}
          </span>
          <span style={{ font: `600 11px ${t.fb}`, color: t.sub2 }}>
            {model?.papelLabel ?? 'Operador'} · ORGATEC
          </span>
        </span>
        <button
          type="button"
          onClick={app.toggleNotif}
          aria-label="Notificações"
          style={{
            position: 'relative',
            flex: 'none',
            width: 38,
            height: 38,
            borderRadius: 11,
            background: t.surface,
            border: `1px solid ${t.border2}`,
            color: t.sub,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            boxShadow: t.cardShadow,
          }}
        >
          <Icon name="bell" size={17} />
          {!!model?.notificacoes.length && (
            <span
              style={{
                position: 'absolute',
                top: 8,
                right: 9,
                width: 7,
                height: 7,
                borderRadius: 999,
                background: t.accent,
              }}
            />
          )}
        </button>
      </div>

      <ScreenScroll style={{ padding: '2px 20px 32px' }}>
        {!!error && <ScreenError mensagem="Não foi possível carregar o painel." />}

        {isLoading && !model && (
          <>
            <SkeletonBar height={190} style={{ borderRadius: 22 }} />
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <SkeletonBar height={96} style={{ borderRadius: 16 }} />
              <SkeletonBar height={96} style={{ borderRadius: 16 }} />
            </div>
            <SkeletonBar height={180} style={{ borderRadius: 16 }} />
          </>
        )}

        {model && (
          <>
            {/* Alertas do banco (gravidade primeiro). */}
            {model.tetoZerado && (
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 10,
                  border: `1px solid ${t.negBorder}`,
                  background: t.negBg,
                  borderRadius: 16,
                  padding: '15px 16px',
                }}
              >
                <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                  <Icon name="alert-triangle" size={18} color={t.neg} />
                  <span style={{ font: `700 13.5px ${t.fb}`, color: t.neg }}>
                    Teto de capital em R$ 0,00
                  </span>
                </div>
                <span style={{ font: `500 12px ${t.fb}`, color: t.sub, lineHeight: 1.5 }}>
                  Capital social ainda não integralizado. Nenhuma operação pode ser ativada —
                  bloqueio do banco (OC001), não da interface.
                </span>
                <button
                  type="button"
                  onClick={app.goCapitalSocial}
                  style={{
                    alignSelf: 'flex-start',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    background: 'transparent',
                    border: `1px solid ${t.negBorder}`,
                    color: t.neg,
                    borderRadius: 10,
                    padding: '8px 13px',
                    font: `700 12px ${t.fb}`,
                    cursor: 'pointer',
                  }}
                >
                  Registrar aporte
                  <Icon name="arrow-right" size={13} />
                </button>
              </div>
            )}
            {!model.cadeiaIntegra && (
              <div
                style={{
                  display: 'flex',
                  gap: 10,
                  alignItems: 'flex-start',
                  border: `1px solid ${t.negBorder}`,
                  background: t.negBg,
                  borderRadius: 16,
                  padding: '15px 16px',
                }}
              >
                <Icon name="alert-octagon" size={18} color={t.neg} />
                <span style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  <span style={{ font: `700 13.5px ${t.fb}`, color: t.neg }}>
                    Quebra na cadeia de auditoria
                  </span>
                  <span style={{ font: `500 12px ${t.fb}`, color: t.sub, lineHeight: 1.5 }}>
                    Hash registrado não confere com o esperado. Investigar imediatamente.
                  </span>
                </span>
              </div>
            )}

            {/* Hero — capital disponível + anel de utilização. */}
            <div
              style={{
                flex: 'none',
                position: 'relative',
                overflow: 'hidden',
                borderRadius: 22,
                padding: '22px 20px',
                background: t.heroBg,
                border: `1px solid ${t.heroBorder}`,
                boxShadow: t.heroShadow,
              }}
            >
              <span
                style={{
                  position: 'absolute',
                  right: -50,
                  top: -50,
                  width: 200,
                  height: 200,
                  borderRadius: '50%',
                  background: `radial-gradient(circle,${glowPorNivel[model.nivelUtilizacao]},transparent 65%)`,
                }}
              />
              <div style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 7 }}>
                <span
                  style={{
                    font: `700 10px ${t.fb}`,
                    letterSpacing: '.14em',
                    textTransform: 'uppercase',
                    color: t.heroLabel,
                  }}
                >
                  Capital disponível
                </span>
                <span
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: 999,
                    background: anelPorNivel[model.nivelUtilizacao],
                    animation: 'oc-pulseDot 2.6s ease-in-out infinite',
                  }}
                />
              </div>
              <div
                style={{
                  position: 'relative',
                  font: "600 32px 'JetBrains Mono Variable',monospace",
                  letterSpacing: '-.02em',
                  marginTop: 10,
                  background: t.heroValGrad,
                  WebkitBackgroundClip: t.heroValGrad === 'none' ? undefined : 'text',
                  backgroundClip: t.heroValGrad === 'none' ? undefined : 'text',
                  color: t.heroValColor,
                }}
              >
                {model.disponivelFmt}
              </div>
              <div
                style={{
                  position: 'relative',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 20,
                  marginTop: 18,
                }}
              >
                <svg viewBox="0 0 120 120" style={{ width: 88, height: 88, flex: 'none' }}>
                  <circle
                    cx="60"
                    cy="60"
                    r="52"
                    fill="none"
                    stroke={t.heroTrack}
                    strokeWidth="10"
                  />
                  <circle
                    cx="60"
                    cy="60"
                    r="52"
                    fill="none"
                    stroke={anelPorNivel[model.nivelUtilizacao]}
                    strokeWidth="10"
                    strokeLinecap="round"
                    strokeDasharray="327"
                    strokeDashoffset={model.anelOffset}
                    transform="rotate(-90 60 60)"
                    style={{ transition: 'stroke-dashoffset .7s cubic-bezier(.2,.7,.2,1)' }}
                  />
                </svg>
                <div
                  style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1, minWidth: 0 }}
                >
                  <LinhaHero
                    label="Teto legal"
                    valor={model.tetoFmt}
                    cor={t.heroText}
                    sub={t.heroSub}
                    fb={t.fb}
                  />
                  <LinhaHero
                    label="Comprometido"
                    valor={model.comprometidoFmt}
                    cor={anelPorNivel[model.nivelUtilizacao]}
                    sub={t.heroSub}
                    fb={t.fb}
                  />
                  <LinhaHero
                    label="Utilizado"
                    valor={model.utilPctLabel}
                    cor={anelPorNivel[model.nivelUtilizacao]}
                    sub={t.heroSub}
                    fb={t.fb}
                    bold
                  />
                </div>
              </div>
              <div
                style={{
                  position: 'relative',
                  font: `500 10.5px ${t.fb}`,
                  color: t.heroSub,
                  marginTop: 16,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 7,
                  borderTop: `1px solid ${t.heroLine}`,
                  paddingTop: 12,
                }}
              >
                <Icon name="shield-check" size={13} color={t.heroLabel} />
                Art. 5º, LC 167/2019 — enforced por trigger no banco
              </div>
            </div>

            {/* KPIs. */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <KpiCard
                icon="file-check-2"
                iconBg={t.accentSoft}
                iconFg={t.accentText}
                rotulo="Operações ativas"
                valor={String(model.opsAtivasCount)}
                grande
              />
              <KpiCard
                icon="alarm-clock"
                iconBg={t.warnBg}
                iconFg={t.warn}
                rotulo="Em atraso"
                valor={model.atrasoSumFmt}
              />
            </div>

            {/* Atividade do ledger. */}
            <Card style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 2 }}>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: 8,
                }}
              >
                <span style={{ font: `700 14px ${t.fd}`, color: t.text }}>Atividade do ledger</span>
                <button
                  type="button"
                  onClick={app.goAuditoria}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: t.accentText,
                    font: `700 12px ${t.fb}`,
                    cursor: 'pointer',
                    padding: 0,
                  }}
                >
                  Ver tudo
                </button>
              </div>
              {model.ledger.length === 0 ? (
                <span style={{ font: `500 12px ${t.fb}`, color: t.muted, padding: '8px 0' }}>
                  Nenhum evento no ledger ainda.
                </span>
              ) : (
                model.ledger.slice(0, 3).map((it) => {
                  const tc = toneColors(t, it.tone)
                  return (
                    <div
                      key={it.id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 11,
                        padding: '10px 0',
                        borderBottom: `1px solid ${t.divider}`,
                      }}
                    >
                      <span
                        style={{
                          width: 32,
                          height: 32,
                          borderRadius: 9,
                          flex: 'none',
                          background: tc.bg,
                          color: tc.fg,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                      >
                        <Icon name={it.icon} size={15} />
                      </span>
                      <span
                        style={{
                          flex: 1,
                          minWidth: 0,
                          display: 'flex',
                          flexDirection: 'column',
                          gap: 1,
                        }}
                      >
                        <span
                          style={{
                            font: `600 12.5px ${t.fb}`,
                            color: t.text,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {it.titulo}
                        </span>
                        <span
                          style={{
                            font: `500 11px ${t.fb}`,
                            color: t.sub2,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {it.detalhe}
                        </span>
                      </span>
                      {it.valorFmt && (
                        <span
                          style={{
                            font: "600 12px 'JetBrains Mono Variable',monospace",
                            color: tc.fg,
                            flex: 'none',
                          }}
                        >
                          {it.valorFmt}
                        </span>
                      )}
                    </div>
                  )
                })
              )}
            </Card>
          </>
        )}
      </ScreenScroll>
    </Screen>
  )
}

function LinhaHero({
  label,
  valor,
  cor,
  sub,
  fb,
  bold,
}: {
  label: string
  valor: string
  cor: string
  sub: string
  fb: string
  bold?: boolean
}) {
  return (
    <span style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
      <span style={{ font: `500 11.5px ${fb}`, color: sub }}>{label}</span>
      <span
        style={{ font: `${bold ? 700 : 600} 13px 'JetBrains Mono Variable',monospace`, color: cor }}
      >
        {valor}
      </span>
    </span>
  )
}

function KpiCard({
  icon,
  iconBg,
  iconFg,
  rotulo,
  valor,
  grande,
}: {
  icon: Parameters<typeof Icon>[0]['name']
  iconBg: string
  iconFg: string
  rotulo: string
  valor: string
  grande?: boolean
}) {
  const t = useMobileTheme()
  return (
    <Card style={{ padding: 16 }}>
      <span
        style={{
          width: 32,
          height: 32,
          borderRadius: 9,
          background: iconBg,
          color: iconFg,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Icon name={icon} size={16} />
      </span>
      <div style={{ font: `500 11.5px ${t.fb}`, color: t.sub2, marginTop: 12 }}>{rotulo}</div>
      <div
        style={{
          font: `600 ${grande ? 22 : 17}px 'JetBrains Mono Variable',monospace`,
          color: t.text,
          marginTop: 2,
        }}
      >
        {valor}
      </div>
    </Card>
  )
}
