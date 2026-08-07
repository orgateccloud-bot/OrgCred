import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RegistrarOperacaoDialog } from './registrar-operacao-dialog'
import { ApiError } from '@/api/errors'

const { postRegistrarMock } = vi.hoisted(() => ({ postRegistrarMock: vi.fn() }))

vi.mock('@/api/generated/sdk.gen', () => ({
  postRegistrarOperacaoApiOperacoesOperacaoIdRegistrarPost: postRegistrarMock,
}))

async function abrirDialog(onSucesso = vi.fn()) {
  const user = userEvent.setup()
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <RegistrarOperacaoDialog operacaoId="op-1" onSucesso={onSucesso} />
    </QueryClientProvider>,
  )
  await user.click(screen.getByRole('button', { name: 'Registrar' }))
  await screen.findByText('Registrar operação')
  return { user, onSucesso }
}

describe('RegistrarOperacaoDialog', () => {
  beforeEach(() => {
    postRegistrarMock.mockReset()
  })

  it('explica por que a referência é obrigatória, citando a lei', async () => {
    await abrirDialog()
    // O operador precisa entender que o bloqueio é legal, não capricho da UI.
    expect(screen.getByText(/OC004/)).toBeInTheDocument()
    expect(screen.getByText(/LC 167\/2019/)).toBeInTheDocument()
  })

  it('mantém o botão desabilitado enquanto a referência estiver vazia', async () => {
    const { user } = await abrirDialog()
    const confirmar = screen.getByRole('button', { name: 'Confirmar registro' })
    expect(confirmar).toBeDisabled()

    // Só espaços não valem como referência.
    await user.type(screen.getByLabelText('Referência do registro'), '   ')
    expect(confirmar).toBeDisabled()

    await user.type(screen.getByLabelText('Referência do registro'), 'B3-REG-1')
    expect(confirmar).toBeEnabled()
  })

  it('envia a referência sem espaços nas bordas e avisa o chamador', async () => {
    postRegistrarMock.mockResolvedValue({ data: { id: 'op-1', status: 'registrada' } })
    const { user, onSucesso } = await abrirDialog()

    await user.type(screen.getByLabelText('Referência do registro'), '  B3-REG-2026-001  ')
    await user.click(screen.getByRole('button', { name: 'Confirmar registro' }))

    await waitFor(() => expect(onSucesso).toHaveBeenCalled())
    expect(postRegistrarMock).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { operacao_id: 'op-1' },
        body: { registro_entidade_ref: 'B3-REG-2026-001' },
      }),
    )
  })

  it('mostra a mensagem traduzida e mantém o diálogo aberto em caso de erro', async () => {
    postRegistrarMock.mockImplementation(() =>
      Promise.reject(new ApiError('Transição inválida', 'OC003', 422)),
    )
    const { user } = await abrirDialog()

    // fireEvent.change (uma alteração só) em vez de user.type: digitar
    // caractere a caractere abre uma fronteira de act() por tecla, e a
    // rejeição da mutação escapa numa delas — o Vitest a reporta como erro
    // não tratado e o teste falha mesmo com a asserção correta. Nos testes
    // que não disparam erro, user.type funciona normalmente (ver acima).
    fireEvent.change(screen.getByLabelText('Referência do registro'), {
      target: { value: 'B3-REG-X' },
    })
    await user.click(screen.getByRole('button', { name: 'Confirmar registro' }))

    expect(
      await screen.findByText(
        'Essa transição de status não é permitida no estado atual da operação.',
      ),
    ).toBeInTheDocument()
    // Nada some em silêncio: o operador vê o erro e o que digitou.
    expect(screen.getByText('Registrar operação')).toBeInTheDocument()

    // Fecha o diálogo como o operador faria. Além de espelhar o uso real,
    // dispara o mutation.reset() do onOpenChange — sem isso a rejeição da
    // mutação assenta depois do fim do teste e o Vitest a reporta como
    // rejeição não tratada.
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    await waitFor(() => expect(screen.queryByText('Registrar operação')).not.toBeInTheDocument())
  })
})
