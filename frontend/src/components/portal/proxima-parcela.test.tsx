import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ParcelaPortalOut } from '@/api/generated/types.gen'
import { ProximaParcelaCard } from './proxima-parcela'

const parcela: ParcelaPortalOut = {
  numero: 3,
  vencimento: '2026-03-10',
  valor_total: '1250.40',
  status: 'aberta',
  pago_em: null,
}

describe('ProximaParcelaCard', () => {
  it('parcela vincenda: sem alarme, com valor e vencimento', () => {
    render(<ProximaParcelaCard parcela={parcela} hoje={new Date(2026, 2, 1)} />)

    expect(screen.getByText('Próxima parcela (3)')).toBeInTheDocument()
    expect(screen.getByText('R$ 1.250,40')).toBeInTheDocument()
    expect(screen.getByText(/Vence em 10\/03\/2026/)).toBeInTheDocument()
    expect(screen.queryByText(/atraso/)).not.toBeInTheDocument()
  })

  it('parcela vencida: diz em texto há quantos dias, não só em cor', () => {
    render(<ProximaParcelaCard parcela={parcela} hoje={new Date(2026, 2, 15)} />)

    expect(screen.getByText('Parcela 3 em atraso há 5 dias')).toBeInTheDocument()
    expect(screen.getByText(/Venceu em 10\/03\/2026/)).toBeInTheDocument()
  })

  it('um dia de atraso conjuga no singular', () => {
    render(<ProximaParcelaCard parcela={parcela} hoje={new Date(2026, 2, 11)} />)

    expect(screen.getByText('Parcela 3 em atraso há 1 dia')).toBeInTheDocument()
  })
})
