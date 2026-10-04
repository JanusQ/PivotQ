# PivotQ

PivotQ is a platform for hybrid quantum–classical scientific computing. It combines heterogeneous task execution, performance prediction, and a browser workspace. The included water-molecule AIMD application combines quantum circuits with a classical machine-learning potential.

## Project website

The public introduction website is maintained in [`website/`](website/README.md), with an overview of the framework, a usage guide, and interactive examples using saved results. Its GitHub Pages address will be [https://janusq.github.io/PivotQ/](https://janusq.github.io/PivotQ/) after the first deployment. See the [deployment guide](website/DEPLOYMENT.md) for setup and local preview instructions.

## Install

Run PivotQ with Docker, or install from source using uv.

### From Docker

Requires Docker with support for Linux x86-64 containers.

```bash
docker pull janusq/pivotq:latest

docker run --rm --init \
  --name pivotq \
  -p 127.0.0.1:8787:8787 \
  --shm-size=1g \
  -v pivotq-data:/data \
  janusq/pivotq:latest
```

Open [http://localhost:8787](http://localhost:8787) in your browser.

Run history and outputs are saved in the `pivotq-data` volume.

### Python library

Use Python 3.12. From the repository root:

```bash
python3.12 -m venv .venv-sdk
. .venv-sdk/bin/activate
python -m pip install ./packages/framework
python packages/framework/examples/hybrid_program.py
```

The library is installed and imported as `pivotq`. It provides CPU tasks,
quantum circuit execution, result references, and ordinary Python control flow:

```python
import pivotq as pq

def square(value):
    return value * value

with pq.Runtime() as runtime:
    answer = runtime.submit(square, 7)
    print(runtime.get(answer))  # 49
    runtime.release(answer)
```

QPU providers implement the common quantum backend interface and declare their
device capabilities. HTTP-based providers can use `"./packages/framework[qpu]"`
for HTTP client dependencies. The default quantum backend is a CPU simulator.
Complete SDK documentation lives inside the
website's [usage guide](website/src/content/docs/docs/index.md). See also the
[library README](packages/framework/README.md). This source installation does
not require the AIMD applications or dashboard.

The SDK also exposes reusable components and actors, explicit workflows,
execution reports, Ray Jobs, third-party quantum providers, and independent
CPU/QPU performance models. Run `system_workflow.py` or `custom_backend.py` in
`packages/framework/examples/` for complete CPU-only examples. Performance
prediction uses the bundled native engine and requires its compatible Linux
runtime. See the [API reference](website/src/content/docs/docs/api.md)
for the public programming interfaces.

## Features

- **Hybrid execution framework** — Schedule application components on CPU, GPU, and QPU resources, with hardware targets specified by the user.
- **Performance simulator** — Estimate execution time and resource utilization from task and hardware descriptions.
- **Water-molecule AIMD** — Run molecular dynamics with a quantum–classical potential and inspect energy curves and molecular trajectories.

The repository also includes the [ten-water application](applications/multi-h2o-aimd-v4/README.md), with a full 30-qubit CPU model, analytic-force short MD validation, and a real Ray Task/Actor energy pipeline. Its command-line runs require a large-memory host; the experimental model is not validated for scientific accuracy.

## Execution modes

Both Docker and source installations perform numerical calculations on the CPU by default. GPU and physical QPU execution require separately configured hardware services and dependencies. Performance predictions are estimates based on hardware parameters and are displayed separately from measured execution time.
