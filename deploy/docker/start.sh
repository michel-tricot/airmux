#!/usr/bin/env sh
set -eu

AIRMUX_CONSOLE_URL=${AIRMUX_CONSOLE_URL:-http://localhost:8080}
export AIRMUX_CONSOLE_URL

start_control_plane() {
  umask 077
  exec airmux control-plane serve --host "$1" --port 8000 --config "$AIRMUX_CONFIG"
}

start_data_plane() {
  exec airmux gateway serve --host "$1" --port 8081 --config "$AIRMUX_CONFIG"
}

start_console() {
  NGINX_RESOLVER=${NGINX_RESOLVER:-$(awk '$1 == "nameserver" { print $2; exit }' /etc/resolv.conf)}
  case "$NGINX_RESOLVER" in
    \[*\]) ;;
    *:*) NGINX_RESOLVER="[$NGINX_RESOLVER]" ;;
  esac
  PUBLIC_SCHEME=${AIRMUX_CONSOLE_URL%%:*}
  case "$PUBLIC_SCHEME" in
    http|https) ;;
    *) echo 'AIRMUX_CONSOLE_URL must start with http:// or https://' >&2; exit 1 ;;
  esac
  export NGINX_RESOLVER PUBLIC_SCHEME
  envsubst "\${CONTROL_PLANE_UPSTREAM} \${DATA_PLANE_UPSTREAM} \${NGINX_RESOLVER} \${PUBLIC_SCHEME}" \
    < /app/deploy/docker/nginx.conf.template > /tmp/airmux-nginx.conf
  exec nginx -c /tmp/airmux-nginx.conf -g 'daemon off;'
}

start_data_plane_after_control_plane() {
  until python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" >/dev/null 2>&1; do
    sleep 1
  done
  start_data_plane 127.0.0.1
}

case "${1:-}" in
  control-plane)
    start_control_plane 0.0.0.0
    ;;
  data-plane)
    start_data_plane 0.0.0.0
    ;;
  console)
    start_console
    ;;
  airmux)
    start_control_plane 127.0.0.1 &
    control_plane_pid=$!
    start_data_plane_after_control_plane &
    data_plane_pid=$!
    start_console &
    console_pid=$!
    ;;
  *)
    echo 'Expected airmux, console, control-plane, or data-plane' >&2
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
