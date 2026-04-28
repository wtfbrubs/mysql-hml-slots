#!/bin/bash
set -eo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REGISTRY="$ROOT_DIR/registry/slots.json"
LOCK_FILE="$ROOT_DIR/registry/slots.lock"

set -a
# shellcheck source=../.env
source "$ROOT_DIR/.env"
set +a

function log()   { echo "[INFO]  $1"; }
function error() { echo "[ERROR] $1" >&2; exit 1; }

# Aguarda MySQL ficar pronto executando mysqladmin ping dentro do container.
function wait_for_mysql() {
  local container=$1 password=$2
  local retries=30 interval=2
  log "Aguardando MySQL no container '$container'..."
  for _ in $(seq 1 $retries); do
    if docker exec "$container" \
         mysqladmin ping -uroot -p"$password" --silent 2>/dev/null; then
      log "MySQL pronto"
      return 0
    fi
    sleep $interval
  done
  error "MySQL no container '$container' não respondeu após $((retries * interval))s"
}

# Lock exclusivo no registry via flock (fd 9).
function lock_registry() {
  exec 9>"$LOCK_FILE"
  flock -w 10 9 || error "Timeout aguardando lock do registry"
}

function unlock_registry() {
  flock -u 9
  exec 9>&-
}
