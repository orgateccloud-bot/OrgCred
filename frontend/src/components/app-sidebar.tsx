import { Link, useNavigate, useRouterState } from '@tanstack/react-router'
import {
  AlarmClock,
  Banknote,
  Building2,
  Calculator,
  ChevronsUpDown,
  Coins,
  LayoutDashboard,
  Landmark,
  LogOut,
  ScrollText,
  ShieldCheck,
} from 'lucide-react'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar'
import { supabase, supabaseConfigurado } from '@/auth/supabaseClient'
import { useAppStore } from '@/stores/useAppStore'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, exact: true },
  { to: '/operacoes', label: 'Operações', icon: Banknote, exact: false },
  { to: '/tomadores', label: 'Tomadores', icon: Building2, exact: false },
  { to: '/cobranca', label: 'Cobrança', icon: AlarmClock, exact: false },
  { to: '/capital', label: 'Capital social', icon: Coins, exact: false },
  { to: '/fiscal', label: 'Fiscal', icon: Calculator, exact: false },
  { to: '/compliance', label: 'Compliance', icon: ShieldCheck, exact: false },
  { to: '/auditoria', label: 'Auditoria', icon: ScrollText, exact: false },
] as const

export function AppSidebar() {
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const navigate = useNavigate()
  const usuario = useAppStore((state) => state.usuario)

  async function handleLogout() {
    if (supabaseConfigurado) await supabase.auth.signOut()
    navigate({ to: '/login' })
  }

  const iniciais = (usuario?.email ?? '?').slice(0, 2).toUpperCase()

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link to="/">
                <div
                  className="flex aspect-square size-8 items-center justify-center rounded-lg text-white"
                  style={{ background: 'var(--oc-grad-globe)' }}
                >
                  <Landmark className="size-4" />
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-heading font-bold">OrgCred</span>
                  <span className="truncate text-xs text-muted-foreground">ESC · ORGATEC</span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Módulos</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV_ITEMS.map((item) => {
                const ativo = item.exact
                  ? pathname === item.to
                  : pathname === item.to || pathname.startsWith(`${item.to}/`)
                return (
                  <SidebarMenuItem key={item.to}>
                    <SidebarMenuButton asChild isActive={ativo} tooltip={item.label}>
                      <Link to={item.to}>
                        <item.icon />
                        <span>{item.label}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton
                  size="lg"
                  className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
                >
                  <Avatar className="size-8 rounded-lg">
                    <AvatarFallback className="rounded-lg">{iniciais}</AvatarFallback>
                  </Avatar>
                  <div className="grid flex-1 text-left text-sm leading-tight">
                    <span className="truncate font-medium">{usuario?.email ?? 'Sessão ativa'}</span>
                    <span className="truncate text-xs text-muted-foreground">
                      {usuario?.papel ?? 'operador'}
                    </span>
                  </div>
                  <ChevronsUpDown className="ml-auto size-4" />
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
                side="top"
                align="start"
                sideOffset={4}
              >
                <DropdownMenuLabel className="truncate">
                  {usuario?.email ?? 'Sessão ativa'}
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={handleLogout}>
                  <LogOut />
                  Sair
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  )
}
