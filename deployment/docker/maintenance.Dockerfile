# Same shape as a service image, no exposed port.
FROM python:3.13-slim AS build
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

FROM python:3.13-slim
RUN useradd --create-home --uid 10001 tadas
WORKDIR /app
COPY --from=build --chown=tadas:tadas /app /app
COPY deployment/docker/entrypoint.sh /entrypoint.sh
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER tadas
ENTRYPOINT ["/entrypoint.sh"]
CMD ["tadas-maintenance", "serve"]
