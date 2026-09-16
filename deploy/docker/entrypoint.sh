#!/usr/bin/env sh
set -eu

role=${1:-all-in-one}
if [ "$(id -u)" = 0 ]; then
  case "$role" in
    setup)
      mkdir -p /state/runtime /state/secrets
      chown 10001:10001 /state /state/runtime /state/secrets
      ;;
    control-plane)
      mkdir -p /state/secrets
      chown 10001:10001 /state /state/secrets
      ;;
    data-plane)
      mkdir -p /state/data-plane
      chown 10001:10001 /state /state/data-plane
      ;;
    all-in-one)
      mkdir -p /state/runtime /state/secrets /state/data-plane
      chown 10001:10001 /state /state/runtime /state/secrets /state/data-plane
      ;;
  esac
  chown 10001:10001 /dev/stdout /dev/stderr
  exec gosu 10001:10001 /usr/bin/tini -- /app/deploy/docker/start.sh "$role"
fi
exec /usr/bin/tini -- /app/deploy/docker/start.sh "$role"
