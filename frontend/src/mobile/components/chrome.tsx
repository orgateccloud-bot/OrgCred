import { useMobileTheme } from '../MobileThemeContext'
import { Icon, type MobileIconName } from '../icons'
import { toneColors } from '../theme'
import { useMobileApp, type MobileTab } from '../MobileAppContext'
import type { NotifItem } from '../data/useOperadorModel'

/** Bottom tab bar — as 5 abas do app, com a ativa realçada. */
const ABAS: Array<{ tab: MobileTab; icon: MobileIconName; label: string }> = [
  { tab: 'inicio', icon: 'home', label: 'Início' },
  { tab: 'operacoes', icon: 'file-text', label: 'Operações' },
  { tab: 'tomadores', icon: 'users', label: 'Tomadores' },
  { tab: 'cobranca', icon: 'calendar-clock', label: 'Cobrança' },
  { tab: 'mais', icon: 'more-horizontal', label: 'Mais' },
]

export function TabBar() {
  const t = useMobileTheme()
  const app = useMobileApp()
  return (
    <nav
      style={{
        flex: 'none',
        display: 'flex',
        padding: '8px 6px calc(env(safe-area-inset-bottom, 0px) + 10px)',
        borderTop: `1px solid ${t.navBorder}`,
        background: t.navBg,
        position: 'relative',
        backdropFilter: 'blur(18px)',
        WebkitBackdropFilter: 'blur(18px)',
      }}
    >
      {ABAS.map((a) => {
        const ativa = app.tab === a.tab
        return (
          <button
            key={a.tab}
            type="button"
            onClick={() => app.goTab(a.tab)}
            aria-current={ativa ? 'page' : undefined}
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 3,
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              padding: '6px 2px',
              color: ativa ? t.navActive : t.navInactive,
            }}
          >
            <Icon name={a.icon} size={21} />
            <span style={{ font: `700 9.5px ${t.fb}` }}>{a.label}</span>
          </button>
        )
      })}
    </nav>
  )
}

/** Toast efêmero (rodapé, acima da tab bar). */
export function Toast() {
  const t = useMobileTheme()
  const app = useMobileApp()
  if (!app.toast) return null
  return (
    <div
      role="status"
      style={{
        position: 'absolute',
        left: 20,
        right: 20,
        bottom: 100,
        zIndex: 50,
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        background: t.toastBg,
        border: `1px solid ${t.toastBorder}`,
        borderRadius: 13,
        padding: '13px 15px',
        animation: 'oc-sheetUp .2s cubic-bezier(.2,.7,.2,1) both',
        boxShadow: '0 12px 30px rgba(0,0,0,.25)',
      }}
    >
      <Icon name="check-circle-2" size={17} color={t.pos} />
      <span style={{ font: `600 12.5px ${t.fb}`, color: t.toastText }}>{app.toast}</span>
    </div>
  )
}

/** Painel de notificações (overlay superior). */
export function NotifPanel({ itens }: { itens: NotifItem[] }) {
  const t = useMobileTheme()
  const app = useMobileApp()
  if (!app.notifOpen) return null
  return (
    <div
      onClick={app.closeNotif}
      style={{
        position: 'absolute',
        inset: 0,
        zIndex: 35,
        background: t.overlay,
        animation: 'oc-fadeIn .15s both',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          margin: '50px 14px 0',
          background: t.sheetBg,
          border: `1px solid ${t.border2}`,
          borderRadius: 18,
          overflow: 'hidden',
          animation: 'oc-sheetUp .2s cubic-bezier(.2,.7,.2,1) both',
          boxShadow: '0 18px 40px rgba(4,8,16,.3)',
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '14px 16px',
            borderBottom: `1px solid ${t.border}`,
          }}
        >
          <span style={{ font: `700 14px ${t.fd}`, color: t.text }}>Notificações</span>
          <button
            type="button"
            onClick={app.closeNotif}
            aria-label="Fechar"
            style={{
              background: 'transparent',
              border: 'none',
              color: t.sub2,
              cursor: 'pointer',
              display: 'flex',
            }}
          >
            <Icon name="x" size={18} />
          </button>
        </div>
        <div style={{ maxHeight: 360, overflowY: 'auto' }}>
          {itens.length === 0 ? (
            <div
              style={{
                padding: '24px 16px',
                font: `500 12px ${t.fb}`,
                color: t.muted,
                textAlign: 'center',
              }}
            >
              Nada por aqui.
            </div>
          ) : (
            itens.map((n) => {
              const tc = toneColors(t, n.tone)
              return (
                <div
                  key={n.id}
                  style={{
                    display: 'flex',
                    gap: 11,
                    padding: '13px 16px',
                    borderBottom: `1px solid ${t.divider}`,
                  }}
                >
                  <span
                    style={{
                      width: 30,
                      height: 30,
                      borderRadius: 9,
                      flex: 'none',
                      background: tc.bg,
                      color: tc.fg,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <Icon name={n.icon} size={14} />
                  </span>
                  <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span style={{ font: `600 12.5px ${t.fb}`, color: t.text }}>{n.titulo}</span>
                    <span style={{ font: `500 11px ${t.fb}`, color: t.sub2, lineHeight: 1.4 }}>
                      {n.detalhe}
                    </span>
                  </span>
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
