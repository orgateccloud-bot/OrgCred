import { describe, expect, it } from 'vitest'
import {
  memoriaComoCsv,
  memoriaComoTexto,
  nomeDoArquivo,
  rotuloPeriodo,
  type MemoriaCalculo,
} from '@/components/fiscal/memoria'
import { MEMORIA_CONFERE, MEMORIA_DIVERGENTE } from '@/components/fiscal/__tests__/fixtures'

describe('rotuloPeriodo', () => {
  it('marca a retificação, porque a versão 1 continua existindo', () => {
    expect(rotuloPeriodo({ ano: 2026, trimestre: 1, versao: 1 })).toBe('1º trimestre de 2026')
    expect(rotuloPeriodo({ ano: 2026, trimestre: 1, versao: 3 })).toBe(
      '1º trimestre de 2026 (retificada, v3)',
    )
  })
})

describe('memoriaComoTexto', () => {
  it('escreve a derivação de cada tributo, não só o valor final', () => {
    const texto = memoriaComoTexto(MEMORIA_CONFERE)

    // Receita -> presunção -> base -> alíquota -> valor, na mesma ordem em que
    // o contador refaz a conta.
    expect(texto).toContain('receita 10000,00 x presunção 32,0000% = base 3200,00')
    expect(texto).toContain('base 3200,00 x 15,0000% = 480,00')
    // PIS/COFINS não têm presunção: a base É a receita, e o texto precisa
    // dizer isso em vez de omitir a coluna.
    expect(texto).toContain('base = receita 10000,00 (sem presunção)')
    expect(texto).toContain('Total de tributos ........ 1133,00')
  })

  it('explicita limite e excedente do adicional', () => {
    expect(memoriaComoTexto(MEMORIA_CONFERE)).toContain(
      'base 3200,00 - limite 60000,00 = excedente 0,00',
    )
  })

  it('leva a divergência junto: quem recebe o texto tem que ver o problema', () => {
    const texto = memoriaComoTexto(MEMORIA_DIVERGENTE)

    expect(texto).toContain('DIVERGE do valor gravado: 999,99')
    expect(texto).toContain('IRPJ: recalculado 480,00, gravado 999,99')
    expect(texto).toContain('retificando o trimestre')
  })

  it('não anuncia divergência quando não há', () => {
    expect(memoriaComoTexto(MEMORIA_CONFERE)).not.toContain('DIVERG')
  })
})

describe('memoriaComoCsv', () => {
  it('usa ponto e vírgula, porque o decimal já é vírgula', () => {
    const linhas = memoriaComoCsv(MEMORIA_CONFERE).split('\r\n')
    const irpj = linhas.find((l) => l.startsWith('IRPJ;')) as string

    // Com separador vírgula, "3200,00" partiria a linha no meio do número e o
    // Excel em pt-BR mostraria colunas deslocadas.
    expect(irpj.split(';')).toEqual([
      'IRPJ',
      '10000,00',
      '32,0000%',
      '3200,00',
      '',
      '',
      '15,0000%',
      '480,00',
      '480,00',
      'sim',
    ])
  })

  it('deixa presunção, limite e excedente vazios onde o conceito não existe', () => {
    const linhas = memoriaComoCsv(MEMORIA_CONFERE).split('\r\n')
    const pis = (linhas.find((l) => l.startsWith('PIS;')) as string).split(';')

    // Vazio, e não "0": zero seria uma presunção de 0%, que é outra afirmação
    // e daria base zero.
    expect(pis[2]).toBe('')
    expect(pis[3]).toBe('10000,00')
  })

  it('traz o bloco de divergência com o gravado ao lado do recalculado', () => {
    const csv = memoriaComoCsv(MEMORIA_DIVERGENTE)

    expect(csv).toContain('DIVERGÊNCIA: o recálculo não reproduz o valor gravado')
    expect(csv).toContain('IRPJ;480,00;999,99;-519,99')
    expect(csv).toContain('IRPJ;10000,00;32,0000%;3200,00;;;15,0000%;480,00;999,99;NÃO')
  })

  it('escapa o separador quando ele aparece dentro de um campo', () => {
    const comPontoEVirgula: MemoriaCalculo = {
      ...MEMORIA_CONFERE,
      linhas: [{ ...MEMORIA_CONFERE.linhas[0], tributo: 'IRPJ; adicional à parte' }],
    }
    expect(memoriaComoCsv(comPontoEVirgula)).toContain('"IRPJ; adicional à parte"')
  })
})

describe('nomeDoArquivo', () => {
  it('identifica período e versão: duas versões do mesmo trimestre coexistem', () => {
    expect(nomeDoArquivo(MEMORIA_CONFERE)).toBe('memoria-calculo-2026-T1-v1.csv')
    expect(nomeDoArquivo(MEMORIA_DIVERGENTE)).toBe('memoria-calculo-2026-T1-v2.csv')
  })
})
