import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getOperacoesApiOperacoesGetOptions } from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { rotuloTipo } from '@/lib/rotulos'
import { useMobileTheme } from '../MobileThemeContext'
import { useMobileApp } from '../MobileAppContext'
import { Icon } from '../icons'
import { statusMeta } from '../theme'
import { formatarMoeda } from '../format'
import {
  Screen,
  ScreenScroll,
  TopBar,
  HeaderAction,
  Card,
  StatusPill,
  EmptyState,
  ScreenError,
  SkeletonBar,
} from '../components/kit'

/** Tela Operações — lista filtrável por status. Design `data-screen-label="Operações"`. */
const FILTROS: Array<{ key: string; label: string }> = [
  { key: 'todas', label: 'Todas' },
  { key: 'ativa', label: 'Ativas' },
  { key: 'registrada', label: 'Registradas' },
  { key: 'proposta', label: 'Propostas' },
  { key: 'inadimplente', label: 'Inadimplentes' },
]

export function OperacoesScreen() {
  const t = useMobileTheme()
  const app = useMobileApp()
  const [filtro, setFiltro] = useState('todas')
  const { data, isPending, error } = useQuery(getOperacoesApiOperacoesGetOptions())

  const lista = data ?? []
  const filtradas = lista.filter((o) => filtro === 'todas' || o.status === filtro)

  return (
    <Screen label="Operações">
      <TopBar
        title="Operações"
        subtitle={`${lista.length} no total`}
        large
        trailing={
          <HeaderAction icon="plus" label="Nova operação" onClick={() => app.abrirNovaOp()} />
        }
      />

      {/* Chips de filtro (com contagem). */}
      <div
        style={{
          flex: 'none',
          display: 'flex',
          gap: 8,
          padding: '2px 20px 10px',
          overflowX: 'auto',
        }}
      >
        {FILTROS.map((f) => {
          const count =
            f.key === 'todas' ? lista.length : lista.filter((o) => o.status === f.key).length
          const ativo = filtro === f.key
          return (
            <button
              key={f.key}
              type="button"
              onClick={() => setFiltro(f.key)}
              style={{
                flex: 'none',
                whiteSpace: 'nowrap',
                background: ativo ? t.chipActiveBg : t.chipBg,
                color: ativo ? t.chipActiveFg : t.chipFg,
                border: `1px solid ${ativo ? t.chipActiveBorder : t.chipBorder}`,
                borderRadius: 999,
                padding: '7px 13px',
                font: `700 11.5px ${t.fb}`,
                cursor: 'pointer',
              }}
            >
              {f.label} · {count}
            </button>
          )
        })}
      </div>

      <ScreenScroll style={{ padding: '4px 20px 28px', gap: 10 }}>
        {error && <ScreenError mensagem={mensagemDeErro(error)} />}
        {isPending &&
          !data &&
          Array.from({ length: 4 }).map((_, i) => (
            <SkeletonBar key={i} height={76} style={{ borderRadius: 16 }} />
          ))}

        {data &&
          filtradas.map((op) => {
            const sm = statusMeta(t, op.status)
            return (
              <Card
                key={op.id}
                onClick={() => app.openOpDetail(op.id)}
                style={{ padding: '15px 16px' }}
              >
                <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'flex-start',
                      gap: 10,
                    }}
                  >
                    <span style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
                      <span
                        style={{
                          font: `700 13.5px ${t.fb}`,
                          color: t.text,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {op.tomador_razao_social}
                      </span>
                      <span style={{ font: `500 11px ${t.fb}`, color: t.sub2 }}>
                        {rotuloTipo(op.tipo)}
                      </span>
                    </span>
                    <StatusPill label={sm.label} bg={sm.bg} fg={sm.fg} />
                  </div>
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                    }}
                  >
                    <span
                      style={{
                        font: "600 15px 'JetBrains Mono Variable',monospace",
                        color: t.text,
                      }}
                    >
                      {formatarMoeda(op.valor_principal)}
                    </span>
                    <Icon name="chevron-right" size={16} color={t.muted} />
                  </div>
                </div>
              </Card>
            )
          })}

        {data && filtradas.length === 0 && (
          <EmptyState icon="inbox" titulo="Nenhuma operação encontrada" />
        )}
      </ScreenScroll>
    </Screen>
  )
}
