FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY . .
RUN uv sync --all-packages --no-dev --frozen

FROM python:3.13-slim
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /state
