import { useMobileTheme } from '../MobileThemeContext'
import { useMobileApp } from '../MobileAppContext'
import { Icon } from '../icons'
import { Screen, ScreenScroll, TopBar, Card } from '../components/kit'

/**
 * Tela Compliance & fiscal — a POSTURA de conformidade da ESC (config
 * organizacional, não dado por request). Fiel ao design: o que está pendente
 * (registradora, IOF, PLD/COAF) e o que já está implementado (trilha de
 * auditoria com autor, validada contra Postgres real).
 */
export function ComplianceScreen() {
  const t = useMobileTheme()
  const app = useMobileApp()

  const pendente = (
    <span
      style={{
        background: t.warnBg,
        color: t.warn,
        borderRadius: 999,
        padding: '3px 9px',
        font: `700 10px ${t.fb}`,
      }}
    >
      Pendente
    </span>
  )

  return (
    <Screen label="Compliance & fiscal">
      <TopBar onBack={app.goMaisMenu} title="Compliance & fiscal" />

      <ScreenScroll style={{ padding: '4px 20px 28px', gap: 12 }}>
        <CardPosture
          titulo="Entidade registradora"
          badge={pendente}
          texto="Registro obrigatório antes da ativação (Art. 5º §3º, LC 167/2019). Finalistas: CRDC, SPC Grafeno, CERC, B3 — aguardando contato comercial."
          t={t}
        />
        <CardPosture
          titulo="Regime de IOF"
          badge={pendente}
          texto="Não determinado se há incidência sobre operações da ESC, nem quem arca com o custo. Aguardando parecer jurídico-tributário."
          t={t}
        />
        <CardPosture
          titulo="PLD / COAF"
          badge={pendente}
          texto="Órgão supervisor e comunicações obrigatórias para ESC ainda não confirmados juridicamente."
          t={t}
        />

        <div
          style={{
            borderRadius: 16,
            padding: 16,
            background: t.posBg,
            border: `1px solid ${t.posBorder}`,
            display: 'flex',
            gap: 10,
            alignItems: 'flex-start',
          }}
        >
          <Icon name="shield-check" size={16} color={t.pos} />
          <span style={{ font: `500 12px ${t.fb}`, color: t.sub, lineHeight: 1.5 }}>
            <span style={{ color: t.pos, fontWeight: 700 }}>Já implementado:</span> trilha de
            auditoria com autor (usuário + timestamp) por ativação, validada contra Postgres real.
          </span>
        </div>
      </ScreenScroll>
    </Screen>
  )
}

function CardPosture({
  titulo,
  badge,
  texto,
  t,
}: {
  titulo: string
  badge: React.ReactNode
  texto: string
  t: ReturnType<typeof useMobileTheme>
}) {
  return (
    <Card style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ font: `700 13.5px ${t.fb}`, color: t.text }}>{titulo}</span>
        {badge}
      </div>
      <span style={{ font: `500 12px ${t.fb}`, color: t.sub, lineHeight: 1.5 }}>{texto}</span>
    </Card>
  )
}
