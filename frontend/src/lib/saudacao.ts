/**
 * Saudação e data por extenso da home do portal.
 *
 * Recebem o relógio por parâmetro (default new Date()) pelo mesmo motivo de
 * lib/parcelas.ts: função que lê a hora por dentro não tem como ser testada
 * nos dois lados de uma fronteira (11h59 vs 12h00).
 */

export function saudacao(agora: Date = new Date()): string {
  const hora = agora.getHours()
  if (hora >= 5 && hora < 12) return 'Bom dia'
  if (hora >= 12 && hora < 18) return 'Boa tarde'
  return 'Boa noite'
}

const formatadorData = new Intl.DateTimeFormat('pt-BR', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
})

/**
 * "Sexta-feira, 28 de agosto" — sem ano: é a data de HOJE, o ano é óbvio.
 * Só a primeira letra sobe, AQUI e não com `capitalize` do CSS — o utilitário
 * capitaliza cada palavra e produzia "3 De Setembro".
 */
export function dataPorExtenso(agora: Date = new Date()): string {
  const texto = formatadorData.format(agora)
  return texto.charAt(0).toUpperCase() + texto.slice(1)
}
