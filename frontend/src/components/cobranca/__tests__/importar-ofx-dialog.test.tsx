import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ImportarOfxDialog } from '@/components/cobranca/importar-ofx-dialog'
import { TAMANHO_MAXIMO_OFX_BYTES } from '@/components/cobranca/mensagens'
import { ApiError } from '@/api/errors'

const { postImportarOfxMock } = vi.hoisted(() => ({ postImportarOfxMock: vi.fn() }))

vi.mock('@/api/generated/sdk.gen', () => ({
  postImportarOfxApiCobrancaMovimentosImportarOfxPost: postImportarOfxMock,
}))

/** Relatório de uma importação normal: 12 lidas, 12 explicadas. */
const RELATORIO = {
  arquivo: 'extrato-marco.ofx',
  arquivo_sha256: 'a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90',
  contas: ['0001/12345-6'],
  lidas: 12,
  creditos: 9,
  criados: 7,
  ja_registrados: 1,
  repetidos_no_arquivo: 1,
  debitos_ignorados: 3,
  periodo_inicio: '2026-03-01',
  periodo_fim: '2026-03-31',
}

function renderDialog() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={queryClient}>
      <ImportarOfxDialog />
    </QueryClientProvider>,
  )
  return { user, queryClient }
}

async function abrirImportacao() {
  const contexto = renderDialog()
  await contexto.user.click(screen.getByRole('button', { name: /Importar extrato OFX/i }))
  await screen.findByRole('dialog')
  return contexto
}

const extratoDeTeste = (bytes = 'OFXHEADER:100') =>
  new File([bytes], 'extrato-marco.ofx', { type: 'application/x-ofx' })

async function importar(user: ReturnType<typeof userEvent.setup>, arquivo = extratoDeTeste()) {
  await user.upload(screen.getByLabelText(/Arquivo do extrato/i), arquivo)
  await user.click(screen.getByRole('button', { name: 'Importar' }))
}

