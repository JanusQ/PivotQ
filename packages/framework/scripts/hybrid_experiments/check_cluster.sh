#!/usr/bin/env bash
set -euo pipefail

EXPECTED_HEAD_IP="${1:-}"
EXPECTED_QPU_WORKER_IP="${2:-}"
MIN_NODES="${3:-2}"
if [[ -z "${EXPECTED_HEAD_IP}" || -z "${EXPECTED_QPU_WORKER_IP}" ]]; then
  echo "usage: $0 HEAD_PRIVATE_IP LABORATORY_QPU_WORKER_PRIVATE_IP [MINIMUM_NODE_COUNT]" >&2
  exit 2
fi
if [[ "${EXPECTED_HEAD_IP}" == "${EXPECTED_QPU_WORKER_IP}" ]]; then
  echo "HEAD_PRIVATE_IP and LABORATORY_QPU_WORKER_PRIVATE_IP must be different" >&2
  exit 2
fi
if [[ ! "${MIN_NODES}" =~ ^[1-9][0-9]*$ ]]; then
  echo "MINIMUM_NODE_COUNT must be a positive integer" >&2
  exit 2
fi

SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${RAY_QUANTUM_PROJECT_ROOT:-$(cd "${SCRIPT_DIRECTORY}/../.." && pwd)}"
RAY_BIN="${RAY_QUANTUM_RAY_BIN:-/opt/ray-quantum/venv/bin/ray}"
PYTHON_BIN="${RAY_QUANTUM_PYTHON_BIN:-/opt/ray-quantum/venv/bin/python}"

test -x "${RAY_BIN}"
test -x "${PYTHON_BIN}"
test -d "${PROJECT_ROOT}/pivotq"
cd "${PROJECT_ROOT}"
"${RAY_BIN}" status
curl --fail --silent --show-error http://127.0.0.1:8265/api/version
echo
export RAY_QUANTUM_EXPECTED_HEAD_IP="${EXPECTED_HEAD_IP}"
export RAY_QUANTUM_EXPECTED_QPU_WORKER_IP="${EXPECTED_QPU_WORKER_IP}"
export RAY_QUANTUM_EXPECTED_MIN_NODES="${MIN_NODES}"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=:. "${PYTHON_BIN}" -c '
import os

import ray

expected_head_ip = os.environ["RAY_QUANTUM_EXPECTED_HEAD_IP"]
expected_qpu_worker_ip = os.environ["RAY_QUANTUM_EXPECTED_QPU_WORKER_IP"]
minimum_nodes = int(os.environ["RAY_QUANTUM_EXPECTED_MIN_NODES"])

ray.init(address="auto", logging_level="ERROR")
try:
    alive_nodes = [node for node in ray.nodes() if node.get("Alive")]
    if len(alive_nodes) < minimum_nodes:
        raise RuntimeError(
            f"expected at least {minimum_nodes} alive nodes, found {len(alive_nodes)}"
        )

    qpu_nodes = []
    nodes_by_address = {}
    for node in alive_nodes:
        address = str(node.get("NodeManagerAddress", ""))
        resources = node.get("Resources") or {}
        nodes_by_address[address] = resources
        cpu = float(resources.get("CPU", 0.0))
        gpu = float(resources.get("GPU", 0.0))
        qpu = float(resources.get("QPU", 0.0))
        print(f"NODE address={address} CPU={cpu:g} GPU={gpu:g} QPU={qpu:g}")
        if qpu > 0.0:
            qpu_nodes.append((address, qpu))

    if expected_head_ip not in nodes_by_address:
        raise RuntimeError(f"expected head node {expected_head_ip} is not alive")
    head_qpu = float(nodes_by_address[expected_head_ip].get("QPU", 0.0))
    if head_qpu != 0.0:
        raise RuntimeError(
            f"head node {expected_head_ip} must not advertise QPU; found {head_qpu:g}"
        )
    if len(qpu_nodes) != 1:
        raise RuntimeError(
            f"expected exactly one QPU resource node, found {qpu_nodes}"
        )
    qpu_address, qpu_capacity = qpu_nodes[0]
    if qpu_address != expected_qpu_worker_ip:
        raise RuntimeError(
            f"QPU resource is on {qpu_address}, expected laboratory QPU worker "
            f"{expected_qpu_worker_ip}"
        )
    if qpu_capacity != 1.0:
        raise RuntimeError(f"expected QPU capacity 1, found {qpu_capacity:g}")

    totals = ray.cluster_resources()
    total_cpu = float(totals.get("CPU", 0.0))
    total_gpu = float(totals.get("GPU", 0.0))
    total_qpu = float(totals.get("QPU", 0.0))
    print(
        "CLUSTER_RESOURCES "
        f"CPU={total_cpu:g} GPU={total_gpu:g} QPU={total_qpu:g}"
    )
    print(f"HEAD_RESOURCE_NODE={expected_head_ip}")
    print(f"QPU_RESOURCE_NODE={qpu_address}")
finally:
    ray.shutdown()
'
echo "CLUSTER_CHECK_RESULT=PASS"
