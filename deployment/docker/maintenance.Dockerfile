# Same shape as a service image, no exposed port. The healthcheck is the
# worker's own `health` subcommand, which reads the liveness key the loop
# heartbeats into the cache.
FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY om/pyproject.toml om/
COPY infra/pyproject.toml infra/
COPY workers/maintenance/pyproject.toml workers/maintenance/
RUN uv sync --frozen --no-dev --package tadas-maintenance --no-install-workspace
COPY om om
COPY infra infra
COPY workers/maintenance workers/maintenance
RUN uv sync --frozen --no-dev --package tadas-maintenance

FROM python:3.14-slim
RUN useradd --create-home --uid 10001 tadas
WORKDIR /app
COPY --from=build --chown=tadas:tadas /app /app
COPY deployment/docker/entrypoint.sh /entrypoint.sh
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER tadas
# The entrypoint execs `serve` as PID 1, so its default worker id is
# maintenance-<hostname>-1; an explicit TADAS_WORKER_ID wins.
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s \
  CMD tadas-maintenance health --worker-id "${TADAS_WORKER_ID:-maintenance-$(cat /etc/hostname)-1}"
ENTRYPOINT ["/entrypoint.sh"]
CMD ["tadas-maintenance", "serve"]
