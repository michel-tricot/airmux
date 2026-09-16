#!/usr/bin/env sh
set -eu

: "${AIRMUX_PUBLIC_URL:?Set AIRMUX_PUBLIC_URL}"

CURL=${CURL:-curl}
AIRMUX_PUBLIC_URL=${AIRMUX_PUBLIC_URL%/}
SMOKE_ATTEMPTS=${SMOKE_ATTEMPTS:-30}
SMOKE_DELAY_SECONDS=${SMOKE_DELAY_SECONDS:-2}

check() {
  label=$1
  expected=$2
  shift 2
  attempt=0
  while [ "$attempt" -lt "$SMOKE_ATTEMPTS" ]; do
    status=$("$CURL" --silent --show-error --output /dev/null --write-out '%{http_code}' --connect-timeout 5 --max-time 10 "$@" || true)
    case " $expected " in
      *" $status "*)
        printf '%s: %s\n' "$label" "$status"
        return
        ;;
    esac
    attempt=$((attempt + 1))
    if [ "$attempt" -lt "$SMOKE_ATTEMPTS" ]; then
      sleep "$SMOKE_DELAY_SECONDS"
    fi
  done
  printf '%s: expected %s, got %s\n' "$label" "$expected" "${status:-no response}" >&2
  exit 1
}

check "Console" 200 "$AIRMUX_PUBLIC_URL/"
check "Control plane" 200 "$AIRMUX_PUBLIC_URL/api/v1/instance/oss/claim"
check "Gateway" '401 503' --request POST --header 'Authorization: Bearer invalid' --header 'Content-Type: application/json' --data '{}' \
  "$AIRMUX_PUBLIC_URL/inf/v1/chat/completions"
