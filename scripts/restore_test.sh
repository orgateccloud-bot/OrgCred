#!/usr/bin/env bash
# OrgCred — teste de restauração de backup (roda UMA VEZ POR MÊS).
#
# Restaura o backup mais recente em um banco temporário e valida que o
# ledger (capital_ledger) e a view v_capital_atual respondem corretamente.
# Um backup nunca testado não é um backup confiável.
#
# Uso: ORGCRED_DATABASE_URL=postgresql://... ./scripts/restore_test.sh [dir_backups]
#
# CHAMADO por `python -m app.rotinas` na primeira execução de cada mês — a
# regra de "uma vez por mês" vive no Python, testada, e não num dia fixo de
# agenda de painel. Ver app/rotinas.py e docs/OPERACAO.md.
set -euo pipefail

BACKUP_DIR="${1:-./backups}"
TEST_DB="orgcred_restore_test_$(date +%s)"

if [ -z "${ORGCRED_DATABASE_URL:-}" ]; then
    echo "ERRO: ORGCRED_DATABASE_URL não definida." >&2
    exit 1
fi

# Mesma tradução do backup.sh: SQLAlchemy ('postgresql+psycopg://') -> libpq.
PG_URL=$(printf '%s' "$ORGCRED_DATABASE_URL" | sed -E 's#^(postgres(ql)?)\+[a-z0-9_]+://#\1://#')

# `createdb` e `psql -d NOME` sem URL usam PGHOST/PGPORT/PGUSER — que num
# contêiner de cron não existem. O script tentava falar com um Postgres LOCAL
# que não está lá, e o erro só apareceria no dia em que alguém finalmente o
# chamasse. As duas URLs abaixo derivam da MESMA variável que a aplicação usa,
# então o teste restaura no servidor onde o dado realmente vive.
#
# A query string (`?sslmode=require`, típica de Postgres gerenciado) é separada
# antes de trocar o nome do banco e recolada depois: sem isso, `${URL%/*}`
# comeria pedaço dela e a conexão sairia sem TLS — ou nem sairia.
QUERY=""
BASE="$PG_URL"
case "$PG_URL" in
    *\?*)
        QUERY="?${PG_URL#*\?}"
        BASE="${PG_URL%%\?*}"
        ;;
esac
ADMIN_URL="${BASE%/*}/postgres${QUERY}"
TEST_URL="${BASE%/*}/${TEST_DB}${QUERY}"

# `|| true` no fim: com `set -e`, um `ls` que não casa nada sai != 0 e mataria
# o script AQUI, antes da mensagem de erro logo abaixo. O operador receberia
# "exit 2" sem texto nenhum em vez de "nenhum backup encontrado".
LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/orgcred_backup_*.sql.gz 2>/dev/null | head -1 || true)

if [ -z "$LATEST_BACKUP" ]; then
    echo "ERRO: nenhum backup encontrado em $BACKUP_DIR" >&2
    exit 1
fi

echo ">> Testando restauração de: $LATEST_BACKUP"
echo ">> Banco temporário: $TEST_DB"

# Trap de EXIT, e não dropdb no fim do caminho feliz: qualquer falha no meio
# (restauração quebrada, validação recusada, timeout do executor) deixava o
# banco temporário para trás. Um por mês, para sempre, ocupando o disco do
# servidor de produção — e cada um deles com uma cópia íntegra dos dados.
trap 'psql "$ADMIN_URL" -q -c "drop database if exists \"$TEST_DB\" with (force)" >/dev/null 2>&1 || true' EXIT

# ON_ERROR_STOP=1 em todo psql: sem ele o psql sai 0 mesmo quando TODOS os
# comandos falharam. Era o furo central deste script — ele podia "passar"
# sobre um dump ilegível, que é precisamente a situação que ele existe para
# detectar.
psql "$ADMIN_URL" -q -v ON_ERROR_STOP=1 -c "create database \"$TEST_DB\""
gunzip -c "$LATEST_BACKUP" | psql "$TEST_URL" -q -v ON_ERROR_STOP=1

echo ">> Validando integridade do ledger..."
COUNT_LEDGER=$(psql "$TEST_URL" -q -v ON_ERROR_STOP=1 -t -c "select count(*) from capital_ledger;" | xargs)
CAPITAL_ATUAL=$(psql "$TEST_URL" -q -v ON_ERROR_STOP=1 -t -c "select capital_atual from v_capital_atual;" | xargs)

echo "   capital_ledger: $COUNT_LEDGER linhas"
echo "   v_capital_atual: R\$ $CAPITAL_ATUAL"

if [ -z "$CAPITAL_ATUAL" ]; then
    echo "FALHA: view v_capital_atual não retornou valor — backup pode estar corrompido." >&2
    exit 1
fi

echo ">> OK — backup restaurável e íntegro."
