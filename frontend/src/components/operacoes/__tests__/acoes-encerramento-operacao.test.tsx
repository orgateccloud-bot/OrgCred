import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AcoesEncerramentoOperacao } from '@/components/operacoes/acoes-encerramento-operacao'
import { ApiError } from '@/api/errors'

const { getCapitalSnapshotMock, postLiquidarMock, postBaixarPrejuizoMock } = vi.hoisted(() => ({
  getCapitalSnapshotMock: vi.fn(),
  postLiquidarMock: vi.fn(),
  postBaixarPrejuizoMock: vi.fn(),
}))

vi.mock('@/api/generated/sdk.gen', () => ({
  getCapitalSnapshotApiCapitalSnapshotGet: getCapitalSnapshotMock,
  postLiquidarOperacaoApiOperacoesOperacaoIdLiquidarPost: postLiquidarMock,
  postBaixarPrejuizoApiOperacoesOperacaoIdBaixarPrejuizoPost: postBaixarPrejuizoMock,
}))

function renderAcoes() {
  const user = userEvent.setup()
  const onSucesso = vi.fn()
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <AcoesEncerramentoOperacao operacaoId="op-1" valorPrincipal="30000" onSucesso={onSucesso} />
    </QueryClientProvider>,
  )
  return { user, onSucesso }
}

describe('AcoesEncerramentoOperacao', () => {
  beforeEach(() => {
    getCapitalSnapshotMock.mockReset()
    postLiquidarMock.mockReset()
    postBaixarPrejuizoMock.mockReset()
    getCapitalSnapshotMock.mockResolvedValue({
      data: { total: '100000', comprometido: '30000', disponivel: '70000' },
    })
  })

  it('oferece os dois encerramentos como ações distintas', () => {
    renderAcoes()

    expect(screen.getByRole('button', { name: 'Liquidar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Baixar como prejuízo' })).toBeInTheDocument()
  })

  it('a baixa por prejuízo exige confirmação digitada antes de chamar o endpoint', async () => {
    postBaixarPrejuizoMock.mockResolvedValue({ data: { id: 'op-1', status: 'baixada_prejuizo' } })
    const { user, onSucesso } = renderAcoes()

    await user.click(screen.getByRole('button', { name: 'Baixar como prejuízo' }))
    const dialogo = within(await screen.findByRole('dialog'))

    expect(dialogo.getByRole('button', { name: 'Confirmar baixa por prejuízo' })).toBeDisabled()
    await user.type(dialogo.getByLabelText(/digite/i), 'PREJUIZO')
    await user.click(dialogo.getByRole('button', { name: 'Confirmar baixa por prejuízo' }))

    await waitFor(() => expect(onSucesso).toHaveBeenCalled())
    expect(postBaixarPrejuizoMock).toHaveBeenCalledWith(
      expect.objectContaining({ path: { operacao_id: 'op-1' } }),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('o OC022 na liquidação leva o operador até a baixa por prejuízo', async () => {
    postLiquidarMock.mockRejectedValue(
      new ApiError('Liquidação bloqueada: 3 de 12 parcelas sem lastro', 'OC022', 422),
    )
    const { user } = renderAcoes()

    await user.click(screen.getByRole('button', { name: 'Liquidar' }))
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', {
        name: 'Confirmar liquidação',
      }),
    )

    const alerta = await screen.findByRole('alert')
    await user.click(within(alerta).getByRole('button', { name: 'Baixar como prejuízo' }))

    // A liquidação sai de cena e o write-off entra no lugar, sem o operador
    // ter que caçar o outro botão atrás do modal.
    await waitFor(() =>
      expect(screen.getByText('Baixar operação como prejuízo')).toBeInTheDocument(),
    )
    expect(screen.queryByText('Liquidar operação')).not.toBeInTheDocument()
    expect(postBaixarPrejuizoMock).not.toHaveBeenCalled()
  })

  it('a troca de diálogos entrega o foco ao write-off', async () => {
    postLiquidarMock.mockRejectedValue(new ApiError('sem lastro', 'OC022', 422))
    const { user } = renderAcoes()

    await user.click(screen.getByRole('button', { name: 'Liquidar' }))
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', {
        name: 'Confirmar liquidação',
      }),
    )
    await user.click(
      within(await screen.findByRole('alert')).getByRole('button', {
        name: 'Baixar como prejuízo',
      }),
    )

    // Fechar um modal e abrir outro no mesmo clique é onde o foco costuma
    // cair no body: teclado e leitor de tela ficariam fora do diálogo que
    // pede a confirmação digitada.
    const writeOff = await screen.findByRole('dialog')
    await waitFor(() => expect(writeOff.contains(document.activeElement)).toBe(true))
  })

  it('reabrir a liquidação depois de desistir do write-off não repete o OC022 velho', async () => {
    postLiquidarMock.mockRejectedValue(new ApiError('sem lastro', 'OC022', 422))
    const { user } = renderAcoes()

    await user.click(screen.getByRole('button', { name: 'Liquidar' }))
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', {
        name: 'Confirmar liquidação',
      }),
    )
    await user.click(
      within(await screen.findByRole('alert')).getByRole('button', {
        name: 'Baixar como prejuízo',
      }),
    )
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Cancelar' }),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    // Quem desiste do write-off costuma ir baixar as parcelas e voltar. Se a
    // liquidação reabrisse já dizendo "bloqueada", estaria afirmando sobre a
    // tentativa anterior — e empurrando para o prejuízo quem já resolveu.
    await user.click(screen.getByRole('button', { name: 'Liquidar' }))
    await screen.findByRole('dialog')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
