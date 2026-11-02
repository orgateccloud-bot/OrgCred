import { MobileThemeProvider, useMobileTheme } from './MobileThemeContext'
import { MobileAppProvider, useMobileApp } from './MobileAppContext'
import { useOperadorModel } from './data/useOperadorModel'
import { TabBar, Toast, NotifPanel } from './components/chrome'
import { OperacaoSheet } from './components/OperacaoSheet'
import { InicioScreen } from './screens/InicioScreen'
import { OperacoesScreen } from './screens/OperacoesScreen'
import { OperacaoDetailScreen } from './screens/OperacaoDetailScreen'
import { NovaOperacaoScreen } from './screens/NovaOperacaoScreen'
import { TomadoresScreen } from './screens/TomadoresScreen'
import { TomadorDetailScreen } from './screens/TomadorDetailScreen'
import { NovoTomadorScreen } from './screens/NovoTomadorScreen'
import { CobrancaScreen } from './screens/CobrancaScreen'
import { MaisScreen } from './screens/MaisScreen'
import { AuditoriaScreen } from './screens/AuditoriaScreen'
import { ComplianceScreen } from './screens/ComplianceScreen'
import { CapitalSocialScreen } from './screens/CapitalSocialScreen'

/**
 * OrgCred Mobile v2 — app operador nativo-mobile.
 *
 * Reimplementa o handoff do Claude Design (`OrgCred Mobile v2.dc.html`) como
 * React de verdade, fiado na API real (O BANCO DECIDE). A navegação é por
 * estado (ver MobileAppContext); os três temas são alternáveis (ver
 * MobileThemeContext). A moldura de iPhone do design era só apresentação — aqui
 * o app preenche o container e respeita `env(safe-area-inset-*)`.
 *
 * Mesmo componente montado em dois lugares: em `/app` (rota mobile autônoma) e
 * dentro de `_authenticated` em telas estreitas (o painel "no lugar").
 */

const KEYFRAMES = `
@keyframes oc-appear{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
@keyframes oc-sheetUp{from{opacity:0;transform:translateY(28px)}to{opacity:1;transform:none}}
@keyframes oc-fadeIn{from{opacity:0}to{opacity:1}}
@keyframes oc-pulse{0%,100%{opacity:.55}50%{opacity:1}}
@keyframes oc-pulseDot{0%,100%{opacity:.55}50%{opacity:1}}
@keyframes oc-floatA{0%,100%{transform:translate(0,0)}50%{transform:translate(30px,-20px)}}
`

/** Decide qual tela renderizar a partir do estado de navegação. */
function ScreenRouter() {
  const app = useMobileApp()
  switch (app.tab) {
    case 'inicio':
      return <InicioScreen />
    case 'operacoes':
      if (app.opScreen === 'detail') return <OperacaoDetailScreen />
      if (app.opScreen === 'new1' || app.opScreen === 'new2') return <NovaOperacaoScreen />
      return <OperacoesScreen />
    case 'tomadores':
      if (app.tomScreen === 'detail') return <TomadorDetailScreen />
      if (app.tomScreen === 'new') return <NovoTomadorScreen />
      return <TomadoresScreen />
    case 'cobranca':
      return <CobrancaScreen />
    case 'mais':
      if (app.maisScreen === 'auditoria') return <AuditoriaScreen />
      if (app.maisScreen === 'compliance') return <ComplianceScreen />
      if (app.maisScreen === 'capitalSocial' || app.maisScreen === 'capitalSocialNew')
        return <CapitalSocialScreen />
      return <MaisScreen />
  }
}

function AppInner() {
  const t = useMobileTheme()
  const { model } = useOperadorModel()
  const isAurora = t.label === 'Aurora Glass'

  return (
    <div
      style={{
        height: '100%',
        width: '100%',
        boxSizing: 'border-box',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        position: 'relative',
        background: t.bg,
        color: t.text,
        fontFamily: t.fb,
      }}
    >
      <style>{KEYFRAMES}</style>

      {/* Halos flutuantes do tema Aurora — decorativos, atrás do conteúdo. */}
      {isAurora && (
        <>
          <span
            aria-hidden
            style={{
              position: 'absolute',
              top: -120,
              left: -80,
              width: 340,
              height: 340,
              borderRadius: '50%',
              background: 'radial-gradient(circle,rgba(0,120,192,.55),transparent 65%)',
              filter: 'blur(10px)',
              animation: 'oc-floatA 9s ease-in-out infinite',
              pointerEvents: 'none',
            }}
          />
          <span
            aria-hidden
            style={{
              position: 'absolute',
              top: 40,
              right: -100,
              width: 300,
              height: 300,
              borderRadius: '50%',
              background: 'radial-gradient(circle,rgba(24,224,248,.28),transparent 65%)',
              filter: 'blur(12px)',
              animation: 'oc-floatA 12s ease-in-out infinite reverse',
              pointerEvents: 'none',
            }}
          />
        </>
      )}

      <ScreenRouter />
      <TabBar />

      {/* Overlays — sempre montados no fim, acima de tudo. */}
      <OperacaoSheet />
      <NotifPanel itens={model?.notificacoes ?? []} />
      <Toast />
    </div>
  )
}

export function OrgCredMobileApp() {
  return (
    <MobileThemeProvider>
      <MobileAppProvider>
        <AppInner />
      </MobileAppProvider>
    </MobileThemeProvider>
  )
}
