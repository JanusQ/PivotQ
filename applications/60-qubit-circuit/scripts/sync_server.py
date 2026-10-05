"""Synchronize only this application and compare every persistent file hash."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
HOST = "109-32cpu"
REMOTE = "/home/hzhang/code/PivotQ/applications/60-qubit-circuit"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ClearAllForwardings=yes", "-o", "ConnectTimeout=15"]
EXCLUDED = {"__pycache__", ".pytest_cache", ".DS_Store", "build", "dist"}


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and not set(p.parts)&EXCLUDED and not any(part.endswith(".egg-info") for part in p.parts)
            and str(p.relative_to(root)) != "reports/synchronization.json"}


def main(mode):
    if ROOT.name != "60-qubit-circuit":
        raise RuntimeError("Refusing to synchronize a different application")
    if mode in ("push", "pull"):
        source, destination = (str(ROOT)+"/", HOST+":"+REMOTE+"/") if mode == "push" else (HOST+":"+REMOTE+"/", str(ROOT)+"/")
        # --delete is confined to this dedicated application; environments,
        # libraries and logs live in the external PivotQ-runtime directory.
        subprocess.run(["rsync", "-az", "--delete", "-e", " ".join(SSH),
                        *[f"--exclude={name}" for name in EXCLUDED], "--exclude=*.egg-info", source, destination], check=True)
    code = "import pathlib,hashlib,json\nroot=pathlib.Path("+repr(REMOTE)+")\n"
    code += "excluded="+repr(EXCLUDED)+"\n"
    code += "print(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file() and not set(p.parts)&excluded and not any(part.endswith('.egg-info') for part in p.parts) and str(p.relative_to(root))!='reports/synchronization.json'}))\n"
    remote = json.loads(subprocess.run([*SSH, HOST, "python3", "-"], input=code, capture_output=True, text=True, check=True).stdout)
    local = hashes(ROOT)
    differences = [key for key in sorted(set(local)|set(remote)) if local.get(key) != remote.get(key)]
    report = dict(host=HOST, remote_application=REMOTE, local_application=str(ROOT), mode=mode,
                  identical=not differences, file_count=len(local), persistent_bytes=sum(p.stat().st_size for p in ROOT.rglob("*") if p.is_file() and not set(p.parts)&EXCLUDED and not any(part.endswith(".egg-info") for part in p.parts)),
                  aggregate_sha256=hashlib.sha256(json.dumps(local, sort_keys=True).encode()).hexdigest(),
                  differences=differences, excluded_control_file="reports/synchronization.json")
    path = ROOT/"reports/synchronization.json"
    path.write_text(json.dumps(report, indent=2)+"\n")
    subprocess.run(["rsync", "-az", "-e", " ".join(SSH), str(path), HOST+":"+REMOTE+"/reports/"], check=True)
    print(json.dumps(report, indent=2))
    if differences:
        raise RuntimeError("Local/server file hashes differ")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("push", "pull", "check"))
    main(p.parse_args().mode)
