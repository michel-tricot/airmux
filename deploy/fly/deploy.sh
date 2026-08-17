#!/usr/bin/env sh
set -eu

: "${FLY_BACKEND_APP:?Set FLY_BACKEND_APP}"
: "${FLY_CONSOLE_APP:?Set FLY_CONSOLE_APP}"

FLY_REGION=${FLY_REGION:-sjc}
FLYCTL=${FLYCTL:-flyctl}
AIRLLM_PUBLIC_URL=${AIRLLM_PUBLIC_URL:-https://${FLY_CONSOLE_APP}.fly.dev}

"$FLYCTL" deploy . --config deploy/fly/backend.toml --app "$FLY_BACKEND_APP" --primary-region "$FLY_REGION" --remote-only --flycast \
  --no-public-ips \
  --env "GW_CONSOLE_URL=$AIRLLM_PUBLIC_URL"
"$FLYCTL" deploy . --config deploy/fly/console.toml --app "$FLY_CONSOLE_APP" --primary-region "$FLY_REGION" --remote-only \
  --env "CONTROL_PLANE_UPSTREAM=${FLY_BACKEND_APP}.flycast:8000" \
  --env "DATA_PLANE_UPSTREAM=${FLY_BACKEND_APP}.flycast:8081"
