import {
  AlertTriangle,
  CheckCheck,
  CheckCircle2,
  Circle,
  FileCheck,
  RefreshCw,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { rotuloStatus } from '@/lib/rotulos'
import { cn } from '@/lib/utils'

// Só ícone e cor: o rótulo vem de lib/rotulos, fonte única compartilhada com
// filtros, selects e tabelas — antes o texto vivia duplicado aqui.
const STATUS_CONFIG: Record<string, { icon: LucideIcon; className: string }> = {
  proposta: { icon: Circle, className: 'text-muted-foreground' },
  registrada: { icon: FileCheck, className: 'text-foreground' },
  ativa: { icon: CheckCircle2, className: 'text-success' },
  liquidada: { icon: CheckCheck, className: 'text-muted-foreground' },
  inadimplente: { icon: AlertTriangle, className: 'text-destructive' },
  renegociada: { icon: RefreshCw, className: 'text-warning' },
  cancelada: { icon: XCircle, className: 'text-destructive' },
}

export function StatusOperacaoBadge({ status }: { status: string }) {
  const config = STATUS_CONFIG[status] ?? { icon: Circle, className: 'text-muted-foreground' }
  const Icon = config.icon

  return (
    <Badge variant="outline" className={cn('gap-1', config.className)}>
      <Icon />
      {rotuloStatus(status)}
    </Badge>
  )
}
