#!/bin/bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

NOW=$(date -Iseconds)
EXPIRED=$(jq -r --arg now "$NOW" \
  '.[] | select(.expires_at < $now and .status == "running") | .slot_name' \
  "$REGISTRY")

if [ -z "$EXPIRED" ]; then
  log "Nenhum slot expirado"
  exit 0
fi

for slot in $EXPIRED; do
  log "Expirando slot '$slot'..."
  "$ROOT_DIR/scripts/destroy_slot.sh" "$slot"
done
