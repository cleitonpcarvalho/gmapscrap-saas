#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-up}"
CONTAINER_NAME="${GMAPSCRAP_DB_BRIDGE_CONTAINER:-gmapscrap_db_bridge}"
NETWORK_NAME="${GMAPSCRAP_DB_NETWORK:-gmapscrap_internal}"
POSTGRES_HOST="${GMAPSCRAP_DB_SERVICE_HOST:-gmapscrap_postgres}"
POSTGRES_PORT="${GMAPSCRAP_DB_SERVICE_PORT:-5432}"
BRIDGE_BIND="${GMAPSCRAP_DB_BRIDGE_BIND:-127.0.0.1}"
BRIDGE_PORT="${GMAPSCRAP_DB_BRIDGE_PORT:-15432}"
IMAGE="${GMAPSCRAP_DB_BRIDGE_IMAGE:-alpine/socat:latest}"

start_bridge() {
  docker network inspect "${NETWORK_NAME}" >/dev/null

  docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  docker pull "${IMAGE}" >/dev/null

  docker run -d \
    --name "${CONTAINER_NAME}" \
    --restart unless-stopped \
    --network "${NETWORK_NAME}" \
    -p "${BRIDGE_BIND}:${BRIDGE_PORT}:${BRIDGE_PORT}" \
    "${IMAGE}" \
    -d -d \
    "TCP-LISTEN:${BRIDGE_PORT},fork,reuseaddr" \
    "TCP:${POSTGRES_HOST}:${POSTGRES_PORT}" >/dev/null

  echo "Ponte ativa: ${BRIDGE_BIND}:${BRIDGE_PORT} -> ${POSTGRES_HOST}:${POSTGRES_PORT} na rede ${NETWORK_NAME}"
}

stop_bridge() {
  docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  echo "Ponte removida: ${CONTAINER_NAME}"
}

case "${ACTION}" in
  up|start)
    start_bridge
    ;;
  down|stop)
    stop_bridge
    ;;
  restart)
    stop_bridge
    start_bridge
    ;;
  status)
    docker ps --filter "name=${CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    ;;
  *)
    echo "Uso: $0 [up|down|restart|status]" >&2
    exit 2
    ;;
esac
