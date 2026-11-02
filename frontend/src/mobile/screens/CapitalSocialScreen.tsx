import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getCapitalSnapshotApiCapitalSnapshotGetOptions,
  getCapitalEventosApiCapitalEventosGetOptions,
  getCapitalEventosApiCapitalEventosGetQueryKey,
  getAuditoriaApiAuditoriaGetQueryKey,
  postCapitalEventoApiCapitalEventosPostMutation,
} from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { useMobileTheme } from '../MobileThemeContext'
import { useMobileApp } from '../MobileAppContext'
import { Icon } from '../icons'
import { formatarMoeda, parseBRL, dataCurta } from '../format'
import {
  Screen,
  ScreenScroll,
  TopBar,
  HeaderAction,
  Field,
  FooterBar,
  PrimaryButton,
  ScreenError,
  SkeletonBar,
} from '../components/kit'

type TipoEvento = 'constituicao' | 'reducao'

/**
 * Tela Capital social — dois estados (lista de eventos + registrar evento).
 * O teto vem do snapshot real; registrar um evento (constituição/redução)
 * chama `postCapitalEvento` e o BANCO recalcula o teto (Art. 5º, LC 167/2019).
 * Admin-only (só chega aqui pelo menu Mais quando isAdmin).
 */
export function CapitalSocialScreen() {
  const app = useMobileApp()
  if (app.maisScreen === 'capitalSocialNew') return <RegistrarEvento />
  return <ListaCapital />
}

function ListaCapital() {
  const t = useMobileTheme()
  const app = useMobileApp()
  const snapshot = useQuery(getCapitalSnapshotApiCapitalSnapshotGetOptions())
  const eventos = useQuery(getCapitalEventosApiCapitalEventosGetOptions())

  const teto = Number(snapshot.data?.total ?? 0)
  const tetoZerado = teto <= 0
  const lista = eventos.data ?? []

  return (
    <Screen label="Capital social">
      <TopBar
        onBack={app.goMaisMenu}
        title="Capital social"
        trailing={
          <HeaderAction icon="plus" label="Registrar evento" onClick={app.abrirCapitalSocialNew} />
        }
      />

      <ScreenScroll style={{ padding: '4px 20px 28px', gap: 16 }}>
        {(!!snapshot.error || !!eventos.error) && (
          <ScreenError mensagem="Não foi possível carregar o capital social." />
        )}
        {snapshot.isPending && !snapshot.data && (
          <SkeletonBar height={120} style={{ borderRadius: 16 }} />
        )}

        {snapshot.data && (
          <div
            style={{
              borderRadius: 16,
              padding: 18,
              background: t.heroBg,
              border: `1px solid ${t.heroBorder}`,
              boxShadow: t.heroShadow,
              display: 'flex',
              flexDirection: 'column',
              gap: 6,
            }}
          >
            <span
              style={{
                font: `700 10px ${t.fb}`,
                letterSpacing: '.12em',
                textTransform: 'uppercase',
                color: t.heroLabel,
              }}
            >
              Teto legal atual
            </span>
            <span
              style={{ font: "600 26px 'JetBrains Mono Variable',monospace", color: t.heroText }}
            >
              {formatarMoeda(teto)}
            </span>
            <span style={{ font: `500 11.5px ${t.fb}`, color: t.heroSub, lineHeight: 1.5 }}>
              {tetoZerado
                ? 'Nenhum evento de constituição registrado. Registre o aporte inicial para liberar o teto operacional (Art. 5º, LC 167/2019).'
                : 'Teto recalculado pelo banco a cada evento — nenhuma mudança de código necessária.'}
            </span>
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <span style={{ font: `700 13.5px ${t.fd}`, color: t.text }}>Eventos</span>
          {lista.map((e) => {
            const reducao = e.tipo_evento === 'reducao'
            const magnitude = Math.abs(Number(e.valor))
            return (
              <div
                key={e.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 11,
                  padding: '12px 13px',
                  background: t.surface,
                  border: `1px solid ${t.border}`,
                  boxShadow: t.cardShadow,
                  borderRadius: 13,
                }}
              >
                <span
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: 9,
                    background: t.accentSoft,
                    color: t.accentText,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flex: 'none',
                  }}
                >
                  <Icon name="landmark" size={15} />
                </span>
                <span style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 1 }}>
                  <span style={{ font: `600 12.5px ${t.fb}`, color: t.text }}>
                    {reducao ? 'Redução' : 'Constituição'}
                  </span>
                  <span style={{ font: `500 11px ${t.fb}`, color: t.sub2 }}>
                    {dataCurta(e.created_at)}
                  </span>
                </span>
                <span
                  style={{
                    font: "600 13px 'JetBrains Mono Variable',monospace",
                    color: reducao ? t.neg : t.pos,
                  }}
                >
                  {reducao ? '− ' : '+ '}
                  {formatarMoeda(magnitude)}
                </span>
              </div>
            )
          })}
          {eventos.data && lista.length === 0 && (
            <span style={{ font: `500 12px ${t.fb}`, color: t.muted }}>
              Nenhum evento registrado ainda.
            </span>
          )}
        </div>
      </ScreenScroll>
    </Screen>
  )
}

