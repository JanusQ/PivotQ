"""Read-only health/profile audit. Never submit a circuit or guess mapping."""
import argparse
import json
import os
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from water20.hardware import HardwareProfile


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default=os.environ.get("QPU_DEVICE_URL"))
    p.add_argument("--profile", type=Path, default=ROOT/"configs/hardware_profile.template.json")
    p.add_argument("--output", type=Path, default=ROOT/"reports/hardware_preflight.json")
    args = p.parse_args()
    report = dict(schema_version=1, host=platform.node(), required_qubits=60, submitted_jobs=0,
                  real_qpu_validated=False, checks={}, ready=False)
    try:
        profile = HardwareProfile.load(args.profile)
        report["checks"]["profile"] = "passed"
    except Exception as exc:
        report["checks"]["profile"] = str(exc)
    if args.url:
        try:
            key = os.environ.get("QPU_DEVICE_API_KEY", "")
            response = httpx.get(args.url.rstrip("/")+"/health", timeout=5, trust_env=False,
                                 headers={"Authorization": f"Bearer {key}"} if key else {})
            response.raise_for_status()
            health = response.json()
            report["health"] = health
            report["checks"]["http_health"] = "passed" if health.get("status") == "ok" and health.get("backend") == "circuit" else "failed"
        except Exception as exc:
            report["checks"]["http_health"] = type(exc).__name__
    else:
        report["checks"]["http_health"] = "QPU_DEVICE_URL not configured"
    report["ready"] = all(value == "passed" for value in report["checks"].values())
    report["remaining_hardware_evidence"] = ["60-qubit connected topology and native gate/depth budgets",
        "register-slot/readout mapping and per-wire excitation probes", "joint-readout correlation probe",
        "successful execution of the actual global application circuit"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))
