import { Ban } from 'lucide-react'
import { formatarMoeda } from '@/lib/format'

/**
 * Faixa permanente no topo da operação baixada como prejuízo.
 *
 * Quem abre a tela depois do ato precisa entender, sem clicar em nada, que
 * este encerramento NÃO é uma quitação: a cobrança acabou, mas o dinheiro
 * não voltou e o teto do Art. 5º (LC 167/2019) segue ocupado por este valor.
 *
 * `role="status"` porque o aviso descreve o estado da página e chega junto
 * com os dados da operação (carregamento assíncrono): sem a região viva, um
 * leitor de tela não recebe nada quando o conteúdo aparece.
 */
export function AvisoBaixaPrejuizo({ valorPrincipal }: { valorPrincipal: string }) {
  return (
    <div
      role="status"
      className="flex gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4"
    >
      <Ban className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden />
      <div className="space-y-1">
        <p className="font-medium text-destructive">Baixada como prejuízo — não é uma quitação</p>
        <p className="text-sm text-muted-foreground">
          A cobrança foi encerrada sem pagamento. Os{' '}
          <span className="font-mono tabular-nums">{formatarMoeda(valorPrincipal)}</span> não
          voltaram para o capital disponível: seguem comprometidos, e o teto operacional encolheu de
          forma permanente. Recuperar essa capacidade exige aporte de capital — nenhuma baixa
          contábil devolve o que foi perdido.
        </p>
        <p className="text-sm text-muted-foreground">
          Estado terminal: não há retorno para ativa, nem caminho daqui para liquidada.
        </p>
      </div>
    </div>
  )
}