function RegistrarEvento() {
  const t = useMobileTheme()
  const app = useMobileApp()
  const queryClient = useQueryClient()
  const [tipo, setTipo] = useState<TipoEvento>('constituicao')
  const [valorStr, setValorStr] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const criar = useMutation(postCapitalEventoApiCapitalEventosPostMutation())

  function confirmar() {
    setErro(null)
    const v = parseBRL(valorStr)
    if (!v || v <= 0) {
      setErro('Informe um valor válido.')
      return
    }
    criar.mutate(
      { body: { valor: v, tipo_evento: tipo } },
      {
        onSuccess: () => {
          queryClient.invalidateQueries({
            queryKey: getCapitalSnapshotApiCapitalSnapshotGetOptions().queryKey,
          })
          queryClient.invalidateQueries({
            queryKey: getCapitalEventosApiCapitalEventosGetQueryKey(),
          })
          queryClient.invalidateQueries({ queryKey: getAuditoriaApiAuditoriaGetQueryKey() })
          app.showToast('Evento de capital social registrado.')
          app.backFromCapitalSocialNew()
        },
        onError: (e) => setErro(mensagemDeErro(e)),
      },
    )
  }

  const chips: Array<{ key: TipoEvento; label: string }> = [
    { key: 'constituicao', label: 'Constituição' },
    { key: 'reducao', label: 'Redução' },
  ]

  return (
    <Screen label="Registrar evento">
      <TopBar onBack={app.backFromCapitalSocialNew} title="Registrar evento" />

      <ScreenScroll style={{ padding: '4px 20px 20px', gap: 16 }}>
        <div style={{ display: 'flex', gap: 8 }}>
          {chips.map((c) => {
            const ativo = tipo === c.key
            return (
              <button
                key={c.key}
                type="button"
                onClick={() => setTipo(c.key)}
                style={{
                  flex: 1,
                  background: ativo ? t.chipActiveBg : t.chipBg,
                  color: ativo ? t.chipActiveFg : t.chipFg,
                  border: `1px solid ${ativo ? t.chipActiveBorder : t.chipBorder}`,
                  borderRadius: 12,
                  padding: 11,
                  font: `700 12.5px ${t.fb}`,
                  cursor: 'pointer',
                }}
              >
                {c.label}
              </button>
            )
          })}
        </div>

        <Field
          label="Valor"
          value={valorStr}
          onChange={setValorStr}
          placeholder="0,00"
          inputMode="decimal"
          mono
          prefix="R$"
        />

        {erro && <span style={{ font: `600 12px ${t.fb}`, color: t.neg }}>{erro}</span>}
      </ScreenScroll>

      <FooterBar>
        <PrimaryButton onClick={confirmar} disabled={criar.isPending}>
          {criar.isPending ? 'Registrando…' : 'Confirmar evento'}
        </PrimaryButton>
      </FooterBar>
    </Screen>
  )
}
