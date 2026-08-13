import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { LiquidarOperacaoDialog } from '@/components/operacoes/liquidar-operacao-dialog'
import { ApiError } from '@/api/errors'

const { postLiquidarMock } = vi.hoisted(() => ({ postLiquidarMock: vi.fn() }))

vi.mock('@/api/generated/sdk.gen', () => ({
  postLiquidarOperacaoApiOperacoesOperacaoIdLiquidarPost: postLiquidarMock,
}))

function renderDialog() {
  const user = userEvent.setup()
  const onOpenChange = vi.fn()
  const onSucesso = vi.fn()
  const onEscolherPrejuizo = vi.fn()
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <LiquidarOperacaoDialog
        operacaoId="op-1"
        valorPrincipal="30000"
        open
        onOpenChange={onOpenChange}
        onSucesso={onSucesso}
        onEscolherPrejuizo={onEscolherPrejuizo}
      />
    </QueryClientProvider>,
  )
  return { user, onOpenChange, onSucesso, onEscolherPrejuizo }
}

const dialogo = () => within(screen.getByRole('dialog'))

describe('LiquidarOperacaoDialog', () => {
  beforeEach(() => {
    postLiquidarMock.mockReset()
  })

  it('diz que a liquidação devolve o capital e exige lastro', async () => {
    renderDialog()

    const d = dialogo()
    expect(d.getByText(/devolve.*ao capital disponível/i)).toBeInTheDocument()
    expect(d.getByText(/movimento bancário/i)).toBeInTheDocument()
  })

  it('liquida e fecha quando o backend aceita', async () => {
    postLiquidarMock.mockResolvedValue({ data: { id: 'op-1', status: 'liquidada' } })
    const { user, onOpenChange, onSucesso } = renderDialog()

    await user.click(dialogo().getByRole('button', { name: 'Confirmar liquidação' }))

    await waitFor(() => expect(onSucesso).toHaveBeenCalled())
    expect(postLiquidarMock).toHaveBeenCalledWith(
      expect.objectContaining({ path: { operacao_id: 'op-1' } }),
    )
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('transforma o OC022 em painel acionável, com a saída alternativa', async () => {
    postLiquidarMock.mockRejectedValue(
      new ApiError('Liquidação bloqueada: 3 de 12 parcelas sem lastro', 'OC022', 422),
    )
    const { user, onEscolherPrejuizo } = renderDialog()

    await user.click(dialogo().getByRole('button', { name: 'Confirmar liquidação' }))

    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent('faltam parcelas com lastro bancário')
    expect(alerta).toHaveTextContent(/Agenda de parcelas/)
    expect(alerta).toHaveTextContent(/não devolve capital/)
    // O diálogo continua aberto: a recusa é conteúdo, não fim de fluxo.
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await user.click(within(alerta).getByRole('button', { name: 'Baixar como prejuízo' }))
    expect(onEscolherPrejuizo).toHaveBeenCalled()
  })

  it('anuncia erros que não são OC022 sem oferecer o write-off', async () => {
    postLiquidarMock.mockRejectedValue(new ApiError('Transição inválida', 'OC003', 409))
    const { user } = renderDialog()

    await user.click(dialogo().getByRole('button', { name: 'Confirmar liquidação' }))

    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent(
      'Essa transição de status não é permitida no estado atual da operação.',
    )
    expect(screen.queryByRole('button', { name: 'Baixar como prejuízo' })).not.toBeInTheDocument()
  })

  it('cancelar fecha sem liquidar', async () => {
    const { user, onOpenChange } = renderDialog()

    await user.click(dialogo().getByRole('button', { name: 'Cancelar' }))

    expect(onOpenChange).toHaveBeenCalledWith(false)
    expect(postLiquidarMock).not.toHaveBeenCalled()
  })
})
