import { useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { UserPlus } from 'lucide-react'
import { toast } from 'sonner'
import {
  getConvitesPortalApiTomadoresTomadorIdPortalConvitesGetQueryKey,
  postConvidarPortalApiTomadoresTomadorIdPortalConvitesPostMutation,
} from '@/api/generated/@tanstack/react-query.gen'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { mensagemDeErroDeConvite } from '@/components/tomadores/mensagens'

/**
 * Convida um e-mail para o portal do tomador.
 *
 * O diálogo pede só e-mail e nome: a senha é definida pelo próprio convidado,
 * no link que ele recebe (rota /definir-senha) — ela nunca passa pela ESC.
 * Quem pode convidar é admin (o backend barra com 403 de qualquer forma; o
 * pai deste componente nem o exibe para operador).
 */
export function ConvidarPortalDialog({ tomadorId }: { tomadorId: string }) {
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [nome, setNome] = useState('')
  const queryClient = useQueryClient()
  const mutation = useMutation(postConvidarPortalApiTomadoresTomadorIdPortalConvitesPostMutation())

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate(
      { path: { tomador_id: tomadorId }, body: { email, nome } },
      {
        onSuccess: (convite) => {
          queryClient.invalidateQueries({
            queryKey: getConvitesPortalApiTomadoresTomadorIdPortalConvitesGetQueryKey({
              path: { tomador_id: tomadorId },
            }),
          })
          alterarAberto(false)
          toast.success('Convite enviado', {
            description: `${convite.email} vai receber o link para definir a senha.`,
          })
        },
      },
    )
  }

  // Um único caminho de fechamento, como no ArquivarDocumentoDialog: limpar
  // só no onOpenChange deixaria erro e campos vivos ao reabrir via Cancelar.
  function alterarAberto(aberto: boolean) {
    setOpen(aberto)
    if (!aberto) {
      mutation.reset()
      setEmail('')
      setNome('')
    }
  }

  return (
    <Dialog open={open} onOpenChange={alterarAberto}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <UserPlus />
          Convidar
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Convidar para o portal</DialogTitle>
          <DialogDescription>
            O convidado recebe por e-mail um link para definir a própria senha e passa a ver{' '}
            <strong>somente os dados desta empresa</strong>: operações, agenda de parcelas e a
            impressão digital do contrato. O portal é leitura — nenhuma ação sobre o crédito.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="convite-nome">Nome</Label>
            <Input
              id="convite-nome"
              autoComplete="off"
              placeholder="Quem recebe o acesso (ex.: sócio, contador)"
              required
              value={nome}
              onChange={(e) => setNome(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="convite-email">E-mail</Label>
            <Input
              id="convite-email"
              type="email"
              autoComplete="off"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          {mutation.isError && (
            <p role="alert" className="text-sm text-destructive">
              {mensagemDeErroDeConvite(mutation.error)}
            </p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => alterarAberto(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={!email || !nome || mutation.isPending}>
              {mutation.isPending ? 'Enviando…' : 'Enviar convite'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
