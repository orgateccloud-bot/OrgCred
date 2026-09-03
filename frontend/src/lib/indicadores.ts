/**
 * Indicadores econômicos do radar — fontes públicas, sem chave.
 *
 * Selic e IPCA vêm do SGS do Banco Central (api.bcb.gov.br, CORS aberto);
 * o dólar vem da AwesomeAPI. São os três números que mudam a conversa de
 * crédito de uma empresa pequena: custo do dinheiro, inflação e câmbio.
 *
 * Nenhum destes números entra em conta nenhuma — são LEITURA, com fonte e
 * data de referência à vista. A regra do app continua: dinheiro do tomador
 * é somado pelo banco; indicador de mercado é notícia, não insumo.
 */

export interface Indicador {
  rotulo: string
  valor: number
  unidade: string
  referencia: string
  fonte: string
}

/**
 * O SGS serve `valor` como string e o separador decimal varia entre séries
 * ("15.00" e "0,26" existem ambos). Normaliza os dois; devolve NaN para o
 * chamador descartar a série em vez de exibir lixo.
 */
export function parseValorBr(valor: string): number {
  const texto = valor.trim()
  if (texto.includes(',')) {
    return Number(texto.replace(/\./g, '').replace(',', '.'))
  }
  return Number(texto)
}

interface SerieSgs {
  data: string
  valor: string
}

async function ultimoSgs(serie: number): Promise<SerieSgs> {
  const resp = await fetch(
    `https://api.bcb.gov.br/dados/serie/bcdata.sgs.${serie}/dados/ultimos/1?formato=json`,
  )
  if (!resp.ok) throw new Error(`SGS ${serie} respondeu ${resp.status}`)
  const corpo = (await resp.json()) as SerieSgs[]
  if (!corpo.length) throw new Error(`SGS ${serie} sem dados`)
  return corpo[0]
}

/** Busca os três em paralelo; quem falhar é omitido — radar parcial vale
 *  mais do que radar nenhum, e a UI diz as fontes do que exibiu. */
export async function buscarIndicadores(): Promise<Indicador[]> {
  const [selic, ipca, dolar] = await Promise.allSettled([
    // 432: meta Selic definida pelo Copom, % a.a.
    ultimoSgs(432).then((s): Indicador => ({
      rotulo: 'Selic (meta)',
      valor: parseValorBr(s.valor),
      unidade: '% a.a.',
      referencia: s.data,
      fonte: 'Banco Central',
    })),
    // 13522: IPCA acumulado em 12 meses, %.
    ultimoSgs(13522).then((s): Indicador => ({
      rotulo: 'IPCA (12 meses)',
      valor: parseValorBr(s.valor),
      unidade: '%',
      referencia: s.data,
      fonte: 'IBGE/BCB',
    })),
    fetch('https://economia.awesomeapi.com.br/json/last/USD-BRL')
      .then((r) => {
        if (!r.ok) throw new Error(`awesomeapi respondeu ${r.status}`)
        return r.json() as Promise<{ USDBRL: { bid: string; create_date: string } }>
      })
      .then((c): Indicador => ({
        rotulo: 'Dólar',
        valor: Number(c.USDBRL.bid),
        unidade: 'R$',
        referencia: c.USDBRL.create_date.slice(0, 10),
        fonte: 'AwesomeAPI',
      })),
  ])

  return [selic, ipca, dolar]
    .filter((r): r is PromiseFulfilledResult<Indicador> => r.status === 'fulfilled')
    .map((r) => r.value)
    .filter((i) => Number.isFinite(i.valor))
}
