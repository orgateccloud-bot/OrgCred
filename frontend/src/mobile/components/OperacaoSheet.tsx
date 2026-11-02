import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getOperacaoApiOperacoesOperacaoIdGetOptions,
  getOperacoesApiOperacoesGetQueryKey,
  getParcelasApiOperacoesOperacaoIdParcelasGetQueryKey,
  getCapitalSnapshotApiCapitalSnapshotGetOptions,
  getCapitalEventosApiCapitalEventosGetQueryKey,
  getAgingApiCobrancaAgingGetQueryKey,
  getAuditoriaApiAuditoriaGetQueryKey,
  postAtivarOperacaoApiOperacoesOperacaoIdAtivarPostMutation,
  postRegistrarOperacaoApiOperacoesOperacaoIdRegistrarPostMutation,
  postLiquidarOperacaoApiOperacoesOperacaoIdLiquidarPostMutation,
  postRenegociarOperacaoApiOperacoesOperacaoIdRenegociarPostMutation,
  postCancelarOperacaoApiOperacoesOperacaoIdCancelarPostMutation,
  postMarcarInadimplenteApiOperacoesOperacaoIdMarcarInadimplentePostMutation,
} from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { useMobileTheme } from '../MobileThemeContext'
import { useMobileApp, type SheetType } from '../MobileAppContext'
import { Icon } from '../icons'
import { formatarMoeda } from '../format'

/**
 * Bottom sheet de ciclo de vida da operação — o equivalente mobile dos diálogos
 * do painel desktop. Cada ação chama a mutação REAL; o BANCO decide (ex.: ativar
 * pode ser barrada por OC001 no trigger, e a mensagem do banco aparece aqui).
 *
 * Fidelidade x realidade: "renegociar" no backend é uma NOVAÇÃO (cria a operação
 * substituta com termos novos). O design pedia só o novo prazo; mantemos essa
 * simplicidade e enviamos valor/taxa/amortização atuais + as novas parcelas.
 */

const num = (v: string | number | null | undefined) => Number(v ?? 0) || 0

