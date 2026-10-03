# PivotQ

PivotQ is a platform for hybrid quantum–classical scientific computing. It combines heterogeneous task execution, performance prediction, and a browser workspace. The included water-molecule AIMD application combines quantum circuits with a classical machine-learning potential.

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

## Features

- **Hybrid execution framework** — Schedule application components on CPU, GPU, and QPU resources, with hardware targets specified by the user.
- **Performance simulator** — Estimate execution time and resource utilization from task and hardware descriptions.
- **Water-molecule AIMD** — Run molecular dynamics with a quantum–classical potential and inspect energy curves and molecular trajectories.

The repository also includes the [ten-water application](applications/multi-h2o-aimd-v4/README.md), with a full 30-qubit CPU model, analytic-force short MD validation, and a real Ray Task/Actor energy pipeline. Its command-line runs require a large-memory host; the experimental model is not validated for scientific accuracy.

## Execution modes

Both Docker and source installations perform numerical calculations on the CPU by default. GPU and physical QPU execution require separately configured hardware services and dependencies. Performance predictions are estimates based on hardware parameters and are displayed separately from measured execution time.
