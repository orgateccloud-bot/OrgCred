import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'

/**
 * Máquina de navegação do app mobile — o `state`/handlers do design, em React
 * idiomático. A navegação é por ESTADO (não por URL): é um app, com transições
 * e sheets, e o design foi desenhado assim. As telas leem o estado e disparam
 * ações por este contexto.
 */

export type MobileTab = 'inicio' | 'operacoes' | 'tomadores' | 'cobranca' | 'mais'
export type OpScreen = 'list' | 'detail' | 'new1' | 'new2'
export type TomScreen = 'list' | 'detail' | 'new'
export type MaisScreen = 'menu' | 'auditoria' | 'compliance' | 'capitalSocial' | 'capitalSocialNew'

/** Ações de ciclo de vida disparadas por um bottom sheet de confirmação. */
export type SheetType =
  'ativar' | 'registrar' | 'liquidar' | 'renegociar' | 'cancelar' | 'marcarInadimplente'

export interface SheetState {
  type: SheetType
  opId: string
}

/** Rascunho da nova operação (passo 1 → 2). */
export interface NovaOpDraft {
  tomadorId: string | null
  tipo: 'emprestimo' | 'financiamento' | null
  valorStr: string
  taxaStr: string
  parcelasStr: string
  amortizacao: 'PRICE' | 'SAC'
}

const NOVA_OP_VAZIA: NovaOpDraft = {
  tomadorId: null,
  tipo: null,
  valorStr: '',
  taxaStr: '',
  parcelasStr: '',
  amortizacao: 'PRICE',
}

interface MobileAppValue {
  tab: MobileTab
  opScreen: OpScreen
  opSelectedId: string | null
  tomScreen: TomScreen
  tomSelectedId: string | null
  maisScreen: MaisScreen
  novaOp: NovaOpDraft
  sheet: SheetState | null
  notifOpen: boolean
  toast: string | null

  goTab: (tab: MobileTab) => void
  openOpDetail: (id: string) => void
  backToOpList: () => void
  abrirNovaOp: (prefillTomadorId?: string) => void
  irNovaOp2: () => void
  voltarNovaOp1: () => void
  setNovaOp: (patch: Partial<NovaOpDraft>) => void
  resetNovaOp: () => void

  openTomDetail: (id: string) => void
  backToTomList: () => void
  abrirNovoTom: () => void
  backFromNovoTom: () => void

  goMaisMenu: () => void
  goAuditoria: () => void
  goCompliance: () => void
  goCapitalSocial: () => void
  abrirCapitalSocialNew: () => void
  backFromCapitalSocialNew: () => void

  openSheet: (type: SheetType, opId: string) => void
  closeSheet: () => void
  showToast: (msg: string) => void
  toggleNotif: () => void
  closeNotif: () => void
}

const MobileAppContext = createContext<MobileAppValue | null>(null)

