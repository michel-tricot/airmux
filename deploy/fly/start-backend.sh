#!/usr/bin/env sh
set -eu

umask 077
mkdir -p /state/.airllm/secrets

if [ ! -f /state/.airllm/signing.key ]; then
  airllmcp keygen --out /state/.airllm/signing.key
fi

airllmcp taxonomy --config /app/deploy/fly/airllm.yml --file ../../taxonomy/taxonomy.yml

airllmcp serve --host 0.0.0.0 --port 8000 --config /app/deploy/fly/airllm.yml &
control_plane_pid=$!
/app/deploy/fly/start-data-plane.sh &
data_plane_pid=$!

shutdown() {
  trap - TERM INT
  kill "$control_plane_pid" "$data_plane_pid" 2>/dev/null || true
  wait "$control_plane_pid" 2>/dev/null || true
  wait "$data_plane_pid" 2>/dev/null || true
  exit 0
}

trap shutdown TERM INT

while kill -0 "$control_plane_pid" 2>/dev/null && kill -0 "$data_plane_pid" 2>/dev/null; do
  sleep 1
done

trap - TERM INT
kill "$control_plane_pid" "$data_plane_pid" 2>/dev/null || true
wait "$control_plane_pid" 2>/dev/null || true
wait "$data_plane_pid" 2>/dev/null || true
exit 1
