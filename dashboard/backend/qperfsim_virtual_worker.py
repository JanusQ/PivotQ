"""Application workload adapter for saved virtual hardware; native execution belongs to PivotQ."""
import os
from pathlib import Path


def predict(args):
    from pivotq._internal.performance.common import read_json, write_json, empty_output, read_csv
    from .qperfsim_virtual import build_virtual_case, frozen_classical_model

    payload = read_json(args.request)
    plan, program = payload["plan"], payload.get("program")
    parameters_path = Path(os.environ.get("FUSION_QPERFSIM_PARAMETERS", str(args.root / "examples/h2o/prediction_parameters.json")))
    parameters = read_json(parameters_path)
    classical_model = None
    if plan["task_id"] == "h2o-hybrid-aimd" and any(s["id"] == "classical_predict" and s["device"] == "cpu" for s in plan["stages"]):
        from .program import checkpoint_path
        classical_model = frozen_classical_model(checkpoint_path(plan["normalized_inputs"]), (program or {}).get("checkpoint_sha256"))
    graph, scene, request, scope = build_virtual_case(plan, program, parameters, classical_model=classical_model)
    empty_output(args.out)
    inputs = args.out / "source"
    inputs.mkdir()
    write_json(inputs / "task_graph.json", graph)
    write_json(inputs / "request.json", request)
    write_json(inputs / "parameters.json", parameters)
    (inputs / "scenario.yaml").write_text(scene, encoding="utf-8")
    result = {"scenario_path": str(inputs / "scenario.yaml"), "scenario_yaml": scene,
              "task_graph_path": str(inputs / "task_graph.json"), "task_graph": graph,
              "output_dir": str(args.out), "request": request, "model_scope": scope}
    if not args.preview:
        from pivotq._internal.performance.runner import PredictionRunner
        prediction = PredictionRunner(library=args.library).run_task(inputs / "scenario.yaml", args.out / "native", backend="qpu")
        summary = read_csv(args.out / "native/output/summary.csv")[0]
        prediction.update(request)
        prediction["task_completion_ratio"] = float(summary["task_completion_ratio"])
        prediction["stage_seconds"] = {}
        for name, seconds in prediction["phase_seconds"].items():
            stage = name.rsplit(".", 1)[-1]
            prediction["stage_seconds"][stage] = prediction["stage_seconds"].get(stage, 0) + seconds
        prediction["qpu_acquisition_seconds"] = (prediction["device_node_seconds"].get("QPU", 0)
            - request["qpu_batch_count"] * request["target_snapshot"]["parameters"]["submit_latency_us"] / 1e6)
        prediction["end_to_end_circuits_per_second"] = request["circuits"] / prediction["latency_seconds"]
        prediction["end_to_end_shots_per_second"] = request["circuits"] * request["shots"] / prediction["latency_seconds"]
        prediction["model_parameter_sources"] = scope["parameter_sources"]
        write_json(args.out / "native/prediction.json", prediction)
        result["result"] = {"prediction": prediction, "interface": "task_prediction",
                            "files": sorted(p.name for p in (args.out / "native/output").glob("*.csv")),
                            "wall_clock_s": prediction["simulator_wall_seconds"]}
    write_json(args.out / "platform_result.json", result)

    return result
