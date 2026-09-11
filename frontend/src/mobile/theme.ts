/**
 * Tokens de tema do app mobile operador (OrgCred Mobile v2).
 *
 * Transcrição FIEL dos três temas do handoff do Claude Design
 * (`OrgCred Mobile v2.dc.html`). Cada tema é um conjunto fechado de tokens que
 * as telas aplicam via `style` inline — é o design pixel-perfect que manda, e
 * mexer num valor aqui muda a cara do app inteiro. Não reinterpretar: os hex e
 * gradientes vêm do arquivo de design, não de tokens do shadcn.
 *
 * As fontes do design (Archivo / Space Grotesk / Quicksand / Manrope /
 * JetBrains Mono) são servidas localmente via `@fontsource-variable/*` (ver
 * `main.tsx`), então os nomes aqui usam o sufixo " Variable".
 */

export type ThemeName = 'platinum' | 'obsidian' | 'aurora'

export type StatusKey =
  'proposta' | 'registrada' | 'ativa' | 'liquidada' | 'renegociada' | 'inadimplente' | 'cancelada'

export type ToneKey = 'positive' | 'neutral' | 'negative' | 'cyan' | 'muted'

/** Par [bg, fg] — o design guarda cor de fundo e de texto lado a lado. */
export type ColorPair = readonly [string, string]

export interface MobileTheme {
  label: string
  dark: boolean
  /** Fonte de display (headings). */
  fd: string
  /** Fonte de corpo. */
  fb: string

  bg: string
  surface: string
  surface2: string
  border: string
  border2: string
  divider: string

  text: string
  sub: string
  sub2: string
  muted: string
  faint: string

  accent: string
  accentText: string
  accentSoft: string
  accentBorder: string

  grad: string
  gradFg: string

  pos: string
  posBg: string
  posBorder: string
  neg: string
  negSoft: string
  negBg: string
  negBorder: string
  warn: string
  warnBg: string

  heroBg: string
  heroBorder: string
  heroShadow: string
  heroLabel: string
  heroSub: string
  heroText: string
  heroTrack: string
  heroLine: string
  heroValGrad: string
  heroValColor: string

  navBg: string
  navBorder: string
  navActive: string
  navInactive: string

  inputBg: string
  inputBorder: string
  trackOnSoft: string

  sheetBg: string
  handle: string
  overlay: string

  toastBg: string
  toastBorder: string
  toastText: string

  cardShadow: string

  ringOk: string
  ringWarn: string
  ringDanger: string
  ringZero: string
  glowOk: string
  glowWarn: string
  glowDanger: string
  glowZero: string

  iconNeutralBg: string
  iconNeutralFg: string

  chipBg: string
  chipFg: string
  chipBorder: string
  chipActiveBg: string
  chipActiveFg: string
  chipActiveBorder: string

  status: Record<StatusKey, ColorPair>
  tones: Record<ToneKey, ColorPair>
}

const ARCHIVO = "'Archivo Variable',sans-serif"
const SPACE_GROTESK = "'Space Grotesk Variable',sans-serif"
const QUICKSAND = "'Quicksand Variable',sans-serif"
const MANROPE = "'Manrope Variable',sans-serif"

