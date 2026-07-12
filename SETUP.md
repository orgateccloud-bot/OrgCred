# Setup — Desenvolvimento Local

## Pré-requisitos

- Python 3.11+
- PostgreSQL 16+
- `uv` (gerenciador de pacotes)

## Passo 1: Instalar dependências

```bash
uv sync --all-extras
```

Ou, com pip clássico:
```bash
pip install -r pyproject.toml
```

## Passo 2: Configurar banco de dados

```bash
# Criar banco de dados (Linux/Mac)
createdb orgcred_dev

# Ou manualmente (PostgreSQL CLI)
psql -c "CREATE DATABASE orgcred_dev;"
```

Ou, com Docker:
```bash
docker run -d \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=orgcred_dev \
  -p 5432:5432 \
  postgres:16
```

## Passo 3: Criar arquivo .env

```bash
cp .env.example .env
# Editar .env com credenciais reais
```

## Passo 4: Aplicar migrações

**Via Alembic (recomendado):**
```bash
alembic upgrade head
```

Isso aplica as 3 revisões baseline (`0001`–`0003`), que executam o SQL em
`migrations/*.sql` e ficam versionadas na tabela `alembic_version`. Ver
[`alembic/README_MIGRACAO.md`](alembic/README_MIGRACAO.md) para o workflow
de novas migrations.

**Via psql direto** (equivalente, sem tracking de versão — usado por
`docker-entrypoint-initdb.d` e pelos scripts de teste legados):
```bash
psql -d orgcred_dev -f migrations/001_initial_schema.sql
psql -d orgcred_dev -f migrations/002_usuarios_papeis.sql
psql -d orgcred_dev -f migrations/003_hardening_capital.sql
```

## Passo 5: Rodar a API em desenvolvimento

```bash
uvicorn app.main:app --reload
```

Acesse:
- **API:** http://localhost:8000
- **Docs:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
- **Métricas:** http://localhost:8000/metrics
- **Readiness:** http://localhost:8000/health/ready

## Passo 6: Rodar testes

```bash
# Suite pytest completa (requer Postgres real via ORGCRED_TEST_DATABASE_URL
# ou ORGCRED_DATABASE_URL — cria e dropa um banco de teste isolado por sessão)
pytest tests/ -v

# Testes de regressão do capital (bash — Linux/Mac apenas)
./tests/test_capital_invariant.sh

# Teste de concorrência standalone (Linux/Mac apenas — não roda via pytest)
python tests/test_concorrencia.py
```

## Troubleshooting

### "permission denied: ./tests/test_capital_invariant.sh"

```bash
chmod +x tests/test_capital_invariant.sh
```

### "psycopg2.OperationalError: could not connect to server"

Verifique se PostgreSQL está rodando e acessível.

```bash
# Test de conexão
psql -U postgres -d orgcred_dev -c "SELECT 1"
```

### "ORGCRED_DATABASE_URL not found"

```bash
# Copie .env.example para .env
cp .env.example .env
# Edite .env com suas credenciais
```
