import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, Clock } from 'lucide-react'
import { getConvitesPortalApiTomadoresTomadorIdPortalConvitesGetOptions } from '@/api/generated/@tanstack/react-query.gen'
import { formatarDataIso } from '@/components/identificacao/mensagens'
import { ConvidarPortalDialog } from '@/components/tomadores/convidar-portal-dialog'
import { mensagemDeErroDeConvite } from '@/components/tomadores/mensagens'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useAppStore } from '@/stores/useAppStore'

/**
 * Acesso ao portal — a trilha de convites da empresa (migration 031).
 *
 * Quem recebeu a janela, quando, e se já entrou. A lista é a própria tabela
 * `convite_portal`, append-only por trigger (OC027): o que aparece aqui é
 * prova de conformidade, não cadastro editável — por isso não há botão de
 * apagar nem de reenviar sobre a linha.
 *
 * O botão Convidar só aparece para admin: dar a um CNPJ externo uma janela
 * para os dados de crédito dele é ato de chave, como a autorização de
 * município. O backend barra de qualquer forma (403); esconder evita oferecer
 * um botão que só responde erro — o mesmo racional da casca do portal.
 */
export function AcessoPortal({ tomadorId }: { tomadorId: string }) {
  const papel = useAppStore((state) => state.usuario?.papel)
  const convites = useQuery(
    getConvitesPortalApiTomadoresTomadorIdPortalConvitesGetOptions({
      path: { tomador_id: tomadorId },
    }),
  )

  // Backend mais velho que o bundle não conhece esta rota e o fallback do
  // SPA devolve o index.html com HTTP 200 — o cliente gerado entrega a
  // STRING como `data`, e `.map` nela derrubava a FICHA INTEIRA (pego pelo
  // E2E de identificação rodando contra a API errada). Dado que não é lista
  // vira erro exibível; o resto da ficha continua de pé.
  const lista = Array.isArray(convites.data) ? convites.data : null
  const respostaInvalida = convites.data !== undefined && lista === null

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div className="space-y-1.5">
          <CardTitle>Acesso ao portal</CardTitle>
          <CardDescription>
            Logins da empresa no portal do tomador — leitura das próprias operações, agenda e
            contrato. O convidado define a senha pelo link do e-mail; a trilha de quem convidou é
            permanente (OC027).
          </CardDescription>
        </div>
        {papel === 'admin' && <ConvidarPortalDialog tomadorId={tomadorId} />}
      </CardHeader>
      <CardContent>
        {convites.isPending && <Skeleton className="h-16" />}

        {(convites.error || respostaInvalida) && (
          <p role="alert" className="text-sm text-destructive">
            {convites.error
              ? mensagemDeErroDeConvite(convites.error)
              : 'A trilha de convites não pôde ser carregada — o servidor respondeu num formato inesperado. Recarregue a página; persistindo, avise quem administra o ambiente.'}
          </p>
        )}

        {lista?.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Nenhum convite enviado. A empresa ainda não tem login no portal
            {papel === 'admin' ? ' — use Convidar para criar o primeiro.' : '.'}
          </p>
        )}

        {lista && lista.length > 0 && (
          <ul className="divide-y divide-border">
            {lista.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{c.email}</p>
                  <p className="text-xs text-muted-foreground">
                    Convidado em {formatarDataIso(c.criado_em)}
                    {c.convidado_por_nome ? ` por ${c.convidado_por_nome}` : ''}
                  </p>
                </div>
                {c.aceito_em ? (
                  <span className="inline-flex items-center gap-1.5 text-sm text-success">
                    <CheckCircle2 className="size-4" aria-hidden />
                    Entrou em {formatarDataIso(c.aceito_em)}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
                    <Clock className="size-4" aria-hidden />
                    Aguardando primeiro acesso
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
