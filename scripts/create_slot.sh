#!/bin/bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

SLOT_NAME=$1
OWNER=${2:-unknown}
TTL=${3:-24}

[ -z "$SLOT_NAME" ] && error "Uso: create_slot.sh <slot_name> [owner] [ttl_horas]"

[[ "$SLOT_NAME" =~ ^[a-z][a-z0-9_-]*$ ]] \
  || error "Nome do slot deve começar com letra minúscula e conter apenas letras minúsculas, números, _ e -"

lock_registry
ALREADY=$(jq --arg n "$SLOT_NAME" '[.[] | select(.slot_name == $n)] | length' "$REGISTRY")
unlock_registry
[ "$ALREADY" != "0" ] && error "Slot '$SLOT_NAME' já existe no registry"

PORT=$("$ROOT_DIR/scripts/next_port.sh" "$SLOT_NAME")
DATA_DIR="$ROOT_DIR/data/slots/$SLOT_NAME"
SLOT_DIR="$ROOT_DIR/docker/slot/$SLOT_NAME"
SLOT_CNF="$SLOT_DIR/my.cnf"
MYSQL_ROOT_PASSWORD="$BASE_MYSQL_ROOT_PASSWORD"

CREATED=false

function _slot_rollback() {
  [ "$CREATED" = "true" ] && return 0
  log "Rollback: removendo estado parcial do slot '$SLOT_NAME'..."
  [ -f "${SLOT_DIR}/docker-compose.yml" ] && \
    docker compose -f "$SLOT_DIR/docker-compose.yml" down -v 2>/dev/null || true
  docker rm -f "$SLOT_NAME" 2>/dev/null || true
  [ -n "$DATA_DIR" ] && docker run --rm \
    -v "$ROOT_DIR/data:/data" \
    --entrypoint sh "mysql:${MYSQL_VERSION}" \
    -c "rm -rf /data/slots/$SLOT_NAME" 2>/dev/null || true
  [ -n "$SLOT_DIR" ] && rm -rf "$SLOT_DIR" 2>/dev/null || true
  [ -f "$REGISTRY" ] || return 0
  TMP=$(mktemp)
  jq --arg n "$SLOT_NAME" \
    'map(select(.slot_name != $n))' \
    "$REGISTRY" > "$TMP" 2>/dev/null && mv "$TMP" "$REGISTRY" || true
}
trap '_slot_rollback' EXIT

log "Criando slot '$SLOT_NAME' — porta $PORT | owner: $OWNER | TTL: ${TTL}h"

docker network inspect mysql-hml > /dev/null 2>&1 \
  || docker network create mysql-hml

mkdir -p "$SLOT_DIR"
docker run --rm \
  -v "$ROOT_DIR/data:/data" \
  --entrypoint sh "mysql:${MYSQL_VERSION}" \
  -c "mkdir -p /data/slots/$SLOT_NAME && chown -R 999:999 /data/slots/$SLOT_NAME"

cat > "$SLOT_CNF" << EOF
[mysqld]
server-id=$PORT
gtid_mode=ON
enforce_gtid_consistency=ON
EOF

export SLOT_NAME PORT DATA_DIR SLOT_CNF MYSQL_ROOT_PASSWORD MYSQL_VERSION
envsubst < "$ROOT_DIR/docker/slot/docker-compose.template.yml" > "$SLOT_DIR/docker-compose.yml"

docker compose -f "$SLOT_DIR/docker-compose.yml" up -d
wait_for_mysql "$SLOT_NAME" "$MYSQL_ROOT_PASSWORD"

# ── detecta modo de restauração: Clone Plugin ou snapshot ────────────────────

CLONE_AVAILABLE=false
if [ -n "$CLONE_USER" ] && [ -n "$CLONE_PASSWORD" ]; then
  PLUGIN_STATUS=$(docker exec mysql-hml-base mysql -uroot -p"$BASE_MYSQL_ROOT_PASSWORD" -sN 2>/dev/null \
    -e "SELECT PLUGIN_STATUS FROM information_schema.PLUGINS WHERE PLUGIN_NAME='clone';" 2>/dev/null)
  [ "$PLUGIN_STATUS" = "ACTIVE" ] && CLONE_AVAILABLE=true
fi

if [ "$CLONE_AVAILABLE" = "true" ]; then
  # ── Clone Plugin (rápido, paralelo, sem dump) ─────────────────────────────
  log "Clonando dados do base via MySQL Clone Plugin..."

  START_TS=$(date +%s)

  docker exec "$SLOT_NAME" mysql -uroot -p"$MYSQL_ROOT_PASSWORD" 2>/dev/null -e "
    INSTALL PLUGIN IF NOT EXISTS clone SONAME 'mysql_clone.so';
    CLONE INSTANCE FROM '${CLONE_USER}'@'mysql-hml-base':3306
      IDENTIFIED BY '${CLONE_PASSWORD}';
  "

  # Clone reinicia MySQL automaticamente — aguarda voltar
  log "Clone concluído — aguardando MySQL reiniciar no slot..."
  sleep 5
  wait_for_mysql "$SLOT_NAME" "$MYSQL_ROOT_PASSWORD"

  # Desconecta o slot da replicação herdada do base
  docker exec "$SLOT_NAME" mysql -uroot -p"$MYSQL_ROOT_PASSWORD" 2>/dev/null -e "
    STOP REPLICA;
    RESET REPLICA ALL;
  " 2>/dev/null || true

  END_TS=$(date +%s)
  log "Clone concluído em $((END_TS - START_TS))s"

else
  # ── Fallback: snapshot (mysqldump) ────────────────────────────────────────
  SNAPSHOT_FILE="$ROOT_DIR/${SNAPSHOT_DIR:-snapshots}/latest.sql.gz"
  [ -f "$SNAPSHOT_FILE" ] \
    || error "Snapshot não encontrado em $SNAPSHOT_FILE. Execute 'make snapshot' primeiro."

  log "Clone Plugin não disponível — restaurando via snapshot (mysqldump)..."
  START_TS=$(date +%s)
  zcat "$SNAPSHOT_FILE" \
    | docker exec -i "$SLOT_NAME" \
        mysql -uroot -p"$MYSQL_ROOT_PASSWORD" 2>/dev/null
  END_TS=$(date +%s)
  log "Snapshot restaurado em $((END_TS - START_TS))s"
fi

lock_registry
NOW=$(date -Iseconds)
EXPIRES=$(date -d "+${TTL} hours" -Iseconds)
TMP=$(mktemp)
jq --arg name    "$SLOT_NAME" \
   --arg owner   "$OWNER"    \
   --argjson port "$PORT"    \
   --arg now     "$NOW"      \
   --arg expires "$EXPIRES"  \
   --arg dir     "$SLOT_DIR" \
   '. + [{
     slot_name:   $name,
     owner:       $owner,
     port:        $port,
     status:      "running",
     created_at:  $now,
     expires_at:  $expires,
     compose_dir: $dir
   }]' "$REGISTRY" > "$TMP" && mv "$TMP" "$REGISTRY"
unlock_registry

CREATED=true
log "Slot '$SLOT_NAME' disponível em localhost:$PORT"
