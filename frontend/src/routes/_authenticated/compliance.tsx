import { createFileRoute, Link } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RadarIcon, ShieldQuestion } from 'lucide-react'
import { toast } from 'sonner'
import {
  getAtipicidadesApiComplianceAtipicidadesGetOptions,
  getAtipicidadesApiComplianceAtipicidadesGetQueryKey,
  getPendenciasIdentificacaoApiComplianceIdentificacaoPendenciasGetOptions,
  getPendenciasRegistroApiContratosRegistrosPendenciasGetOptions,
  postDetectarApiComplianceAtipicidadesDetectarPostMutation,
} from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { formatarMoeda } from '@/lib/format'
import { rotuloRegraAtipicidade, rotuloSeveridade } from '@/lib/rotulos'
import { StatusOperacaoBadge } from '@/components/status-operacao-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

export const Route = createFileRoute('/_authenticated/compliance')({
  component: CompliancePage,
})

function classeSeveridade(severidade: string): string {
  if (severidade === 'alta') return 'text-destructive'
  if (severidade === 'media') return 'text-warning'
  return 'text-muted-foreground'
}

/**
 * Compliance PLD/FT — a parte que não depende de terceiro.
 *
 * O regime aplicável a uma ESC ainda depende de parecer jurídico, e o canal
 * externo (COAF) é um adaptador que nada preenche hoje. O que já vale:
 * identificação com evidência arquivada, retenção de 5 anos garantida pelo
 * banco, e detecção interna de atipicidade.
 */