describe('ImportarOfxDialog', () => {
  beforeEach(() => {
    postImportarOfxMock.mockReset()
  })

  it('envia os BYTES do arquivo no corpo multipart', async () => {
    postImportarOfxMock.mockResolvedValue({ data: RELATORIO })

    const { user } = await abrirImportacao()
    await importar(user)

    await waitFor(() => expect(postImportarOfxMock).toHaveBeenCalled())
    const chamada = postImportarOfxMock.mock.calls[0][0]
    expect(chamada.body.arquivo).toBeInstanceOf(File)
    expect(chamada.body.arquivo.name).toBe('extrato-marco.ofx')
  })

  it('mostra o relatório com a aritmética fechando — nenhuma linha do extrato se perdeu', async () => {
    postImportarOfxMock.mockResolvedValue({ data: RELATORIO })

    const { user } = await abrirImportacao()
    await importar(user)

    const dialogo = await screen.findByRole('dialog')
    const conferencia = await within(dialogo).findByRole('status')
    // 7 + 1 + 1 + 3 = 12, e 12 é o que o arquivo tinha.
    expect(conferencia).toHaveTextContent('7 + 1 + 1 + 3 = 12')
    expect(conferencia).toHaveTextContent(/Conferência fecha/)
    expect(conferencia).toHaveTextContent(/Nenhuma linha do extrato se perdeu/)

    // Os quatro destinos aparecem NOMEADOS: o número sozinho não diz para
    // onde a linha foi.
    expect(within(dialogo).getByText('Movimentos criados')).toBeInTheDocument()
    expect(within(dialogo).getByText('Já registrados')).toBeInTheDocument()
    expect(within(dialogo).getByText('Repetidos dentro do arquivo')).toBeInTheDocument()
    expect(within(dialogo).getByText('Débitos ignorados')).toBeInTheDocument()
  })

  it('mostra período e contas — é o que revela o extrato do mês ou da conta errada', async () => {
    postImportarOfxMock.mockResolvedValue({ data: RELATORIO })

    const { user } = await abrirImportacao()
    await importar(user)

    const dialogo = await screen.findByRole('dialog')
    // Datas 'YYYY-MM-DD' formatadas sem passar por Date(): em fuso negativo o
    // toLocaleDateString devolveria 28/02 e 30/03, e o operador conferiria o
    // período errado.
    expect(within(dialogo).getByText('01/03/2026')).toBeInTheDocument()
    expect(within(dialogo).getByText('31/03/2026')).toBeInTheDocument()
    expect(within(dialogo).getByText('0001/12345-6')).toBeInTheDocument()
  })

  it('identifica o arquivo de que o relatório fala: nome e resumo dos bytes', async () => {
    postImportarOfxMock.mockResolvedValue({ data: RELATORIO })

    const { user } = await abrirImportacao()
    await importar(user)

    // Sem isto o relatório é um punhado de números que não se amarra a
    // arquivo nenhum — e é o arquivo do banco que a ESC arquiva e o fiscal
    // pede. O hash abreviado confere de olho; o inteiro fica no title.
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByText('extrato-marco.ofx')).toBeInTheDocument()
    const resumo = within(dialogo).getByText('a1b2c3d4e5f6…')
    expect(resumo).toHaveAttribute('title', RELATORIO.arquivo_sha256)
  })

  it('distingue anomalia DO ARQUIVO de reimportação normal', async () => {
    postImportarOfxMock.mockResolvedValue({ data: RELATORIO })

    const { user } = await abrirImportacao()
    await importar(user)

    const dialogo = await screen.findByRole('dialog')
    // FITID repetido pelo banco é anomalia do arquivo...
    expect(within(dialogo).getByText(/anomalia DO ARQUIVO/)).toBeInTheDocument()
    // ...enquanto já registrado é o esperado ao reimportar.
    expect(within(dialogo).getByText(/foi importado antes\. Não é erro/)).toBeInTheDocument()
    // ...e débito não vira movimento porque não baixa parcela.
    expect(within(dialogo).getByText(/débito não baixa parcela/)).toBeInTheDocument()
  })

  it('sinaliza o FITID repetido pelo banco — e NUNCA a reimportação', async () => {
    // O texto explica; o destaque é o que o olho pega primeiro. Pintar
    // `ja_registrados` de anomalia ensinaria o operador a temer reimportar,
    // que é a ação certa e rotineira.
    postImportarOfxMock.mockResolvedValue({
      data: { ...RELATORIO, ja_registrados: 5, repetidos_no_arquivo: 1, lidas: 16 },
    })

    const { user } = await abrirImportacao()
    await importar(user)

    const dialogo = await screen.findByRole('dialog')
    const cartao = (rotulo: string) =>
      within(dialogo).getByText(rotulo).closest('li') as HTMLElement

    expect(cartao('Repetidos dentro do arquivo')).toHaveAttribute('data-anomalia', 'sim')
    expect(cartao('Já registrados')).toHaveAttribute('data-anomalia', 'nao')
    expect(cartao('Movimentos criados')).toHaveAttribute('data-anomalia', 'nao')
    expect(cartao('Débitos ignorados')).toHaveAttribute('data-anomalia', 'nao')
  })

  it('sem FITID repetido, nada é sinalizado como anomalia', async () => {
    postImportarOfxMock.mockResolvedValue({
      data: { ...RELATORIO, repetidos_no_arquivo: 0, lidas: 11 },
    })

    const { user } = await abrirImportacao()
    await importar(user)

    const dialogo = await screen.findByRole('dialog')
    expect(
      within(dialogo)
        .getAllByRole('listitem')
        .every((li) => li.getAttribute('data-anomalia') === 'nao'),
    ).toBe(true)
  })

  it('reimportação: tudo em já registrados, e a conferência continua fechando', async () => {
    postImportarOfxMock.mockResolvedValue({
      data: {
        ...RELATORIO,
        lidas: 9,
        creditos: 9,
        criados: 0,
        ja_registrados: 9,
        repetidos_no_arquivo: 0,
        debitos_ignorados: 0,
      },
    })

    const { user } = await abrirImportacao()
    await importar(user)

    const dialogo = await screen.findByRole('dialog')
    const conferencia = await within(dialogo).findByRole('status')
    expect(conferencia).toHaveTextContent('0 + 9 + 0 + 0 = 9')
    expect(conferencia).toHaveTextContent(/Conferência fecha/)
    // Zero criados NÃO é falha: o alerta é para conferência que não fecha.
    expect(within(dialogo).queryByRole('alert')).not.toBeInTheDocument()
  })

  it('extrato válido e VAZIO não ganha o selo verde: 0 = 0 não prova importação', async () => {
    // `ler_ofx` só recusa bytes vazios e OFX malformado — um extrato sem
    // nenhuma <STMTTRN> (mês sem movimento, ou filtro de datas errado na
    // exportação) volta 200 com tudo zerado e sem período.
    postImportarOfxMock.mockResolvedValue({
      data: {
        ...RELATORIO,
        lidas: 0,
        creditos: 0,
        criados: 0,
        ja_registrados: 0,
        repetidos_no_arquivo: 0,
        debitos_ignorados: 0,
        periodo_inicio: null,
        periodo_fim: null,
      },
    })

    const { user } = await abrirImportacao()
    await importar(user)

    const dialogo = await screen.findByRole('dialog')
    const conferencia = await within(dialogo).findByRole('status')
    expect(conferencia).toHaveTextContent(/Não há o que conferir/)
    expect(conferencia).toHaveTextContent(/nenhum movimento foi criado/i)
    expect(conferencia).toHaveTextContent(/exportação do período errado/)
    // A frase do caso feliz não pode aparecer: nenhuma linha se perdeu porque
    // nenhuma linha existia, e o verde daria o mês por importado.
    expect(conferencia).not.toHaveTextContent(/Nenhuma linha do extrato se perdeu/)
    expect(conferencia).not.toHaveTextContent(/Conferência fecha/)
    // Sem período não há a conferência que revelaria o arquivo errado — e a
    // tela precisa dizer isso, não omitir a linha.
    expect(within(dialogo).getByText(/não trouxe transação nenhuma/)).toBeInTheDocument()
  })

  it('acusa quando a soma dos destinos não fecha com as linhas lidas', async () => {
    postImportarOfxMock.mockResolvedValue({ data: { ...RELATORIO, lidas: 13 } })

    const { user } = await abrirImportacao()
    await importar(user)

    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent(/Conferência NÃO fecha/)
    expect(alerta).toHaveTextContent(/não use esta importação como prova/)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('arquivo malformado: mostra a causa que o parser apontou, não "erro inesperado"', async () => {
    postImportarOfxMock.mockRejectedValue(
      new ApiError('Transação sem FITID na posição 42 — o arquivo está truncado.', null, 422),
    )

    const { user } = await abrirImportacao()
    await importar(user)

    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent('Transação sem FITID na posição 42')
    expect(alerta).not.toHaveTextContent('Ocorreu um erro inesperado')
    // O diálogo continua aberto: o operador precisa ler o motivo para pedir a
    // exportação de novo ao banco.
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('excesso de transações e valor fora da faixa chegam com o texto do servidor', async () => {
    postImportarOfxMock.mockRejectedValue(
      new ApiError(
        'Transação 20260301001 tem valor 1000000000000.00, fora da faixa aceita para ' +
          'movimento bancário — o arquivo está corrompido.',
        null,
        422,
      ),
    )

    const { user } = await abrirImportacao()
    await importar(user)

    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent('20260301001')
    expect(alerta).toHaveTextContent(/fora da faixa/)
  })

  it('413 vira instrução acionável mesmo sem corpo JSON — um gateway não manda detail', async () => {
    postImportarOfxMock.mockRejectedValue(new ApiError('Ocorreu um erro inesperado.', null, 413))

    const { user } = await abrirImportacao()
    await importar(user)

    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent('8 MiB')
    expect(alerta).toHaveTextContent(/um mês por arquivo/)
    expect(alerta).not.toHaveTextContent('Ocorreu um erro inesperado')
  })

  it('recusa arquivo acima do limite ANTES de enviar um byte', async () => {
    const grande = new File([new Uint8Array(TAMANHO_MAXIMO_OFX_BYTES + 1)], 'extrato-anual.ofx', {
      type: 'application/x-ofx',
    })

    const { user } = await abrirImportacao()
    await importar(user, grande)

    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent('8 MiB')
    expect(alerta).toHaveTextContent('Nada foi enviado.')
    expect(postImportarOfxMock).not.toHaveBeenCalled()
  })

  it('invalida a lista de movimentos — e só ela, porque nenhuma parcela foi baixada', async () => {
    postImportarOfxMock.mockResolvedValue({ data: RELATORIO })

    const { user, queryClient } = await abrirImportacao()
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    await importar(user)

    await waitFor(() => expect(invalidate).toHaveBeenCalled())
    const chaves = invalidate.mock.calls.map(([arg]) => JSON.stringify(arg?.queryKey))
    expect(chaves.some((c) => c?.includes('getMovimentosApiCobrancaMovimentosGet'))).toBe(true)
    expect(chaves.some((c) => c?.includes('getAgingApiCobrancaAgingGet'))).toBe(false)
    expect(chaves.some((c) => c?.includes('getOperacoesApiOperacoesGet'))).toBe(false)
  })

  it('fechar descarta arquivo e relatório — reabrir não afirma sobre importação que não houve', async () => {
    postImportarOfxMock.mockResolvedValue({ data: RELATORIO })

    const { user } = await abrirImportacao()
    await importar(user)
    await screen.findByRole('status')

    await user.click(screen.getByRole('button', { name: 'Fechar' }))
    await user.click(await screen.findByRole('button', { name: /Importar extrato OFX/i }))
    await screen.findByRole('dialog')

    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    // Input reabre vazio; o botão tem que refletir isso, senão reenviaria o
    // arquivo da vez anterior.
    expect(screen.getByRole('button', { name: 'Importar' })).toBeDisabled()
    expect(postImportarOfxMock).toHaveBeenCalledTimes(1)
  })

  it('escolher outro arquivo apaga o relatório do anterior', async () => {
    postImportarOfxMock.mockResolvedValue({ data: RELATORIO })

    const { user } = await abrirImportacao()
    await importar(user)
    await screen.findByRole('status')

    await user.upload(
      screen.getByLabelText(/Arquivo do extrato/i),
      new File(['OFXHEADER:100'], 'extrato-abril.ofx', { type: 'application/x-ofx' }),
    )

    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Importar' })).toBeEnabled()
  })
})
