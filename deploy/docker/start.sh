#!/usr/bin/env sh
set -eu

prepare_control_plane() {
  umask 077
  mkdir -p /state/runtime /state/secrets
  if [ ! -f /state/runtime/dataplane.key ]; then
    tokkeeper control-plane bootstrap-keygen --out /state/runtime/dataplane.key
  fi
  DATABASE_URL="${DIRECT_DATABASE_URL:-$DATABASE_URL}" tokkeeper control-plane migrate --config /app/deploy/docker/migrate.yml
  tokkeeper control-plane taxonomy --config "$TOKKEEPER_CONFIG" --file /app/taxonomy/taxonomy.yml
}

start_control_plane() {
  exec tokkeeper control-plane serve --host "$1" --port 8000 --config "$TOKKEEPER_CONFIG"
}

start_data_plane() {
  exec tokkeeper gateway serve --host "$1" --port 8081 --config "$TOKKEEPER_CONFIG"
}

start_console() {
  NGINX_RESOLVER=${NGINX_RESOLVER:-$(awk '$1 == "nameserver" { print $2; exit }' /etc/resolv.conf)}
  case "$NGINX_RESOLVER" in
    \[*\]) ;;
    *:*) NGINX_RESOLVER="[$NGINX_RESOLVER]" ;;
  esac
  PUBLIC_SCHEME=${TOKKEEPER_CONSOLE_URL%%:*}
  case "$PUBLIC_SCHEME" in
    http|https) ;;
    *) echo 'TOKKEEPER_CONSOLE_URL must start with http:// or https://' >&2; exit 1 ;;
  esac
  export NGINX_RESOLVER PUBLIC_SCHEME
  envsubst '${CONTROL_PLANE_UPSTREAM} ${DATA_PLANE_UPSTREAM} ${NGINX_RESOLVER} ${PUBLIC_SCHEME}' \
    < /app/deploy/docker/nginx.conf.template > /tmp/tokkeeper-nginx.conf
  exec nginx -c /tmp/tokkeeper-nginx.conf -g 'daemon off;'
}

case "${1:-}" in
  control-plane)
    prepare_control_plane
    start_control_plane 0.0.0.0
    ;;
  data-plane)
    start_data_plane 0.0.0.0
    ;;
  console)
    start_console
    ;;
  all-in-one)
    prepare_control_plane
    start_control_plane 127.0.0.1 &
    control_plane_pid=$!
    start_data_plane 127.0.0.1 &
    data_plane_pid=$!
    start_console &
    console_pid=$!
    ;;
  *)
    echo 'Expected all-in-one, console, control-plane, or data-plane' >&2
    exit 2
    ;;
esac

shutdown() {
  trap - TERM INT
  kill "$control_plane_pid" "$data_plane_pid" "$console_pid" 2>/dev/null || true
  wait "$control_plane_pid" 2>/dev/null || true
  wait "$data_plane_pid" 2>/dev/null || true
  wait "$console_pid" 2>/dev/null || true
}
trap 'shutdown; exit 0' TERM INT
while kill -0 "$control_plane_pid" 2>/dev/null && kill -0 "$data_plane_pid" 2>/dev/null && kill -0 "$console_pid" 2>/dev/null; do
  sleep 1
done
shutdown
exit 1
