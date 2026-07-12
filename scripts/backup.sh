#!/usr/bin/env bash
# OrgCred — backup lógico diário do banco (pg_dump) + rotação.
#
# Uso: ORGCRED_DATABASE_URL=postgresql://... ./scripts/backup.sh [diretorio_destino]
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

mkdir -p "$DEST_DIR"

FILENAME="$DEST_DIR/orgcred_backup_${TIMESTAMP}.sql.gz"

echo ">> Iniciando backup: $FILENAME"
pg_dump "$ORGCRED_DATABASE_URL" --format=plain --no-owner --no-privileges | gzip > "$FILENAME"

if [ -s "$FILENAME" ]; then
    echo ">> Backup concluído: $(du -h "$FILENAME" | cut -f1)"
else
    echo "ERRO: backup vazio ou falhou." >&2
    rm -f "$FILENAME"
    exit 1
fi

echo ">> Removendo backups com mais de $RETENTION_DAYS dias"
find "$DEST_DIR" -name "orgcred_backup_*.sql.gz" -mtime "+$RETENTION_DAYS" -delete

echo ">> Backups atuais em $DEST_DIR:"
ls -lh "$DEST_DIR"/orgcred_backup_*.sql.gz 2>/dev/null || echo "  (nenhum)"
