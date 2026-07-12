# Alembic — workflow de migrations do OrgCred

## Decisão de design: SQL raw como fonte de verdade, Alembic como orquestrador

As revisões `0001`–`0003` **não reescrevem o schema em Python** (`op.create_table(...)`).
Elas leem e executam os arquivos SQL originais em `migrations/*.sql` via
`op.execute(path.read_text())`.

**Por quê:** o núcleo do OrgCred é lógica de negócio em PL/pgSQL (triggers com
`pg_advisory_xact_lock`, SQLSTATEs customizados OC001–OC005) — não há um
equivalente direto e legível em `op.execute_batch()` do Alembic para
`CREATE OR REPLACE FUNCTION ... $$ ... $$ LANGUAGE plpgsql`, e traduzir isso
para chamadas Python só criaria uma segunda fonte de verdade para revisar a
cada mudança de trigger. Os arquivos `.sql` continuam sendo o artefato que
`tests/conftest.py`, `docker-compose.yml` (via
`docker-entrypoint-initdb.d`) e os scripts de regressão aplicam diretamente —
Alembic aqui só adiciona **rastreamento de versão** (`alembic_version`) e o
comando `alembic upgrade`/`downgrade` como interface única de operação.

## Workflow para novas migrations

A partir da `0004` em diante, **não é mais obrigatório** seguir o padrão
"ler arquivo .sql" — para mudanças de schema simples (nova coluna, novo
índice), use `op.add_column()`/`op.create_index()` normalmente:

```bash
# Gera o esqueleto de uma nova revisão
alembic revision -m "adicionar coluna x em operacao_credito"
# Edita o arquivo gerado em alembic/versions/
```

Para mudanças que envolvem função/trigger PL/pgSQL (o caso mais comum aqui,
dado o princípio "o banco decide"), siga o padrão das revisões baseline:
escreva o SQL num arquivo em `migrations/NNN_descricao.sql` **e** crie a
revisão Alembic correspondente que o executa via `op.execute()`. Isso mantém
os dois mundos sincronizados: `migrations/*.sql` para quem aplica manualmente
(scripts de regressão, `docker-entrypoint-initdb.d`), Alembic para o
histórico de versão e rollback ordenado.

## Comandos

```bash
# Ver a revisão atual do banco
alembic current

# Ver o histórico completo
alembic history --verbose

# Aplicar todas as migrations pendentes
alembic upgrade head

# Reverter a última migration
alembic downgrade -1

# Reverter tudo (cuidado: apaga o schema)
alembic downgrade base
```

## Configuração

`alembic/env.py` lê a URL de conexão de `app.core.config.settings`
(`ORGCRED_DATABASE_URL`) — não há URL duplicada em `alembic.ini`.

## Rollback de downgrade em produção

O `downgrade()` da revisão `0003` **não** reverte automaticamente o corpo de
`fn_check_teto_capital()` para a versão pré-hardening (isso exigiria
reaplicar manualmente a função de `0001`, o que não é recomendado fora de
ambiente de teste — a versão pré-hardening tem a race condition F1
documentada em `REVISAO_2026-07-11.md`). Downgrade de `0003` remove apenas
o trigger de proteção de redução de capital (`OC005`).
