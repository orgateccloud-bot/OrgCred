import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { IdentificacaoTomador } from '@/components/identificacao/identificacao-tomador'
import { ApiError } from '@/api/errors'

const { getDocumentosMock, postDocumentoMock, postVerificarMock, getConteudoMock } = vi.hoisted(
  () => ({
    getDocumentosMock: vi.fn(),
    postDocumentoMock: vi.fn(),
    postVerificarMock: vi.fn(),
    getConteudoMock: vi.fn(),
  }),
)

vi.mock('@/api/generated/sdk.gen', () => ({
  getDocumentosApiComplianceTomadoresTomadorIdDocumentosGet: getDocumentosMock,
  postDocumentoApiComplianceTomadoresTomadorIdDocumentosPost: postDocumentoMock,
  postVerificarDocumentoApiComplianceDocumentosDocumentoIdVerificarPost: postVerificarMock,
  getConteudoDocumentoApiComplianceDocumentosDocumentoIdConteudoGet: getConteudoMock,
}))

const DOCUMENTO = {
  id: 'doc-1',
  tomador_id: 'tom-1',
  tipo: 'contrato_social',
  nome_arquivo: 'contrato-social.pdf',
  sha256: 'abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789',
  arquivado_em: '2026-02-10T13:00:00Z',
  retencao_ate: '2031-02-10',
  storage_objeto: 'identificacao-tomador/ab/cdef.pdf',
}

function renderSecao() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={queryClient}>
      <IdentificacaoTomador tomadorId="tom-1" />
    </QueryClientProvider>,
  )
  return { user, queryClient }
}

async function abrirArquivamento() {
  const { user, queryClient } = renderSecao()
  await user.click(await screen.findByRole('button', { name: /Arquivar documento/i }))
  await screen.findByRole('dialog')
  return { user, queryClient }
}

const arquivoDeTeste = () =>
  new File(['conteudo-da-evidencia'], 'contrato-social.pdf', { type: 'application/pdf' })

