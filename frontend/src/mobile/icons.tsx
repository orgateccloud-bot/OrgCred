import {
  AlarmClock,
  AlertOctagon,
  AlertTriangle,
  ArrowDownLeft,
  ArrowRight,
  Bell,
  Building2,
  CalendarClock,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  FileCheck2,
  FileText,
  Home,
  Inbox,
  Landmark,
  LogOut,
  MapPin,
  MoreHorizontal,
  Plus,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  UserPlus,
  Users,
  X,
  type LucideIcon,
} from 'lucide-react'

/**
 * Ponte entre os nomes de ícone do design (`data-lucide="bell"`) e os
 * componentes do `lucide-react`. O design carregava o lucide UMD e resolvia por
 * nome; aqui resolvemos por um mapa tipado, sem runtime extra.
 */
const MAPA = {
  'alarm-clock': AlarmClock,
  'alert-octagon': AlertOctagon,
  'alert-triangle': AlertTriangle,
  'arrow-down-left': ArrowDownLeft,
  'arrow-right': ArrowRight,
  bell: Bell,
  'building-2': Building2,
  'calendar-clock': CalendarClock,
  'check-circle-2': CheckCircle2,
  'chevron-left': ChevronLeft,
  'chevron-right': ChevronRight,
  'file-check-2': FileCheck2,
  'file-text': FileText,
  home: Home,
  inbox: Inbox,
  landmark: Landmark,
  'log-out': LogOut,
  'map-pin': MapPin,
  'more-horizontal': MoreHorizontal,
  plus: Plus,
  'shield-alert': ShieldAlert,
  'shield-check': ShieldCheck,
  'shield-x': ShieldX,
  'user-plus': UserPlus,
  users: Users,
  x: X,
} satisfies Record<string, LucideIcon>

export type MobileIconName = keyof typeof MAPA

export function Icon({
  name,
  size = 16,
  color = 'currentColor',
  className,
  strokeWidth = 2,
}: {
  name: MobileIconName
  size?: number
  color?: string
  className?: string
  strokeWidth?: number
}) {
  const Cmp = MAPA[name]
  return (
    <Cmp size={size} color={color} strokeWidth={strokeWidth} className={className} aria-hidden />
  )
}
