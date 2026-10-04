# Integration tests

## System SDK extension (2026-10-04)

[System SDK evidence](evidence/pivotq_system_sdk_20261004.json) records the public
component/Actor, Workflow, Provider, Jobs, report and independent prediction
acceptance. It includes wheel/sdist/editable resource checks, real local Ray,
Dashboard offline prediction, and both website deployment paths. The older
SDK migration and scientific experiment records remain separate.

From `packages/framework`, run the relevant SDK integrations:

```bash
../../.venv/bin/python -m pytest tests/integration/test_sdk_ray_script.py tests/integration/test_sdk_provider_ray.py tests/integration/test_clean_core_package.py -q
PIVOTQ_TEST_JOBS=1 ../../.venv/bin/python -m pytest tests/integration/test_sdk_jobs_service.py -q
PIVOTQ_RUN_NATIVE_PREDICTIONS=1 ../../.venv/bin/python -m pytest tests/integration/test_performance_native.py -q
```

The last command requires a compatible native runtime. On older Linux systems,
set `FUSION_QPERFSIM_RUNTIME` to an existing compatible directory first. This
acceptance used Ubuntu 22.04 with that explicit configuration, not an Ubuntu
24.04 host. No physical QPU or full scientific experiment is part of these tests.
The recorded 29 legacy QASM test failures and four single-water fake-bridge
failures match the earlier baseline.

## Application bridge

`test_framework_aimd.py` verifies the real boundary between `pivotq._internal` and `single_h20_aimd`. It starts isolated local Ray, registers the AIMD F2 CPU quantum component in the real framework, submits the existing H2O request through `FusionExecutionClient`, and verifies the returned 14-feature shape.

Run it from the repository root in the unified environment:

```bash
uv run --locked python -B -m unittest discover -s tests/integration -v
```

Run the complete single-water chain with framework simulation enabled:

```bash
uv run --locked python -B tests/integration/run_cpu_aimd.py --steps 1000
```

The application retains its QPU quantum request and GPU classical Actor request.
`FusionFramework(simulation=True)` replaces components whose hardware is
unavailable with registered CPU simulators. The default `--quantum-target qpu`
uses the QPU circuit service and a persistent simulated QPU Actor, returning
exact circuit probabilities. `--quantum-target gpu` instead exercises the
application's GPU quantum Task route through its CPU statevector simulator:

```bash
uv run --locked python -B tests/integration/run_cpu_aimd.py --quantum-target gpu --steps 10
```

Both routes use real Ray scheduling, a persistent classical Actor, the framework
Driver, Cartesian central finite differences, ASE NVE integration, diagnostics,
figures, and artifact packaging. The framework-owned bridge is
`pivotq._internal.integrations.h2o`; the launcher does not add a CPU target to the
application configuration or modify its GPU/QPU scheduling declarations.

The default is the frozen 300 K, 0.1 fs, 1000-step experiment. A smaller
`--steps` value is a temporary smoke-test override; configuration and checkpoint
files are never rewritten. Optional `--run-id` and `--output-dir` select output
names; the default directory is
`applications/h2o-hybrid-aimd/outputs/integration/<generated-run-id>/`.

`validation.json` checks scientific acceptance, trajectory and log frame counts,
artifact hashes, successful task and actor traces, stable Actor IDs, and cleanup.
The Driver manifest and trace explicitly distinguish requested GPU/QPU devices
from effective CPU execution and record why a simulator was selected. Validation
also checks that the application's original hardware schedule was preserved.
Before Ray starts, the launcher records SHA-256 hashes for all framework and
application Python source files, the root dependency files, this launcher, the
frozen configuration and checkpoint. It hashes them again after shutdown and
requires the complete manifest to match. `validation.json` includes these
hashes, any differences, and the starting Git commit, branch and working status.
The complete Driver manifest, AIMD result, invocation trace,
trajectory, CSV logs, PNG figures and result archive remain in that directory.
Ray logs remain in the unique temporary directory recorded in `validation.json`.

The launcher creates its own local Ray cluster with four CPU slots and no GPUs,
and closes only that cluster. It does not attach to an existing cluster, start
training, or contact a QPU. QPU simulation returns exact probabilities without
finite-shot sampling; the original requested shot count remains audit metadata.
Ray Jobs HTTP submission, actual GPU/QPU execution, and the performance simulator
are outside this check.

