import { useState } from 'react'
import { BaixarPrejuizoDialog } from '@/components/operacoes/baixar-prejuizo-dialog'
import { LiquidarOperacaoDialog } from '@/components/operacoes/liquidar-operacao-dialog'

/**
 * As duas formas de encerrar uma operação em cobrança, lado a lado.
 *
 * Ficam no mesmo componente porque uma é a saída da outra: quando a
 * liquidação é recusada por OC022 (parcelas sem lastro), o painel de erro
 * oferece a baixa por prejuízo — e alguém precisa segurar o estado dos dois
 * diálogos para fechar um e abrir o outro sem o operador se perder.
 *
 * Disponível só em `ativa` e `inadimplente`: são os estados de onde o
 * backend aceita ambas as transições. Nos demais, nada disto é renderizado.
 */
export function AcoesEncerramentoOperacao({
  operacaoId,
  valorPrincipal,
  onSucesso,
}: {
  operacaoId: string
  valorPrincipal: string
  onSucesso: () => void
}) {
  const [liquidarAberto, setLiquidarAberto] = useState(false)
  const [prejuizoAberto, setPrejuizoAberto] = useState(false)

  return (
    <>
      <LiquidarOperacaoDialog
        operacaoId={operacaoId}
        valorPrincipal={valorPrincipal}
        open={liquidarAberto}
        onOpenChange={setLiquidarAberto}
        onSucesso={onSucesso}
        onEscolherPrejuizo={() => {
          setLiquidarAberto(false)
          setPrejuizoAberto(true)
        }}
      />
      <BaixarPrejuizoDialog
        operacaoId={operacaoId}
        valorPrincipal={valorPrincipal}
        open={prejuizoAberto}
        onOpenChange={setPrejuizoAberto}
        onSucesso={onSucesso}
      />
    </>
  )
}
