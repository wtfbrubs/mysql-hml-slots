#!/bin/bash
# Configura replicação nativa PRD → base e instala Clone Plugin no base.
# Deve ser executado uma vez para bootstrapar o ambiente.
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

# ── validação de variáveis ────────────────────────────────────────────────────

for var in REPLICATION_USER REPLICATION_PASSWORD CLONE_USER CLONE_PASSWORD; do
  [ -n "${!var}" ] || error "Variável $var não definida no .env"
done

PRD_MODE="${PRD_MODE:-docker}"
PRD_SSL="${PRD_SSL:-false}"

if [ "$PRD_MODE" = "docker" ]; then
  PRD_HOST_INTERNAL="mysql-hml-prd"   # nome do container na rede mysql-hml
  PRD_PORT_INTERNAL=3306
  PRD_PASSWORD="$PRD_MYSQL_ROOT_PASSWORD"
  PRD_SSL=false   # SSL não faz sentido em rede Docker local
else
  [ -n "$PRD_HOST" ]     || error "PRD_HOST não definido para PRD_MODE=remote"
  [ -n "$PRD_USER" ]     || error "PRD_USER não definido para PRD_MODE=remote"
  PRD_HOST_INTERNAL="$PRD_HOST"
  PRD_PORT_INTERNAL="${PRD_PORT:-3306}"
  PRD_PASSWORD="$PRD_MYSQL_ROOT_PASSWORD"
fi

# ── pré-condições ─────────────────────────────────────────────────────────────

log "Verificando pré-condições..."

if [ "$PRD_MODE" = "docker" ]; then
  docker inspect mysql-hml-prd > /dev/null 2>&1 \
    || error "Container mysql-hml-prd não encontrado. Execute 'make up-prd' primeiro."
  wait_for_mysql "mysql-hml-prd" "$PRD_MYSQL_ROOT_PASSWORD"
else
  mysql -h "$PRD_HOST" -P "$PRD_PORT_INTERNAL" -u "$PRD_USER" -p"$PRD_PASSWORD" \
    -e "SELECT 1" > /dev/null 2>&1 \
    || error "Não foi possível conectar ao PRD remoto ($PRD_HOST:$PRD_PORT_INTERNAL)"
fi

docker inspect mysql-hml-base > /dev/null 2>&1 \
  || error "Container mysql-hml-base não encontrado. Execute 'make up-base' primeiro."
wait_for_mysql "mysql-hml-base" "$BASE_MYSQL_ROOT_PASSWORD"

# ── Docker network ────────────────────────────────────────────────────────────

log "Garantindo rede Docker mysql-hml..."
docker network inspect mysql-hml > /dev/null 2>&1 \
  || docker network create mysql-hml

