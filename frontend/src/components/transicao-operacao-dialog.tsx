import { useState, type ReactNode } from 'react'
import { type UseMutationResult } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { mensagemDeErro } from '@/api/errors'

/**
 * Confirmação genérica para transições da máquina de estados. A validade da
 * transição é decidida pelo trigger do banco (OC003) — este componente só
 * confirma a intenção e traduz o erro se o banco recusar.
 */
export function TransicaoOperacaoDialog({
  operacaoId,
  titulo,
  descricao,
  rotuloBotao,
  rotuloConfirmar,
  variant = 'outline',
  mutation,
  invalidar,
  children,
}: {
  operacaoId: string
  titulo: string
  descricao: string
  rotuloBotao: string
  rotuloConfirmar: string
  variant?: 'outline' | 'destructive' | 'secondary' | 'default'
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mutation: UseMutationResult<any, any, any, any>
  invalidar: () => void
  children?: ReactNode
}) {
  const [open, setOpen] = useState(false)

  function handleConfirmar() {
    mutation.mutate(
      { path: { operacao_id: operacaoId } },
      {
        onSuccess: () => {
          invalidar()
          setOpen(false)
          toast.success(titulo, { description: 'Transição registrada no ledger.' })
        },
        onError: (error: unknown) => {
          toast.error('Transição recusada', { description: mensagemDeErro(error) })
        },
      },
    )
  }

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger asChild>
        <Button size="sm" variant={variant}>
          {rotuloBotao}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{titulo}</AlertDialogTitle>
          <AlertDialogDescription>{descricao}</AlertDialogDescription>
        </AlertDialogHeader>
        {children}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={mutation.isPending}>Cancelar</AlertDialogCancel>
          <AlertDialogAction onClick={handleConfirmar} disabled={mutation.isPending}>
            {mutation.isPending ? 'Processando…' : rotuloConfirmar}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
