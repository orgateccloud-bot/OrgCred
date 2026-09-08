import { describe, expect, it } from 'vitest'
import {
  diasDeAtraso,
  proximaParcelaEmAberto,
  proximasParcelas,
  ultimosPagamentos,
} from './parcelas'

const parcela = (numero: number, vencimento: string, status = 'aberta') => ({
  numero,
  vencimento,
  status,
})

describe('proximaParcelaEmAberto', () => {
  it('devolve a primeira parcela não paga pela ordem de vencimento', () => {
    const proxima = proximaParcelaEmAberto([
      parcela(1, '2026-01-10', 'paga'),
      parcela(2, '2026-02-10'),
      parcela(3, '2026-03-10'),
    ])
    expect(proxima?.numero).toBe(2)
  })

  it('não depende da ordem em que a agenda chega', () => {
    const proxima = proximaParcelaEmAberto([
      parcela(3, '2026-03-10'),
      parcela(2, '2026-02-10'),
      parcela(1, '2026-01-10', 'paga'),
    ])
    expect(proxima?.numero).toBe(2)
  })

  it('desempata vencimentos iguais pelo número', () => {
    const proxima = proximaParcelaEmAberto([parcela(5, '2026-02-10'), parcela(4, '2026-02-10')])
    expect(proxima?.numero).toBe(4)
  })

  it('devolve null com a agenda toda paga (operação quitada)', () => {
    expect(
      proximaParcelaEmAberto([parcela(1, '2026-01-10', 'paga'), parcela(2, '2026-02-10', 'paga')]),
    ).toBeNull()
  })

  it('devolve null para agenda vazia (operação ainda não ativada)', () => {
    expect(proximaParcelaEmAberto([])).toBeNull()
  })
})

describe('proximasParcelas / ultimosPagamentos', () => {
  const agendas = [
    {
      operacaoId: 'op-a',
      tipo: 'emprestimo',
      parcelas: [
        { numero: 1, vencimento: '2026-01-10', status: 'paga', pago_em: '2026-01-09' },
        { numero: 2, vencimento: '2026-02-10', status: 'aberta', pago_em: null },
      ],
    },
    {
      operacaoId: 'op-b',
      tipo: 'financiamento',
      parcelas: [
        { numero: 1, vencimento: '2026-01-20', status: 'paga', pago_em: '2026-01-22' },
        { numero: 2, vencimento: '2026-02-05', status: 'aberta', pago_em: null },
        { numero: 3, vencimento: '2026-03-05', status: 'aberta', pago_em: null },
      ],
    },
  ]

  it('próximas parcelas atravessam operações e ordenam por vencimento', () => {
    const proximas = proximasParcelas(agendas, 2)
    expect(proximas.map((p) => [p.operacaoId, p.parcela.numero])).toEqual([
      ['op-b', 2],
      ['op-a', 2],
    ])
  })

  it('limite corta a lista, não a ordenação', () => {
    expect(proximasParcelas(agendas, 10)).toHaveLength(3)
  })

  it('últimos pagamentos vêm do mais recente para o mais antigo', () => {
    const pagos = ultimosPagamentos(agendas, 5)
    expect(pagos.map((p) => p.parcela.pago_em)).toEqual(['2026-01-22', '2026-01-09'])
  })

  it('parcela paga sem pago_em não vira pagamento listável', () => {
    const pagos = ultimosPagamentos(
      [
        {
          operacaoId: 'op-c',
          tipo: 'emprestimo',
          parcelas: [{ numero: 1, vencimento: '2026-01-10', status: 'paga', pago_em: null }],
        },
      ],
      5,
    )
    expect(pagos).toEqual([])
  })
})

describe('diasDeAtraso', () => {
  // "Hoje" fixo em vez de new Date(): o teste precisa valer em qualquer dia
  // e em qualquer fuso em que a suíte rode.
  const hoje = new Date(2026, 2, 15) // 15/03/2026 no fuso local

  it('parcela vincenda não tem atraso', () => {
    expect(diasDeAtraso('2026-03-20', hoje)).toBe(0)
  })

  it('parcela que vence hoje não tem atraso', () => {
    expect(diasDeAtraso('2026-03-15', hoje)).toBe(0)
  })

  it('conta dias corridos desde o vencimento', () => {
    expect(diasDeAtraso('2026-03-10', hoje)).toBe(5)
  })

  it('atravessa meses e anos sem drift de fuso', () => {
    expect(diasDeAtraso('2025-12-15', hoje)).toBe(90)
  })

  it('ignora hora anexada ao vencimento (compara dia civil, não timestamp)', () => {
    expect(diasDeAtraso('2026-03-10T23:59:00', hoje)).toBe(5)
  })
})
