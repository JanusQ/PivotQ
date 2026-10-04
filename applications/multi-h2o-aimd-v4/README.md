# Ten-water quantum–classical AIMD

This PivotQ application models ten interacting water molecules (30 atoms) with a full 30-qubit circuit, 48 shared quantum parameters, 60 X/Z expectation features, and a 60→64→32→1 tanh energy head. It includes the original frozen energy model, an experimental analytic-force model, the complete 5,000-configuration MB-pol dataset, and the existing fusion-framework interface.

The migration source is qhai-2026 commit `f9a3de008cd428e098b5d6ff688bc0c57da43145`. Resource hashes and source paths are recorded in `provenance/migration_manifest.json`. Inference runs entirely from this application and does not require the old repository or servers.

## Install

From the PivotQ repository root on Linux x86-64:

```bash
uv sync --locked
```

Python 3.12 is selected by the root project. Analytic forces require `g++` with C++17 and OpenMP; the Dockerfile includes it. Native kernels compile into each run's output directory. The application is installed editable, alongside `pivotq`, so the complete model and data resources remain in the application directory.

## Models and validation scope

- `models/final/best_model.json` is the original frozen energy model selected at epoch 6. Its historical metrics came from MPS training; current CPU inference uses full double-precision statevector simulation. Its encoding includes the historical angle floor.
- `models/experimental/current_model.json` uses the later continuous encoding and analytic derivatives. It has only 11 completed updates and is **not converged**. It is retained for software execution checks, not accuracy claims.
- `dataset_water10_mbpol_v1/` contains the complete frozen data package, including labels, source records, and manifests. Labels are MB-pol/MBX, not DFT.

Neither model is retrained by the commands below. Results carry `scientific_status=not_validated`; successful execution does not establish accurate forces, energy conservation, or physical-QPU readiness.

## Verify frozen resources and run light tests

From the PivotQ repository root:

```bash
uv run --locked python -B applications/multi-h2o-aimd-v4/scripts/verify_migration.py
uv run --locked python -B -m pytest applications/multi-h2o-aimd-v4/tests -q
```

The default pytest configuration excludes tests marked `heavy`. Small-system Qiskit/parameter-shift checks verify the derivative implementation without allocating a 30-qubit state. The real runs below provide separate execution evidence.

The source dataset's historical `code/verify_package.py` does not pass even on the original Git snapshot: its manifests reference omitted logs and several different file hashes. `provenance/source_dataset_audit.json` records these inherited discrepancies. Migration validation uses the exact source-commit hashes and checks the HDF5 structure; the frozen dataset and its historical manifests are preserved byte-for-byte.

## Real CPU short MD run

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --locked python -B \
  applications/multi-h2o-aimd-v4/scripts/run_smoke.py \
  --output-dir applications/multi-h2o-aimd-v4/outputs/smoke-001 \
  --threads 8
```

This runs the experimental model on the supplied ten-water geometry, computes analytic forces, and performs one 0.1 fs VelocityVerlet step at 300 K (seed 916). The initial and final frames contain all 30 atoms. It uses full complex128 statevectors, one worker, and at least 96 GiB of available memory after considering host and cgroup limits. Historical execution took about 15 minutes per energy/force query on a different host; actual timing is recorded for the current machine.

The short-run entry point loads all saved quantum and classical weights. It does not invoke training, MBX reference evaluation, or the formal 50 fs workflow. The formal workflow's convergence requirement remains in place.

## Real Ray energy pipeline

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --locked python -B \
  tests/integration/run_cpu_water10.py \
  --output-dir applications/multi-h2o-aimd-v4/outputs/ray-001 \
  --smoke-output applications/multi-h2o-aimd-v4/outputs/smoke-001
```

The runner starts a local Ray instance and runs actual CPU quantum Tasks followed by a persistent classical Actor, with `simulation=False`. It evaluates the original frozen model and the experimental model once each. The experimental energy is compared to the same model and geometry in the independent MD initial frame, with a maximum absolute difference of `1e-6 eV`.

The independent short MD does not run through Ray; this command validates the framework energy pipeline. The original fusion finite-difference force/MD interface is retained, but a one-step trajectory through that route requires about 362 full 30-qubit evaluations and is not the default smoke test.

`configs/fusion_cpu.json` is a portable application-relative template. The new runner writes a resolved absolute-path configuration into its run directory before invoking the existing framework Driver. For distributed deployment, model/config/input paths must be visible to all workers; see `water10_v4/integration/fusion_framework/BRIDGE.md`. The built-in three-qubit QPU service cannot execute this application.

## Outputs

Use a new output directory for every run. Outputs include finite-value and shape checks, runtime/peak-memory records, dependency versions, input/model hashes, trajectory frames, framework traces, and artifact hashes. Generated output and native libraries are ignored by Git. A compact record of the completed migration validation is kept in `provenance/` when the real runs finish.

The other migrated training, server synchronization, and circuit-export scripts are historical tools, outside the smoke workflow. Some execute actions when imported; use the documented entry points above for validation.

## Measured validation on 2026-10-03

[Validation record](provenance/runtime_validation_20261003.json): 83 application tests and 8 single-water/framework regression tests passed. The real 30-qubit analytic-force run completed one step and two frames in 1,920 seconds, with a 32.3 GiB peak RSS. Both Ray energy runs passed Task/Actor trace, input/output hash, and cleanup checks; quantum execution took 121 seconds for the frozen model and 106 seconds for the experimental model. The independent and Ray experimental energies differed by `1.461e-13 eV` (required tolerance: `1e-6 eV`). These measurements validate software execution only.

The Python wheel was built and its native kernel source verified. Docker build configuration was updated, but an image build was not run because this host has no Docker executable.
