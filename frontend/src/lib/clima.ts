/**
 * Clima do município do tomador — Open-Meteo (sem chave, CORS aberto).
 *
 * O tomador de uma ESC é agro/comércio de município pequeno: chuva forte e
 * vento não são curiosidade, são o dia de trabalho e a receita da semana. O
 * local NÃO é geolocalização do navegador (pedir permissão para um dado que
 * já temos seria atrito): é o município do CADASTRO, o mesmo do gate
 * geográfico — vem de GET /portal/perfil.
 *
 * Toda a interpretação (código WMO -> rótulo, previsão -> alerta) é pura e
 * testada; só as duas funções de rede tocam fetch. Falha de rede degrada em
 * silêncio na UI — clima é cortesia, não pode derrubar a home.
 */

export interface ClimaAtual {
  temperatura: number
  codigo: number
  vento: number
  umidade: number
}

export interface PrevisaoDia {
  data: string // 'aaaa-mm-dd'
  codigo: number
  tempMax: number
  tempMin: number
  chuvaMm: number
  probChuva: number
  ventoMax: number
}

export interface Clima {
  local: string
  atual: ClimaAtual
  dias: PrevisaoDia[]
}

export interface AlertaTempo {
  data: string
  titulo: string
  detalhe: string
  severidade: 'atencao' | 'alerta'
}

/** Sigla -> nome, para conferir o admin1 do geocoding (que vem por extenso). */
const UF_NOME: Record<string, string> = {
  AC: 'Acre',
  AL: 'Alagoas',
  AP: 'Amapá',
  AM: 'Amazonas',
  BA: 'Bahia',
  CE: 'Ceará',
  DF: 'Distrito Federal',
  ES: 'Espírito Santo',
  GO: 'Goiás',
  MA: 'Maranhão',
  MT: 'Mato Grosso',
  MS: 'Mato Grosso do Sul',
  MG: 'Minas Gerais',
  PA: 'Pará',
  PB: 'Paraíba',
  PR: 'Paraná',
  PE: 'Pernambuco',
  PI: 'Piauí',
  RJ: 'Rio de Janeiro',
  RN: 'Rio Grande do Norte',
  RS: 'Rio Grande do Sul',
  RO: 'Rondônia',
  RR: 'Roraima',
  SC: 'Santa Catarina',
  SP: 'São Paulo',
  SE: 'Sergipe',
  TO: 'Tocantins',
}

interface RotuloTempo {
  rotulo: string
  familia: 'sol' | 'nublado' | 'nevoeiro' | 'chuva' | 'tempestade' | 'neve'
}

/**
 * Código WMO -> rótulo humano. A família decide o ícone no componente — a
 * lista completa da Open-Meteo tem ~30 códigos e a home precisa de 6 caras.
 */
export function interpretarCodigoTempo(codigo: number): RotuloTempo {
  if (codigo === 0) return { rotulo: 'Céu limpo', familia: 'sol' }
  if (codigo === 1 || codigo === 2) return { rotulo: 'Parcialmente nublado', familia: 'sol' }
  if (codigo === 3) return { rotulo: 'Nublado', familia: 'nublado' }
  if (codigo === 45 || codigo === 48) return { rotulo: 'Nevoeiro', familia: 'nevoeiro' }
  if (codigo >= 51 && codigo <= 57) return { rotulo: 'Garoa', familia: 'chuva' }
  if (codigo >= 61 && codigo <= 67) return { rotulo: 'Chuva', familia: 'chuva' }
  if (codigo >= 71 && codigo <= 77) return { rotulo: 'Neve', familia: 'neve' }
  if (codigo >= 80 && codigo <= 82) return { rotulo: 'Pancadas de chuva', familia: 'chuva' }
  if (codigo >= 95) return { rotulo: 'Tempestade', familia: 'tempestade' }
  return { rotulo: 'Tempo indefinido', familia: 'nublado' }
}

/**
 * Alertas derivados da previsão — determinísticos e com o critério à vista.
 *
 * NÃO são os avisos oficiais da Defesa Civil (a Open-Meteo não os serve):
 * são limiares simples sobre a previsão, e o componente diz a fonte. Regra
 * de ouro herdada do resto do app: número que aparece vem com o critério
 * junto, para o leitor poder discordar dele.
 */
