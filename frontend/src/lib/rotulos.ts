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

const FAIXA_AGING: Record<string, string> = {
  em_dia: 'Em dia',
  ate_30: 'Até 30 dias',
  de_31_a_60: '31 a 60 dias',
  de_61_a_90: '61 a 90 dias',
  acima_de_90: 'Acima de 90 dias',
}

const ORIGEM_EVENTO: Record<string, string> = {
  usuario: 'Operador',
  sistema: 'Régua automática',
}

const REGRA_ATIPICIDADE: Record<string, string> = {
  fracionamento: 'Fracionamento',
  liquidacao_antecipada: 'Liquidação antecipada',
  // Migration 023: write-off antes do primeiro vencimento. Regra separada da
  // liquidação antecipada de propósito — lá o dinheiro voltou cedo demais,
  // aqui não voltou —, e o rótulo precisa deixar os dois distinguíveis na
  // lista sem que o analista abra o detalhe.
  baixa_prejuizo_antecipada: 'Baixa por prejuízo antecipada',
  pagamento_em_excesso: 'Pagamento em excesso',
}

const SEVERIDADE: Record<string, string> = {
  alta: 'Alta',
  media: 'Média',
  baixa: 'Baixa',
}

export const rotuloTipo = (v: string) => TIPO_OPERACAO[v] ?? v
export const rotuloRegraAtipicidade = (v: string) => REGRA_ATIPICIDADE[v] ?? v
export const rotuloSeveridade = (v: string) => SEVERIDADE[v] ?? v
export const rotuloFaixaAging = (v: string) => FAIXA_AGING[v] ?? v
export const rotuloOrigemEvento = (v: string) => ORIGEM_EVENTO[v] ?? v
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
