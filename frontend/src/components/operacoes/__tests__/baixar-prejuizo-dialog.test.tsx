import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BaixarPrejuizoDialog } from '@/components/operacoes/baixar-prejuizo-dialog'
import { ApiError } from '@/api/errors'

const { getCapitalSnapshotMock, postBaixarPrejuizoMock } = vi.hoisted(() => ({
  getCapitalSnapshotMock: vi.fn(),
  postBaixarPrejuizoMock: vi.fn(),
}))

vi.mock('@/api/generated/sdk.gen', () => ({
  getCapitalSnapshotApiCapitalSnapshotGet: getCapitalSnapshotMock,
  postBaixarPrejuizoApiOperacoesOperacaoIdBaixarPrejuizoPost: postBaixarPrejuizoMock,
}))

function renderDialog(props: Partial<Parameters<typeof BaixarPrejuizoDialog>[0]> = {}) {
  const user = userEvent.setup()
  const onOpenChange = vi.fn()
  const onSucesso = vi.fn()
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <BaixarPrejuizoDialog
        operacaoId="op-1"
        valorPrincipal="30000"
        open
        onOpenChange={onOpenChange}
        onSucesso={onSucesso}
        {...props}
      />
    </QueryClientProvider>,
  )
  return { user, onOpenChange, onSucesso }
}

const dialogo = () => within(screen.getByRole('dialog'))

describe('BaixarPrejuizoDialog', () => {
  beforeEach(() => {
    getCapitalSnapshotMock.mockReset()
    postBaixarPrejuizoMock.mockReset()
    getCapitalSnapshotMock.mockResolvedValue({
      data: { total: '100000', comprometido: '30000', disponivel: '70000' },
    })
  })

  it('declara as três consequências sem eufemismo', async () => {
    renderDialog()

    const d = dialogo()
    expect(d.getByText('Baixar operação como prejuízo')).toBeInTheDocument()
    expect(d.getByText(/não é uma liquidação/i)).toBeInTheDocument()
    expect(d.getByText('O capital não volta.')).toBeInTheDocument()
    expect(d.getByText('O teto encolhe de forma permanente.')).toBeInTheDocument()
    expect(d.getByText('A operação sai da cobrança.')).toBeInTheDocument()
    expect(d.getByText(/irreversível/i)).toBeInTheDocument()
    expect(d.getByText(/aporte de capital/i)).toBeInTheDocument()
  })

  it('mostra que nada é devolvido e qual fatia do teto congela', async () => {
    renderDialog()

    const d = dialogo()
    // U+00A0 no separador do Intl pt-BR: regex evita fixar o caractere.
    expect(d.getByText(/R\$\s?30\.000,00/)).toBeInTheDocument()
    expect(d.getByText(/R\$\s?0,00/)).toBeInTheDocument()
    // 30.000 de um teto de 100.000 = 30% congelados para sempre.
    await waitFor(() => expect(d.getByText('30,0%')).toBeInTheDocument())
  })

  it('mantém a confirmação bloqueada até a palavra ser digitada', async () => {
    const { user } = renderDialog()

    const confirmar = dialogo().getByRole('button', { name: 'Confirmar baixa por prejuízo' })
    expect(confirmar).toBeDisabled()

    await user.type(dialogo().getByLabelText(/digite/i), 'prejuizo')

    await waitFor(() => expect(confirmar).toBeEnabled())
    expect(postBaixarPrejuizoMock).not.toHaveBeenCalled()
  })

  it('chama o endpoint de write-off, fecha e avisa a tela em caso de sucesso', async () => {
    postBaixarPrejuizoMock.mockResolvedValue({
      data: { id: 'op-1', status: 'baixada_prejuizo' },
    })
    const { user, onOpenChange, onSucesso } = renderDialog()

    await user.type(dialogo().getByLabelText(/digite/i), 'PREJUIZO')
    await user.click(dialogo().getByRole('button', { name: 'Confirmar baixa por prejuízo' }))

    await waitFor(() => expect(onSucesso).toHaveBeenCalled())
    expect(postBaixarPrejuizoMock).toHaveBeenCalledWith(
      expect.objectContaining({ path: { operacao_id: 'op-1' } }),
    )
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('anuncia a recusa do backend e mantém o diálogo aberto', async () => {
    postBaixarPrejuizoMock.mockRejectedValue(new ApiError('Transição não permitida', 'OC003', 409))
    const { user, onSucesso } = renderDialog()

    await user.type(dialogo().getByLabelText(/digite/i), 'PREJUIZO')
    await user.click(dialogo().getByRole('button', { name: 'Confirmar baixa por prejuízo' }))

    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent(
      'Essa transição de status não é permitida no estado atual da operação.',
    )
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(onSucesso).not.toHaveBeenCalled()
  })

  it('cancelar fecha sem chamar o endpoint', async () => {
    const { user, onOpenChange } = renderDialog()

    await user.click(dialogo().getByRole('button', { name: 'Cancelar' }))

    expect(onOpenChange).toHaveBeenCalledWith(false)
    expect(postBaixarPrejuizoMock).not.toHaveBeenCalled()
  })
})
