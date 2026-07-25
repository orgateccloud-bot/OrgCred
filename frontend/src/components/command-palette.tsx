import { useEffect, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import {
  Banknote,
  Building2,
  Coins,
  LayoutDashboard,
  ScrollText,
} from 'lucide-react'
import {
  getOperacoesApiOperacoesGetOptions,
  getTomadoresApiTomadoresGetOptions,
} from '@/api/generated/@tanstack/react-query.gen'
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'

const TELAS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/operacoes', label: 'Operações', icon: Banknote },
  { to: '/tomadores', label: 'Tomadores', icon: Building2 },
  { to: '/capital', label: 'Capital social', icon: Coins },
  { to: '/auditoria', label: 'Auditoria', icon: ScrollText },
] as const

/**
 * Paleta de comandos global (⌘K / Ctrl+K). Só busca operações/tomadores
 * quando aberta (enabled: open) para não pagar as queries no boot.
 */
export function CommandPalette() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()

  const operacoes = useQuery({ ...getOperacoesApiOperacoesGetOptions(), enabled: open })
  const tomadores = useQuery({ ...getTomadoresApiTomadoresGetOptions(), enabled: open })

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen((v) => !v)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  function ir(to: string, params?: Record<string, string>) {
    setOpen(false)
    // navigate aceita rotas tipadas; aqui as strings são conhecidas em runtime.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    navigate({ to, params } as any)
  }

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Buscar telas, operações, tomadores…" />
      <CommandList>
        <CommandEmpty>Nenhum resultado.</CommandEmpty>
        <CommandGroup heading="Telas">
          {TELAS.map((t) => (
            <CommandItem key={t.to} value={`tela ${t.label}`} onSelect={() => ir(t.to)}>
              <t.icon />
              {t.label}
            </CommandItem>
          ))}
        </CommandGroup>

        {(operacoes.data?.length ?? 0) > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Operações">
              {operacoes.data!.slice(0, 8).map((op) => (
                <CommandItem
                  key={op.id}
                  value={`operacao ${op.tomador_razao_social} ${op.status}`}
                  onSelect={() => ir('/operacoes/$id', { id: op.id })}
                >
                  <Banknote />
                  {op.tomador_razao_social}
                  <span className="ml-auto text-xs text-muted-foreground">{op.status}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}

        {(tomadores.data?.length ?? 0) > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Tomadores">
              {tomadores.data!.slice(0, 8).map((t) => (
                <CommandItem
                  key={t.id}
                  value={`tomador ${t.razao_social} ${t.cnpj}`}
                  onSelect={() => ir('/tomadores/$id', { id: t.id })}
                >
                  <Building2 />
                  {t.razao_social}
                  <span className="ml-auto text-xs text-muted-foreground">
                    {t.municipio}/{t.uf}
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
      </CommandList>
    </CommandDialog>
  )
}
