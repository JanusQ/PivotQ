#!/usr/bin/env bash
set -euo pipefail

HEAD_PRIVATE_IP="${1:-}"
if [[ -z "${HEAD_PRIVATE_IP}" ]]; then
  echo "usage: $0 HEAD_PRIVATE_IP" >&2
  exit 2
fi

RAY_BIN="${RAY_QUANTUM_RAY_BIN:-/opt/ray-quantum/venv/bin/ray}"
WORKER_PORTS="12000,12001,12002,12003,12004,12005,12006,12007,12008,12009,12010,12011,12012,12013,12014,12015,12016,12017,12018,12019,12020,12021,12022,12023,12024,12025,12026,12027,12028,12029,12030,12031"
SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${RAY_QUANTUM_PROJECT_ROOT:-$(cd "${SCRIPT_DIRECTORY}/../.." && pwd)}"
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:+:${PYTHONPATH}}"

test -x "${RAY_BIN}"
test -d "${PROJECT_ROOT}/pivotq"
"${RAY_BIN}" stop --force || true
"${RAY_BIN}" start \
  --head \
  --node-ip-address="${HEAD_PRIVATE_IP}" \
  --port=6379 \
  --node-manager-port=11001 \
  --object-manager-port=11002 \
  --runtime-env-agent-port=11003 \
  --dashboard-agent-listen-port=11004 \
  --dashboard-agent-grpc-port=11005 \
  --worker-port-list="${WORKER_PORTS}" \
  --include-dashboard=true \
  --dashboard-host=127.0.0.1 \
  --dashboard-port=8265 \
  --disable-usage-stats

echo "HEAD_PRIVATE_IP=${HEAD_PRIVATE_IP}"
echo "PROJECT_ROOT=${PROJECT_ROOT}"
echo "NODE_ROLE=HEAD"
echo "HEAD_RESOURCES=CPU:auto,GPU:auto,QPU:0"
echo "JOBS_API=http://127.0.0.1:8265"
echo "JOBS_API_PUBLICLY_EXPOSED=false"
"${RAY_BIN}" status
echo "HEAD_START_RESULT=PASS"
