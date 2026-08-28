/**
 * Seleção e leitura da agenda de parcelas — SEM aritmética de dinheiro.
 *
 * A regra do portal (app/routers/portal.py) vale aqui também: todo valor
 * monetário vem somado pelo banco. O que este módulo faz é ESCOLHER — qual
 * parcela é a próxima — e CONTAR DIAS, que são operações de apresentação,
 * não de negócio. Se um dia parecer natural somar valores aqui, o lugar
 * certo é um campo novo no endpoint.
 */

interface ParcelaOrdenavel {
  numero: number
  vencimento: string
  status: string
}

/**
 * A parcela que o tomador procura ao abrir a tela: a primeira em aberto.
 *
 * O backend devolve a agenda ordenada por número, e o vencimento acompanha o
 * número — mas a ordenação é refeita aqui de propósito: a escolha da "próxima"
 * é o destaque da tela, e depender da ordem do transporte para acertá-la
 * deixaria o erro invisível (a lista continuaria correta; só o destaque
 * apontaria para a parcela errada).
 */
export function proximaParcelaEmAberto<T extends ParcelaOrdenavel>(parcelas: T[]): T | null {
  const emAberto = parcelas
    .filter((p) => p.status !== 'paga')
    .sort((a, b) => a.vencimento.localeCompare(b.vencimento) || a.numero - b.numero)
  return emAberto[0] ?? null
}

/** 'aaaa-mm-dd' -> milissegundos UTC do dia, ignorando qualquer hora. */
function diaUtc(iso: string): number {
  const [ano, mes, dia] = iso.slice(0, 10).split('-').map(Number)
  return Date.UTC(ano, mes - 1, dia)
}

/**
 * Dias de atraso de um vencimento em relação a hoje; 0 se ainda não venceu.
 *
 * Compara DIA com DIA, nunca timestamps: o vencimento é uma data civil
 * ('aaaa-mm-dd') e `new Date('2026-03-10')` a interpretaria como meia-noite
 * UTC — o que, no fuso de Brasília, faria uma parcela vencer às 21h da
 * véspera. Os dois lados são normalizados para o dia em UTC antes do diff.
 */
export function diasDeAtraso(vencimentoIso: string, hoje: Date = new Date()): number {
  const hojeUtc = Date.UTC(hoje.getFullYear(), hoje.getMonth(), hoje.getDate())
  const diff = Math.floor((hojeUtc - diaUtc(vencimentoIso)) / 86_400_000)
  return Math.max(0, diff)
}
