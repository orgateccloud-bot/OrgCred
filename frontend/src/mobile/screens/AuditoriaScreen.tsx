import { useMobileTheme } from '../MobileThemeContext'
import { useMobileApp } from '../MobileAppContext'
import { useOperadorModel } from '../data/useOperadorModel'
import { Icon } from '../icons'
import { toneColors } from '../theme'
import {
  Screen,
  ScreenScroll,
  TopBar,
  ScreenError,
  SkeletonBar,
  EmptyState,
} from '../components/kit'

/** Tela Auditoria — o ledger completo + selo de integridade da cadeia. */
export function AuditoriaScreen() {
  const t = useMobileTheme()
  const app = useMobileApp()
  const { model, isLoading, error } = useOperadorModel()

  const cadeiaOk = model?.cadeiaIntegra ?? true
  const badgeBg = cadeiaOk ? t.posBg : t.negBg
  const badgeFg = cadeiaOk ? t.pos : t.neg

  return (
    <Screen label="Auditoria">
      <TopBar
        onBack={app.goMaisMenu}
        title="Auditoria"
        trailing={
          <span
            style={{
              flex: 'none',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              background: badgeBg,
              color: badgeFg,
              borderRadius: 999,
              padding: '4px 10px',
              font: `700 10.5px ${t.fb}`,
            }}
          >
            <Icon name={cadeiaOk ? 'shield-check' : 'alert-octagon'} size={11} />
            {cadeiaOk ? 'Cadeia íntegra' : 'Quebra detectada'}
          </span>
        }
      />

      <ScreenScroll style={{ padding: '4px 20px 28px', gap: 9 }}>
        {!!error && <ScreenError mensagem="Não foi possível carregar a auditoria." />}
        {isLoading &&
          !model &&
          Array.from({ length: 5 }).map((_, i) => (
            <SkeletonBar key={i} height={58} style={{ borderRadius: 14 }} />
          ))}

        {model &&
          model.ledger.map((it) => {
            const tc = toneColors(t, it.tone)
            return (
              <div
                key={it.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 11,
                  padding: '12px 13px',
                  background: t.surface,
                  border: `1px solid ${t.border}`,
                  boxShadow: t.cardShadow,
                  borderRadius: 14,
                }}
              >
                <span
                  style={{
                    width: 34,
                    height: 34,
                    borderRadius: 10,
                    flex: 'none',
                    background: tc.bg,
                    color: tc.fg,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <Icon name={it.icon} size={16} />
                </span>
                <span
                  style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 1 }}
                >
                  <span style={{ font: `600 12.5px ${t.fb}`, color: t.text }}>{it.titulo}</span>
                  <span style={{ font: `500 11px ${t.fb}`, color: t.sub2 }}>{it.detalhe}</span>
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
          })}

        {model && model.ledger.length === 0 && (
          <EmptyState
            icon="inbox"
            titulo="Ledger vazio"
            descricao="Os eventos aparecem aqui conforme o capital se move."
          />
        )}
      </ScreenScroll>
    </Screen>
  )
}
