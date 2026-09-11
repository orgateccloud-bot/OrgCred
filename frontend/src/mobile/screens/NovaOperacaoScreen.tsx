import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getTomadoresApiTomadoresGetOptions,
  getCapitalSnapshotApiCapitalSnapshotGetOptions,
  getOperacoesApiOperacoesGetQueryKey,
  getAuditoriaApiAuditoriaGetQueryKey,
  postCriarOperacaoApiOperacoesPostMutation,
} from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { useMobileTheme } from '../MobileThemeContext'
import { useMobileApp } from '../MobileAppContext'
import { formatarMoeda, parseBRL, formatarTaxa } from '../format'
import { Icon } from '../icons'
import {
  Screen,
  ScreenScroll,
  TopBar,
  Card,
  Field,
  FooterBar,
  PrimaryButton,
} from '../components/kit'

/**
 * Nova operação — assistente de 2 passos (condições → revisão), fiel ao design.
 * Cria sempre uma PROPOSTA (`postCriarOperacao`); a ativação, que compromete o
 * teto, é um passo separado sujeito ao Art. 5º (O BANCO DECIDE). A API real
 * exige `sistema_amortizacao` (PRICE/SAC) e só aceita empréstimo/financiamento.
 */
const num = (v: string | number | null | undefined) => Number(v ?? 0) || 0

export function NovaOperacaoScreen() {
  const app = useMobileApp()
  return app.opScreen === 'new2' ? <Passo2 /> : <Passo1 />
}

