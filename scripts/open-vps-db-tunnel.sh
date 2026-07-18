#!/usr/bin/env bash
set -euo pipefail

VPS_HOST="${GMAPSCRAP_VPS_HOST:-178.18.240.24}"
VPS_USER="${GMAPSCRAP_VPS_USER:-root}"
LOCAL_PORT="${REMOTE_DB_LOCAL_PORT:-5433}"
REMOTE_BRIDGE_PORT="${GMAPSCRAP_DB_BRIDGE_PORT:-15432}"

echo "Abrindo tunel SSH: localhost:${LOCAL_PORT} -> ${VPS_USER}@${VPS_HOST}:127.0.0.1:${REMOTE_BRIDGE_PORT}"
echo "Mantenha este terminal aberto enquanto usar o backend local."

exec ssh \
  -N \
  -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_BRIDGE_PORT}" \
  "${VPS_USER}@${VPS_HOST}"
