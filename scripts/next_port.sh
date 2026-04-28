#!/bin/bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

SLOT_NAME=${1:-}
BASE_PORT=${SLOTS_BASE_PORT:-3310}
MAX_PORT=$((BASE_PORT + 100))

# Nome com sufixo numérico (ex: hml-01) → porta determinística
if [[ "$SLOT_NAME" =~ [0-9]+$ ]]; then
  N=$((10#${BASH_REMATCH[0]}))   # 10# converte para decimal (01 → 1)
  PORT=$((BASE_PORT + N - 1))

  IN_USE=$(jq --argjson p "$PORT" --arg n "$SLOT_NAME" \
    '[.[] | select(.port == $p and .slot_name != $n)] | length' "$REGISTRY")
  [ "$IN_USE" != "0" ] && error "Porta $PORT já ocupada por outro slot"

  ss -tln 2>/dev/null | grep -q ":${PORT} " \
    && error "Porta $PORT já está em uso no host"

  echo "$PORT"
  exit 0
fi

# Fallback dinâmico para nomes sem sufixo numérico
for port in $(seq "$BASE_PORT" "$MAX_PORT"); do
  IN_REGISTRY=$(jq --argjson p "$port" \
    '[.[] | select(.port == $p)] | length' "$REGISTRY")
  if [ "$IN_REGISTRY" = "0" ]; then
    if ! ss -tln 2>/dev/null | grep -q ":${port} "; then
      echo "$port"
      exit 0
    fi
  fi
done

error "Nenhuma porta disponível entre $BASE_PORT e $MAX_PORT"
