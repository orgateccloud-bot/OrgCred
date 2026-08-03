import { describe, expect, it } from 'vitest'
import {
  formatarPercentual,
  rotuloEventoCapital,
  rotuloPorte,
  rotuloStatus,
  rotuloTipo,
} from './rotulos'

describe('rotulos', () => {
  it('traduz enums do banco para texto de interface', () => {
    expect(rotuloTipo('emprestimo')).toBe('Empréstimo')
    expect(rotuloStatus('inadimplente')).toBe('Inadimplente')
    expect(rotuloPorte('ME')).toBe('Microempresa')
    expect(rotuloEventoCapital('ativacao_operacao')).toBe('Ativação de operação')
  })

  it('devolve o valor cru quando o enum é desconhecido', () => {
    // Enum novo no banco deve aparecer na tela, não sumir.
    expect(rotuloTipo('consignado')).toBe('consignado')
    expect(rotuloStatus('em_analise')).toBe('em_analise')
  })

  it('formata percentual em pt-BR com vírgula decimal', () => {
    expect(formatarPercentual(0)).toBe('0,0%')
    expect(formatarPercentual(50)).toBe('50,0%')
    expect(formatarPercentual(38.04)).toBe('38,0%')
    expect(formatarPercentual(100)).toBe('100,0%')
  })
})