export function OperacaoSheet() {
  const t = useMobileTheme()
  const app = useMobileApp()
  const queryClient = useQueryClient()
  const sheet = app.sheet

  // Estado dos campos do sheet (registro / novas parcelas).
  const [registroRef, setRegistroRef] = useState('')
  const [renegParcelas, setRenegParcelas] = useState('')
  const [erro, setErro] = useState<string | null>(null)

  const opId = sheet?.opId ?? ''
  const opQuery = useQuery({
    ...getOperacaoApiOperacoesOperacaoIdGetOptions({ path: { operacao_id: opId } }),
    enabled: !!opId,
  })
  const snapshot = useQuery(getCapitalSnapshotApiCapitalSnapshotGetOptions())

  const ativar = useMutation(postAtivarOperacaoApiOperacoesOperacaoIdAtivarPostMutation())
  const registrar = useMutation(postRegistrarOperacaoApiOperacoesOperacaoIdRegistrarPostMutation())
  const liquidar = useMutation(postLiquidarOperacaoApiOperacoesOperacaoIdLiquidarPostMutation())
  const renegociar = useMutation(
    postRenegociarOperacaoApiOperacoesOperacaoIdRenegociarPostMutation(),
  )
  const cancelar = useMutation(postCancelarOperacaoApiOperacoesOperacaoIdCancelarPostMutation())
  const inadimplente = useMutation(
    postMarcarInadimplenteApiOperacoesOperacaoIdMarcarInadimplentePostMutation(),
  )

  if (!sheet) return null

  const op = opQuery.data
  const teto = num(snapshot.data?.total)
  const comprometido = num(snapshot.data?.comprometido)
  const valor = num(op?.valor_principal)

  function fechar() {
    setRegistroRef('')
    setRenegParcelas('')
    setErro(null)
    app.closeSheet()
  }

  function invalidarTudo() {
    queryClient.invalidateQueries({ queryKey: getOperacoesApiOperacoesGetQueryKey() })
    queryClient.invalidateQueries({
      queryKey: getOperacaoApiOperacoesOperacaoIdGetOptions({ path: { operacao_id: opId } })
        .queryKey,
    })
    queryClient.invalidateQueries({
      queryKey: getParcelasApiOperacoesOperacaoIdParcelasGetQueryKey({
        path: { operacao_id: opId },
      }),
    })
    queryClient.invalidateQueries({
      queryKey: getCapitalSnapshotApiCapitalSnapshotGetOptions().queryKey,
    })
    queryClient.invalidateQueries({ queryKey: getCapitalEventosApiCapitalEventosGetQueryKey() })
    queryClient.invalidateQueries({ queryKey: getAgingApiCobrancaAgingGetQueryKey() })
    queryClient.invalidateQueries({ queryKey: getAuditoriaApiAuditoriaGetQueryKey() })
  }

  function aoSucesso(msg: string) {
    invalidarTudo()
    fechar()
    app.showToast(msg)
  }

  function aoErro(e: unknown) {
    setErro(mensagemDeErro(e))
  }

  const anyPending =
    ativar.isPending ||
    registrar.isPending ||
    liquidar.isPending ||
    renegociar.isPending ||
    cancelar.isPending ||
    inadimplente.isPending

  // Projeção de ativação (mesma conta do banco, só para PRÉ-visualizar).
  const proj = comprometido + valor
  const ativarBloqueado = teto <= 0 || proj > teto
  const projPct = teto > 0 ? Math.min(100, Math.round((proj / teto) * 100)) : 100

  const meta = metaPorTipo(sheet.type)

  function confirmar() {
    setErro(null)
    if (!sheet || !op) return
    switch (sheet.type) {
      case 'ativar':
        if (ativarBloqueado) return
        ativar.mutate(
          { path: { operacao_id: opId } },
          { onSuccess: () => aoSucesso('Operação ativada com sucesso.'), onError: aoErro },
        )
        break
      case 'registrar':
        if (!registroRef.trim()) return
        registrar.mutate(
          { path: { operacao_id: opId }, body: { registro_entidade_ref: registroRef.trim() } },
          { onSuccess: () => aoSucesso('Operação registrada na entidade.'), onError: aoErro },
        )
        break
      case 'liquidar':
        liquidar.mutate(
          { path: { operacao_id: opId } },
          { onSuccess: () => aoSucesso('Operação liquidada. Capital liberado.'), onError: aoErro },
        )
        break
      case 'renegociar': {
        const n = parseInt(renegParcelas, 10)
        if (!n || n <= 0) return
        renegociar.mutate(
          {
            path: { operacao_id: opId },
            body: {
              valor_principal: op.valor_principal,
              taxa_juros_mensal: op.taxa_juros_mensal,
              sistema_amortizacao: op.sistema_amortizacao === 'SAC' ? 'SAC' : 'PRICE',
              numero_parcelas: n,
              registro_entidade_ref: op.registro_entidade_ref ?? undefined,
            },
          },
          { onSuccess: () => aoSucesso('Operação renegociada (novação).'), onError: aoErro },
        )
        break
      }
      case 'cancelar':
        cancelar.mutate(
          { path: { operacao_id: opId } },
          { onSuccess: () => aoSucesso('Operação cancelada.'), onError: aoErro },
        )
        break
      case 'marcarInadimplente':
        inadimplente.mutate(
          { path: { operacao_id: opId } },
          { onSuccess: () => aoSucesso('Operação marcada como inadimplente.'), onError: aoErro },
        )
        break
    }
  }

  const confirmDisabled =
    anyPending ||
    !op ||
    (sheet.type === 'ativar' && ativarBloqueado) ||
    (sheet.type === 'registrar' && !registroRef.trim()) ||
    (sheet.type === 'renegociar' && !(parseInt(renegParcelas, 10) > 0))

  return (
    <div
      onClick={fechar}
      style={{
        position: 'absolute',
        inset: 0,
        zIndex: 40,
        background: t.overlay,
        display: 'flex',
        alignItems: 'flex-end',
        animation: 'oc-fadeIn .15s both',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: '100%',
          boxSizing: 'border-box',
          background: t.sheetBg,
          borderTop: `1px solid ${t.border2}`,
          borderRadius: '22px 22px 0 0',
          padding: '20px 20px 30px',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
          animation: 'oc-sheetUp .22s cubic-bezier(.2,.7,.2,1) both',
        }}
      >
        <div
          style={{
            width: 36,
            height: 4,
            borderRadius: 999,
            background: t.handle,
            margin: '0 auto',
          }}
        />
        <span style={{ font: `700 16px ${t.fd}`, color: t.text }}>{meta.titulo}</span>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ font: `600 13px ${t.fb}`, color: t.sub }}>
            {op?.tomador.razao_social ?? '…'}
          </span>
          {!!valor && (
            <span style={{ font: "600 20px 'JetBrains Mono Variable',monospace", color: t.text }}>
              {formatarMoeda(valor)}
            </span>
          )}
        </div>

        {sheet.type === 'ativar' && (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
              background: t.surface2,
              borderRadius: 13,
              padding: 13,
            }}
          >
            <LinhaSheet label="Comprometido após ativar" valor={formatarMoeda(proj)} t={t} />
            <LinhaSheet label="Teto legal" valor={formatarMoeda(teto)} t={t} />
            <div
              style={{
                height: 6,
                borderRadius: 999,
                background: t.trackOnSoft,
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  height: '100%',
                  width: `${projPct}%`,
                  background: ativarBloqueado ? t.ringDanger : t.ringOk,
                }}
              />
            </div>
            {ativarBloqueado && (
              <div
                style={{
                  display: 'flex',
                  gap: 9,
                  alignItems: 'flex-start',
                  background: t.negBg,
                  border: `1px solid ${t.negBorder}`,
                  borderRadius: 12,
                  padding: 12,
                }}
              >
                <Icon name="shield-x" size={16} color={t.neg} />
                <span style={{ font: `600 12px ${t.fb}`, color: t.negSoft, lineHeight: 1.5 }}>
                  Excederia o teto legal (Art. 5º, LC 167/2019 · OC001). O banco recusará.
                </span>
              </div>
            )}
          </div>
        )}

        {sheet.type === 'registrar' && (
          <>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
              <span style={{ font: `700 11.5px ${t.fb}`, color: t.sub }}>
                Referência de registro
              </span>
              <input
                value={registroRef}
                onChange={(e) => setRegistroRef(e.target.value)}
                placeholder="Ex.: CRDC-00000-0"
                style={{
                  boxSizing: 'border-box',
                  width: '100%',
                  background: t.inputBg,
                  border: `1px solid ${t.inputBorder}`,
                  borderRadius: 12,
                  padding: '12px 14px',
                  color: t.text,
                  font: "600 13.5px 'JetBrains Mono Variable',monospace",
                  outline: 'none',
                }}
              />
            </label>
            <span style={{ font: `500 11px ${t.fb}`, color: t.sub2, lineHeight: 1.5 }}>
              Obrigatório para ativar depois (Art. 5º §3º, LC 167/2019 · OC004).
            </span>
          </>
        )}

        {sheet.type === 'renegociar' && (
          <label style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
            <span style={{ font: `700 11.5px ${t.fb}`, color: t.sub }}>Novo prazo (parcelas)</span>
            <input
              value={renegParcelas}
              onChange={(e) => setRenegParcelas(e.target.value)}
              inputMode="numeric"
              placeholder="24"
              style={{
                boxSizing: 'border-box',
                width: '100%',
                background: t.inputBg,
                border: `1px solid ${t.inputBorder}`,
                borderRadius: 12,
                padding: '12px 14px',
                color: t.text,
                font: "600 13.5px 'JetBrains Mono Variable',monospace",
                outline: 'none',
              }}
            />
            <span style={{ font: `500 11px ${t.fb}`, color: t.sub2, lineHeight: 1.5 }}>
              Cria a operação substituta com valor e taxa atuais e o novo prazo (novação).
            </span>
          </label>
        )}

        {(sheet.type === 'cancelar' || sheet.type === 'marcarInadimplente') && (
          <span style={{ font: `500 12px ${t.fb}`, color: t.sub2, lineHeight: 1.5 }}>
            {sheet.type === 'cancelar'
              ? 'Esta ação é registrada na trilha de auditoria e não pode ser desfeita.'
              : 'Marca a operação como inadimplente. É reversível: a regularização retorna ao estado ativo.'}
          </span>
        )}

        {erro && (
          <span style={{ font: `600 12px ${t.fb}`, color: t.neg, lineHeight: 1.5 }}>{erro}</span>
        )}

        <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
          <button
            type="button"
            onClick={fechar}
            style={{
              flex: 1,
              background: t.surface,
              border: `1px solid ${t.border2}`,
              color: t.text,
              borderRadius: 13,
              padding: 13,
              font: `700 13.5px ${t.fb}`,
              cursor: 'pointer',
            }}
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={confirmar}
            disabled={confirmDisabled}
            style={{
              flex: 1.4,
              border: 'none',
              borderRadius: 13,
              padding: 13,
              font: `700 13.5px ${t.fb}`,
              cursor: confirmDisabled ? 'default' : 'pointer',
              background: confirmDisabled ? t.surface2 : t.grad,
              color: confirmDisabled ? t.muted : t.gradFg,
            }}
          >
            {anyPending ? 'Processando…' : meta.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

function LinhaSheet({
  label,
  valor,
  t,
}: {
  label: string
  valor: string
  t: ReturnType<typeof useMobileTheme>
}) {
  return (
    <span style={{ display: 'flex', justifyContent: 'space-between' }}>
      <span style={{ font: `500 11.5px ${t.fb}`, color: t.sub2 }}>{label}</span>
      <span style={{ font: "600 12.5px 'JetBrains Mono Variable',monospace", color: t.text }}>
        {valor}
      </span>
    </span>
  )
}

function metaPorTipo(type: SheetType): { titulo: string; confirmLabel: string } {
  switch (type) {
    case 'ativar':
      return { titulo: 'Ativar operação?', confirmLabel: 'Confirmar ativação' }
    case 'registrar':
      return { titulo: 'Registrar na entidade', confirmLabel: 'Confirmar registro' }
    case 'liquidar':
      return { titulo: 'Liquidar operação?', confirmLabel: 'Confirmar liquidação' }
    case 'renegociar':
      return { titulo: 'Renegociar operação', confirmLabel: 'Confirmar renegociação' }
    case 'cancelar':
      return { titulo: 'Cancelar operação?', confirmLabel: 'Confirmar cancelamento' }
    case 'marcarInadimplente':
      return { titulo: 'Marcar inadimplência?', confirmLabel: 'Confirmar marcação' }
  }
}
