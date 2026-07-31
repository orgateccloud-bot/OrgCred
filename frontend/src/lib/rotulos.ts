/**
 * Tradução de valores de enum do banco para texto de interface.
 *
 * O banco guarda 'emprestimo', 'proposta', 'PRICE' — sem acento e em caixa
 * baixa, como convém a uma chave. Vazar isso na tela mostra ao operador o
 * schema em vez do domínio ("emprestimo" sem acento num produto de crédito
 * brasileiro é erro visível). O fallback devolve o valor cru para um enum
 * novo aparecer em vez de sumir.
 */

const TIPO_OPERACAO: Record<string, string> = {
  emprestimo: 'Empréstimo',
  financiamento: 'Financiamento',
}

const STATUS_OPERACAO: Record<string, string> = {
  proposta: 'Proposta',
  registrada: 'Registrada',
  ativa: 'Ativa',
  liquidada: 'Liquidada',
  inadimplente: 'Inadimplente',
  renegociada: 'Renegociada',
  cancelada: 'Cancelada',
}

const PORTE_TOMADOR: Record<string, string> = {
  ME: 'Microempresa',
  EPP: 'Empresa de pequeno porte',
}

const EVENTO_CAPITAL: Record<string, string> = {
  constituicao: 'Aporte',
  reducao: 'Redução',
  ativacao_operacao: 'Ativação de operação',
  liquidacao: 'Liquidação',
}

export const rotuloTipo = (v: string) => TIPO_OPERACAO[v] ?? v
export const rotuloStatus = (v: string) => STATUS_OPERACAO[v] ?? v
export const rotuloPorte = (v: string) => PORTE_TOMADOR[v] ?? v
export const rotuloEventoCapital = (v: string) => EVENTO_CAPITAL[v] ?? v

/**
 * Percentual em pt-BR (vírgula decimal). `toFixed()` produz "0.0", que num
 * app financeiro brasileiro lê como erro — e mesmo `Intl` precisa do
 * mínimo/máximo explícitos para não arredondar para inteiro.
 */
export function formatarPercentual(valor: number, casas = 1): string {
  return `${valor.toLocaleString('pt-BR', {
    minimumFractionDigits: casas,
    maximumFractionDigits: casas,
  })}%`
}
