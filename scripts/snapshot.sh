#!/bin/bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

SNAPSHOT_BASE="$ROOT_DIR/${SNAPSHOT_DIR:-snapshots}"
mkdir -p "$SNAPSHOT_BASE"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SNAPSHOT_FILE="$SNAPSHOT_BASE/snapshot_${TIMESTAMP}.sql.gz"
LATEST_LINK="$SNAPSHOT_BASE/latest.sql.gz"

docker inspect mysql-hml-base > /dev/null 2>&1 \
  || error "Container mysql-hml-base não encontrado. Execute 'make up-base' primeiro."

log "Identificando databases de aplicação..."
DATABASES=$(docker exec mysql-hml-base \
  mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" -sN 2>/dev/null \
  -e "SELECT schema_name FROM information_schema.schemata
      WHERE schema_name NOT IN
        ('information_schema','performance_schema','sys','mysql');" \
  | tr '\n' ' ' | xargs)

if [ -z "$DATABASES" ]; then
  log "Nenhuma database de aplicação encontrada — snapshot conterá apenas estrutura de sistema."
  # Cria um dump mínimo para que o slot suba limpo
  docker exec mysql-hml-base \
    mysqldump -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" \
    --no-tablespaces \
    --set-gtid-purged=OFF \
    2>/dev/null | gzip > "$SNAPSHOT_FILE"
else
  log "Databases encontradas: $DATABASES"
  log "Gerando snapshot..."
  # shellcheck disable=SC2086
  docker exec mysql-hml-base \
    mysqldump -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" \
    --databases $DATABASES \
    --single-transaction \
    --set-gtid-purged=OFF \
    --flush-logs \
    --no-tablespaces \
    2>/dev/null | gzip > "$SNAPSHOT_FILE"
fi

[ -s "$SNAPSHOT_FILE" ] || error "Snapshot gerado está vazio — verifique o MySQL base."

ln -sf "$SNAPSHOT_FILE" "$LATEST_LINK"
SIZE=$(du -sh "$SNAPSHOT_FILE" | cut -f1)
log "Snapshot salvo: $SNAPSHOT_FILE ($SIZE)"
log "Link atualizado: $LATEST_LINK"
