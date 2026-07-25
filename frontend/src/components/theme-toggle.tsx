import { Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAppStore } from '@/stores/useAppStore'

export function ThemeToggle() {
  const tema = useAppStore((state) => state.tema)
  const setTema = useAppStore((state) => state.setTema)

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={tema === 'dark' ? 'Mudar para tema claro' : 'Mudar para tema escuro'}
      onClick={() => setTema(tema === 'dark' ? 'light' : 'dark')}
    >
      {tema === 'dark' ? <Sun /> : <Moon />}
    </Button>
  )
}
