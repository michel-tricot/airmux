#!/usr/bin/env sh
set -eu
umask 077
mkdir -p /state/runtime /state/secrets
if [ ! -f /state/runtime/dataplane.key ]; then
  airllmcp bootstrap-keygen --out /state/runtime/dataplane.key
fi
airllmcp taxonomy --config /app/deploy/docker/control-plane.yml --file /app/taxonomy/taxonomy.yml
