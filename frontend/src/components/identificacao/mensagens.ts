import { ApiError, mensagemDeErro } from '@/api/errors'

/**
 * Tipos aceitos pelo backend (app/routers/compliance.py, `TipoDocumento`).
 * A lista é fechada no servidor: oferecer um rótulo livre aqui só produziria
 * 422 depois do upload.
 */
export const TIPOS_DOCUMENTO = [
  { valor: 'contrato_social', rotulo: 'Contrato social' },
  { valor: 'cartao_cnpj', rotulo: 'Cartão CNPJ' },
  { valor: 'documento_socio', rotulo: 'Documento do sócio' },
  { valor: 'comprovante_endereco', rotulo: 'Comprovante de endereço' },
  { valor: 'procuracao', rotulo: 'Procuração' },
  { valor: 'outro', rotulo: 'Outro' },
] as const

export type TipoDocumento = (typeof TIPOS_DOCUMENTO)[number]['valor']

const ROTULO_POR_TIPO: Record<string, string> = Object.fromEntries(
  TIPOS_DOCUMENTO.map((t) => [t.valor, t.rotulo]),
)

/** Fallback devolve o valor cru — tipo novo aparece em vez de sumir. */
export const rotuloTipoDocumento = (valor: string) => ROTULO_POR_TIPO[valor] ?? valor

/**
 * 503 aqui não é "erro inesperado": a dependência `storage_de_documentos`
 * (app/routers/compliance.py) responde 503 quando o bucket não está
 * configurado. Quem lê a tela não tem nada a corrigir no formulário — a
 * instrução é para quem opera a infraestrutura, e some se cair no texto
 * genérico do dicionário.
 *
 * O texto aponta a causa provável em vez de afirmá-la: um 503 pode vir da
 * borda (aplicação fora do ar, gateway) sem passar pelo router, e mandar o
 * operador conferir SUPABASE_URL como fato seria diagnóstico inventado.
 *
 * Vale para as duas pontas — arquivar e recuperar dependem do mesmo bucket —,
 * por isso a frase não nomeia a operação: a mesma função atende o upload, o
 * download e a conferência.
 */
export function mensagemDeErroDeEvidencia(erro: unknown): string {
  if (erro instanceof ApiError && erro.httpStatus === 503) {
    return (
      'Acervo de evidências indisponível (HTTP 503): enquanto isso, nenhum documento pode ser ' +
      'arquivado, recuperado ou conferido. A causa mais comum é o servidor estar sem armazenamento ' +
      'configurado — faltam SUPABASE_URL e a service_role key do bucket de identificação. ' +
      'Peça a verificação a quem administra o ambiente.'
    )
  }
  return mensagemDeErro(erro)
}

/**
 * `retencao_ate` chega como 'YYYY-MM-DD'. `new Date('2031-01-01')` é lido
 * como meia-noite UTC e, em fuso negativo (o do Brasil inteiro),
 * `toLocaleDateString` devolveria o dia anterior — num prazo legal de guarda,
 * um dia a menos é a diferença que uma fiscalização cobra.
 */
export function formatarDataIso(valor: string): string {
  const [ano, mes, dia] = valor.slice(0, 10).split('-')
  if (!ano || !mes || !dia) return valor
  return `${dia}/${mes}/${ano}`
}

/** Hash inteiro tem 64 caracteres e não cabe numa célula; o começo basta para conferir de olho. */
export const hashAbreviado = (sha256: string) => `${sha256.slice(0, 12)}…`
