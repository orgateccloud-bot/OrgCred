import type { Meta, StoryObj } from '@storybook/tanstack-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from './dialog'
import { Button } from './button'

const meta = {
  title: 'ui/Dialog',
  component: Dialog,
  parameters: { layout: 'centered' },
} satisfies Meta<typeof Dialog>

export default meta
type Story = StoryObj<typeof meta>

export const ConfirmacaoDeAcaoIrreversivel: Story = {
  render: () => (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="secondary">Ativar</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Confirmar ativação de operação</DialogTitle>
          <DialogDescription>
            Esta ação é <strong>irreversível</strong>: uma vez ativada, a operação passa a
            comprometer o capital disponível.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline">Cancelar</Button>
          <Button>Confirmar ativação</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  ),
}
