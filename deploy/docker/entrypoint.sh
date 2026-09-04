#!/usr/bin/env sh
set -eu
if [ "$(id -u)" = 0 ]; then
  mkdir -p /state/runtime /state/secrets /state/data-plane
  chown 10001:10001 /state /state/runtime /state/secrets /state/data-plane
  chown 10001:10001 /dev/stdout /dev/stderr
  exec gosu 10001:10001 /usr/bin/tini -- "$@"
fi
exec /usr/bin/tini -- "$@"