# Conecta containers à rede caso ainda não estejam
for CONTAINER in mysql-hml-base mysql-hml-prd; do
  if docker inspect "$CONTAINER" > /dev/null 2>&1; then
    ALREADY=$(docker inspect "$CONTAINER" \
      --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' \
      | grep -c mysql-hml || true)
    if [ "$ALREADY" = "0" ]; then
      docker network connect mysql-hml "$CONTAINER" \
        && log "Container $CONTAINER conectado à rede mysql-hml"
    fi
  fi
done

# ── Usuário de replicação no PRD ──────────────────────────────────────────────

log "Criando usuário de replicação no PRD ($REPLICATION_USER)..."

_prd_mysql() {
  if [ "$PRD_MODE" = "docker" ]; then
    docker exec mysql-hml-prd mysql -uroot -p"$PRD_PASSWORD" -sN 2>/dev/null "$@"
  elif [ "$PRD_SSL" = "true" ]; then
    mysql -h "$PRD_HOST" -P "$PRD_PORT_INTERNAL" -u "$PRD_USER" -p"$PRD_PASSWORD" \
      --ssl-mode=REQUIRED -sN 2>/dev/null "$@"
  else
    mysql -h "$PRD_HOST" -P "$PRD_PORT_INTERNAL" -u "$PRD_USER" -p"$PRD_PASSWORD" -sN 2>/dev/null "$@"
  fi
}

_prd_mysql -e "
  CREATE USER IF NOT EXISTS '${REPLICATION_USER}'@'%'
    IDENTIFIED WITH mysql_native_password BY '${REPLICATION_PASSWORD}';
  GRANT REPLICATION SLAVE, REPLICATION CLIENT ON *.* TO '${REPLICATION_USER}'@'%';
  FLUSH PRIVILEGES;
"

log "Usuário de replicação criado/verificado no PRD"

# ── Clone Plugin + usuário clone no base ──────────────────────────────────────

log "Instalando Clone Plugin no base..."
docker exec mysql-hml-base mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" 2>/dev/null -e "
  INSTALL PLUGIN IF NOT EXISTS clone SONAME 'mysql_clone.so';
  CREATE USER IF NOT EXISTS '${CLONE_USER}'@'%'
    IDENTIFIED WITH mysql_native_password BY '${CLONE_PASSWORD}';
  GRANT BACKUP_ADMIN ON *.* TO '${CLONE_USER}'@'%';
  FLUSH PRIVILEGES;
"

log "Clone Plugin e usuário clone configurados no base"

# ── Bootstrap: dump inicial PRD → base ───────────────────────────────────────
# Necessário apenas se o base estiver vazio, para evitar sincronização full
# via binlog (lento para bancos grandes).

BASE_TABLES=$(docker exec mysql-hml-base mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" -sN 2>/dev/null \
  -e "SELECT COUNT(*) FROM information_schema.tables
      WHERE table_schema NOT IN
        ('information_schema','performance_schema','sys','mysql');" 2>/dev/null || echo "0")

if [ "${BASE_TABLES:-0}" = "0" ]; then
  log "Base vazio — executando dump inicial do PRD (pode demorar para bancos grandes)..."

  if [ "$PRD_MODE" = "docker" ]; then
    DATABASES=$(docker exec mysql-hml-prd \
      mysql -uroot -p"$PRD_PASSWORD" -sN 2>/dev/null \
      -e "SELECT schema_name FROM information_schema.schemata
          WHERE schema_name NOT IN
            ('information_schema','performance_schema','sys','mysql');" \
      | tr '\n' ' ' | xargs)

    if [ -n "$DATABASES" ]; then
      # shellcheck disable=SC2086
      docker exec mysql-hml-prd \
        mysqldump -uroot -p"$PRD_PASSWORD" \
        --databases $DATABASES \
        --single-transaction \
        --set-gtid-purged=ON \
        --master-data=2 \
        2>/dev/null \
        | docker exec -i mysql-hml-base \
            mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" 2>/dev/null
      log "Dump inicial concluído"
    fi
  else
    DATABASES=$(mysql -h "$PRD_HOST" -P "$PRD_PORT_INTERNAL" \
      -u "$PRD_USER" -p"$PRD_PASSWORD" -sN 2>/dev/null \
      -e "SELECT schema_name FROM information_schema.schemata
          WHERE schema_name NOT IN
            ('information_schema','performance_schema','sys','mysql');" \
      | tr '\n' ' ' | xargs)

    if [ -n "$DATABASES" ]; then
      SSL_OPT=""
      [ "$PRD_SSL" = "true" ] && SSL_OPT="--ssl-mode=REQUIRED"
      # RDS não concede SUPER; COMMENTED preserva os GTIDs como comentário
      # para que o base possa aplicar sem conflito após ligar a replicação.
      # shellcheck disable=SC2086
      mysqldump -h "$PRD_HOST" -P "$PRD_PORT_INTERNAL" \
        -u "$PRD_USER" -p"$PRD_PASSWORD" \
        $SSL_OPT \
        --databases $DATABASES \
        --single-transaction \
        --set-gtid-purged=COMMENTED \
        --master-data=2 \
        --compress \
        2>/dev/null \
        | docker exec -i mysql-hml-base \
            mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" 2>/dev/null
      log "Dump inicial (remoto) concluído"
    fi
  fi
else
  log "Base já possui dados — pulando dump inicial"
fi

# ── Configura canal de replicação no base ────────────────────────────────────

log "Configurando canal de replicação PRD → base..."

SOURCE_SSL_CLAUSE=""
[ "$PRD_SSL" = "true" ] && SOURCE_SSL_CLAUSE="SOURCE_SSL=1,"

docker exec mysql-hml-base mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" 2>/dev/null -e "
  STOP REPLICA;
  CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='${PRD_HOST_INTERNAL}',
    SOURCE_PORT=${PRD_PORT_INTERNAL},
    SOURCE_USER='${REPLICATION_USER}',
    SOURCE_PASSWORD='${REPLICATION_PASSWORD}',
    ${SOURCE_SSL_CLAUSE}
    SOURCE_AUTO_POSITION=1,
    SOURCE_CONNECT_RETRY=10,
    SOURCE_RETRY_COUNT=86400;
  START REPLICA;
"

# ── Verifica replicação ───────────────────────────────────────────────────────

log "Aguardando replicação iniciar..."
for i in $(seq 1 30); do
  IO=$(docker exec mysql-hml-base mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" -sN 2>/dev/null \
    -e "SHOW REPLICA STATUS\G" | grep "Replica_IO_Running" | awk '{print $2}')
  SQL=$(docker exec mysql-hml-base mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" -sN 2>/dev/null \
    -e "SHOW REPLICA STATUS\G" | grep "Replica_SQL_Running:" | awk '{print $2}')

  if [ "$IO" = "Yes" ] && [ "$SQL" = "Yes" ]; then
    log "Replicação ativa — IO: Yes | SQL: Yes"
    break
  fi
  sleep 2
done

if [ "$IO" != "Yes" ] || [ "$SQL" != "Yes" ]; then
  ERROR=$(docker exec mysql-hml-base mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" -sN 2>/dev/null \
    -e "SHOW REPLICA STATUS\G" | grep "Last_Error" | head -2)
  error "Replicação não iniciou. IO=$IO SQL=$SQL\n$ERROR"
fi

log "Setup de replicação concluído com sucesso!"
log "PRD → base: replicação nativa ativa (GTID, auto-position)"
log "Clone Plugin pronto — slots serão criados via CLONE INSTANCE FROM"
