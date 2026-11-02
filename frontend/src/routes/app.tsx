import { createFileRoute, redirect } from '@tanstack/react-router'
import { getSession } from '@/auth/supabaseClient'
import { papelDoLogin } from '@/auth/papel'
import { OrgCredMobileApp } from '@/mobile/OrgCredMobileApp'

/**
 * Rota `/app` — o app mobile operador (OrgCred Mobile v2) como experiência
 * autônoma. Mesmo guarda de acesso do painel: sem sessão vai para o login; um
 * tomador vai para o portal (o backend já barra, isto evita uma tela que só
 * responderia 403).
 *
 * Em telas largas o app é centralizado numa coluna de ~480px sobre um fundo
 * escuro (o app é phone-shaped por design); no celular preenche a viewport.
 */
export const Route = createFileRoute('/app')({
  beforeLoad: async () => {
    const session = await getSession()
    if (!session) {
      throw redirect({ to: '/login' })
    }
    if ((await papelDoLogin()) === 'tomador') {
      throw redirect({ to: '/portal' })
    }
  },
  component: AppMobilePage,
})

function AppMobilePage() {
  return (
    <div
      style={{
        minHeight: '100dvh',
        width: '100%',
        display: 'flex',
        justifyContent: 'center',
        background: '#04060b',
      }}
    >
      <div style={{ width: '100%', maxWidth: 480, height: '100dvh' }}>
        <OrgCredMobileApp />
      </div>
    </div>
  )
}
