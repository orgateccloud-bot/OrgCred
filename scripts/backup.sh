#!/usr/bin/env bash
# OrgCred — backup lógico diário do banco (pg_dump) + rotação.
#
# Uso: ORGCRED_DATABASE_URL=postgresql://... ./scripts/backup.sh [diretorio_destino]
#
# CHAMADO TODO DIA por `python -m app.rotinas` (app/rotinas.py). Continua
# chamável à mão pelo mesmo comando — são o mesmo caminho, de propósito: um
# script que só o cron sabe invocar é um script que ninguém consegue testar
# quando ele falha às 3h da manhã. Ver docs/OPERACAO.md.
#
# Este é o backup MÍNIMO viável (dump lógico diário + retenção de 30 dias).
# Para RPO < 24h em produção, migrar para WAL-G ou pgBackRest com PITR
# contínuo — ver RELATORIO_MODERNIZACAO_2026-07-12.md, Fase 3.
set -euo pipefail

DEST_DIR="${1:-./backups}"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

if [ -z "${ORGCRED_DATABASE_URL:-}" ]; then
    echo "ERRO: ORGCRED_DATABASE_URL não definida." >&2
    exit 1
fi

# A aplicação fala SQLAlchemy ('postgresql+psycopg://'); o pg_dump fala libpq
# ('postgresql://'). Passar a URL da aplicação crua ao pg_dump falha com
# "invalid URI scheme" — e falhava na hora do backup, longe de quem configurou
# a variável, num script que ninguém chamava. Uma variável, duas gramáticas: a
# tradução mora aqui, e não numa segunda variável de ambiente que alguém teria
# de lembrar de manter em sincronia com a primeira.
PG_URL=$(printf '%s' "$ORGCRED_DATABASE_URL" | sed -E 's#^(postgres(ql)?)\+[a-z0-9_]+://#\1://#')

mkdir -p "$DEST_DIR"

FILENAME="$DEST_DIR/orgcred_backup_${TIMESTAMP}.sql.gz"

# Um dump interrompido no meio (rede, disco cheio, OOM) deixa um .gz truncado
# no diretório. E o restore_test.sh escolhe o backup MAIS RECENTE — ou seja,
# escolheria justamente o arquivo quebrado, e `ls` mostraria um backup do dia
# como se estivesse tudo bem. O trap apaga o parcial antes de o script sair.
trap 'rm -f "$FILENAME"' ERR

echo ">> Iniciando backup: $FILENAME"
pg_dump "$PG_URL" --format=plain --no-owner --no-privileges | gzip > "$FILENAME"

if [ -s "$FILENAME" ]; then
    echo ">> Backup concluído: $(du -h "$FILENAME" | cut -f1)"
else
    echo "ERRO: backup vazio ou falhou." >&2
    rm -f "$FILENAME"
    exit 1
fi

# A partir daqui o backup do dia está válido e não deve mais ser apagado por
# falha das etapas de faxina abaixo.
trap - ERR

echo ">> Removendo backups com mais de $RETENTION_DAYS dias"
find "$DEST_DIR" -name "orgcred_backup_*.sql.gz" -mtime "+$RETENTION_DAYS" -delete

echo ">> Backups atuais em $DEST_DIR:"
ls -lh "$DEST_DIR"/orgcred_backup_*.sql.gz 2>/dev/null || echo "  (nenhum)"
