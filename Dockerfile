FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependency layer: only the manifests, so it stays cached until the lock or a pyproject changes.
# --no-install-workspace installs the third-party deps but not our own packages.
COPY pyproject.toml uv.lock ./
COPY packages/contract/pyproject.toml packages/contract/
COPY apps/cli/pyproject.toml apps/cli/
COPY apps/control-plane/pyproject.toml apps/control-plane/
COPY apps/data-plane/pyproject.toml apps/data-plane/
RUN uv sync --all-packages --no-dev --frozen --no-install-workspace

# Source layer: any code change invalidates this COPY, so the workspace packages are always
# reinstalled from current source, never served stale from the dependency layer.
COPY . .
RUN uv sync --all-packages --no-dev --frozen

FROM python:3.13-slim
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /state
