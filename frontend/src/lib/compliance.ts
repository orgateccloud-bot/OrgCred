/**
 * Frase do dia — educação de compliance em dose homeopática.
 *
 * O tomador não lê manual de PLD; lê uma linha por dia se ela for curta e
 * falar da vida dele. As frases são deste repositório (nenhuma citação de
 * terceiros) e giram pelo dia do ano — determinístico: todo mundo vê a
 * mesma frase no mesmo dia, e o teste sabe qual é.
 */

export interface FraseCompliance {
  texto: string
  tema: string
}

export const FRASES_COMPLIANCE: FraseCompliance[] = [
  {
    texto:
      'Pagar em dia é o argumento mais barato que existe para o seu próximo crédito sair maior.',
    tema: 'Pontualidade',
  },
  {
    texto:
      'A agenda de parcelas é emitida pelo banco e ninguém a reescreve — nem a ESC. O que foi contratado é o que vale.',
    tema: 'Transparência',
  },
  {
    texto:
      'Toda operação desta ESC é registrada em entidade autorizada pelo Banco Central antes de valer. Crédito informal não tem essa proteção.',
    tema: 'LC 167/2019',
  },
  {
    texto:
      'Confira a impressão digital do seu contrato no portal: se a via que você recebeu tem o mesmo código, ela é a que a ESC emitiu.',
    tema: 'Integridade',
  },
  {
    texto:
      'A ESC só empresta no município autorizado e dentro do próprio capital — é isso que mantém o crédito perto de quem produz.',
    tema: 'LC 167/2019',
  },
  {
    texto:
      'Seus documentos de identificação ficam guardados por 5 anos, por lei. É proteção sua: prova quem contratou o quê.',
    tema: 'Prevenção à lavagem',
  },
  {
    texto:
      'Pagamento só se prova com extrato: cada baixa de parcela nasce amarrada a um movimento bancário real.',
    tema: 'Lastro',
  },
  {
    texto:
      'Vai atrasar? Avise antes. Renegociar cedo custa menos do que esperar a régua de inadimplência alcançar a operação.',
    tema: 'Pontualidade',
  },
  {
    texto:
      'Fracionar uma operação grande em várias pequenas não passa despercebido: o sistema procura exatamente esse padrão.',
    tema: 'Prevenção à lavagem',
  },
  {
    texto:
      'O portal mostra tudo o que existe sobre o seu crédito — se um número daqui não bater com o que te disseram, pergunte à ESC.',
    tema: 'Transparência',
  },
]

/** Dia do ano (1-366) no fuso local — o giro diário das frases. */
function diaDoAno(data: Date): number {
  const inicio = Date.UTC(data.getFullYear(), 0, 1)
  const hoje = Date.UTC(data.getFullYear(), data.getMonth(), data.getDate())
  return Math.floor((hoje - inicio) / 86_400_000) + 1
}

export function fraseDoDia(agora: Date = new Date()): FraseCompliance {
  return FRASES_COMPLIANCE[diaDoAno(agora) % FRASES_COMPLIANCE.length]
}
