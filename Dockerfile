FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY dashboard/frontend/package*.json ./
RUN npm ci
COPY dashboard/frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.12.2 AS uv
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates libgomp1 libstdc++6 g++ \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /uvx /usr/local/bin/
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY packages/ ./packages/
COPY applications/h2o-hybrid-aimd/ ./applications/h2o-hybrid-aimd/
RUN uv sync --locked --no-dev
COPY dashboard/ ./dashboard/
COPY --from=frontend /build/dist/ ./dashboard/frontend/dist/
ENV FUSION_EXECUTOR=local_cpu \
    FUSION_API_HOST=0.0.0.0 \
    FUSION_API_PORT=8787 \
    QPERFSIM_ROOT=/app/packages/perf-sim \
    FUSION_RUN_HISTORY_FILE=/data/runtime-state/runs.json \
    FUSION_DEVICE_STATE_FILE=/data/runtime-state/devices.json \
    FUSION_REGISTRATION_TOKEN_FILE=/data/secrets/registration.token \
    FUSION_RAY_OUTPUT_ROOT=/data/outputs \
    FUSION_PERF_OUTPUT_ROOT=/data/performance \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
EXPOSE 8787
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/v1/system/status', timeout=3)"]
STOPSIGNAL SIGTERM
ENTRYPOINT ["/app/.venv/bin/python", "dashboard/serve.py", "--host", "0.0.0.0", "--no-open"]
