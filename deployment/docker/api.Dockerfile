# Two stages, a locked install of one workspace package, a non-root user,
# and a healthcheck on /healthz.
FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY om/pyproject.toml om/
COPY infra/pyproject.toml infra/
COPY services/api/pyproject.toml services/api/
# Every workspace member's manifest, so the frozen lock resolves; only the
# members this image runs are copied whole below.
COPY clients/python/pyproject.toml clients/python/
RUN uv sync --frozen --no-dev --package tadas-api --no-install-workspace
COPY om om
COPY infra infra
COPY services/api services/api
RUN uv sync --frozen --no-dev --package tadas-api

FROM python:3.14-slim
RUN useradd --create-home --uid 10001 tadas
WORKDIR /app
COPY --from=build --chown=tadas:tadas /app /app
COPY deployment/docker/entrypoint.sh /entrypoint.sh
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER tadas
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status == 200 else 1)"
ENTRYPOINT ["/entrypoint.sh"]
CMD ["tadas-api", "serve", "--host", "0.0.0.0", "--port", "8000"]
