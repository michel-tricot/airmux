FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS python-build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
COPY lib/api-models/pyproject.toml lib/api-models/
COPY lib/contract/pyproject.toml lib/contract/
COPY apps/cli/pyproject.toml apps/cli/
COPY apps/control-plane/pyproject.toml apps/control-plane/
COPY apps/data-plane/pyproject.toml apps/data-plane/
RUN uv sync --only-group backend --frozen --no-install-workspace
COPY lib/api-models lib/api-models
COPY lib/contract lib/contract
COPY apps/cli/src apps/cli/src
COPY apps/control-plane/alembic.ini apps/control-plane/
COPY apps/control-plane/migrations apps/control-plane/migrations
COPY apps/control-plane/src apps/control-plane/src
COPY apps/data-plane/src apps/data-plane/src
RUN uv sync --only-group backend --frozen

FROM oven/bun:1 AS console-build
WORKDIR /app
COPY package.json bun.lock bunfig.toml tsconfig.json tsconfig.base.json ./
COPY lib/api-client-react lib/api-client-react
COPY lib/api-spec lib/api-spec
COPY lib/api-zod lib/api-zod
COPY apps/console apps/console
RUN bun install --frozen-lockfile
RUN bun run --filter '@workspace/gateway-console' build

FROM python:3.13-slim-bookworm AS runtime
RUN groupadd --system --gid 10001 airllm && useradd --system --uid 10001 --gid airllm --home-dir /state --shell /usr/sbin/nologin airllm \
    && mkdir -p /state/runtime /state/secrets /state/data-plane \
    && chown -R airllm:airllm /state
COPY --from=python-build /app /app
COPY deploy/docker /app/deploy/docker
COPY taxonomy/taxonomy.yml /app/taxonomy/taxonomy.yml
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 AIRLLM_CONFIG=/app/deploy/docker/airllm.yml
WORKDIR /state
USER 10001:10001

FROM runtime AS control-plane
EXPOSE 8000
CMD ["/app/deploy/docker/start.sh", "control-plane"]

FROM runtime AS data-plane
EXPOSE 8081
CMD ["/app/deploy/docker/start.sh", "data-plane"]

FROM nginx:stable-bookworm AS console
COPY --from=console-build /app/apps/console/dist/public /usr/share/nginx/html
COPY deploy/docker/nginx.conf.template /app/deploy/docker/nginx.conf.template
COPY deploy/docker/start.sh /app/deploy/docker/start.sh
ENV CONTROL_PLANE_UPSTREAM=control-plane:8000 DATA_PLANE_UPSTREAM=data-plane:8081 AIRLLM_CONSOLE_URL=http://localhost:8080
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["/app/deploy/docker/start.sh"]
CMD ["console"]

FROM runtime AS all-in-one
USER root
RUN apt-get update && apt-get install -y --no-install-recommends nginx gettext-base tini gosu \
    && rm -rf /var/lib/apt/lists/*
COPY --from=console-build /app/apps/console/dist/public /usr/share/nginx/html
ENV CONTROL_PLANE_UPSTREAM=127.0.0.1:8000 DATA_PLANE_UPSTREAM=127.0.0.1:8081 \
    AIRLLM_DATAPLANE_CONTROL_PLANE_URL=http://127.0.0.1:8000 FORWARDED_ALLOW_IPS=127.0.0.1
EXPOSE 8080
ENTRYPOINT ["/app/deploy/docker/entrypoint.sh"]
CMD ["/app/deploy/docker/start.sh", "all-in-one"]