## Verified framework simulation (2026-10-02)

The original AIMD application and its tests remained unchanged. On Ubuntu
22.04.5 x86-64 / Python 3.12.13, the full QPU-request run
`sim-qpu-full-20261002` passed using the root locked environment:

| Check | Result |
| --- | --- |
| Frozen NVE trajectory | 1000 steps, 1001 frames, 100 fs |
| Scientific acceptance | 14/14 passed; full-length linear-drift gate applied |
| Framework, trajectory, artifacts and source checks | 19/19 passed |
| Requested execution | QPU quantum circuit service + GPU classical Actor |
| Actual execution | CPU Qiskit exact probabilities + CPU PyTorch |
| Simulated QPU Actor invocations | 1003 succeeded |
| Classical Actor invocations | 1003 calls, one create and one terminate; all succeeded |
| Circuit work, including force preflight | 19343 geometries, 38686 X/Z circuit settings |
| Physical QPU executions | 0; no sampling or noise |
| Absolute initial-to-final energy change | 0.0000828634 eV (limit 0.005 eV) |
| Total-energy range | 0.000431468 eV (limit 0.010 eV) |
| Absolute linear energy drift | 0.0000480172 eV/ps (limit 0.05 eV/ps) |
| Source/configuration/checkpoint manifest | All 110 files unchanged during execution |
| Cleanup | Both persistent Actors cleaned up; local Ray shut down |
| GPU-request simulation smoke | 10 steps; 17 integration and 14 scientific checks passed |

The [current evidence summary](evidence/simulation_aimd_20261002.json) contains
the full scientific metrics, execution selections, environment versions, Git
baseline, source hashes and result hashes. Full local outputs are under
`applications/h2o-hybrid-aimd/outputs/integration/sim-qpu-full-20261002/`.
An independent read-back check verified the trajectory, source/artifact hashes,
archive and cleanup; its maximum coordinate difference from the historical CPU
trajectory was approximately `3.49e-14 Å`.

Focused validation passed: four H2O simulation parity tests and the real-Ray
framework/AIMD integration test. The final framework unit run reported 303
passed, 29 failed, 3 skipped, and 140 passed subtests; the same 29 failures also
occurred on the isolated starting Git HEAD. The unmodified application suite
reported 47 passed and four fake-framework `StringMetadata` conversion errors.
These existing suite failures are recorded in the evidence rather than being
reported as passing tests. Dependency and lock checks passed.

## Historical CPU run (2026-10-01)

This record belongs to the earlier application-level CPU adaptation, before
framework simulation mode was introduced. That adaptation has been superseded;
these results do not validate the current GPU/QPU-request simulation route.
The command and launcher hash in the evidence describe the version used at the
time. Running the current command executes the new framework simulation route.

Ubuntu 22.04.5 x86-64 / Python 3.12.13, using the root locked environment:

| Check | Result |
| --- | --- |
| Frozen NVE trajectory | 1000 steps, 1001 frames, 100 fs |
| Scientific acceptance | 14/14 passed |
| Framework/trajectory/artifact checks | 11/11 passed |
| CPU quantum Task invocations | 1003 succeeded |
| Persistent CPU classical Actor | 1003 calls, one create and one terminate, all succeeded |
| Absolute initial-to-final total-energy change | 0.0000828634 eV (limit 0.005 eV) |
| Total-energy range | 0.000431468 eV (limit 0.010 eV) |
| Absolute linear energy drift | 0.0000480172 eV/ps (limit 0.05 eV/ps) |
| Application contract/bridge/standalone tests | 23 passed |
| Framework AIMD integration test | 1 passed |
| Dependency and lock checks | passed |

The checkpoint and original scientific configuration hashes were unchanged.
The Driver and its actor cleaned up successfully, and the launcher shut down
its local Ray instance. Existing ASE/NumPy deprecation and Ray resource warnings
did not fail the checks.

The historical CPU acceptance record from 2026-10-01 is archived outside the public
repository. The current [simulation evidence](evidence/simulation_aimd_20261002.json)
records versions, checks, source hashes and result hashes. Full local outputs are under
`applications/h2o-hybrid-aimd/outputs/integration/cpu-fusion-20261001/`, which is
ignored by Git. A new run creates its own result directory and validation record.
