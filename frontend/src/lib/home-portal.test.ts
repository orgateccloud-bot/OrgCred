import { describe, expect, it } from 'vitest'
import { saudacao, dataPorExtenso } from './saudacao'
import { derivarAlertas, interpretarCodigoTempo, type PrevisaoDia } from './clima'
import { parseValorBr } from './indicadores'
import { FRASES_COMPLIANCE, fraseDoDia } from './compliance'
import { montarSolicitacao } from './solicitacao'

describe('saudacao', () => {
  it('cada faixa do dia tem a sua', () => {
    expect(saudacao(new Date(2026, 7, 28, 7, 0))).toBe('Bom dia')
    expect(saudacao(new Date(2026, 7, 28, 11, 59))).toBe('Bom dia')
    expect(saudacao(new Date(2026, 7, 28, 12, 0))).toBe('Boa tarde')
    expect(saudacao(new Date(2026, 7, 28, 17, 59))).toBe('Boa tarde')
    expect(saudacao(new Date(2026, 7, 28, 18, 0))).toBe('Boa noite')
    expect(saudacao(new Date(2026, 7, 28, 3, 0))).toBe('Boa noite')
  })

  it('data por extenso em pt-BR, sem ano, só a primeira letra maiúscula', () => {
    expect(dataPorExtenso(new Date(2026, 7, 28))).toBe('Sexta-feira, 28 de agosto')
  })
})

describe('interpretarCodigoTempo', () => {
  it('mapeia os códigos WMO comuns', () => {
    expect(interpretarCodigoTempo(0)).toEqual({ rotulo: 'Céu limpo', familia: 'sol' })
    expect(interpretarCodigoTempo(3).familia).toBe('nublado')
    expect(interpretarCodigoTempo(63).familia).toBe('chuva')
    expect(interpretarCodigoTempo(81).rotulo).toBe('Pancadas de chuva')
    expect(interpretarCodigoTempo(95).familia).toBe('tempestade')
  })

  it('código desconhecido degrada para indefinido, não para erro', () => {
    expect(interpretarCodigoTempo(42).rotulo).toBe('Tempo indefinido')
  })
})

describe('derivarAlertas', () => {
  const dia = (extra: Partial<PrevisaoDia>): PrevisaoDia => ({
    data: '2026-08-29',
    codigo: 1,
    tempMax: 28,
    tempMin: 16,
    chuvaMm: 0,
    probChuva: 10,
    ventoMax: 20,
    ...extra,
  })

  it('dia tranquilo não gera alerta nenhum', () => {
    expect(derivarAlertas([dia({})])).toEqual([])
  })

  it('chuva volumosa gera alerta com o critério no texto', () => {
    const alertas = derivarAlertas([dia({ chuvaMm: 42, probChuva: 90 })])
    expect(alertas).toHaveLength(1)
    expect(alertas[0].titulo).toBe('Chuva forte prevista')
    expect(alertas[0].detalhe).toBe('42 mm previstos, 90% de chance')
    expect(alertas[0].severidade).toBe('atencao')
  })

  it('acima de 50 mm a severidade sobe', () => {
    expect(derivarAlertas([dia({ chuvaMm: 55 })])[0].severidade).toBe('alerta')
  })

  it('vento, calor e frio têm limiares próprios', () => {
    const alertas = derivarAlertas([dia({ ventoMax: 72, tempMax: 38, tempMin: 3 })])
    expect(alertas.map((a) => a.titulo)).toEqual([
      'Vento forte previsto',
      'Calor intenso',
      'Frio intenso',
    ])
    expect(alertas[0].severidade).toBe('alerta')
  })

  it('ordena por data entre dias diferentes', () => {
    const alertas = derivarAlertas([
      dia({ data: '2026-08-31', chuvaMm: 40 }),
      dia({ data: '2026-08-30', ventoMax: 60 }),
    ])
    expect(alertas.map((a) => a.data)).toEqual(['2026-08-30', '2026-08-31'])
  })
})

describe('parseValorBr', () => {
  it('aceita decimal com ponto (formato de algumas séries do SGS)', () => {
    expect(parseValorBr('15.00')).toBe(15)
  })

  it('aceita decimal com vírgula e milhar com ponto', () => {
    expect(parseValorBr('1.234,56')).toBe(1234.56)
    expect(parseValorBr('0,26')).toBe(0.26)
  })

  it('lixo vira NaN para o chamador descartar', () => {
    expect(Number.isNaN(parseValorBr('n/d'))).toBe(true)
  })
})

describe('fraseDoDia', () => {
  it('é determinística no mesmo dia e gira entre dias', () => {
    const d1 = fraseDoDia(new Date(2026, 7, 28, 9, 0))
    const d1Noite = fraseDoDia(new Date(2026, 7, 28, 22, 0))
    const d2 = fraseDoDia(new Date(2026, 7, 29))
    expect(d1).toEqual(d1Noite)
    expect(d1).not.toEqual(d2)
  })

  it('todas as frases têm texto e tema', () => {
    for (const frase of FRASES_COMPLIANCE) {
      expect(frase.texto.length).toBeGreaterThan(20)
      expect(frase.tema.length).toBeGreaterThan(2)
    }
  })
})

describe('montarSolicitacao', () => {
  it('carrega empresa, valores e o aviso de que o banco decide', () => {
    const texto = montarSolicitacao({
      razaoSocial: 'Padaria Demonstração ME',
      cnpj: '12345678000190',
      valor: '20.000,00',
      parcelas: '12',
      finalidade: 'Reforma do forno',
    })
    expect(texto).toContain('Padaria Demonstração ME')
    expect(texto).toContain('R$ 20.000,00')
    expect(texto).toContain('Parcelas: 12')
    expect(texto).toContain('Reforma do forno')
    expect(texto).toContain('não representa aprovação automática')
  })
})
