FROM oven/bun:1 AS build
WORKDIR /app
COPY package.json bun.lock bunfig.toml tsconfig.json tsconfig.base.json ./
COPY lib lib
COPY apps/console apps/console
RUN bun install --frozen-lockfile
RUN bun run --filter '@workspace/gateway-console' build

FROM nginx:alpine
ENV CONTROL_PLANE_UPSTREAM=control-plane:8000 \
    DATA_PLANE_UPSTREAM=data-plane:8080 \
    NGINX_ENVSUBST_FILTER='^(CONTROL_PLANE_UPSTREAM|DATA_PLANE_UPSTREAM)$'
COPY --from=build /app/apps/console/dist/public /usr/share/nginx/html
COPY apps/console/nginx.conf /etc/nginx/templates/default.conf.template
