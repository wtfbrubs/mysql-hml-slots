#!/bin/bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

COUNT=$(jq 'length' "$REGISTRY")
if [ "$COUNT" = "0" ]; then
  echo "Nenhum slot ativo."
  exit 0
fi

NOW=$(date -Iseconds)
printf "%-22s %-15s %-6s %-10s %-26s %-26s\n" \
  "SLOT" "OWNER" "PORTA" "STATUS" "CRIADO EM" "EXPIRA EM"
printf "%-22s %-15s %-6s %-10s %-26s %-26s\n" \
  "----" "-----" "-----" "------" "---------" "---------"

jq -r --arg now "$NOW" '
  .[] |
  [
    .slot_name,
    .owner,
    (.port | tostring),
    (if .expires_at < $now then "EXPIRADO" else .status end),
    .created_at,
    .expires_at
  ] | @tsv
' "$REGISTRY" \
| while IFS=$'\t' read -r slot owner port status created expires; do
    printf "%-22s %-15s %-6s %-10s %-26s %-26s\n" \
      "$slot" "$owner" "$port" "$status" "$created" "$expires"
  done
