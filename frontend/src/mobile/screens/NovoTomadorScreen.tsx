import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getTomadoresApiTomadoresGetQueryKey,
  postCriarTomadorApiTomadoresPostMutation,
} from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { useMobileTheme } from '../MobileThemeContext'
import { useMobileApp } from '../MobileAppContext'
import { Screen, ScreenScroll, TopBar, Field, FooterBar, PrimaryButton } from '../components/kit'

type Porte = 'ME' | 'EPP'

/**
 * Tela Novo tomador — cadastro. Além de razão social/CNPJ (o mock parava aí), a
 * API real exige `porte` (ME/EPP) e `uf`. O gate geográfico (OC002) é do banco,
 * na ATIVAÇÃO — o cadastro aceita qualquer município; o banco decide depois.
 */
export function NovoTomadorScreen() {
  const t = useMobileTheme()
  const app = useMobileApp()
  const queryClient = useQueryClient()

  const [razaoSocial, setRazaoSocial] = useState('')
  const [cnpj, setCnpj] = useState('')
  const [porte, setPorte] = useState<Porte>('ME')
  const [municipio, setMunicipio] = useState('')
  const [uf, setUf] = useState('')
  const [erro, setErro] = useState<string | null>(null)

  const criar = useMutation(postCriarTomadorApiTomadoresPostMutation())

  const podeSalvar =
    razaoSocial.trim().length > 0 &&
    cnpj.replace(/\D/g, '').length === 14 &&
    municipio.trim().length > 0 &&
    uf.trim().length === 2

  function salvar() {
    setErro(null)
    if (!podeSalvar) {
      setErro('Preencha razão social, CNPJ (14 dígitos), município e UF (2 letras).')
      return
    }
    criar.mutate(
      {
        body: {
          razao_social: razaoSocial.trim(),
          cnpj: cnpj.replace(/\D/g, ''),
          porte,
          municipio: municipio.trim(),
          uf: uf.trim().toUpperCase(),
        },
      },
      {
        onSuccess: (novo) => {
          queryClient.invalidateQueries({ queryKey: getTomadoresApiTomadoresGetQueryKey() })
          app.showToast('Tomador cadastrado.')
          app.openTomDetail(novo.id)
        },
        onError: (e) => setErro(mensagemDeErro(e)),
      },
    )
  }

  return (
    <Screen label="Novo tomador">
      <TopBar onBack={app.backFromNovoTom} title="Novo tomador" />

      <ScreenScroll style={{ padding: '4px 20px 20px', gap: 16 }}>
        <Field
          label="Razão social"
          value={razaoSocial}
          onChange={setRazaoSocial}
          placeholder="Nome da empresa Ltda"
        />
        <Field
          label="CNPJ"
          value={cnpj}
          onChange={setCnpj}
          placeholder="00.000.000/0001-00"
          inputMode="numeric"
          mono
        />

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <span style={{ font: `700 11.5px ${t.fb}`, color: t.sub }}>Porte</span>
          <div style={{ display: 'flex', gap: 8 }}>
            {(['ME', 'EPP'] as Porte[]).map((p) => {
              const ativo = porte === p
              return (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPorte(p)}
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
                  {p}
                </button>
              )
            })}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 12 }}>
          <div style={{ flex: 2 }}>
            <Field
              label="Município"
              value={municipio}
              onChange={setMunicipio}
              placeholder="Formoso"
            />
          </div>
          <div style={{ flex: 1 }}>
            <Field
              label="UF"
              value={uf}
              onChange={(v) => setUf(v.toUpperCase().slice(0, 2))}
              placeholder="GO"
            />
          </div>
        </div>

        {erro && <span style={{ font: `600 12px ${t.fb}`, color: t.neg }}>{erro}</span>}
      </ScreenScroll>

      <FooterBar>
        <PrimaryButton onClick={salvar} disabled={!podeSalvar || criar.isPending}>
          {criar.isPending ? 'Salvando…' : 'Salvar tomador'}
        </PrimaryButton>
      </FooterBar>
    </Screen>
  )
}