describe('IdentificacaoTomador', () => {
  beforeEach(() => {
    getDocumentosMock.mockReset()
    postDocumentoMock.mockReset()
    postVerificarMock.mockReset()
    getConteudoMock.mockReset()
    getDocumentosMock.mockResolvedValue({ data: [] })
  })

  it('mostra esqueleto de carregamento antes da resposta', () => {
    getDocumentosMock.mockReturnValue(new Promise(() => {}))
    const { container } = render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <IdentificacaoTomador tomadorId="tom-1" />
      </QueryClientProvider>,
    )
    expect(container.querySelector('[data-slot="skeleton"]')).toBeInTheDocument()
  })

  it('lista os documentos arquivados com tipo, prazo de guarda e hash abreviado', async () => {
    getDocumentosMock.mockResolvedValue({ data: [DOCUMENTO] })

    renderSecao()

    expect(await screen.findByText('Contrato social')).toBeInTheDocument()
    expect(screen.getByText('contrato-social.pdf')).toBeInTheDocument()
    // 'YYYY-MM-DD' formatado sem passar por Date() — em fuso negativo o
    // toLocaleDateString devolveria 09/02/2031 e o prazo legal encolheria um dia.
    expect(screen.getByText('10/02/2031')).toBeInTheDocument()
    expect(screen.getByText('abcdef012345…')).toBeInTheDocument()
  })

  it('no vazio, explica que nenhuma operação do tomador poderá ser ativada', async () => {
    getDocumentosMock.mockResolvedValue({ data: [] })

    renderSecao()

    expect(
      await screen.findByText('Nenhuma evidência de identificação arquivada.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('nenhuma operação deste tomador poderá ser ativada'),
    ).toBeInTheDocument()
    expect(screen.getByText(/OC019/)).toBeInTheDocument()
  })

  it('anuncia a falha de carregamento em região viva', async () => {
    getDocumentosMock.mockRejectedValue(new ApiError('Falha ao listar', null, 500))

    renderSecao()

    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent('Falha ao listar')
  })

  it('envia o ARQUIVO no upload — nunca um hash informado pelo cliente', async () => {
    postDocumentoMock.mockResolvedValue({ data: DOCUMENTO })

    const { user } = await abrirArquivamento()
    await user.upload(screen.getByLabelText('Arquivo'), arquivoDeTeste())
    await user.click(screen.getByRole('button', { name: 'Arquivar' }))

    await waitFor(() => expect(postDocumentoMock).toHaveBeenCalled())
    const chamada = postDocumentoMock.mock.calls[0][0]
    expect(chamada.path).toEqual({ tomador_id: 'tom-1' })
    expect(chamada.body.tipo).toBe('contrato_social')
    expect(chamada.body.arquivo).toBeInstanceOf(File)
    expect(chamada.body).not.toHaveProperty('sha256')
  })

  it('invalida a lista de documentos após arquivar', async () => {
    postDocumentoMock.mockResolvedValue({ data: DOCUMENTO })

    const { user, queryClient } = await abrirArquivamento()
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    await user.upload(screen.getByLabelText('Arquivo'), arquivoDeTeste())
    await user.click(screen.getByRole('button', { name: 'Arquivar' }))

    await waitFor(() => expect(invalidate).toHaveBeenCalled())
    const chaves = invalidate.mock.calls.map(([arg]) => JSON.stringify(arg?.queryKey))
    expect(
      chaves.some((c) => c?.includes('getDocumentosApiComplianceTomadoresTomadorIdDocumentosGet')),
    ).toBe(true)
    expect(
      chaves.some((c) =>
        c?.includes('getPendenciasIdentificacaoApiComplianceIdentificacaoPendenciasGet'),
      ),
    ).toBe(true)
  })

  it('no 503, explica que falta armazenamento no servidor em vez de "erro inesperado"', async () => {
    postDocumentoMock.mockRejectedValue(
      new ApiError('Storage de documentos não configurado.', null, 503),
    )

    const { user } = await abrirArquivamento()
    await user.upload(screen.getByLabelText('Arquivo'), arquivoDeTeste())
    await user.click(screen.getByRole('button', { name: 'Arquivar' }))

    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent(/sem armazenamento configurado/i)
    expect(alerta).toHaveTextContent(/SUPABASE_URL/)
    expect(alerta).not.toHaveTextContent('Ocorreu um erro inesperado')
    // O modal continua aberto: o operador precisa ler o motivo.
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('cancelar descarta o arquivo escolhido — reabrir não reenvia o da vez anterior', async () => {
    const { user } = await abrirArquivamento()
    await user.upload(screen.getByLabelText('Arquivo'), arquivoDeTeste())
    expect(screen.getByRole('button', { name: 'Arquivar' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    await user.click(await screen.findByRole('button', { name: /Arquivar documento/i }))
    await screen.findByRole('dialog')

    // O input reabre vazio; o botão tem que refletir isso. Habilitado aqui
    // significaria arquivar evidência que ninguém escolheu nesta vez.
    expect(screen.getByRole('button', { name: 'Arquivar' })).toBeDisabled()
    expect(postDocumentoMock).not.toHaveBeenCalled()
  })

  it('cancelar apaga o erro anterior — reabrir não anuncia falha que não houve', async () => {
    postDocumentoMock.mockRejectedValue(
      new ApiError('Storage de documentos não configurado.', null, 503),
    )

    const { user } = await abrirArquivamento()
    await user.upload(screen.getByLabelText('Arquivo'), arquivoDeTeste())
    await user.click(screen.getByRole('button', { name: 'Arquivar' }))
    await screen.findByRole('alert')

    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    await user.click(await screen.findByRole('button', { name: /Arquivar documento/i }))
    await screen.findByRole('dialog')

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('fechar a verificação descarta o resultado — reabrir não afirma integridade não conferida', async () => {
    getDocumentosMock.mockResolvedValue({ data: [DOCUMENTO] })
    postVerificarMock.mockResolvedValue({
      data: {
        sha256_calculado: DOCUMENTO.sha256,
        sha256_arquivado: DOCUMENTO.sha256,
        confere: true,
        storage_integro: true,
      },
    })

    const { user } = renderSecao()
    await user.click(await screen.findByRole('button', { name: /Verificar contrato-social.pdf/ }))
    let dialogo = await screen.findByRole('dialog')
    await user.upload(within(dialogo).getByLabelText('Arquivo a conferir'), arquivoDeTeste())
    await user.click(within(dialogo).getByRole('button', { name: 'Conferir' }))
    await screen.findByRole('status')

    await user.click(within(dialogo).getByRole('button', { name: 'Fechar' }))
    await user.click(await screen.findByRole('button', { name: /Verificar contrato-social.pdf/ }))
    dialogo = await screen.findByRole('dialog')

    // Nada de "Confere" pendurado de uma conferência que não foi feita agora.
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(within(dialogo).getByRole('button', { name: 'Conferir' })).toBeDisabled()
  })

  it('a verificação bit a bit confirma quando o arquivo confere', async () => {
    getDocumentosMock.mockResolvedValue({ data: [DOCUMENTO] })
    postVerificarMock.mockResolvedValue({
      data: {
        sha256_calculado: DOCUMENTO.sha256,
        sha256_arquivado: DOCUMENTO.sha256,
        confere: true,
        storage_integro: true,
      },
    })

    const { user } = renderSecao()
    await user.click(await screen.findByRole('button', { name: /Verificar contrato-social.pdf/ }))
    const dialogo = await screen.findByRole('dialog')

    await user.upload(within(dialogo).getByLabelText('Arquivo a conferir'), arquivoDeTeste())
    await user.click(within(dialogo).getByRole('button', { name: 'Conferir' }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent('Confere: é bit a bit o documento arquivado.')
    expect(status).toHaveTextContent(/íntegros/)
    expect(postVerificarMock.mock.calls[0][0].path).toEqual({ documento_id: 'doc-1' })
  })

  it('a verificação alerta quando o arquivo apresentado não é o arquivado', async () => {
    getDocumentosMock.mockResolvedValue({ data: [DOCUMENTO] })
    postVerificarMock.mockResolvedValue({
      data: {
        sha256_calculado: '0'.repeat(64),
        sha256_arquivado: DOCUMENTO.sha256,
        confere: false,
        storage_integro: false,
      },
    })

    const { user } = renderSecao()
    await user.click(await screen.findByRole('button', { name: /Verificar contrato-social.pdf/ }))
    const dialogo = await screen.findByRole('dialog')

    await user.upload(within(dialogo).getByLabelText('Arquivo a conferir'), arquivoDeTeste())
    await user.click(within(dialogo).getByRole('button', { name: 'Conferir' }))

    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent('Não confere: este arquivo NÃO é o que foi arquivado.')
    expect(alerta).toHaveTextContent(/adulterados/)
  })

  it('não oferece download de evidência anterior ao armazenamento de bytes', async () => {
    getDocumentosMock.mockResolvedValue({ data: [{ ...DOCUMENTO, storage_objeto: null }] })

    renderSecao()

    expect(await screen.findByText('Sem arquivo guardado')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Baixar contrato-social.pdf/ })).toBeDisabled()
  })

  it('baixa os bytes pela API — e não por um link que perderia o Authorization', async () => {
    getDocumentosMock.mockResolvedValue({ data: [DOCUMENTO] })
    getConteudoMock.mockResolvedValue({ data: new Blob(['bytes']) })
    const criarUrl = vi.fn(() => 'blob:evidencia')
    vi.stubGlobal('URL', { ...URL, createObjectURL: criarUrl, revokeObjectURL: vi.fn() })

    const { user } = renderSecao()
    await user.click(await screen.findByRole('button', { name: /Baixar contrato-social.pdf/ }))

    await waitFor(() => expect(getConteudoMock).toHaveBeenCalled())
    expect(getConteudoMock.mock.calls[0][0]).toMatchObject({
      path: { documento_id: 'doc-1' },
      parseAs: 'blob',
    })
    await waitFor(() => expect(criarUrl).toHaveBeenCalled())
    vi.unstubAllGlobals()
  })

  it('a âncora do download entra no documento antes do clique e sai depois', async () => {
    getDocumentosMock.mockResolvedValue({ data: [DOCUMENTO] })
    getConteudoMock.mockResolvedValue({ data: new Blob(['bytes']) })
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:evidencia'),
      revokeObjectURL: vi.fn(),
    })
    // <a> desconectado não dispara download no Firefox: o clique tem que
    // acontecer com a âncora ligada ao documento, e ela não pode ficar lá.
    let conectadaNoClique: boolean | null = null
    const cliqueOriginal = HTMLAnchorElement.prototype.click
    const espiao = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      conectadaNoClique = this.isConnected
    })

    const { user } = renderSecao()
    await user.click(await screen.findByRole('button', { name: /Baixar contrato-social.pdf/ }))

    await waitFor(() => expect(espiao).toHaveBeenCalled())
    expect(conectadaNoClique).toBe(true)
    expect(document.querySelector('a[download]')).toBeNull()

    espiao.mockRestore()
    HTMLAnchorElement.prototype.click = cliqueOriginal
    vi.unstubAllGlobals()
  })

  it('não revoga o objectURL na mesma volta do clique — abortaria arquivo grande', async () => {
    getDocumentosMock.mockResolvedValue({ data: [DOCUMENTO] })
    getConteudoMock.mockResolvedValue({ data: new Blob(['bytes']) })
    const revogar = vi.fn()
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:evidencia'),
      revokeObjectURL: revogar,
    })

    const { user } = renderSecao()
    await user.click(await screen.findByRole('button', { name: /Baixar contrato-social.pdf/ }))

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Baixar contrato-social.pdf/ })).toBeEnabled(),
    )
    expect(revogar).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('anuncia falha de download sem derrubar a lista', async () => {
    getDocumentosMock.mockResolvedValue({ data: [DOCUMENTO] })
    getConteudoMock.mockRejectedValue(new ApiError('Storage indisponível', null, 503))

    const { user } = renderSecao()
    await user.click(await screen.findByRole('button', { name: /Baixar contrato-social.pdf/ }))

    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent(/sem armazenamento configurado/i)
    expect(screen.getByText('Contrato social')).toBeInTheDocument()
  })
})
