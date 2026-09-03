/**
 * Texto da solicitação de crédito que o tomador manda à ESC.
 *
 * O portal continua SEM verbo de escrita (a promessa de app/routers/
 * portal.py): a solicitação não grava nada no banco — ela compõe a mensagem
 * que vai por e-mail ou copiada para o canal que a empresa já usa, e a
 * análise é humana, na ESC. Quando (e se) existir um endpoint de proposta,
 * este texto vira o corpo do POST; até lá, prometer um botão que "envia"
 * para lugar nenhum seria o anti-padrão que a migration 019 matou no
 * arquivamento de documentos.
 */

export interface DadosSolicitacao {
  razaoSocial: string
  cnpj: string
  valor: string
  parcelas: string
  finalidade: string
}

export function montarSolicitacao(dados: DadosSolicitacao): string {
  return [
    'Solicitação de crédito — Portal do Tomador OrgCred',
    '',
    `Empresa: ${dados.razaoSocial}`,
    `CNPJ: ${dados.cnpj}`,
    `Valor pretendido: R$ ${dados.valor}`,
    `Parcelas: ${dados.parcelas}`,
    `Finalidade: ${dados.finalidade}`,
    '',
    'Estou ciente de que a solicitação será analisada pela equipe da ESC e ' +
      'não representa aprovação automática de crédito.',
  ].join('\n')
}
