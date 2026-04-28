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

SNAPSHOT_FILE="$ROOT_DIR/${SNAPSHOT_DIR:-snapshots}/latest.sql.gz"
[ -f "$SNAPSHOT_FILE" ] \
  || error "Snapshot não encontrado em $SNAPSHOT_FILE. Execute 'make snapshot' primeiro."

PORT=$("$ROOT_DIR/scripts/next_port.sh")
DATA_DIR="$ROOT_DIR/data/slots/$SLOT_NAME"
SLOT_DIR="$ROOT_DIR/docker/slot/$SLOT_NAME"
SLOT_CNF="$SLOT_DIR/my.cnf"
MYSQL_ROOT_PASSWORD="$BASE_MYSQL_ROOT_PASSWORD"

CREATED=false

# Rollback automático se qualquer passo falhar
function _slot_rollback() {
  [ "$CREATED" = "true" ] && return 0
  log "Rollback: removendo estado parcial do slot '$SLOT_NAME'..."
  [ -f "${SLOT_DIR}/docker-compose.yml" ] && \
    docker compose -f "$SLOT_DIR/docker-compose.yml" down -v 2>/dev/null || true
  docker rm -f "$SLOT_NAME" 2>/dev/null || true
  [ -n "$DATA_DIR" ] && rm -rf "$DATA_DIR"
  [ -n "$SLOT_DIR"  ] && rm -rf "$SLOT_DIR"
  [ -f "$REGISTRY" ] || return 0
  TMP=$(mktemp)
  jq --arg n "$SLOT_NAME" \
    'map(select(.slot_name != $n))' \
    "$REGISTRY" > "$TMP" 2>/dev/null && mv "$TMP" "$REGISTRY" || true
}
trap '_slot_rollback' EXIT

log "Criando slot '$SLOT_NAME' — porta $PORT | owner: $OWNER | TTL: ${TTL}h"

mkdir -p "$DATA_DIR" "$SLOT_DIR"

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

log "Restaurando snapshot..."
zcat "$SNAPSHOT_FILE" \
  | docker exec -i "$SLOT_NAME" \
      mysql -uroot -p"$MYSQL_ROOT_PASSWORD" 2>/dev/null
log "Snapshot restaurado"

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
