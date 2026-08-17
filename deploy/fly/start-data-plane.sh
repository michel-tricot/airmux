#!/usr/bin/env sh
set -eu

while [ ! -s /state/.airllm/dataplane.key ]; do
  echo "waiting for airllm quickstart to connect the data plane"
  sleep 2
done

exec airllmdp serve --host 0.0.0.0 --port 8081 --config /app/deploy/fly/airllm.yml
