# Arquivo — duplicatas do snapshot inicial

**Data de arquivamento:** 2026-07-12

## O que é isto

Durante a reconstituição da árvore de pacote na Fase 0 (`migrations/`, `tests/`),
os arquivos originais soltos na raiz do projeto foram **copiados** para seus
lugares corretos, mas as cópias na raiz não foram removidas — ficaram como
duplicatas esquecidas, nunca commitadas.

| Arquivo aqui | Cópia oficial (versionada) |
|---|---|
| `003_hardening_capital.sql` | [`migrations/003_hardening_capital.sql`](../migrations/003_hardening_capital.sql) |
| `test_capital_invariant.sh` | [`tests/test_capital_invariant.sh`](../tests/test_capital_invariant.sh) |
| `test_concorrencia.py` | [`tests/test_concorrencia.py`](../tests/test_concorrencia.py) — *nota: a cópia oficial recebeu formatação `ruff format` na Fase 1; este arquivo aqui é a versão anterior, sem formatação* |

## Plano de rollback

Nenhuma lógica foi alterada — são cópias texto-idênticas (exceto formatação em
`test_concorrencia.py`). Se algo parecer ter sido perdido na reconstituição:

```bash
diff _legado/003_hardening_capital.sql migrations/003_hardening_capital.sql
diff _legado/test_capital_invariant.sh tests/test_capital_invariant.sh
diff _legado/test_concorrencia.py tests/test_concorrencia.py
```

Se os diffs confirmarem que são redundantes, esta pasta pode ser removida com
segurança em uma limpeza futura.

---

## Originais pré-modernização (arquivados em 2026-07-12, sessão de Fases 0-7)

`capital_engine.py.pre-modernizacao`, `config.py.pre-modernizacao` e
`operacoes.py.pre-modernizacao` são os três arquivos Python que existiam na
raiz do projeto **antes** da reconstituição da Fase 0 — a versão que a
revisão de 2026-07-11 (`REVISAO_2026-07-11.md`) analisou e testou pela
primeira vez contra Postgres real.

Eles **divergem** das versões atuais em `app/`:
- `capital_engine.py` → [`app/capital_engine.py`](../app/capital_engine.py):
  ganhou hierarquia de exceções (`app/core/exceptions.py`), mapeamento de
  OC005, métricas Prometheus, propagação de `usuario_id` (migration 004).
- `config.py` → [`app/core/config.py`](../app/core/config.py): migrou de
  `os.environ` manual para `pydantic-settings`, com validação no startup em
  vez de no import do módulo.
- `operacoes.py` → [`app/routers/operacoes.py`](../app/routers/operacoes.py):
  ganhou autenticação JWT obrigatória, resposta de erro estruturada com
  código SQLSTATE, rate limiting.

Mantidos aqui só como referência histórica do estado antes da modernização
— não são a fonte de verdade e não devem ser reintroduzidos na raiz.

---

# Arquivo — `alerts.py`, alertas por SMTP nunca integrados

**Data de arquivamento:** 2026-07-31

## O que e isto

`app/core/alerts.py` implementava dois alertas por email (SMTP): capital
disponivel abaixo de 20% do total, e rajada de 5+ bloqueios em janela curta.

Foi escrito na Fase 3 da modernizacao e **nunca foi chamado**: zero
referencias em todo o projeto, 0% de cobertura em 37 statements. O
mapeamento de 2026-07-31 o identificou como o unico modulo orfao do
backend.

## Por que foi arquivado em vez de integrado

Tres razoes, em ordem de peso:

1. **Duplica sinal que ja existe.** `app/core/metrics.py` ja exporta para o
   Prometheus exatamente os dois sinais que este modulo tentava detectar:
   `orgcred_capital_disponivel` (Gauge) e
   `orgcred_operacoes_bloqueadas_total{sqlstate}` (Counter). Alerta sobre
   esses valores pertence a regra de alerting do Prometheus/Alertmanager,
   que le as metricas ja publicadas — nao a uma segunda implementacao
   dentro da aplicacao.

2. **O desenho e perigoso no caminho que ele monitoraria.** O ponto natural
   de chamada de `checar_capital_baixo` seria logo apos a ativacao de uma
   operacao — que roda sob `pg_advisory_xact_lock`, o lock global que
   serializa TODAS as ativacoes de credito do sistema. Um SMTP sincrono ali
   significa que um servidor de email lento segura a transacao que bloqueia
   todo o resto. O modulo captura excecoes, entao nao quebraria, mas
   atrasaria.

3. **O proprio arquivo dizia isso.** Seu docstring ja registrava: "Producao
   real deve integrar com um canal de alerta ja monitorado (Slack,
   PagerDuty); este modulo e o ponto de extensao."

## Plano de rollback

O arquivo esta integro, sem nenhuma alteracao — basta
`git mv _legado/alerts.py.nunca-integrado app/core/alerts.py` para
restaura-lo. Nenhum import precisa ser reparado, porque nada o importava.

## O que fazer no lugar

Configurar regra de alerta no Prometheus sobre as metricas ja exportadas
em `GET /metrics`. Se for necessario alerta dentro da aplicacao no futuro,
faze-lo **fora da transacao de negocio** — a fila sobre Postgres proposta
no Blueprint V2 (Procrastinate) e o lugar correto.
