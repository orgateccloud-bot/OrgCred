import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AtivarOperacaoDialog } from './ativar-operacao-dialog'
import { ApiError } from '@/api/errors'

const { getCapitalSnapshotMock, postAtivarMock } = vi.hoisted(() => ({
  getCapitalSnapshotMock: vi.fn(),
  postAtivarMock: vi.fn(),
}))

vi.mock('@/api/generated/sdk.gen', () => ({
  getCapitalSnapshotApiCapitalSnapshotGet: getCapitalSnapshotMock,
  postAtivarOperacaoApiOperacoesOperacaoIdAtivarPost: postAtivarMock,
}))

async function renderComDialogAberto() {
  const user = userEvent.setup()
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <AtivarOperacaoDialog operacaoId="op-1" valorPrincipal="30000" />
    </QueryClientProvider>,
  )
  await user.click(screen.getByRole('button', { name: 'Ativar' }))
  return user
}

describe('AtivarOperacaoDialog', () => {
  beforeEach(() => {
    getCapitalSnapshotMock.mockReset()
    postAtivarMock.mockReset()
  })

  it('mostra valor da operação e o teto resultante ao abrir', async () => {
    getCapitalSnapshotMock.mockResolvedValue({
      data: { total: '100000', comprometido: '20000', disponivel: '80000' },
    })

    await renderComDialogAberto()

    expect(await screen.findByText('Confirmar ativação de operação')).toBeInTheDocument()
    // Intl.NumberFormat('pt-BR') usa espaço não separável (U+00A0) — regex evita depender do char exato.
    expect(screen.getByText(/R\$\s?30\.000,00/)).toBeInTheDocument()
    // (20000 comprometido + 30000 desta operação) / 100000 total = 50%
    // Vírgula decimal, não ponto: a asserção anterior ('50.0%') fixava o
    // formato en-US que vazava do toFixed() e mascarava o bug.
    await waitFor(() => expect(screen.getByText('50,0%')).toBeInTheDocument())
  })

  it('avisa explicitamente que a ação é irreversível', async () => {
    getCapitalSnapshotMock.mockResolvedValue({
      data: { total: '100000', comprometido: '0', disponivel: '100000' },
    })

    await renderComDialogAberto()

    expect(await screen.findByText(/irreversível/i)).toBeInTheDocument()
  })

  it('confirma a ativação e fecha o modal em caso de sucesso', async () => {
    getCapitalSnapshotMock.mockResolvedValue({
      data: { total: '100000', comprometido: '0', disponivel: '100000' },
    })
    postAtivarMock.mockResolvedValue({
      data: { id: 'op-1', status: 'ativa', valor_principal: '30000' },
    })

    const user = await renderComDialogAberto()
    await screen.findByText('Confirmar ativação de operação')

    await user.click(screen.getByRole('button', { name: 'Confirmar ativação' }))

    await waitFor(() =>
      expect(screen.queryByText('Confirmar ativação de operação')).not.toBeInTheDocument(),
    )
    expect(postAtivarMock).toHaveBeenCalledWith(
      expect.objectContaining({ path: { operacao_id: 'op-1' } }),
    )
  })

  it('mostra a mensagem traduzida do dicionário quando o teto é excedido (OC001)', async () => {
    getCapitalSnapshotMock.mockResolvedValue({
      data: { total: '100000', comprometido: '0', disponivel: '100000' },
    })
    postAtivarMock.mockRejectedValue(new ApiError('Teto de capital excedido', 'OC001', 422))

    const user = await renderComDialogAberto()
    await screen.findByText('Confirmar ativação de operação')

    await user.click(screen.getByRole('button', { name: 'Confirmar ativação' }))

    expect(
      await screen.findByText('Esta operação excede o teto de capital disponível.'),
    ).toBeInTheDocument()
    // Modal continua aberto — usuário precisa poder ver o erro, não sumir.
    expect(screen.getByText('Confirmar ativação de operação')).toBeInTheDocument()
  })

  it('cancelar fecha o modal sem chamar a mutação', async () => {
    getCapitalSnapshotMock.mockResolvedValue({
      data: { total: '100000', comprometido: '0', disponivel: '100000' },
    })

    const user = await renderComDialogAberto()
    await screen.findByText('Confirmar ativação de operação')

    await user.click(screen.getByRole('button', { name: 'Cancelar' }))

    await waitFor(() =>
      expect(screen.queryByText('Confirmar ativação de operação')).not.toBeInTheDocument(),
    )
    expect(postAtivarMock).not.toHaveBeenCalled()
  })
})
