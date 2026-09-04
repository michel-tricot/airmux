#!/usr/bin/env sh
set -eu
: "${FLY_APP:?Set FLY_APP}"
FLY_REGION=${FLY_REGION:-sjc}
FLYCTL=${FLYCTL:-flyctl}
AIRLLM_PUBLIC_URL=${AIRLLM_PUBLIC_URL:-https://${FLY_APP}.fly.dev}
"$FLYCTL" deploy . --config deploy/fly/fly.toml --app "$FLY_APP" --primary-region "$FLY_REGION" --remote-only \
  --ha=false --env "GW_CONSOLE_URL=$AIRLLM_PUBLIC_URL"