export function MobileAppProvider({ children }: { children: ReactNode }) {
  const [tab, setTab] = useState<MobileTab>('inicio')
  const [opScreen, setOpScreen] = useState<OpScreen>('list')
  const [opSelectedId, setOpSelectedId] = useState<string | null>(null)
  const [tomScreen, setTomScreen] = useState<TomScreen>('list')
  const [tomSelectedId, setTomSelectedId] = useState<string | null>(null)
  const [maisScreen, setMaisScreen] = useState<MaisScreen>('menu')
  const [novaOp, setNovaOpState] = useState<NovaOpDraft>(NOVA_OP_VAZIA)
  const [sheet, setSheet] = useState<SheetState | null>(null)
  const [notifOpen, setNotifOpen] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const goTab = useCallback((proximo: MobileTab) => {
    // Tocar na aba ativa reseta a pilha daquela aba (padrão iOS).
    setTab((atual) => {
      if (atual === proximo) {
        if (proximo === 'operacoes') {
          setOpScreen('list')
          setOpSelectedId(null)
        } else if (proximo === 'tomadores') {
          setTomScreen('list')
          setTomSelectedId(null)
        } else if (proximo === 'mais') {
          setMaisScreen('menu')
        }
      }
      return proximo
    })
    setNotifOpen(false)
  }, [])

  const openOpDetail = useCallback((id: string) => {
    setTab('operacoes')
    setOpScreen('detail')
    setOpSelectedId(id)
  }, [])
  const backToOpList = useCallback(() => {
    setOpScreen('list')
    setOpSelectedId(null)
  }, [])
  const abrirNovaOp = useCallback((prefillTomadorId?: string) => {
    setNovaOpState({ ...NOVA_OP_VAZIA, tomadorId: prefillTomadorId ?? null })
    setTab('operacoes')
    setOpScreen('new1')
  }, [])
  const irNovaOp2 = useCallback(() => setOpScreen('new2'), [])
  const voltarNovaOp1 = useCallback(() => setOpScreen('new1'), [])
  const setNovaOp = useCallback(
    (patch: Partial<NovaOpDraft>) => setNovaOpState((d) => ({ ...d, ...patch })),
    [],
  )
  const resetNovaOp = useCallback(() => setNovaOpState(NOVA_OP_VAZIA), [])

  const openTomDetail = useCallback((id: string) => {
    setTab('tomadores')
    setTomScreen('detail')
    setTomSelectedId(id)
  }, [])
  const backToTomList = useCallback(() => {
    setTomScreen('list')
    setTomSelectedId(null)
  }, [])
  const abrirNovoTom = useCallback(() => setTomScreen('new'), [])
  const backFromNovoTom = useCallback(() => setTomScreen('list'), [])

  const goMaisMenu = useCallback(() => setMaisScreen('menu'), [])
  const goAuditoria = useCallback(() => {
    setTab('mais')
    setMaisScreen('auditoria')
  }, [])
  const goCompliance = useCallback(() => {
    setTab('mais')
    setMaisScreen('compliance')
  }, [])
  const goCapitalSocial = useCallback(() => {
    setTab('mais')
    setMaisScreen('capitalSocial')
  }, [])
  const abrirCapitalSocialNew = useCallback(() => setMaisScreen('capitalSocialNew'), [])
  const backFromCapitalSocialNew = useCallback(() => setMaisScreen('capitalSocial'), [])

  const openSheet = useCallback((type: SheetType, opId: string) => setSheet({ type, opId }), [])
  const closeSheet = useCallback(() => setSheet(null), [])
  const showToast = useCallback((msg: string) => {
    setToast(msg)
    if (toastTimer.current) clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(null), 2800)
  }, [])
  const toggleNotif = useCallback(() => setNotifOpen((v) => !v), [])
  const closeNotif = useCallback(() => setNotifOpen(false), [])

  const value = useMemo<MobileAppValue>(
    () => ({
      tab,
      opScreen,
      opSelectedId,
      tomScreen,
      tomSelectedId,
      maisScreen,
      novaOp,
      sheet,
      notifOpen,
      toast,
      goTab,
      openOpDetail,
      backToOpList,
      abrirNovaOp,
      irNovaOp2,
      voltarNovaOp1,
      setNovaOp,
      resetNovaOp,
      openTomDetail,
      backToTomList,
      abrirNovoTom,
      backFromNovoTom,
      goMaisMenu,
      goAuditoria,
      goCompliance,
      goCapitalSocial,
      abrirCapitalSocialNew,
      backFromCapitalSocialNew,
      openSheet,
      closeSheet,
      showToast,
      toggleNotif,
      closeNotif,
    }),
    [
      tab,
      opScreen,
      opSelectedId,
      tomScreen,
      tomSelectedId,
      maisScreen,
      novaOp,
      sheet,
      notifOpen,
      toast,
      goTab,
      openOpDetail,
      backToOpList,
      abrirNovaOp,
      irNovaOp2,
      voltarNovaOp1,
      setNovaOp,
      resetNovaOp,
      openTomDetail,
      backToTomList,
      abrirNovoTom,
      backFromNovoTom,
      goMaisMenu,
      goAuditoria,
      goCompliance,
      goCapitalSocial,
      abrirCapitalSocialNew,
      backFromCapitalSocialNew,
      openSheet,
      closeSheet,
      showToast,
      toggleNotif,
      closeNotif,
    ],
  )

  return <MobileAppContext.Provider value={value}>{children}</MobileAppContext.Provider>
}

export function useMobileApp(): MobileAppValue {
  const ctx = useContext(MobileAppContext)
  if (!ctx) throw new Error('useMobileApp precisa estar dentro de <MobileAppProvider>')
  return ctx
}
