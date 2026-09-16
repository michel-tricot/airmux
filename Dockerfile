ARG AIRMUX_PYTHON_BUILD=python-build

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS python-build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
COPY lib/api-models/pyproject.toml lib/api-models/
COPY lib/contract/pyproject.toml lib/contract/
COPY lib/runtime/pyproject.toml lib/runtime/
COPY apps/control-plane/pyproject.toml apps/control-plane/
COPY apps/cli/pyproject.toml apps/cli/
COPY apps/data-plane/pyproject.toml apps/data-plane/README.md apps/data-plane/
RUN uv sync --only-group backend --frozen --no-install-workspace
COPY lib/api-models lib/api-models
COPY lib/contract lib/contract
COPY lib/runtime lib/runtime
COPY apps/control-plane/src apps/control-plane/src
COPY apps/data-plane/src apps/data-plane/src
COPY apps/cli/src apps/cli/src
RUN uv sync --only-group backend --frozen

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS python-candidate
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
COPY lib/api-models/pyproject.toml lib/api-models/
COPY lib/contract/pyproject.toml lib/contract/
COPY lib/runtime/pyproject.toml lib/runtime/
COPY apps/control-plane/pyproject.toml apps/control-plane/
COPY apps/cli/pyproject.toml apps/cli/
COPY apps/data-plane/pyproject.toml apps/data-plane/README.md apps/data-plane/
RUN uv sync --only-group backend --frozen --no-install-workspace
COPY candidate/airmux-*.whl /tmp/candidate/
RUN uv pip install --python .venv/bin/python --no-deps /tmp/candidate/airmux-*.whl

FROM ${AIRMUX_PYTHON_BUILD} AS selected-python-build

FROM oven/bun:1 AS console-build
WORKDIR /app
COPY package.json bun.lock bunfig.toml tsconfig.json tsconfig.base.json ./
COPY lib/api-client-react lib/api-client-react
COPY lib/api-spec lib/api-spec
COPY apps/console apps/console
RUN bun install --frozen-lockfile
RUN bun run --filter '@workspace/gateway-console' build

FROM python:3.13-slim-bookworm AS image
RUN groupadd --system --gid 10001 airmux && useradd --system --uid 10001 --gid airmux --home-dir /state --shell /usr/sbin/nologin airmux \
    && mkdir -p /state/runtime /state/secrets /state/data-plane \
    && chown -R airmux:airmux /state \
    && apt-get update && apt-get install -y --no-install-recommends nginx gettext-base tini gosu \
    && rm -rf /var/lib/apt/lists/*
COPY --from=selected-python-build /app /app
COPY --from=console-build /app/apps/console/dist/public /usr/share/nginx/html
COPY deploy/docker /app/deploy/docker
COPY taxonomy/taxonomy.yml /app/taxonomy/taxonomy.yml
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 AIRMUX_CONFIG=/app/deploy/docker/airmux.yml \
    CONTROL_PLANE_UPSTREAM=127.0.0.1:8000 DATA_PLANE_UPSTREAM=127.0.0.1:8081 \
    AIRMUX_DATAPLANE_CONTROL_PLANE_URL=http://127.0.0.1:8000 FORWARDED_ALLOW_IPS=127.0.0.1
WORKDIR /state
EXPOSE 8000 8080 8081
ENTRYPOINT ["/app/deploy/docker/entrypoint.sh"]
CMD ["all-in-one"]
