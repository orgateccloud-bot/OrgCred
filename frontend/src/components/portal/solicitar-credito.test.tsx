import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SolicitarCredito } from './solicitar-credito'

describe('SolicitarCredito', () => {
  it('mostra exatamente o que será enviado antes de qualquer ação', async () => {
    const user = userEvent.setup()
    render(<SolicitarCredito razaoSocial="Padaria Demonstração ME" cnpj="12345678000190" />)

    await user.click(screen.getByRole('button', { name: 'Solicitar crédito' }))
    expect(screen.getByText(/nenhum crédito nasce aprovado automaticamente/)).toBeInTheDocument()

    // Sem valor e finalidade não há o que enviar: prévia ausente, copiar
    // desabilitado.
    expect(screen.queryByText(/Solicitação de crédito — Portal do Tomador/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copiar' })).toBeDisabled()

    await user.type(screen.getByLabelText('Valor pretendido (R$)'), '20.000,00')
    await user.type(screen.getByLabelText('Finalidade'), 'Reforma do forno')

    const previa = screen.getByText(/Solicitação de crédito — Portal do Tomador/)
    expect(previa).toHaveTextContent('Padaria Demonstração ME')
    expect(previa).toHaveTextContent('R$ 20.000,00')
    expect(previa).toHaveTextContent('Reforma do forno')
  })

  it('copiar entrega o mesmo texto da prévia', async () => {
    // userEvent.setup() instala um clipboard de verdade (stub do jsdom) —
    // lê-se de volta o que o botão escreveu, em vez de mockar writeText.
    const user = userEvent.setup()
    render(<SolicitarCredito razaoSocial="Padaria Demonstração ME" cnpj="12345678000190" />)

    await user.click(screen.getByRole('button', { name: 'Solicitar crédito' }))
    await user.type(screen.getByLabelText('Valor pretendido (R$)'), '20.000,00')
    await user.type(screen.getByLabelText('Finalidade'), 'Capital de giro')
    await user.click(screen.getByRole('button', { name: 'Copiar' }))

    const texto = await navigator.clipboard.readText()
    expect(texto).toContain('Capital de giro')
    expect(texto).toContain('não representa aprovação automática')
  })

  it('sem VITE_ESC_EMAIL configurado, não promete botão de e-mail', async () => {
    const user = userEvent.setup()
    render(<SolicitarCredito razaoSocial="Padaria Demonstração ME" cnpj="12345678000190" />)

    await user.click(screen.getByRole('button', { name: 'Solicitar crédito' }))
    expect(screen.queryByRole('link', { name: /Enviar por e-mail/ })).not.toBeInTheDocument()
  })
})
