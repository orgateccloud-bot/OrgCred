#!/usr/bin/env bash
# OrgCred — teste de restauração de backup (deve rodar mensalmente).
#
# Restaura o backup mais recente em um banco temporário e valida que o
# ledger (capital_ledger) e a view v_capital_atual respondem corretamente.
# Um backup nunca testado não é um backup confiável.
#
# Uso: ./scripts/restore_test.sh [caminho_do_backup.sql.gz]
set -euo pipefail

BACKUP_DIR="${1:-./backups}"
TEST_DB="orgcred_restore_test_$(date +%s)"

LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/orgcred_backup_*.sql.gz 2>/dev/null | head -1)

if [ -z "$LATEST_BACKUP" ]; then
    echo "ERRO: nenhum backup encontrado em $BACKUP_DIR" >&2
    exit 1
fi

echo ">> Testando restauração de: $LATEST_BACKUP"
echo ">> Banco temporário: $TEST_DB"

createdb "$TEST_DB"
gunzip -c "$LATEST_BACKUP" | psql -d "$TEST_DB" -q

echo ">> Validando integridade do ledger..."
COUNT_LEDGER=$(psql -d "$TEST_DB" -t -c "select count(*) from capital_ledger;" | xargs)
CAPITAL_ATUAL=$(psql -d "$TEST_DB" -t -c "select capital_atual from v_capital_atual;" | xargs)

echo "   capital_ledger: $COUNT_LEDGER linhas"
echo "   v_capital_atual: R\$ $CAPITAL_ATUAL"

if [ -z "$CAPITAL_ATUAL" ]; then
    echo "FALHA: view v_capital_atual não retornou valor — backup pode estar corrompido." >&2
    dropdb "$TEST_DB"
    exit 1
fi

echo ">> OK — backup restaurável e íntegro."
dropdb "$TEST_DB"
