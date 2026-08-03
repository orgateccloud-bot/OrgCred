import type { Meta, StoryObj } from '@storybook/tanstack-react'
import { StatusOperacaoBadge } from './status-operacao-badge'

const meta = {
  title: 'domain/StatusOperacaoBadge',
  component: StatusOperacaoBadge,
  parameters: { layout: 'centered' },
} satisfies Meta<typeof StatusOperacaoBadge>

export default meta
type Story = StoryObj<typeof meta>

export const Proposta: Story = { args: { status: 'proposta' } }
export const Registrada: Story = { args: { status: 'registrada' } }
export const Ativa: Story = { args: { status: 'ativa' } }
export const Liquidada: Story = { args: { status: 'liquidada' } }
export const Inadimplente: Story = { args: { status: 'inadimplente' } }
export const Renegociada: Story = { args: { status: 'renegociada' } }
export const Cancelada: Story = { args: { status: 'cancelada' } }

export const TodosOsStatus: Story = {
  args: { status: 'ativa' },
  render: () => (
    <div className="flex flex-wrap gap-2">
      {[
        'proposta',
        'registrada',
        'ativa',
        'liquidada',
        'inadimplente',
        'renegociada',
        'cancelada',
      ].map((status) => (
        <StatusOperacaoBadge key={status} status={status} />
      ))}
    </div>
  ),
}
