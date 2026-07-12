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

```bash
psql -d orgcred_dev -f migrations/001_initial_schema.sql
psql -d orgcred_dev -f migrations/002_usuarios_papeis.sql
psql -d orgcred_dev -f migrations/003_hardening_capital.sql
```

Ou, com Python (futuramente Alembic):
```bash
python -c "from app.db import engine; from app.models import Base; Base.metadata.create_all(engine)"
```

## Passo 5: Rodar a API em desenvolvimento

```bash
uvicorn app.main:app --reload
```

Acesse:
- **API:** http://localhost:8000
- **Docs:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

## Passo 6: Rodar testes (Linux/Mac)

```bash
# Testes de regressão do capital (bash)
./tests/test_capital_invariant.sh

# Teste de concorrência (Python)
python tests/test_concorrencia.py

# Suite pytest (quando implementado)
pytest tests/ -v --cov=app
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
