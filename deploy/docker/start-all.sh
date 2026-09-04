#!/usr/bin/env sh
set -eu
/app/deploy/docker/initialize.sh
airllmcp serve --host 127.0.0.1 --port 8000 --config /app/deploy/docker/control-plane.yml &
control_plane_pid=$!
airllmdp serve --host 127.0.0.1 --port 8081 --config /app/deploy/docker/data-plane.yml &
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
