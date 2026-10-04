#!/usr/bin/env bash
set -euo pipefail

HEAD_PRIVATE_IP="${1:-}"
WORKER_PRIVATE_IP="${2:-}"
WORKER_ROLE="${3:-compute}"
if [[ -z "${HEAD_PRIVATE_IP}" || -z "${WORKER_PRIVATE_IP}" ]]; then
  echo "usage: $0 HEAD_PRIVATE_IP WORKER_PRIVATE_IP [compute|qpu]" >&2
  exit 2
fi
if [[ "${WORKER_ROLE}" != "compute" && "${WORKER_ROLE}" != "qpu" ]]; then
  echo "WORKER_ROLE must be 'compute' or 'qpu'" >&2
  exit 2
fi

RAY_BIN="${RAY_QUANTUM_RAY_BIN:-/opt/ray-quantum/venv/bin/ray}"
WORKER_PORTS="12000,12001,12002,12003,12004,12005,12006,12007,12008,12009,12010,12011,12012,12013,12014,12015,12016,12017,12018,12019,12020,12021,12022,12023,12024,12025,12026,12027,12028,12029,12030,12031"
RESOURCE_ARGUMENTS=()
if [[ "${WORKER_ROLE}" == "qpu" ]]; then
  RESOURCE_ARGUMENTS+=(--resources='{"QPU":1}')
fi
SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${RAY_QUANTUM_PROJECT_ROOT:-$(cd "${SCRIPT_DIRECTORY}/../.." && pwd)}"
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:+:${PYTHONPATH}}"

test -x "${RAY_BIN}"
test -d "${PROJECT_ROOT}/pivotq"
"${RAY_BIN}" stop --force || true
"${RAY_BIN}" start \
  --address="${HEAD_PRIVATE_IP}:6379" \
  --node-ip-address="${WORKER_PRIVATE_IP}" \
  --node-manager-port=11001 \
  --object-manager-port=11002 \
  --runtime-env-agent-port=11003 \
  --dashboard-agent-listen-port=11004 \
  --dashboard-agent-grpc-port=11005 \
  --worker-port-list="${WORKER_PORTS}" \
  "${RESOURCE_ARGUMENTS[@]}" \
  --disable-usage-stats

echo "HEAD_PRIVATE_IP=${HEAD_PRIVATE_IP}"
echo "WORKER_PRIVATE_IP=${WORKER_PRIVATE_IP}"
echo "PROJECT_ROOT=${PROJECT_ROOT}"
if [[ "${WORKER_ROLE}" == "qpu" ]]; then
  echo "NODE_ROLE=LABORATORY_QPU_WORKER"
  echo "WORKER_RESOURCES=CPU:auto,GPU:auto,QPU:1"
  echo "QPU_RESOURCE_IS_LOGICAL_SCHEDULING_TOKEN=true"
else
  echo "NODE_ROLE=COMPUTE_WORKER"
  echo "WORKER_RESOURCES=CPU:auto,GPU:auto,QPU:0"
fi
echo "WORKER_START_RESULT=PASS"
