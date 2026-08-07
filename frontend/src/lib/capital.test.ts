import { describe, expect, it } from 'vitest'
import {
  comprometidoPorTipo,
  operacoesPorStatus,
  percentualUtilizacao,
  serieSaldoDisponivel,
  somarValorPrincipal,
  type OperacaoResumo,
} from './capital'

const OPERACOES: OperacaoResumo[] = [
  { status: 'ativa', tipo: 'emprestimo', valor_principal: '30000.00' },
  { status: 'ativa', tipo: 'emprestimo', valor_principal: '10000.00' },
  { status: 'ativa', tipo: 'financiamento', valor_principal: '20000.00' },
  { status: 'registrada', tipo: 'emprestimo', valor_principal: '5000.00' },
  { status: 'registrada', tipo: 'financiamento', valor_principal: '2500.50' },
  { status: 'liquidada', tipo: 'emprestimo', valor_principal: '99999.00' },
  { status: 'proposta', tipo: 'emprestimo', valor_principal: '888.00' },
]

describe('percentualUtilizacao', () => {
  it('calcula a fração do teto comprometida', () => {
    expect(percentualUtilizacao(50000, 20000)).toBe(40)
    expect(percentualUtilizacao(100000, 0)).toBe(0)
    expect(percentualUtilizacao(100000, 100000)).toBe(100)
  })

  it('devolve 0 com teto zerado, sem dividir por zero', () => {
    // Este é o estado REAL de produção: capital social não integralizado.
    // NaN aqui vazaria para a tela como "NaN% do teto".
    expect(percentualUtilizacao(0, 0)).toBe(0)
    expect(percentualUtilizacao(0, 5000)).toBe(0)
  })

  it('não passa de 100% se o comprometido exceder o teto', () => {
    // Não deveria acontecer (o trigger impede), mas se um dado inconsistente
    // chegar, a barra de progresso não pode estourar o container.
    expect(percentualUtilizacao(10000, 25000)).toBe(100)
  })

  it('trata teto negativo como zero', () => {
    expect(percentualUtilizacao(-1000, 500)).toBe(0)
  })
})

describe('operacoesPorStatus', () => {
  it('separa ativas de registradas sem contar as demais', () => {
    expect(operacoesPorStatus(OPERACOES, 'ativa')).toHaveLength(3)
    expect(operacoesPorStatus(OPERACOES, 'registrada')).toHaveLength(2)
    // Liquidadas e propostas não entram em nenhum dos dois KPIs.
    expect(operacoesPorStatus(OPERACOES, 'liquidada')).toHaveLength(1)
  })

  it('devolve vazio para status inexistente', () => {
    expect(operacoesPorStatus(OPERACOES, 'inadimplente')).toEqual([])
  })
})

describe('somarValorPrincipal', () => {
  it('soma valores decimais vindos como string do backend', () => {
    const registradas = operacoesPorStatus(OPERACOES, 'registrada')
    expect(somarValorPrincipal(registradas)).toBe(7500.5)
  })

  it('devolve 0 para lista vazia', () => {
    expect(somarValorPrincipal([])).toBe(0)
  })
})

describe('comprometidoPorTipo', () => {
  it('agrupa e soma por tipo', () => {
    const ativas = operacoesPorStatus(OPERACOES, 'ativa')
    const porTipo = comprometidoPorTipo(ativas)
    expect(porTipo).toEqual([
      { tipo: 'emprestimo', valor: 40000 },
      { tipo: 'financiamento', valor: 20000 },
    ])
  })

  it('devolve vazio sem operações — o donut mostra estado vazio', () => {
    expect(comprometidoPorTipo([])).toEqual([])
  })
})

describe('serieSaldoDisponivel', () => {
  it('ordena do mais antigo ao mais recente, independente da ordem de entrada', () => {
    // O ledger pode chegar em qualquer ordem; um gráfico de saldo com o eixo
    // X embaralhado conta uma história errada sobre a evolução do capital.
    const serie = serieSaldoDisponivel([
      { created_at: '2026-03-15T10:00:00Z', saldo_disponivel_pos: '20000' },
      { created_at: '2026-01-10T10:00:00Z', saldo_disponivel_pos: '50000' },
      { created_at: '2026-02-20T10:00:00Z', saldo_disponivel_pos: '35000' },
    ])
    expect(serie.map((p) => p.saldo)).toEqual([50000, 35000, 20000])
  })

  it('formata a data como dia/mês em pt-BR', () => {
    const serie = serieSaldoDisponivel([
      { created_at: '2026-01-09T12:00:00Z', saldo_disponivel_pos: '1000' },
    ])
    expect(serie[0].quando).toMatch(/^\d{2}\/\d{2}$/)
  })

  it('não muta o array recebido', () => {
    const original = [
      { created_at: '2026-03-01T00:00:00Z', saldo_disponivel_pos: '1' },
      { created_at: '2026-01-01T00:00:00Z', saldo_disponivel_pos: '2' },
    ]
    const copia = [...original]
    serieSaldoDisponivel(original)
    expect(original).toEqual(copia)
  })

  it('devolve vazio sem eventos', () => {
    expect(serieSaldoDisponivel([])).toEqual([])
  })
})