function CompliancePage() {
  const queryClient = useQueryClient()
  const pendencias = useQuery(
    getPendenciasIdentificacaoApiComplianceIdentificacaoPendenciasGetOptions(),
  )
  const atipicidades = useQuery(getAtipicidadesApiComplianceAtipicidadesGetOptions())
  const detectar = useMutation(postDetectarApiComplianceAtipicidadesDetectarPostMutation())

  const expostoSemIdentificacao = (pendencias.data ?? []).reduce(
    (soma, p) => soma + Number(p.capital_exposto),
    0,
  )

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-heading text-2xl font-bold tracking-tight">Compliance</h1>
        <Button
          className="ml-auto"
          disabled={detectar.isPending}
          onClick={() =>
            detectar.mutate(
              { body: {} },
              {
                onSuccess: (resultado) => {
                  queryClient.invalidateQueries({
                    queryKey: getAtipicidadesApiComplianceAtipicidadesGetQueryKey(),
                  })
                  toast.success(
                    resultado.novas_ocorrencias === 0
                      ? 'Varredura concluída: nenhuma ocorrência nova.'
                      : `${resultado.novas_ocorrencias} ocorrência(s) nova(s).`,
                  )
                },
              },
            )
          }
        >
          <RadarIcon />
          {detectar.isPending ? 'Varrendo…' : 'Rodar varredura'}
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Identificação pendente</CardTitle>
          <CardDescription>
            Tomadores sem nenhuma evidência arquivada (Lei 9.613/98, art. 10, I). Desde que o gate
            foi ligado, <strong>nenhuma operação destes tomadores consegue ativar</strong> — o
            capital exposto é o que já estava emprestado antes disso.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {pendencias.isPending && <Skeleton className="h-24" />}
          {pendencias.error && (
            <p className="text-sm text-destructive">{mensagemDeErro(pendencias.error)}</p>
          )}
          {pendencias.data && pendencias.data.length === 0 && (
            <p className="text-sm text-muted-foreground">
              Todos os tomadores têm ao menos uma evidência arquivada.
            </p>
          )}
          {pendencias.data && pendencias.data.length > 0 && (
            <>
              <p className="mb-4 flex gap-2 text-sm">
                <ShieldQuestion className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
                <span>
                  <strong>{formatarMoeda(String(expostoSemIdentificacao))}</strong> emprestados a
                  tomadores sem identificação arquivada.
                </span>
              </p>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Tomador</TableHead>
                      <TableHead>CNPJ</TableHead>
                      <TableHead className="text-right">Capital exposto</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pendencias.data.map((p) => (
                      <TableRow key={p.tomador_id}>
                        <TableCell>
                          <Link
                            to="/tomadores/$id"
                            params={{ id: p.tomador_id }}
                            className="text-primary hover:underline"
                          >
                            {p.razao_social}
                          </Link>
                        </TableCell>
                        <TableCell className="font-mono tabular-nums">{p.cnpj}</TableCell>
                        <TableCell className="text-right font-mono tabular-nums">
                          {formatarMoeda(String(p.capital_exposto))}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <RegistroPendente />

      <Card>
        <CardHeader>
          <CardTitle>Atipicidades detectadas</CardTitle>
          <CardDescription>
            Detecção interna sobre os dados que já existem — fracionamento, encerramento antes do
            primeiro vencimento (liquidação antecipada e baixa por prejuízo antecipada) e pagamento
            em excesso. A comunicação a canal externo ainda não está ligada: o regime PLD/COAF de
            uma ESC depende de parecer jurídico. As ocorrências ficam registradas até lá, e são
            imutáveis.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {atipicidades.isPending && <Skeleton className="h-24" />}
          {atipicidades.error && (
            <p className="text-sm text-destructive">{mensagemDeErro(atipicidades.error)}</p>
          )}
          {atipicidades.data && atipicidades.data.length === 0 && (
            <p className="text-sm text-muted-foreground">
              Nenhuma atipicidade registrada. Rode a varredura para analisar os dados atuais.
            </p>
          )}
          {atipicidades.data && atipicidades.data.length > 0 && (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Severidade</TableHead>
                    <TableHead>Regra</TableHead>
                    <TableHead>Tomador</TableHead>
                    <TableHead>Detalhe</TableHead>
                    <TableHead>Detectada em</TableHead>
                    <TableHead>Comunicação</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {atipicidades.data.map((o) => (
                    <TableRow key={o.id}>
                      <TableCell>
                        <Badge variant="outline" className={classeSeveridade(o.severidade)}>
                          {rotuloSeveridade(o.severidade)}
                        </Badge>
                      </TableCell>
                      <TableCell>{rotuloRegraAtipicidade(o.regra)}</TableCell>
                      <TableCell>{o.tomador_razao_social ?? '—'}</TableCell>
                      <TableCell className="text-muted-foreground">{o.detalhe}</TableCell>
                      <TableCell className="tabular-nums">
                        {new Date(o.created_at).toLocaleDateString('pt-BR')}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {o.comunicado_em
                          ? new Date(o.comunicado_em).toLocaleDateString('pt-BR')
                          : 'canal não ligado'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

/**
 * Operações sem registro CONFIRMADO em entidade registradora.
 *
 * Fica ao lado da identificação pendente de propósito: são as duas amarras
 * legais que existem no sistema mas estão DESLIGADAS, ambas por serem
 * decisão de negócio. Juntá-las numa tela só evita que uma delas seja
 * esquecida por estar num canto diferente.
 */
function RegistroPendente() {
  const { data, error, isPending } = useQuery(
    getPendenciasRegistroApiContratosRegistrosPendenciasGetOptions(),
  )

  const exposto = (data ?? []).reduce((soma, p) => soma + Number(p.valor_principal), 0)

  return (
    <Card>
      <CardHeader>
        <CardTitle>Registro em entidade registradora pendente</CardTitle>
        <CardDescription>
          Art. 5º, §3º, da LC 167/2019. O gate está ligado: estas operações{' '}
          <strong>não conseguem ativar</strong> enquanto não houver registro confirmado, com
          protocolo. As que já estão ativas não foram afetadas — o gate roda na transição.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isPending && <Skeleton className="h-24" />}
        {error && <p className="text-sm text-destructive">{mensagemDeErro(error)}</p>}
        {data && data.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Todas as operações têm registro confirmado.
          </p>
        )}
        {data && data.length > 0 && (
          <>
            <p className="mb-4 flex gap-2 text-sm">
              <ShieldQuestion className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
              <span>
                <strong>{formatarMoeda(String(exposto))}</strong> em operações sem registro
                confirmado.
              </span>
            </p>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Tomador</TableHead>
                    <TableHead>Situação</TableHead>
                    <TableHead className="text-right">Principal</TableHead>
                    <TableHead>Referência atual</TableHead>
                    <TableHead>Contrato</TableHead>
                    <TableHead>Registro</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.map((p) => (
                    <TableRow key={p.operacao_id}>
                      <TableCell>
                        <Link
                          to="/operacoes/$id"
                          params={{ id: p.operacao_id }}
                          className="text-primary hover:underline"
                        >
                          {p.tomador_razao_social}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <StatusOperacaoBadge status={p.status} />
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {formatarMoeda(String(p.valor_principal))}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {p.registro_entidade_ref ?? '—'}
                      </TableCell>
                      <TableCell>
                        {p.tem_contrato ? (
                          <Badge variant="outline" className="text-success">
                            Emitido
                          </Badge>
                        ) : (
                          <Badge variant="outline">Não emitido</Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        {p.tem_registro_pendente ? (
                          <Badge variant="outline">Pendente</Badge>
                        ) : (
                          <Badge variant="outline" className="text-destructive">
                            Sem tentativa
                          </Badge>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
