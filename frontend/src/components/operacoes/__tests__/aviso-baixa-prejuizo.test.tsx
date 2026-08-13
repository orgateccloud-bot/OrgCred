import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AvisoBaixaPrejuizo } from '@/components/operacoes/aviso-baixa-prejuizo'
import { BadgeStatusOperacao } from '@/components/operacoes/badge-status-operacao'
import { rotuloStatusOperacao } from '@/components/operacoes/rotulo-status-operacao'

describe('AvisoBaixaPrejuizo', () => {
  it('separa write-off de quitação numa região anunciável', () => {
    render(<AvisoBaixaPrejuizo valorPrincipal="30000" />)

    const aviso = screen.getByRole('status')
    expect(aviso).toHaveTextContent('Baixada como prejuízo — não é uma quitação')
    expect(aviso).toHaveTextContent(/não\s+voltaram para o capital disponível/)
    expect(aviso).toHaveTextContent(/teto operacional encolheu de forma permanente/)
    expect(aviso).toHaveTextContent(/aporte de capital/)
    expect(aviso).toHaveTextContent(/R\$\s?30\.000,00/)
  })
})

describe('BadgeStatusOperacao', () => {
  it('nomeia o estado de write-off em vez de vazar a chave do banco', () => {
    render(<BadgeStatusOperacao status="baixada_prejuizo" />)

    expect(screen.getByText('Baixada como prejuízo')).toBeInTheDocument()
    expect(screen.queryByText('baixada_prejuizo')).not.toBeInTheDocument()
  })

  it('delega os demais status ao badge compartilhado', () => {
    render(<BadgeStatusOperacao status="liquidada" />)

    expect(screen.getByText('Liquidada')).toBeInTheDocument()
  })
})

describe('rotuloStatusOperacao', () => {
  it('nomeia o write-off e delega o resto ao dicionário compartilhado', () => {
    // Também é o texto lido pelo aria-label do status atual na tela da
    // operação: sem isto, o leitor de tela anuncia a chave do banco.
    expect(rotuloStatusOperacao('baixada_prejuizo')).toBe('Baixada como prejuízo')
    expect(rotuloStatusOperacao('liquidada')).toBe('Liquidada')
    expect(rotuloStatusOperacao('inadimplente')).toBe('Inadimplente')
  })
})
