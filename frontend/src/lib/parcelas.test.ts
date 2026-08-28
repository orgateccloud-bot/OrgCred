import { describe, expect, it } from 'vitest'
import { diasDeAtraso, proximaParcelaEmAberto } from './parcelas'

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
