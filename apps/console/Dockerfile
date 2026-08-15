FROM oven/bun:1 AS build
WORKDIR /app
COPY package.json bun.lock bunfig.toml tsconfig.json tsconfig.base.json ./
COPY lib lib
COPY apps/console apps/console
RUN bun install --frozen-lockfile
RUN bun run --filter '@workspace/gateway-console' build

FROM nginx:alpine
COPY --from=build /app/apps/console/dist/public /usr/share/nginx/html
COPY apps/console/nginx.conf /etc/nginx/conf.d/default.conf
