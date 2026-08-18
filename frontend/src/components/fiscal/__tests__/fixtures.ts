import type { MemoriaCalculo } from '@/components/fiscal/memoria'

/**
 * Números escolhidos para conferir a olho — NÃO são recomendação tributária.
 * Percentuais e alíquotas reais são configuração do contador, e é por isso que
 * nada vem semeado nem no banco nem aqui.
 *
 * Receita total 10.000,00 (9.500,00 de juros + 500,00 de mora). Presunção 32%
 * dá base 3.200,00; IRPJ 15% dá 480,00; CSLL 9% sobre a mesma base dá 288,00;
 * PIS 0,65% e COFINS 3% incidem sobre a receita e dão 65,00 e 300,00. Total
 * 1.133,00, com adicional zero — a base não chega perto do limite de 60.000.
 */
export const MEMORIA_CONFERE: MemoriaCalculo = {
  apuracao_id: 'apuracao-1',
  ano: 2026,
  trimestre: 1,
  versao: 1,
  regime_reconhecimento: 'competencia',
  receita_juros: '9500.00',
  receita_demais: '500.00',
  receita_total: '10000.00',
  receita_total_gravada: '10000.00',
  linhas: [
    {
      chave: 'irpj',
      tributo: 'IRPJ',
      receita_considerada: '10000.00',
      percentual_presuncao: '0.3200',
      base_calculo: '3200.00',
      limite: null,
      excedente: null,
      aliquota: '0.1500',
      valor: '480.00',
      valor_gravado: '480.00',
      confere: true,
    },
    {
      chave: 'adicional_irpj',
      tributo: 'Adicional de IRPJ',
      receita_considerada: '10000.00',
      percentual_presuncao: '0.3200',
      base_calculo: '3200.00',
      limite: '60000.00',
      excedente: '0',
      aliquota: '0.1000',
      valor: '0.00',
      valor_gravado: '0.00',
      confere: true,
    },
    {
      chave: 'csll',
      tributo: 'CSLL',
      receita_considerada: '10000.00',
      percentual_presuncao: '0.3200',
      base_calculo: '3200.00',
      limite: null,
      excedente: null,
      aliquota: '0.0900',
      valor: '288.00',
      valor_gravado: '288.00',
      confere: true,
    },
    {
      chave: 'pis',
      tributo: 'PIS',
      receita_considerada: '10000.00',
      percentual_presuncao: null,
      base_calculo: '10000.00',
      limite: null,
      excedente: null,
      aliquota: '0.0065',
      valor: '65.00',
      valor_gravado: '65.00',
      confere: true,
    },
    {
      chave: 'cofins',
      tributo: 'COFINS',
      receita_considerada: '10000.00',
      percentual_presuncao: null,
      base_calculo: '10000.00',
      limite: null,
      excedente: null,
      aliquota: '0.0300',
      valor: '300.00',
      valor_gravado: '300.00',
      confere: true,
    },
  ],
  total_tributos: '1133.00',
  total_tributos_gravado: '1133.00',
  confere: true,
  divergencias: [],
}

/** Mesmo trimestre, versão 2, com IRPJ gravado que a fórmula atual não reproduz. */
export const MEMORIA_DIVERGENTE: MemoriaCalculo = {
  ...MEMORIA_CONFERE,
  apuracao_id: 'apuracao-2',
  versao: 2,
  linhas: MEMORIA_CONFERE.linhas.map((linha) =>
    linha.chave === 'irpj' ? { ...linha, valor_gravado: '999.99', confere: false } : linha,
  ),
  total_tributos_gravado: '1652.99',
  confere: false,
  divergencias: [
    {
      campo: 'irpj',
      rotulo: 'IRPJ',
      calculado: '480.00',
      gravado: '999.99',
      diferenca: '-519.99',
    },
    {
      campo: 'total_tributos',
      rotulo: 'Total de tributos',
      calculado: '1133.00',
      gravado: '1652.99',
      diferenca: '-519.99',
    },
  ],
}

/** Adicional incidindo: base acima do limite do trimestre. */
export const MEMORIA_COM_ADICIONAL: MemoriaCalculo = {
  ...MEMORIA_CONFERE,
  apuracao_id: 'apuracao-3',
  receita_juros: '250000.00',
  receita_demais: '0.00',
  receita_total: '250000.00',
  receita_total_gravada: '250000.00',
  linhas: MEMORIA_CONFERE.linhas.map((linha) =>
    linha.chave === 'adicional_irpj'
      ? {
          ...linha,
          receita_considerada: '250000.00',
          base_calculo: '80000.00',
          excedente: '20000.00',
          valor: '2000.00',
          valor_gravado: '2000.00',
        }
      : linha,
  ),
}
