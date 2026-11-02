import type { CSSProperties, ReactNode } from 'react'
import { useMobileTheme } from '../MobileThemeContext'
import { Icon, type MobileIconName } from '../icons'

/**
 * Kit de primitivas do app mobile. Cada peça lê o tema ativo por conta própria
 * (as telas não precisam passar `theme`), aplicando os tokens via `style`
 * inline — o caminho fiel ao design, pixel a pixel.
 *
 * Safe-area: o topo dos cabeçalhos e o rodapé da tab bar respeitam
 * `env(safe-area-inset-*)` (o app é PWA, `viewport-fit=cover`); sem inset
 * (aba comum, desktop) caem num respiro padrão.
 */

/** Padding-top do cabeçalho de cada tela (respeita o notch quando instalado). */
export const HEADER_TOP = 'calc(env(safe-area-inset-top, 0px) + 16px)'

/** Moldura externa de uma tela (coluna que ocupa o corpo do app). */
export function Screen({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div
      data-screen-label={label}
      style={{
        flex: 1,
        minHeight: 0,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        position: 'relative',
        animation: 'oc-appear .25s both',
      }}
    >
      {children}
    </div>
  )
}

/** Área rolável do corpo da tela. */
export function ScreenScroll({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div
      style={{
        flex: 1,
        overflowY: 'auto',
        WebkitOverflowScrolling: 'touch',
        padding: '4px 20px 28px',
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
        ...style,
      }}
    >
      {children}
    </div>
  )
}

/** Cabeçalho da tela: back opcional, título, subtítulo, ação à direita. */
export function TopBar({
  title,
  subtitle,
  onBack,
  trailing,
  large,
}: {
  title: ReactNode
  subtitle?: ReactNode
  onBack?: () => void
  trailing?: ReactNode
  large?: boolean
}) {
  const t = useMobileTheme()
  return (
    <div
      style={{
        flex: 'none',
        paddingTop: HEADER_TOP,
        paddingLeft: 20,
        paddingRight: 20,
        paddingBottom: 12,
        display: 'flex',
        alignItems: 'center',
        gap: 12,
      }}
    >
      {onBack && (
        <button
          type="button"
          onClick={onBack}
          aria-label="Voltar"
          style={{
            flex: 'none',
            width: 34,
            height: 34,
            borderRadius: 10,
            background: t.surface,
            border: `1px solid ${t.border2}`,
            color: t.text,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
          }}
        >
          <Icon name="chevron-left" size={18} />
        </button>
      )}
      <span style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 1 }}>
        <span
          style={{
            font: `700 ${large ? 20 : 16}px ${t.fd}`,
            color: t.text,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {title}
        </span>
        {subtitle && <span style={{ font: `500 11.5px ${t.fb}`, color: t.sub2 }}>{subtitle}</span>}
      </span>
      {trailing}
    </div>
  )
}

/** Botão redondo de ação no cabeçalho (ex.: "+"), no gradiente do tema. */
export function HeaderAction({
  icon,
  onClick,
  label,
  variant = 'grad',
}: {
  icon: MobileIconName
  onClick: () => void
  label: string
  variant?: 'grad' | 'surface'
}) {
  const t = useMobileTheme()
  const grad = variant === 'grad'
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      style={{
        flex: 'none',
        width: 38,
        height: 38,
        borderRadius: 11,
        background: grad ? t.grad : t.surface,
        border: grad ? 'none' : `1px solid ${t.border2}`,
        color: grad ? t.gradFg : t.sub,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'pointer',
        boxShadow: grad ? 'none' : t.cardShadow,
      }}
    >
      <Icon name={icon} size={19} />
    </button>
  )
}

/** Cartão de superfície temático. */
export function Card({
  children,
  onClick,
  style,
}: {
  children: ReactNode
  onClick?: () => void
  style?: CSSProperties
}) {
  const t = useMobileTheme()
  return (
    <div
      onClick={onClick}
      style={{
        borderRadius: 16,
        padding: 16,
        background: t.surface,
        border: `1px solid ${t.border}`,
        boxShadow: t.cardShadow,
        cursor: onClick ? 'pointer' : undefined,
        ...style,
      }}
    >
      {children}
    </div>
  )
}

/** Pílula de status de operação (bg/fg vindos de `statusMeta`). */
export function StatusPill({ label, bg, fg }: { label: string; bg: string; fg: string }) {
  const t = useMobileTheme()
  return (
    <span
      style={{
        flex: 'none',
        background: bg,
        color: fg,
        borderRadius: 999,
        padding: '3px 10px',
        font: `700 10.5px ${t.fb}`,
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </span>
  )
}

/** Ícone dentro de um quadrado arredondado (usado em listas e cabeçalhos). */
export function IconTile({
  icon,
  bg,
  fg,
  size = 32,
  radius = 9,
  iconSize = 15,
}: {
  icon: MobileIconName
  bg: string
  fg: string
  size?: number
  radius?: number
  iconSize?: number
}) {
  return (
    <span
      style={{
        width: size,
        height: size,
        borderRadius: radius,
        background: bg,
        color: fg,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flex: 'none',
      }}
    >
      <Icon name={icon} size={iconSize} />
    </span>
  )
}

/** Chip clicável (filtro / seleção). */
export function Chip({
  label,
  active,
  onClick,
  tone,
}: {
  label: string
  active: boolean
  onClick: () => void
  /** Sobrescreve as cores ativas (ex.: verde para município autorizado). */
  tone?: { bg: string; fg: string; border: string }
}) {
  const t = useMobileTheme()
  const bg = tone ? tone.bg : active ? t.chipActiveBg : t.chipBg
  const fg = tone ? tone.fg : active ? t.chipActiveFg : t.chipFg
  const border = tone ? tone.border : active ? t.chipActiveBorder : t.chipBorder
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        flex: 'none',
        whiteSpace: 'nowrap',
        background: bg,
        color: fg,
        border: `1px solid ${border}`,
        borderRadius: 999,
        padding: '8px 14px',
        font: `700 12px ${t.fb}`,
        cursor: 'pointer',
      }}
    >
      {label}
    </button>
  )
}

