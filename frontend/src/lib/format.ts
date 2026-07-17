const formatadorMoeda = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
})

export function formatarMoeda(valor: string | number): string {
  return formatadorMoeda.format(Number(valor))
}
