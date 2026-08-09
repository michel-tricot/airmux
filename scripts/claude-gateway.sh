#!/usr/bin/env bash
# Launch Claude Code against the airllm gateway, on any model registered in the control plane.
#
# Claude Code speaks the Anthropic Messages API, and the gateway exposes it at
# POST /v1/messages, so the "model" can be any provider in the catalog — a Claude
# model runs natively, an OpenAI or Groq model is translated transparently.
#
#   scripts/claude-gateway.sh --list                 # show registered models
#   scripts/claude-gateway.sh gpt-4o-mini            # start Claude Code on gpt-4o-mini
#   scripts/claude-gateway.sh claude-sonnet-4-6 -p "hi"   # extra args pass through to claude
#
# Env overrides: AIRLLM_URL (default http://127.0.0.1:8080),
#                AIRLLM_SMALL_MODEL (background/fast model, default = the main model).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

gateway="${AIRLLM_URL:-http://127.0.0.1:8080}"

die() {
  echo "error: $*" >&2
  exit 1
}

env_value() {
  # Read one key from .env without sourcing it, stripping surrounding quotes.
  [ -f .env ] || return 0
  grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed "s/^['\"]//; s/['\"]\$//"
}

list_models() {
  uv run airllm models list -f text 2>/dev/null | cut -f1
}

command -v claude >/dev/null || die "claude not found on PATH (install Claude Code)"
command -v uv >/dev/null || die "uv not found on PATH"

model="${1:-}"
case "$model" in
  "" | -l | --list | -h | --help)
    echo "Registered models:"
    list_models | sed 's/^/  /' || echo "  (control plane unreachable — pass a model id anyway)"
    echo
    echo "usage: $0 <model> [claude args...]"
    exit 0
    ;;
esac
shift

token="$(env_value AIRLLM_TOKEN)"
[ -n "$token" ] || die "AIRLLM_TOKEN not in .env — run 'uv run airllm quickstart' first"

if models="$(list_models)" && [ -n "$models" ] && ! grep -qxF "$model" <<<"$models"; then
  echo "warning: '$model' is not in the catalog; starting anyway (requests may 404)" >&2
fi

small="${AIRLLM_SMALL_MODEL:-$model}"

# Claude Code appends /v1/messages to ANTHROPIC_BASE_URL and sends the auth token as a bearer,
# which is exactly what the gateway's Anthropic ingress expects. x-api-key auth is unset so it
# does not shadow the bearer.
export ANTHROPIC_BASE_URL="$gateway"
export ANTHROPIC_AUTH_TOKEN="$token"
export ANTHROPIC_MODEL="$model"
export ANTHROPIC_SMALL_FAST_MODEL="$small"
unset ANTHROPIC_API_KEY

echo "claude -> $gateway/v1/messages | model: $model | small: $small" >&2
exec claude "$@"
