import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MovimentosBancarios } from '@/components/cobranca/movimentos-bancarios'
import { ApiError } from '@/api/errors'

const { getMovimentosMock } = vi.hoisted(() => ({ getMovimentosMock: vi.fn() }))

vi.mock('@/api/generated/sdk.gen', () => ({
  getMovimentosApiCobrancaMovimentosGet: getMovimentosMock,
}))

const SHA = 'a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90'

const DO_ARQUIVO = {
  id: 'mov-1',
  data_movimento: '2026-03-10',
  valor: '1500.00',
  descricao: 'TED RECEBIDA',
  documento: '20260310001',
  origem: 'ofx',
  conciliado: false,
  conta_origem: '0001/12345-6',
  arquivo_sha256: SHA,
}

const DIGITADO = {
  id: 'mov-2',
  data_movimento: '2026-03-11',
  valor: '900.00',
  descricao: null,
  documento: 'DEP-0011',
  origem: 'manual',
  conciliado: true,
  conta_origem: null,
  arquivo_sha256: null,
}

function renderLista() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MovimentosBancarios />
    </QueryClientProvider>,
  )
}

async function linhaDe(documento: string) {
  return (await screen.findByText(documento)).closest('tr') as HTMLElement
}

describe('MovimentosBancarios', () => {
  beforeEach(() => {
    getMovimentosMock.mockReset()
    getMovimentosMock.mockResolvedValue({ data: [] })
  })

  it('mostra esqueleto de carregamento antes da resposta', () => {
    getMovimentosMock.mockReturnValue(new Promise(() => {}))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <MovimentosBancarios />
      </QueryClientProvider>,
    )
    expect(container.querySelector('[data-slot="skeleton"]')).toBeInTheDocument()
  })

  it('anuncia a falha de carregamento em região viva', async () => {
    getMovimentosMock.mockRejectedValue(new ApiError('Falha ao listar movimentos', null, 500))

    renderLista()

    expect(await screen.findByRole('alert')).toHaveTextContent('Falha ao listar movimentos')
  })

  it('no vazio, oferece a importação do extrato como caminho', async () => {
    renderLista()

    expect(await screen.findByText(/Nenhum movimento registrado/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Importar extrato OFX/i })).toBeInTheDocument()
  })

  it('mostra a proveniência do movimento importado: origem, conta e resumo do arquivo', async () => {
    getMovimentosMock.mockResolvedValue({ data: [DO_ARQUIVO] })

    renderLista()

    const linha = await linhaDe('20260310001')
    expect(within(linha).getByText('Extrato OFX')).toBeInTheDocument()
    expect(within(linha).getByText('Conta 0001/12345-6')).toBeInTheDocument()
    // Hash abreviado na célula, inteiro no title — quem audita precisa dos 64.
    const resumo = within(linha).getByText('a1b2c3d4e5f6…')
    expect(resumo).toHaveAttribute('title', expect.stringContaining(SHA))
  })

  it('distingue o movimento digitado, que não tem arquivo do banco por trás', async () => {
    getMovimentosMock.mockResolvedValue({ data: [DIGITADO] })

    renderLista()

    const linha = await linhaDe('DEP-0011')
    expect(within(linha).getByText('Digitado')).toBeInTheDocument()
    expect(within(linha).getByText('Sem arquivo do banco por trás')).toBeInTheDocument()
    expect(within(linha).queryByText(/^Conta /)).not.toBeInTheDocument()
  })

  it('as duas proveniências convivem na mesma lista e não se confundem', async () => {
    getMovimentosMock.mockResolvedValue({ data: [DO_ARQUIVO, DIGITADO] })

    renderLista()

    await screen.findByText('Extrato OFX')
    expect(screen.getByRole('columnheader', { name: 'Origem' })).toBeInTheDocument()

    const importado = await linhaDe('20260310001')
    const manual = await linhaDe('DEP-0011')
    expect(within(importado).queryByText('Digitado')).not.toBeInTheDocument()
    expect(within(manual).queryByText('Extrato OFX')).not.toBeInTheDocument()
    expect(within(manual).queryByText('a1b2c3d4e5f6…')).not.toBeInTheDocument()
  })

  it('origem desconhecida aparece crua em vez de sumir', async () => {
    getMovimentosMock.mockResolvedValue({
      data: [{ ...DIGITADO, origem: 'conciliacao_automatica' }],
    })

    renderLista()

    expect(await screen.findByText('conciliacao_automatica')).toBeInTheDocument()
  })
})
