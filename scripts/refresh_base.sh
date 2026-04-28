#!/bin/bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

PRD_MODE="${PRD_MODE:-docker}"
log "Iniciando refresh do base (modo: $PRD_MODE)"

# Verifica pré-condições do PRD
if [ "$PRD_MODE" = "docker" ]; then
  docker inspect mysql-hml-prd > /dev/null 2>&1 \
    || error "Container mysql-hml-prd não encontrado. Execute 'make up-prd' primeiro."
  wait_for_mysql "mysql-hml-prd" "$PRD_MYSQL_ROOT_PASSWORD"
else
  [ -z "$PRD_HOST" ] \
    || error "PRD_HOST não definido no .env para PRD_MODE=remote"
fi

# Para e limpa o base para garantir restore limpo
log "Parando mysql-hml-base..."
docker compose --env-file "$ROOT_DIR/.env" \
  -f "$ROOT_DIR/docker/base/docker-compose.yml" down 2>/dev/null || true

log "Limpando data/base..."
# Os arquivos pertencem ao uid do MySQL dentro do container — limpar via Docker
docker run --rm \
  -v "$ROOT_DIR/data/base:/var/lib/mysql" \
  --entrypoint sh "mysql:${MYSQL_VERSION}" \
  -c "rm -rf /var/lib/mysql/*"

# Sobe base limpo
log "Subindo mysql-hml-base..."
docker compose --env-file "$ROOT_DIR/.env" \
  -f "$ROOT_DIR/docker/base/docker-compose.yml" up -d
wait_for_mysql "mysql-hml-base" "$BASE_MYSQL_ROOT_PASSWORD"

# Descobre databases de aplicação no PRD
function _app_databases_docker() {
  docker exec mysql-hml-prd \
    mysql -uroot -p"$PRD_MYSQL_ROOT_PASSWORD" -sN 2>/dev/null \
    -e "SELECT schema_name FROM information_schema.schemata
        WHERE schema_name NOT IN
          ('information_schema','performance_schema','sys','mysql');" \
    | tr '\n' ' ' | xargs
}

function _app_databases_remote() {
  mysql -h "$PRD_HOST" -P "${PRD_PORT:-3306}" \
    -u "${PRD_USER:-admin}" -p"$PRD_MYSQL_ROOT_PASSWORD" -sN 2>/dev/null \
    -e "SELECT schema_name FROM information_schema.schemata
        WHERE schema_name NOT IN
          ('information_schema','performance_schema','sys','mysql');" \
    | tr '\n' ' ' | xargs
}

if [ "$PRD_MODE" = "docker" ]; then
  DATABASES=$(_app_databases_docker)
else
  DATABASES=$(_app_databases_remote)
fi

if [ -z "$DATABASES" ]; then
  log "Nenhuma database de aplicação encontrada no PRD — base ficará vazio"
else
  log "Copiando databases: $DATABASES"

  if [ "$PRD_MODE" = "docker" ]; then
    # shellcheck disable=SC2086
    docker exec mysql-hml-prd \
      mysqldump -uroot -p"$PRD_MYSQL_ROOT_PASSWORD" \
      --databases $DATABASES \
      --single-transaction \
      --set-gtid-purged=OFF \
      2>/dev/null \
      | docker exec -i mysql-hml-base \
          mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" 2>/dev/null
  else
    # shellcheck disable=SC2086
    mysqldump -h "$PRD_HOST" -P "${PRD_PORT:-3306}" \
      -u "${PRD_USER:-admin}" -p"$PRD_MYSQL_ROOT_PASSWORD" \
      --databases $DATABASES \
      --single-transaction \
      --set-gtid-purged=OFF \
      2>/dev/null \
      | docker exec -i mysql-hml-base \
          mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" 2>/dev/null
  fi
  log "Databases copiadas do PRD para o base"
fi

log "Gerando snapshot atualizado..."
"$ROOT_DIR/scripts/snapshot.sh"

log "Base atualizado com sucesso"
