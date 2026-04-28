#!/bin/bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

BASE_PORT=${SLOTS_BASE_PORT:-3310}
MAX_PORT=$((BASE_PORT + 100))

for port in $(seq "$BASE_PORT" "$MAX_PORT"); do
  IN_REGISTRY=$(jq --argjson p "$port" \
    '[.[] | select(.port == $p)] | length' "$REGISTRY")
  if [ "$IN_REGISTRY" = "0" ]; then
    # Verifica disponibilidade real no host
    if ! ss -tln 2>/dev/null | grep -q ":${port} "; then
      echo "$port"
      exit 0
    fi
  fi
done

error "Nenhuma porta disponível entre $BASE_PORT e $MAX_PORT"
