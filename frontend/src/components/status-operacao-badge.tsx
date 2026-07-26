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
import { cn } from '@/lib/utils'

const STATUS_CONFIG: Record<string, { label: string; icon: LucideIcon; className: string }> = {
  proposta: { label: 'Proposta', icon: Circle, className: 'text-muted-foreground' },
  registrada: { label: 'Registrada', icon: FileCheck, className: 'text-foreground' },
  ativa: {
    label: 'Ativa',
    icon: CheckCircle2,
    className: 'text-success',
  },
  liquidada: { label: 'Liquidada', icon: CheckCheck, className: 'text-muted-foreground' },
  inadimplente: {
    label: 'Inadimplente',
    icon: AlertTriangle,
    className: 'text-destructive',
  },
  renegociada: {
    label: 'Renegociada',
    icon: RefreshCw,
    className: 'text-warning',
  },
  cancelada: { label: 'Cancelada', icon: XCircle, className: 'text-destructive' },
}

export function StatusOperacaoBadge({ status }: { status: string }) {
  const config = STATUS_CONFIG[status] ?? {
    label: status,
    icon: Circle,
    className: 'text-muted-foreground',
  }
  const Icon = config.icon

  return (
    <Badge variant="outline" className={cn('gap-1', config.className)}>
      <Icon />
      {config.label}
    </Badge>
  )
}
