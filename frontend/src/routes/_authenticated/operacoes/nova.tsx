import { useState, type FormEvent } from 'react'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { toast } from 'sonner'
import {
  getOperacoesApiOperacoesGetQueryKey,
  getTomadoresApiTomadoresGetOptions,
  postCriarOperacaoApiOperacoesPostMutation,
} from '@/api/generated/@tanstack/react-query.gen'
import { mensagemDeErro } from '@/api/errors'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export const Route = createFileRoute('/_authenticated/operacoes/nova')({
  component: NovaOperacaoPage,
})

function NovaOperacaoPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const tomadores = useQuery(getTomadoresApiTomadoresGetOptions())
  const mutation = useMutation(postCriarOperacaoApiOperacoesPostMutation())

  const [tomadorId, setTomadorId] = useState('')
  const [tipo, setTipo] = useState<'emprestimo' | 'financiamento'>('emprestimo')
  const [valor, setValor] = useState('')
  const [taxa, setTaxa] = useState('')
  const [sistema, setSistema] = useState<'PRICE' | 'SAC'>('PRICE')
  const [parcelas, setParcelas] = useState('')

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate(
      {
        body: {
          tomador_id: tomadorId,
          tipo,
          valor_principal: valor,
          taxa_juros_mensal: taxa,
          sistema_amortizacao: sistema,
          numero_parcelas: Number(parcelas),
        },
      },
      {
        onSuccess: (data) => {
          queryClient.invalidateQueries({ queryKey: getOperacoesApiOperacoesGetQueryKey() })
          toast.success('Proposta criada', {
            description: 'A operação nasce como proposta — registre-a para poder ativar.',
          })
          navigate({ to: '/operacoes/$id', params: { id: data.id } })
        },
      },
    )
  }

  const formValido = tomadorId && Number(valor) > 0 && Number(taxa) >= 0 && Number(parcelas) > 0

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center gap-3">
        <Button asChild variant="ghost" size="icon" aria-label="Voltar para a lista">
          <Link to="/operacoes">
            <ArrowLeft />
          </Link>
        </Button>
        <h1 className="text-2xl font-semibold">Nova operação</h1>
      </div>

      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>Condições da proposta</CardTitle>
          <CardDescription>
            A operação é criada como <strong>proposta</strong> e não compromete capital. Teto
            (OC001) e gate geográfico (OC002) são validados pelo banco na ativação.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="tomador">Tomador</Label>
              <Select value={tomadorId} onValueChange={setTomadorId}>
                <SelectTrigger id="tomador" className="w-full">
                  <SelectValue
                    placeholder={
                      tomadores.isPending
                        ? 'Carregando tomadores…'
                        : (tomadores.data?.length ?? 0) === 0
                          ? 'Nenhum tomador cadastrado'
                          : 'Selecione o tomador'
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {(tomadores.data ?? []).map((t) => (
                    <SelectItem key={t.id} value={t.id}>
                      {t.razao_social} — {t.municipio}/{t.uf}
                      {!t.municipio_autorizado && ' (município não autorizado)'}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {(tomadores.data?.length ?? 0) === 0 && !tomadores.isPending && (
                <p className="text-xs text-muted-foreground">
                  <Link to="/tomadores" className="text-primary hover:underline">
                    Cadastre um tomador
                  </Link>{' '}
                  antes de criar a operação.
                </p>
              )}
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="tipo">Tipo</Label>
                <Select value={tipo} onValueChange={(v) => setTipo(v as typeof tipo)}>
                  <SelectTrigger id="tipo" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="emprestimo">Empréstimo</SelectItem>
                    <SelectItem value="financiamento">Financiamento</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="valor">Valor principal (R$)</Label>
                <Input
                  id="valor"
                  type="number"
                  min="0.01"
                  step="0.01"
                  required
                  value={valor}
                  onChange={(event) => setValor(event.target.value)}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="taxa">Taxa de juros (% a.m.)</Label>
                <Input
                  id="taxa"
                  type="number"
                  min="0"
                  step="0.01"
                  required
                  value={taxa}
                  onChange={(event) => setTaxa(event.target.value)}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="parcelas">Número de parcelas</Label>
                <Input
                  id="parcelas"
                  type="number"
                  min="1"
                  step="1"
                  required
                  value={parcelas}
                  onChange={(event) => setParcelas(event.target.value)}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="sistema">Sistema de amortização</Label>
                <Select value={sistema} onValueChange={(v) => setSistema(v as typeof sistema)}>
                  <SelectTrigger id="sistema" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="PRICE">PRICE</SelectItem>
                    <SelectItem value="SAC">SAC</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {mutation.isError && (
              <p className="text-sm text-destructive">{mensagemDeErro(mutation.error)}</p>
            )}

            <div className="flex justify-end gap-2">
              <Button asChild variant="outline">
                <Link to="/operacoes">Cancelar</Link>
              </Button>
              <Button type="submit" disabled={!formValido || mutation.isPending}>
                {mutation.isPending ? 'Criando…' : 'Criar proposta'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
