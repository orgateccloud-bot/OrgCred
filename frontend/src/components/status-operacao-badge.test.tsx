import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatusOperacaoBadge } from './status-operacao-badge'

describe('StatusOperacaoBadge', () => {
  it.each([
    'proposta',
    'registrada',
    'ativa',
    'liquidada',
    'inadimplente',
    'renegociada',
    'cancelada',
  ])('renderiza rótulo em texto para o status %s (nunca só cor)', (status) => {
    render(<StatusOperacaoBadge status={status} />)
    // O texto do badge existe no DOM independente de cor — é o requisito
    // de acessibilidade (WCAG: cor nunca é o único veículo de informação).
    expect(screen.getByText(/./)).toBeInTheDocument()
  })

  it('renderiza um ícone junto do texto', () => {
    const { container } = render(<StatusOperacaoBadge status="ativa" />)
    expect(container.querySelector('svg')).toBeInTheDocument()
    expect(screen.getByText('Ativa')).toBeInTheDocument()
  })

  it('lida com status desconhecido sem quebrar', () => {
    render(<StatusOperacaoBadge status="status-nunca-visto" />)
    expect(screen.getByText('status-nunca-visto')).toBeInTheDocument()
  })
})
