import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AcessoPortal } from './acesso-portal'
import { ApiError } from '@/api/errors'
import { useAppStore } from '@/stores/useAppStore'

const { getConvitesMock, postConvidarMock } = vi.hoisted(() => ({
  getConvitesMock: vi.fn(),
  postConvidarMock: vi.fn(),
}))

vi.mock('@/api/generated/sdk.gen', () => ({
  getConvitesPortalApiTomadoresTomadorIdPortalConvitesGet: getConvitesMock,
  postConvidarPortalApiTomadoresTomadorIdPortalConvitesPost: postConvidarMock,
}))

function renderAcesso() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <AcessoPortal tomadorId="tom-1" />
    </QueryClientProvider>,
  )
}

describe('AcessoPortal', () => {
  beforeEach(() => {
    getConvitesMock.mockReset()
    postConvidarMock.mockReset()
    useAppStore.setState({
      usuario: { id: 'u1', email: 'admin@orgatec.com', papel: 'admin' },
    })
  })

  it('mostra a trilha: quem aguarda e quem já entrou', async () => {
    getConvitesMock.mockResolvedValue({
      data: [
        {
          id: 'c1',
          email: 'socio@empresa.com',
          criado_em: '2026-08-01T10:00:00',
          aceito_em: '2026-08-03T09:00:00',
          convidado_por_nome: 'Admin da ESC',
        },
        {
          id: 'c2',
          email: 'contador@empresa.com',
          criado_em: '2026-08-20T10:00:00',
          aceito_em: null,
          convidado_por_nome: 'Admin da ESC',
        },
      ],
    })

    renderAcesso()

    expect(await screen.findByText('socio@empresa.com')).toBeInTheDocument()
    expect(screen.getByText('Entrou em 03/08/2026')).toBeInTheDocument()
    expect(screen.getByText('Aguardando primeiro acesso')).toBeInTheDocument()
    expect(screen.getByText(/Convidado em 01\/08\/2026 por Admin da ESC/)).toBeInTheDocument()
  })

  it('operador vê a trilha, mas não o botão de convidar (ato de admin)', async () => {
    useAppStore.setState({
      usuario: { id: 'u2', email: 'op@orgatec.com', papel: 'operador' },
    })
    getConvitesMock.mockResolvedValue({ data: [] })

    renderAcesso()

    expect(await screen.findByText(/ainda não tem login no portal/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Convidar' })).not.toBeInTheDocument()
  })

  it('admin convida: nome + e-mail, e a lista é atualizada', async () => {
    getConvitesMock.mockResolvedValue({ data: [] })
    postConvidarMock.mockResolvedValue({
      data: {
        id: 'c9',
        email: 'socio@empresa.com',
        criado_em: '2026-08-28T12:00:00',
        aceito_em: null,
        convidado_por_nome: 'Admin da ESC',
      },
    })

    renderAcesso()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Convidar' }))
    await user.type(screen.getByLabelText('Nome'), 'Sócio da Empresa')
    await user.type(screen.getByLabelText('E-mail'), 'socio@empresa.com')
    await user.click(screen.getByRole('button', { name: 'Enviar convite' }))

    await waitFor(() =>
      expect(postConvidarMock).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { tomador_id: 'tom-1' },
          body: { email: 'socio@empresa.com', nome: 'Sócio da Empresa' },
        }),
      ),
    )
    // O diálogo fecha no sucesso — o formulário some.
    await waitFor(() => expect(screen.queryByLabelText('E-mail')).not.toBeInTheDocument())
  })

  it('503 (Supabase sem credenciais) mostra a instrução de infraestrutura', async () => {
    getConvitesMock.mockResolvedValue({ data: [] })
    postConvidarMock.mockRejectedValue(new ApiError('Service Unavailable', null, 503))

    renderAcesso()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Convidar' }))
    await user.type(screen.getByLabelText('Nome'), 'Sócio')
    await user.type(screen.getByLabelText('E-mail'), 'socio@empresa.com')
    await user.click(screen.getByRole('button', { name: 'Enviar convite' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/sem as credenciais do Supabase/)
    // E o diálogo continua aberto: há o que ler e nada foi criado.
    expect(screen.getByLabelText('E-mail')).toBeInTheDocument()
  })
})
