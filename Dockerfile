FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependency layer: only the manifests, so it stays cached until the lock or a pyproject changes.
# --no-install-workspace installs the third-party deps but not our own packages.
COPY pyproject.toml uv.lock ./
COPY lib/api-models/pyproject.toml lib/api-models/
COPY lib/contract/pyproject.toml lib/contract/
COPY apps/cli/pyproject.toml apps/cli/
COPY apps/control-plane/pyproject.toml apps/control-plane/
COPY apps/data-plane/pyproject.toml apps/data-plane/
RUN uv sync --only-group backend --frozen --no-install-workspace

# Source layer: any code change invalidates this COPY, so the workspace packages are always
# reinstalled from current source, never served stale from the dependency layer.
COPY . .
RUN uv sync --only-group backend --frozen

FROM python:3.13-slim
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH"
RUN groupadd --system --gid 10001 airllm && useradd --system --uid 10001 --gid airllm --home-dir /state --shell /usr/sbin/nologin airllm && mkdir -p /state && chown airllm:airllm /state
WORKDIR /state
USER 10001:10001