function Passo1() {
  const t = useMobileTheme()
  const app = useMobileApp()
  const { novaOp } = app
  const tomadores = useQuery(getTomadoresApiTomadoresGetOptions())

  const tipos: Array<{ key: 'emprestimo' | 'financiamento'; label: string }> = [
    { key: 'emprestimo', label: 'Empréstimo' },
    { key: 'financiamento', label: 'Financiamento' },
  ]

  const erroCampos =
    !novaOp.tomadorId || !novaOp.tipo || parseBRL(novaOp.valorStr) <= 0 || !novaOp.parcelasStr

  return (
    <Screen label="Nova operação — 1">
      <TopBar onBack={app.backToOpList} title="Nova operação" subtitle="Passo 1 de 2 · condições" />

      <ScreenScroll style={{ padding: '4px 20px 20px', gap: 16 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <span style={{ font: `700 11.5px ${t.fb}`, color: t.sub }}>Tomador</span>
          {(tomadores.data ?? []).map((tm) => {
            const sel = novaOp.tomadorId === tm.id
            return (
              <div
                key={tm.id}
                onClick={() => app.setNovaOp({ tomadorId: tm.id })}
                style={{
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '11px 13px',
                  borderRadius: 12,
                  background: sel ? t.chipActiveBg : t.surface,
                  border: `1px solid ${sel ? t.chipActiveBorder : t.border2}`,
                }}
              >
                <span
                  style={{
                    flex: 1,
                    minWidth: 0,
                    font: `600 13px ${t.fb}`,
                    color: t.text,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {tm.razao_social}
                </span>
                {sel && <Icon name="check-circle-2" size={17} color={t.accentText} />}
              </div>
            )
          })}
          {tomadores.data && tomadores.data.length === 0 && (
            <span style={{ font: `500 12px ${t.fb}`, color: t.muted }}>
              Cadastre um tomador antes (aba Tomadores).
            </span>
          )}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <span style={{ font: `700 11.5px ${t.fb}`, color: t.sub }}>Tipo de operação</span>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {tipos.map((c) => {
              const ativo = novaOp.tipo === c.key
              return (
                <button
                  key={c.key}
                  type="button"
                  onClick={() => app.setNovaOp({ tipo: c.key })}
                  style={{
                    background: ativo ? t.chipActiveBg : t.chipBg,
                    color: ativo ? t.chipActiveFg : t.chipFg,
                    border: `1px solid ${ativo ? t.chipActiveBorder : t.chipBorder}`,
                    borderRadius: 999,
                    padding: '8px 14px',
                    font: `700 12px ${t.fb}`,
                    cursor: 'pointer',
                  }}
                >
                  {c.label}
                </button>
              )
            })}
          </div>
        </div>

        <Field
          label="Valor principal"
          value={novaOp.valorStr}
          onChange={(v) => app.setNovaOp({ valorStr: v })}
          placeholder="0,00"
          inputMode="decimal"
          mono
          prefix="R$"
        />

        <div style={{ display: 'flex', gap: 12 }}>
          <div style={{ flex: 1 }}>
            <Field
              label="Taxa a.m. (%)"
              value={novaOp.taxaStr}
              onChange={(v) => app.setNovaOp({ taxaStr: v })}
              placeholder="2,10"
              inputMode="decimal"
              mono
            />
          </div>
          <div style={{ flex: 1 }}>
            <Field
              label="Parcelas"
              value={novaOp.parcelasStr}
              onChange={(v) => app.setNovaOp({ parcelasStr: v })}
              placeholder="18"
              inputMode="numeric"
              mono
            />
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <span style={{ font: `700 11.5px ${t.fb}`, color: t.sub }}>Sistema de amortização</span>
          <div style={{ display: 'flex', gap: 8 }}>
            {(['PRICE', 'SAC'] as const).map((a) => {
              const ativo = novaOp.amortizacao === a
              return (
                <button
                  key={a}
                  type="button"
                  onClick={() => app.setNovaOp({ amortizacao: a })}
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
                  {a}
                </button>
              )
            })}
          </div>
        </div>

        {erroCampos && (
          <span style={{ font: `600 12px ${t.fb}`, color: t.sub2, lineHeight: 1.5 }}>
            Preencha tomador, tipo, valor e parcelas para continuar.
          </span>
        )}
      </ScreenScroll>

      <FooterBar>
        <PrimaryButton onClick={app.irNovaOp2} disabled={erroCampos}>
          Avançar
        </PrimaryButton>
      </FooterBar>
    </Screen>
  )
}

function Passo2() {
  const t = useMobileTheme()
  const app = useMobileApp()
  const { novaOp } = app
  const queryClient = useQueryClient()
  const tomadores = useQuery(getTomadoresApiTomadoresGetOptions())
  const snapshot = useQuery(getCapitalSnapshotApiCapitalSnapshotGetOptions())
  const criar = useMutation(postCriarOperacaoApiOperacoesPostMutation())

  const tomador = (tomadores.data ?? []).find((x) => x.id === novaOp.tomadorId)
  const valor = parseBRL(novaOp.valorStr)
  const teto = num(snapshot.data?.total)
  const comprometido = num(snapshot.data?.comprometido)
  const proj = comprometido + valor
  const projPct = teto > 0 ? Math.min(100, Math.round((proj / teto) * 100)) : 100
  const bloqueado = teto <= 0 || proj > teto

  function confirmar() {
    if (!novaOp.tomadorId || !novaOp.tipo) return
    criar.mutate(
      {
        body: {
          tomador_id: novaOp.tomadorId,
          tipo: novaOp.tipo,
          valor_principal: valor,
          taxa_juros_mensal: parseBRL(novaOp.taxaStr),
          sistema_amortizacao: novaOp.amortizacao,
          numero_parcelas: parseInt(novaOp.parcelasStr, 10) || 1,
        },
      },
      {
        onSuccess: (nova) => {
          queryClient.invalidateQueries({ queryKey: getOperacoesApiOperacoesGetQueryKey() })
          queryClient.invalidateQueries({ queryKey: getAuditoriaApiAuditoriaGetQueryKey() })
          app.resetNovaOp()
          app.showToast('Operação registrada como proposta.')
          app.openOpDetail(nova.id)
        },
      },
    )
  }

  return (
    <Screen label="Nova operação — 2">
      <TopBar onBack={app.voltarNovaOp1} title="Nova operação" subtitle="Passo 2 de 2 · revisão" />

      <ScreenScroll style={{ padding: '4px 20px 20px', gap: 14 }}>
        <Card style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <LinhaRev label="Tomador" valor={tomador?.razao_social ?? '—'} t={t} />
          <LinhaRev
            label="Tipo"
            valor={novaOp.tipo === 'financiamento' ? 'Financiamento' : 'Empréstimo'}
            t={t}
          />
          <LinhaRev label="Valor" valor={formatarMoeda(valor)} mono t={t} />
          <LinhaRev
            label="Taxa · parcelas · amort."
            valor={`${formatarTaxa(parseBRL(novaOp.taxaStr))} · ${novaOp.parcelasStr || '0'}x · ${novaOp.amortizacao}`}
            mono
            t={t}
          />
        </Card>

        <div
          style={{
            borderRadius: 16,
            padding: 16,
            background: t.accentSoft,
            border: `1px solid ${t.accentBorder}`,
            display: 'flex',
            flexDirection: 'column',
            gap: 9,
          }}
        >
          <span
            style={{
              font: `700 11px ${t.fb}`,
              letterSpacing: '.1em',
              textTransform: 'uppercase',
              color: t.accentText,
            }}
          >
            Impacto no teto (após ativação)
          </span>
          <div
            style={{ height: 7, borderRadius: 999, background: t.trackOnSoft, overflow: 'hidden' }}
          >
            <div
              style={{
                height: '100%',
                width: `${projPct}%`,
                background: bloqueado ? t.ringDanger : t.ringOk,
              }}
            />
          </div>
          <span style={{ font: `600 12px ${t.fb}`, color: t.sub }}>
            {formatarMoeda(proj)} de {formatarMoeda(teto)} —{' '}
            {bloqueado ? 'excede o teto' : `${projPct}% do teto`}
          </span>
        </div>

        <span style={{ font: `500 11.5px ${t.fb}`, color: t.sub2, lineHeight: 1.5 }}>
          A proposta é sempre criada; a ativação (que compromete o teto) é um passo separado,
          sujeito ao Art. 5º, LC 167/2019.
        </span>

        {!!criar.error && (
          <span style={{ font: `600 12px ${t.fb}`, color: t.neg }}>
            {mensagemDeErro(criar.error)}
          </span>
        )}
      </ScreenScroll>

      <FooterBar>
        <PrimaryButton onClick={confirmar} disabled={criar.isPending}>
          {criar.isPending ? 'Registrando…' : 'Confirmar e registrar proposta'}
        </PrimaryButton>
      </FooterBar>
    </Screen>
  )
}

function LinhaRev({
  label,
  valor,
  mono,
  t,
}: {
  label: string
  valor: string
  mono?: boolean
  t: ReturnType<typeof useMobileTheme>
}) {
  return (
    <span style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
      <span style={{ font: `500 12px ${t.fb}`, color: t.sub2 }}>{label}</span>
      <span
        style={{
          font: `600 12.5px ${mono ? "'JetBrains Mono Variable',monospace" : t.fb}`,
          color: t.text,
          textAlign: 'right',
        }}
      >
        {valor}
      </span>
    </span>
  )
}
