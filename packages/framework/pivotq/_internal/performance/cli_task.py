import argparse
import sys
from pathlib import Path


from .common import empty_output, write_json, read_json
from .runner import PredictionRunner
from .task import compare_tasks, validate_comparison


def arguments():
    parser = argparse.ArgumentParser(description="Predict a custom task graph or compare caller-supplied GPU/QPU paths.")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--scenario", type=Path, help="Scenario YAML referencing a task graph JSON")
    modes.add_argument("--gpu-scenario", type=Path, help="GPU path; requires --qpu-scenario")
    parser.add_argument("--qpu-scenario", type=Path)
    parser.add_argument("--library", type=Path,
                        help="Shared library path; otherwise use environment configuration or the installed package")
    parser.add_argument("--out", type=Path, required=True, help="New or empty output directory")
    args = parser.parse_args()
    if bool(args.gpu_scenario) != bool(args.qpu_scenario):
        parser.error("Supply both --gpu-scenario and --qpu-scenario, or only --scenario")
    sources = ({"custom": args.scenario} if args.scenario else
               {"gpu": args.gpu_scenario, "qpu": args.qpu_scenario})
    for source in sources.values():
        if not source.is_file():
            parser.error(f"Scenario file does not exist: {source}")
    return args, sources


def main():
    args, sources = arguments()
    runner = PredictionRunner(library=args.library)
    empty_output(args.out)
    results = []
    prepared = {}
    for backend, source in sources.items():
        folder = args.out if backend == "custom" else args.out / backend
        result = runner.run_task(source, folder, backend=backend)
        prepared[backend] = {"nodes": read_json(folder / "inputs/task_graph.json")["nodes"]}
        results.append(result)
        print(f"{backend}: {result['latency_seconds']:.6f} s", flush=True)
    if len(results) == 2:
        validate_comparison(prepared)
        write_json(args.out / "comparison.json", compare_tasks(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
