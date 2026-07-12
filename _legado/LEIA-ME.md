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
