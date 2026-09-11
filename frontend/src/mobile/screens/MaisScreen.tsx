import { supabase } from '@/auth/supabaseClient'
import { useAppStore } from '@/stores/useAppStore'
import { useMobileTheme, useMobileThemeControls } from '../MobileThemeContext'
import { useMobileApp } from '../MobileAppContext'
import { useOperadorModel } from '../data/useOperadorModel'
import { Icon, type MobileIconName } from '../icons'
import { THEME_NAMES, THEMES, type ThemeName } from '../theme'
import { Screen, ScreenScroll, HEADER_TOP } from '../components/kit'

/** Tela Mais — perfil, seletor de tema, navegação secundária e sair. */
export function MaisScreen() {
  const t = useMobileTheme()
  const app = useMobileApp()
  const { name, setName } = useMobileThemeControls()
  const { model } = useOperadorModel()
  const setUsuario = useAppStore((s) => s.setUsuario)

  const nome = model?.nomeUsuario ?? 'Operador'
  const iniciais = nome
    .split(' ')
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join('')
    .toUpperCase()

  async function sair() {
    try {
      await supabase.auth.signOut()
    } catch {
      // Mesmo se o signOut falhar (rede), limpamos o estado local e saímos.
    }
    setUsuario(null)
    window.location.assign('/login')
  }

  const itens: Array<{
    icon: MobileIconName
    label: string
    onClick: () => void
    admin?: boolean
  }> = [
    { icon: 'file-check-2', label: 'Auditoria', onClick: app.goAuditoria },
    { icon: 'shield-alert', label: 'Compliance & fiscal', onClick: app.goCompliance },
    { icon: 'landmark', label: 'Capital social', onClick: app.goCapitalSocial, admin: true },
  ]
  const visiveis = itens.filter((i) => !i.admin || model?.isAdmin)

  return (
    <Screen label="Mais">
      <div style={{ flex: 'none', padding: `${HEADER_TOP} 20px 16px` }}>
        <img
          src="/mobile/orgatec-logo.jpeg"
          alt="Orgatec"
          style={{
            width: 190,
            height: 66,
            objectFit: 'cover',
            objectPosition: '50% 40%',
            borderRadius: 10,
            display: 'block',
          }}
        />
      </div>

      <ScreenScroll style={{ padding: '4px 20px 28px', gap: 18 }}>
        {/* Perfil. */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            borderRadius: 16,
            padding: 16,
            background: t.surface,
            border: `1px solid ${t.border}`,
            boxShadow: t.cardShadow,
          }}
        >
          <span
            style={{
              width: 42,
              height: 42,
              borderRadius: 12,
              background: t.grad,
              color: t.gradFg,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              font: `800 14px ${t.fb}`,
              flex: 'none',
            }}
          >
            {iniciais || 'OP'}
          </span>
          <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ font: `700 14px ${t.fb}`, color: t.text }}>{nome}</span>
            <span
              style={{
                font: `600 10.5px ${t.fb}`,
                letterSpacing: '.1em',
                textTransform: 'uppercase',
                color: t.accentText,
              }}
            >
              {model?.papelLabel ?? 'Operador'}
            </span>
          </span>
        </div>

        {/* Seletor de tema (os três, alternáveis). */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <span
            style={{
              font: `700 11px ${t.fb}`,
              letterSpacing: '.1em',
              textTransform: 'uppercase',
              color: t.sub2,
            }}
          >
            Tema
          </span>
          <div style={{ display: 'flex', gap: 8 }}>
            {THEME_NAMES.map((tn: ThemeName) => {
              const ativo = name === tn
              return (
                <button
                  key={tn}
                  type="button"
                  onClick={() => setName(tn)}
                  style={{
                    flex: 1,
                    background: ativo ? t.chipActiveBg : t.chipBg,
                    color: ativo ? t.chipActiveFg : t.chipFg,
                    border: `1px solid ${ativo ? t.chipActiveBorder : t.chipBorder}`,
                    borderRadius: 12,
                    padding: '10px 8px',
                    font: `700 11.5px ${t.fb}`,
                    cursor: 'pointer',
                  }}
                >
                  {THEMES[tn].label.split(' ')[0]}
                </button>
              )
            })}
          </div>
        </div>

        {/* Navegação secundária. */}
        <div
          style={{
            flex: 'none',
            display: 'flex',
            flexDirection: 'column',
            borderRadius: 16,
            background: t.surface,
            border: `1px solid ${t.border}`,
            boxShadow: t.cardShadow,
            overflow: 'hidden',
          }}
        >
          {visiveis.map((it, i) => (
            <button
              key={it.label}
              type="button"
              onClick={it.onClick}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '15px 16px',
                background: 'transparent',
                border: 'none',
                borderBottom: i < visiveis.length - 1 ? `1px solid ${t.divider}` : 'none',
                cursor: 'pointer',
                textAlign: 'left',
              }}
            >
              <Icon name={it.icon} size={18} color={t.sub} />
              <span style={{ flex: 1, font: `600 13.5px ${t.fb}`, color: t.text }}>{it.label}</span>
              <Icon name="chevron-right" size={16} color={t.muted} />
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={sair}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '15px 16px',
            borderRadius: 16,
            background: t.negBg,
            border: `1px solid ${t.negBorder}`,
            color: t.neg,
            font: `700 13px ${t.fb}`,
            cursor: 'pointer',
          }}
        >
          <Icon name="log-out" size={16} />
          Sair
        </button>

        <span
          style={{
            font: "500 10.5px 'JetBrains Mono Variable',monospace",
            color: t.faint,
            textAlign: 'center',
            marginTop: 4,
          }}
        >
          OrgCred · ESC · produção
        </span>
      </ScreenScroll>
    </Screen>
  )
}
