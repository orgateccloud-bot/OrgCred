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
