import { useQuery } from '@tanstack/react-query'
import { getTomadoresApiTomadoresGetOptions } from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { useMobileTheme } from '../MobileThemeContext'
import { useMobileApp } from '../MobileAppContext'
import { Icon } from '../icons'
import {
  Screen,
  ScreenScroll,
  TopBar,
  HeaderAction,
  Card,
  IconTile,
  EmptyState,
  ScreenError,
  SkeletonBar,
} from '../components/kit'

/** Tela Tomadores — lista de empresas cadastradas. Design `data-screen-label="Tomadores"`. */
export function TomadoresScreen() {
  const t = useMobileTheme()
  const app = useMobileApp()
  const { data, isPending, error } = useQuery(getTomadoresApiTomadoresGetOptions())
  const lista = data ?? []

  return (
    <Screen label="Tomadores">
      <TopBar
        title="Tomadores"
        subtitle={`${lista.length} cadastrados`}
        large
        trailing={<HeaderAction icon="plus" label="Novo tomador" onClick={app.abrirNovoTom} />}
      />
      <ScreenScroll style={{ padding: '12px 20px 28px', gap: 10 }}>
        {error && <ScreenError mensagem={mensagemDeErro(error)} />}
        {isPending &&
          !data &&
          Array.from({ length: 5 }).map((_, i) => (
            <SkeletonBar key={i} height={62} style={{ borderRadius: 16 }} />
          ))}

        {data &&
          lista.map((tm) => (
            <Card
              key={tm.id}
              onClick={() => app.openTomDetail(tm.id)}
              style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 15px' }}
            >
              <IconTile
                icon="building-2"
                bg={t.accentSoft}
                fg={t.accentText}
                size={34}
                radius={10}
                iconSize={16}
              />
              <span
                style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 2 }}
              >
                <span
                  style={{
                    font: `700 13px ${t.fb}`,
                    color: t.text,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {tm.razao_social}
                </span>
                <span
                  style={{ font: "500 11px 'JetBrains Mono Variable',monospace", color: t.sub2 }}
                >
                  {tm.cnpj} · {tm.municipio}/{tm.uf}
                </span>
              </span>
              <Icon name="chevron-right" size={16} color={t.muted} />
            </Card>
          ))}

        {data && lista.length === 0 && (
          <EmptyState
            icon="inbox"
            titulo="Nenhum tomador cadastrado"
            descricao="Toque em + para cadastrar o primeiro."
          />
        )}
      </ScreenScroll>
    </Screen>
  )
}