export const THEMES: Record<ThemeName, MobileTheme> = {
  platinum: {
    label: 'Platinum Light',
    dark: false,
    fd: ARCHIVO,
    fb: ARCHIVO,
    bg: '#f2f4f7',
    surface: '#ffffff',
    surface2: '#f2f4f7',
    border: '#e2e6ec',
    border2: '#dde2e9',
    divider: '#eef1f5',
    text: '#0b1220',
    sub: '#3a4454',
    sub2: '#66707f',
    muted: '#8b95a5',
    faint: '#aab2bf',
    accent: '#0aa6d8',
    accentText: '#0a86ad',
    accentSoft: '#e6f6fc',
    accentBorder: '#a7dff1',
    grad: 'linear-gradient(135deg,#0aa6d8,#31c3ef)',
    gradFg: '#ffffff',
    pos: '#0f9e57',
    posBg: '#e7f8ee',
    posBorder: '#bce7cf',
    neg: '#c92739',
    negSoft: '#a63340',
    negBg: '#fdeaec',
    negBorder: '#f3c2c8',
    warn: '#b97e10',
    warnBg: '#fdf3e0',
    heroBg: 'linear-gradient(160deg,#0c0f14,#000000 70%)',
    heroBorder: 'transparent',
    heroShadow: '0 18px 40px rgba(11,18,32,.28)',
    heroLabel: '#7dd8f5',
    heroSub: '#9fb3c8',
    heroText: '#ffffff',
    heroTrack: 'rgba(255,255,255,.16)',
    heroLine: 'rgba(255,255,255,.18)',
    heroValGrad: 'none',
    heroValColor: '#ffffff',
    navBg: '#ffffff',
    navBorder: '#e2e6ec',
    navActive: '#0aa6d8',
    navInactive: '#8b95a5',
    inputBg: '#ffffff',
    inputBorder: '#dde2e9',
    trackOnSoft: '#ffffff',
    sheetBg: '#ffffff',
    handle: '#d6dbe3',
    overlay: 'rgba(11,18,32,.42)',
    toastBg: '#ffffff',
    toastBorder: '#bce7cf',
    toastText: '#0b1220',
    cardShadow: '0 1px 2px rgba(11,18,32,.05)',
    ringOk: '#0aa6d8',
    ringWarn: '#d18a00',
    ringDanger: '#c92739',
    ringZero: '#8b95a5',
    glowOk: 'rgba(43,184,232,.4)',
    glowWarn: 'rgba(245,165,36,.35)',
    glowDanger: 'rgba(239,95,111,.4)',
    glowZero: 'rgba(125,147,166,.3)',
    iconNeutralBg: '#eef1f5',
    iconNeutralFg: '#3a4454',
    chipBg: '#ffffff',
    chipFg: '#3a4454',
    chipBorder: '#dde2e9',
    chipActiveBg: '#e6f6fc',
    chipActiveFg: '#0a86ad',
    chipActiveBorder: '#7fd2ea',
    status: {
      proposta: ['#eef1f5', '#66707f'],
      registrada: ['#e6f6fc', '#0a86ad'],
      ativa: ['#e7f8ee', '#0f9e57'],
      liquidada: ['#eef1f5', '#8b95a5'],
      renegociada: ['#fdf3e0', '#b97e10'],
      inadimplente: ['#fdeaec', '#c92739'],
      cancelada: ['#f4f5f7', '#9aa2af'],
    },
    tones: {
      positive: ['#e7f8ee', '#0f9e57'],
      neutral: ['#eef1f5', '#3a4454'],
      negative: ['#fdeaec', '#c92739'],
      cyan: ['#e6f6fc', '#0a86ad'],
      muted: ['#f2f4f7', '#8b95a5'],
    },
  },
  obsidian: {
    label: 'Obsidian Chrome',
    dark: true,
    fd: SPACE_GROTESK,
    fb: MANROPE,
    bg: '#000000',
    surface: '#0b0f14',
    surface2: '#11161d',
    border: '#ffffff14',
    border2: '#ffffff24',
    divider: '#ffffff10',
    text: '#ffffff',
    sub: '#c8d6e2',
    sub2: '#8fa1b3',
    muted: '#5d6b82',
    faint: '#3a4256',
    accent: '#2bb8e8',
    accentText: '#2bb8e8',
    accentSoft: 'rgba(43,184,232,.13)',
    accentBorder: 'rgba(43,184,232,.4)',
    grad: 'linear-gradient(180deg,#3ecbf5,#149ed6)',
    gradFg: '#00131f',
    pos: '#3ddb8a',
    posBg: 'rgba(22,201,100,.13)',
    posBorder: 'rgba(22,201,100,.32)',
    neg: '#ff7080',
    negSoft: '#ff9aa4',
    negBg: 'rgba(226,59,78,.13)',
    negBorder: 'rgba(226,59,78,.45)',
    warn: '#f5a524',
    warnBg: 'rgba(245,165,36,.15)',
    heroBg: '#07090d',
    heroBorder: '#ffffff1a',
    heroShadow: 'none',
    heroLabel: '#5d6b82',
    heroSub: '#8fa1b3',
    heroText: '#ffffff',
    heroTrack: 'rgba(255,255,255,.12)',
    heroLine: 'rgba(255,255,255,.12)',
    heroValGrad: 'linear-gradient(180deg,#ffffff 8%,#c8d6e2 42%,#7d93a6 52%,#eef6fc 78%)',
    heroValColor: 'transparent',
    navBg: '#000000',
    navBorder: '#ffffff14',
    navActive: '#2bb8e8',
    navInactive: '#5d6b82',
    inputBg: '#0b0f14',
    inputBorder: '#ffffff24',
    trackOnSoft: 'rgba(255,255,255,.14)',
    sheetBg: '#0c1016',
    handle: '#ffffff2a',
    overlay: 'rgba(0,0,0,.7)',
    toastBg: '#0f1a12',
    toastBorder: 'rgba(22,201,100,.4)',
    toastText: '#ffffff',
    cardShadow: 'none',
    ringOk: '#2bb8e8',
    ringWarn: '#f5a524',
    ringDanger: '#ff5f6f',
    ringZero: '#5d6b82',
    glowOk: 'rgba(43,184,232,.35)',
    glowWarn: 'rgba(245,165,36,.3)',
    glowDanger: 'rgba(239,95,111,.35)',
    glowZero: 'rgba(93,107,130,.25)',
    iconNeutralBg: '#141a22',
    iconNeutralFg: '#e8eef4',
    chipBg: '#0b0f14',
    chipFg: '#c8d6e2',
    chipBorder: '#ffffff24',
    chipActiveBg: 'rgba(43,184,232,.14)',
    chipActiveFg: '#2bb8e8',
    chipActiveBorder: 'rgba(43,184,232,.5)',
    status: {
      proposta: ['rgba(200,214,226,.13)', '#c8d6e2'],
      registrada: ['rgba(43,184,232,.15)', '#5fd3ef'],
      ativa: ['rgba(22,201,100,.15)', '#3ddb8a'],
      liquidada: ['rgba(143,161,179,.14)', '#8fa1b3'],
      renegociada: ['rgba(245,165,36,.15)', '#f5a524'],
      inadimplente: ['rgba(239,95,111,.15)', '#ff7080'],
      cancelada: ['rgba(143,161,179,.1)', '#6b7688'],
    },
    tones: {
      positive: ['rgba(22,201,100,.13)', '#3ddb8a'],
      neutral: ['#141a22', '#e8eef4'],
      negative: ['rgba(239,95,111,.13)', '#ff7080'],
      cyan: ['#141a22', '#2bb8e8'],
      muted: ['#141a22', '#8fa1b3'],
    },
  },
  aurora: {
    label: 'Aurora Glass',
    dark: true,
    fd: QUICKSAND,
    fb: MANROPE,
    bg: '#050a16',
    surface: 'rgba(255,255,255,.07)',
    surface2: 'rgba(255,255,255,.06)',
    border: 'rgba(255,255,255,.16)',
    border2: 'rgba(255,255,255,.22)',
    divider: 'rgba(255,255,255,.1)',
    text: '#ffffff',
    sub: '#cfe0ec',
    sub2: '#a8bdd0',
    muted: '#7d93ad',
    faint: '#5a6d85',
    accent: '#18e0f8',
    accentText: '#8fd8f0',
    accentSoft: 'rgba(24,224,248,.14)',
    accentBorder: 'rgba(24,224,248,.4)',
    grad: 'linear-gradient(135deg,#0078c0,#18e0f8)',
    gradFg: '#021a2d',
    pos: '#3ddb8a',
    posBg: 'rgba(22,201,100,.15)',
    posBorder: 'rgba(22,201,100,.35)',
    neg: '#ff8a97',
    negSoft: '#ffb3bc',
    negBg: 'rgba(226,59,78,.16)',
    negBorder: 'rgba(255,112,128,.4)',
    warn: '#f5b445',
    warnBg: 'rgba(245,165,36,.18)',
    heroBg: 'rgba(255,255,255,.08)',
    heroBorder: 'rgba(255,255,255,.18)',
    heroShadow: 'none',
    heroLabel: '#8fd8f0',
    heroSub: '#a8bdd0',
    heroText: '#ffffff',
    heroTrack: 'rgba(255,255,255,.14)',
    heroLine: 'rgba(255,255,255,.14)',
    heroValGrad: 'none',
    heroValColor: '#ffffff',
    navBg: 'rgba(9,16,30,.85)',
    navBorder: 'rgba(255,255,255,.14)',
    navActive: '#18e0f8',
    navInactive: '#7d93ad',
    inputBg: 'rgba(255,255,255,.08)',
    inputBorder: 'rgba(255,255,255,.22)',
    trackOnSoft: 'rgba(255,255,255,.16)',
    sheetBg: '#0b1424',
    handle: 'rgba(255,255,255,.25)',
    overlay: 'rgba(2,8,18,.66)',
    toastBg: '#0f1e1a',
    toastBorder: 'rgba(22,201,100,.4)',
    toastText: '#ffffff',
    cardShadow: 'none',
    ringOk: '#18e0f8',
    ringWarn: '#f5a524',
    ringDanger: '#ff5f6f',
    ringZero: '#7d93ad',
    glowOk: 'rgba(0,192,240,.4)',
    glowWarn: 'rgba(245,165,36,.3)',
    glowDanger: 'rgba(239,95,111,.35)',
    glowZero: 'rgba(125,147,173,.25)',
    iconNeutralBg: 'rgba(255,255,255,.1)',
    iconNeutralFg: '#e8f2fa',
    chipBg: 'rgba(255,255,255,.08)',
    chipFg: '#cfe0ec',
    chipBorder: 'rgba(255,255,255,.2)',
    chipActiveBg: 'rgba(24,224,248,.16)',
    chipActiveFg: '#18e0f8',
    chipActiveBorder: 'rgba(24,224,248,.5)',
    status: {
      proposta: ['rgba(207,224,236,.14)', '#cfe0ec'],
      registrada: ['rgba(24,224,248,.16)', '#5fd3ef'],
      ativa: ['rgba(22,201,100,.16)', '#3ddb8a'],
      liquidada: ['rgba(168,189,208,.16)', '#a8bdd0'],
      renegociada: ['rgba(245,165,36,.16)', '#f5b445'],
      inadimplente: ['rgba(239,95,111,.16)', '#ff8a97'],
      cancelada: ['rgba(168,189,208,.1)', '#7d93ad'],
    },
    tones: {
      positive: ['rgba(22,201,100,.15)', '#3ddb8a'],
      neutral: ['rgba(255,255,255,.1)', '#e8f2fa'],
      negative: ['rgba(239,95,111,.15)', '#ff8a97'],
      cyan: ['rgba(255,255,255,.1)', '#18e0f8'],
      muted: ['rgba(255,255,255,.08)', '#a8bdd0'],
    },
  },
}

export const THEME_NAMES: ThemeName[] = ['platinum', 'obsidian', 'aurora']

/** Rótulo humano de cada status de operação (espelha o backend). */
const STATUS_LABELS: Record<StatusKey, string> = {
  proposta: 'Proposta',
  registrada: 'Registrada',
  ativa: 'Ativa',
  liquidada: 'Liquidada',
  renegociada: 'Renegociada',
  inadimplente: 'Inadimplente',
  cancelada: 'Cancelada',
}

export interface ChipColors {
  label: string
  bg: string
  fg: string
}

/** bg/fg + rótulo de um status, no tema dado. Fallback: 'proposta'. */
export function statusMeta(theme: MobileTheme, status: string): ChipColors {
  const key = (status in theme.status ? status : 'proposta') as StatusKey
  const [bg, fg] = theme.status[key]
  return { label: STATUS_LABELS[key] ?? status, bg, fg }
}

/** bg/fg de um "tone" (usado por ícones do ledger etc.). Fallback: 'muted'. */
export function toneColors(theme: MobileTheme, tone: string): { bg: string; fg: string } {
  const key = (tone in theme.tones ? tone : 'muted') as ToneKey
  const [bg, fg] = theme.tones[key]
  return { bg, fg }
}
