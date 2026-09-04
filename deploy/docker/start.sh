#!/usr/bin/env sh
set -eu
case "${1:-all}" in
  data-plane)
    exec airllmdp serve --host 0.0.0.0 --port 8081 --config "$GW_CONFIG"
    ;;
  all|control-plane) ;;
  *) echo 'Expected all, control-plane, or data-plane' >&2; exit 2 ;;
esac

umask 077
mkdir -p /state/runtime /state/secrets
if [ ! -f /state/runtime/dataplane.key ]; then
  airllmcp bootstrap-keygen --out /state/runtime/dataplane.key
fi
DATABASE_URL="${DIRECT_DATABASE_URL:-$DATABASE_URL}" airllmcp migrate --config /app/deploy/docker/migrate.yml
airllmcp taxonomy --config "$GW_CONFIG" --file /app/taxonomy/taxonomy.yml
if [ "${1:-all}" = control-plane ]; then
  exec airllmcp serve --host 0.0.0.0 --port 8000 --config "$GW_CONFIG"
fi

airllmcp serve --host 127.0.0.1 --port 8000 --config "$GW_CONFIG" &
control_plane_pid=$!
airllmdp serve --host 127.0.0.1 --port 8081 --config "$GW_CONFIG" &
data_plane_pid=$!
/app/deploy/docker/start-console.sh &
console_pid=$!

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
