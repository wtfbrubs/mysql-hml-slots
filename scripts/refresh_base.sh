#!/bin/bash
# Verifica e garante que a replicação PRD → base está ativa.
# Se replicação não estiver configurada, cai no modo legado (mysqldump).
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

PRD_MODE="${PRD_MODE:-docker}"
MAX_LAG_SECONDS="${MAX_LAG_SECONDS:-30}"

log "Verificando status da replicação no base..."

# ── detecta se replicação está configurada ────────────────────────────────────

REPL_IO=$(docker exec mysql-hml-base mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" -sN 2>/dev/null \
  -e "SHOW REPLICA STATUS\G" 2>/dev/null | grep "Replica_IO_Running" | awk '{print $2}')

if [ -n "$REPL_IO" ]; then
  # ── modo replicação nativa ────────────────────────────────────────────────

  REPL_SQL=$(docker exec mysql-hml-base mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" -sN 2>/dev/null \
    -e "SHOW REPLICA STATUS\G" | grep "Replica_SQL_Running:" | awk '{print $2}')
  LAG=$(docker exec mysql-hml-base mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" -sN 2>/dev/null \
    -e "SHOW REPLICA STATUS\G" | grep "Seconds_Behind_Source" | awk '{print $2}')
  LAST_ERROR=$(docker exec mysql-hml-base mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" -sN 2>/dev/null \
    -e "SHOW REPLICA STATUS\G" | grep "Last_Error:" | head -1 | cut -d: -f2- | xargs)

  log "IO: $REPL_IO | SQL: $REPL_SQL | Lag: ${LAG}s"

  if [ -n "$LAST_ERROR" ]; then
    log "Erro de replicação detectado: $LAST_ERROR"
    log "Tentando reiniciar replicação..."
    docker exec mysql-hml-base mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" 2>/dev/null \
      -e "STOP REPLICA; START REPLICA;"
    sleep 5

    REPL_IO=$(docker exec mysql-hml-base mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" -sN 2>/dev/null \
      -e "SHOW REPLICA STATUS\G" | grep "Replica_IO_Running" | awk '{print $2}')
    [ "$REPL_IO" = "Yes" ] || error "Replicação não recuperou. Execute 'make setup-replication' para re-configurar."
    log "Replicação reiniciada com sucesso"
  fi

  if [ "$REPL_IO" != "Yes" ] || [ "$REPL_SQL" != "Yes" ]; then
    log "Replicação parada (IO=$REPL_IO SQL=$REPL_SQL) — tentando iniciar..."
    docker exec mysql-hml-base mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" 2>/dev/null \
      -e "START REPLICA;"
    sleep 5
  fi

  # Aguarda lag cair abaixo do threshold
  log "Aguardando lag < ${MAX_LAG_SECONDS}s..."
  for i in $(seq 1 60); do
    LAG=$(docker exec mysql-hml-base mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" -sN 2>/dev/null \
      -e "SHOW REPLICA STATUS\G" | grep "Seconds_Behind_Source" | awk '{print $2}')
    LAG_NUM=${LAG:-9999}
    if [ "$LAG_NUM" -le "$MAX_LAG_SECONDS" ] 2>/dev/null; then
      log "Lag atual: ${LAG}s — base atualizado"
      break
    fi
    log "Lag: ${LAG}s — aguardando..."
    sleep 5
  done

  # Gera snapshot do estado atual do base
  log "Gerando snapshot do base para os slots..."
  "$ROOT_DIR/scripts/snapshot.sh"
  log "Base sincronizado via replicação nativa"

else
  # ── modo legado: mysqldump (sem replicação configurada) ───────────────────

  log "Replicação não configurada — usando modo legado (mysqldump)."
  log "Para performance com bancos grandes, execute 'make setup-replication'."

  if [ "$PRD_MODE" = "docker" ]; then
    docker inspect mysql-hml-prd > /dev/null 2>&1 \
      || error "Container mysql-hml-prd não encontrado. Execute 'make up-prd' primeiro."
    wait_for_mysql "mysql-hml-prd" "$PRD_MYSQL_ROOT_PASSWORD"
  else
    [ -n "$PRD_HOST" ] || error "PRD_HOST não definido no .env para PRD_MODE=remote"
  fi

  log "Parando mysql-hml-base..."
  docker compose --env-file "$ROOT_DIR/.env" \
    -f "$ROOT_DIR/docker/base/docker-compose.yml" down 2>/dev/null || true

  log "Limpando data/base..."
  docker run --rm \
    -v "$ROOT_DIR/data/base:/var/lib/mysql" \
    --entrypoint sh "mysql:${MYSQL_VERSION}" \
    -c "rm -rf /var/lib/mysql/*"

  log "Subindo mysql-hml-base..."
  docker compose --env-file "$ROOT_DIR/.env" \
    -f "$ROOT_DIR/docker/base/docker-compose.yml" up -d
  wait_for_mysql "mysql-hml-base" "$BASE_MYSQL_ROOT_PASSWORD"

  if [ "$PRD_MODE" = "docker" ]; then
    DATABASES=$(docker exec mysql-hml-prd \
      mysql -uroot -p"$PRD_MYSQL_ROOT_PASSWORD" -sN 2>/dev/null \
      -e "SELECT schema_name FROM information_schema.schemata
          WHERE schema_name NOT IN
            ('information_schema','performance_schema','sys','mysql');" \
      | tr '\n' ' ' | xargs)
    if [ -n "$DATABASES" ]; then
      # shellcheck disable=SC2086
      docker exec mysql-hml-prd \
        mysqldump -uroot -p"$PRD_MYSQL_ROOT_PASSWORD" \
        --databases $DATABASES \
        --single-transaction \
        --set-gtid-purged=OFF \
        2>/dev/null \
        | docker exec -i mysql-hml-base \
            mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" 2>/dev/null
    fi
  else
    DATABASES=$(mysql -h "$PRD_HOST" -P "${PRD_PORT:-3306}" \
      -u "${PRD_USER:-admin}" -p"$PRD_MYSQL_ROOT_PASSWORD" -sN 2>/dev/null \
      -e "SELECT schema_name FROM information_schema.schemata
          WHERE schema_name NOT IN
            ('information_schema','performance_schema','sys','mysql');" \
      | tr '\n' ' ' | xargs)
    if [ -n "$DATABASES" ]; then
      # shellcheck disable=SC2086
      mysqldump -h "$PRD_HOST" -P "${PRD_PORT:-3306}" \
        -u "${PRD_USER:-admin}" -p"$PRD_MYSQL_ROOT_PASSWORD" \
        --databases $DATABASES \
        --single-transaction \
        --set-gtid-purged=OFF \
        --compress \
        2>/dev/null \
        | docker exec -i mysql-hml-base \
            mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" 2>/dev/null
    fi
  fi

  log "Gerando snapshot..."
  "$ROOT_DIR/scripts/snapshot.sh"
  log "Base atualizado via mysqldump (legado)"
fi