/** Rótulo de seção (título forte acima de um grupo). */
export function SectionTitle({ children }: { children: ReactNode }) {
  const t = useMobileTheme()
  return <span style={{ font: `700 14px ${t.fd}`, color: t.text }}>{children}</span>
}

/** Campo de texto rotulado. */
export function Field({
  label,
  value,
  onChange,
  placeholder,
  inputMode,
  mono,
  prefix,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  inputMode?: 'text' | 'decimal' | 'numeric'
  mono?: boolean
  prefix?: string
}) {
  const t = useMobileTheme()
  const input = (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      inputMode={inputMode}
      placeholder={placeholder}
      style={{
        flex: 1,
        minWidth: 0,
        boxSizing: 'border-box',
        width: '100%',
        background: prefix ? 'transparent' : t.inputBg,
        border: prefix ? 'none' : `1px solid ${t.inputBorder}`,
        borderRadius: prefix ? 0 : 12,
        padding: prefix ? 0 : '12px 14px',
        color: t.text,
        outline: 'none',
        font: `600 ${mono ? 14 : 13.5}px ${mono ? "'JetBrains Mono Variable',monospace" : t.fb}`,
      }}
    />
  )
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
      <span style={{ font: `700 11.5px ${t.fb}`, color: t.sub }}>{label}</span>
      {prefix ? (
        <span
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 9,
            background: t.inputBg,
            border: `1px solid ${t.inputBorder}`,
            borderRadius: 12,
            padding: '12px 14px',
          }}
        >
          <span style={{ font: `600 13px ${t.fb}`, color: t.muted }}>{prefix}</span>
          {input}
        </span>
      ) : (
        input
      )}
    </label>
  )
}

/** Botão primário de largura total (rodapé de formulário). */
export function PrimaryButton({
  children,
  onClick,
  disabled,
}: {
  children: ReactNode
  onClick: () => void
  disabled?: boolean
}) {
  const t = useMobileTheme()
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        width: '100%',
        boxSizing: 'border-box',
        background: disabled ? t.surface2 : t.grad,
        color: disabled ? t.muted : t.gradFg,
        border: 'none',
        borderRadius: 13,
        padding: 14,
        font: `700 14.5px ${t.fb}`,
        cursor: disabled ? 'default' : 'pointer',
      }}
    >
      {children}
    </button>
  )
}

/** Barra de rodapé fixa com um botão primário (ação da tela). */
export function FooterBar({ children }: { children: ReactNode }) {
  const t = useMobileTheme()
  return (
    <div
      style={{
        flex: 'none',
        padding: '12px 20px 22px',
        borderTop: `1px solid ${t.border}`,
      }}
    >
      {children}
    </div>
  )
}

/** Estado vazio: ícone + texto centralizados. */
export function EmptyState({
  icon,
  titulo,
  descricao,
}: {
  icon: MobileIconName
  titulo: string
  descricao?: string
}) {
  const t = useMobileTheme()
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 10,
        padding: '48px 20px',
        color: t.muted,
      }}
    >
      <Icon name={icon} size={30} />
      <span style={{ font: `600 13px ${t.fb}`, textAlign: 'center' }}>{titulo}</span>
      {descricao && (
        <span style={{ font: `500 11.5px ${t.fb}`, textAlign: 'center', lineHeight: 1.5 }}>
          {descricao}
        </span>
      )}
    </div>
  )
}

/** Erro de tela inteiro (falha de carregamento). */
export function ScreenError({ mensagem }: { mensagem: string }) {
  const t = useMobileTheme()
  return (
    <div
      style={{
        padding: '48px 24px',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        alignItems: 'center',
      }}
    >
      <Icon name="alert-triangle" size={28} color={t.neg} />
      <span style={{ font: `600 13px ${t.fb}`, color: t.neg, textAlign: 'center' }}>
        {mensagem}
      </span>
    </div>
  )
}

/** Skeleton simples (barra pulsante) para estados de carregamento. */
export function SkeletonBar({ height = 16, style }: { height?: number; style?: CSSProperties }) {
  const t = useMobileTheme()
  return (
    <div
      style={{
        height,
        borderRadius: 10,
        background: t.surface2,
        animation: 'oc-pulse 1.4s ease-in-out infinite',
        ...style,
      }}
    />
  )
}
