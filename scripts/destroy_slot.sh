#!/bin/bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

SLOT_NAME=$1
[ -z "$SLOT_NAME" ] && error "Uso: destroy_slot.sh <slot_name>"

SLOT_DIR="$ROOT_DIR/docker/slot/$SLOT_NAME"
DATA_DIR="$ROOT_DIR/data/slots/$SLOT_NAME"

log "Removendo slot '$SLOT_NAME'..."

if [ -f "$SLOT_DIR/docker-compose.yml" ]; then
  docker compose -f "$SLOT_DIR/docker-compose.yml" down -v 2>/dev/null || true
else
  docker rm -f "$SLOT_NAME" 2>/dev/null || true
fi

rm -rf "$DATA_DIR" "$SLOT_DIR"

lock_registry
TMP=$(mktemp)
jq --arg name "$SLOT_NAME" \
   'map(select(.slot_name != $name))' \
   "$REGISTRY" > "$TMP" && mv "$TMP" "$REGISTRY"
unlock_registry

log "Slot '$SLOT_NAME' removido"