export function derivarAlertas(dias: PrevisaoDia[]): AlertaTempo[] {
  const alertas: AlertaTempo[] = []
  for (const dia of dias) {
    if (dia.chuvaMm >= 30 || (dia.probChuva >= 80 && dia.chuvaMm >= 10)) {
      alertas.push({
        data: dia.data,
        titulo: 'Chuva forte prevista',
        detalhe: `${Math.round(dia.chuvaMm)} mm previstos, ${dia.probChuva}% de chance`,
        severidade: dia.chuvaMm >= 50 ? 'alerta' : 'atencao',
      })
    }
    if (dia.ventoMax >= 50) {
      alertas.push({
        data: dia.data,
        titulo: 'Vento forte previsto',
        detalhe: `rajadas de até ${Math.round(dia.ventoMax)} km/h`,
        severidade: dia.ventoMax >= 70 ? 'alerta' : 'atencao',
      })
    }
    if (dia.tempMax >= 36) {
      alertas.push({
        data: dia.data,
        titulo: 'Calor intenso',
        detalhe: `máxima prevista de ${Math.round(dia.tempMax)} °C`,
        severidade: 'atencao',
      })
    }
    if (dia.tempMin <= 5) {
      alertas.push({
        data: dia.data,
        titulo: 'Frio intenso',
        detalhe: `mínima prevista de ${Math.round(dia.tempMin)} °C`,
        severidade: 'atencao',
      })
    }
  }
  return alertas.sort((a, b) => a.data.localeCompare(b.data))
}

interface GeocodeResultado {
  latitude: number
  longitude: number
  name: string
  admin1?: string
}

/**
 * Busca o clima do município. Lança em qualquer falha — quem chama (React
 * Query) trata o erro como "sem clima hoje", nunca como tela quebrada.
 */
export async function buscarClima(municipio: string, uf: string): Promise<Clima> {
  const geoUrl =
    'https://geocoding-api.open-meteo.com/v1/search?count=5&language=pt&format=json&name=' +
    encodeURIComponent(municipio)
  const geoResp = await fetch(geoUrl)
  if (!geoResp.ok) throw new Error(`geocoding respondeu ${geoResp.status}`)
  const geo = (await geoResp.json()) as { results?: GeocodeResultado[] }
  const candidatos = geo.results ?? []
  // Prefere o resultado no estado certo; homônimos entre UFs são comuns
  // (Formoso existe em GO e em MG).
  const lugar = candidatos.find((c) => c.admin1 === UF_NOME[uf]) ?? candidatos[0]
  if (!lugar) throw new Error(`município ${municipio}/${uf} não encontrado no geocoding`)

  const url =
    'https://api.open-meteo.com/v1/forecast' +
    `?latitude=${lugar.latitude}&longitude=${lugar.longitude}` +
    '&current=temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m' +
    '&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max' +
    '&timezone=America%2FSao_Paulo&forecast_days=3'
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`open-meteo respondeu ${resp.status}`)
  const corpo = (await resp.json()) as {
    current: {
      temperature_2m: number
      weather_code: number
      wind_speed_10m: number
      relative_humidity_2m: number
    }
    daily: {
      time: string[]
      weather_code: number[]
      temperature_2m_max: number[]
      temperature_2m_min: number[]
      precipitation_sum: number[]
      precipitation_probability_max: Array<number | null>
      wind_speed_10m_max: number[]
    }
  }

  return {
    local: `${lugar.name}/${uf}`,
    atual: {
      temperatura: corpo.current.temperature_2m,
      codigo: corpo.current.weather_code,
      vento: corpo.current.wind_speed_10m,
      umidade: corpo.current.relative_humidity_2m,
    },
    dias: corpo.daily.time.map((data, i) => ({
      data,
      codigo: corpo.daily.weather_code[i],
      tempMax: corpo.daily.temperature_2m_max[i],
      tempMin: corpo.daily.temperature_2m_min[i],
      chuvaMm: corpo.daily.precipitation_sum[i],
      probChuva: corpo.daily.precipitation_probability_max[i] ?? 0,
      ventoMax: corpo.daily.wind_speed_10m_max[i],
    })),
  }
}
