/**
 * Barra de progresso da quitação: pagas / total.
 *
 * Verde de sucesso, e não ciano da marca, porque parcela paga é ESTADO com
 * significado (dívida diminuindo), não identidade visual — a mesma separação
 * marca vs. semântica dos badges de status.
 */
export function ProgressoParcelas({ pagas, total }: { pagas: number; total: number }) {
  const pct = total > 0 ? Math.round((pagas / total) * 100) : 0

  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={pagas}
      aria-label={`${pagas} de ${total} parcelas pagas`}
      className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
    >
      <div className="h-full rounded-full bg-success" style={{ width: `${pct}%` }} />
    </div>
  )
}
