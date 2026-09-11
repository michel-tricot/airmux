#!/usr/bin/env bash
# Launch a coding agent against the airllm gateway, on any model registered in the catalog.
#
# Claude Code speaks the Anthropic Messages API, served at /inf/v1/messages. Codex speaks the
# OpenAI Responses API, served at /inf/v1/responses. The gateway routes both through the same
# canonical middle, so either agent runs any provider's model.
#
#   scripts/agent-gateway.sh claude gpt-5.2                # Claude Code on gpt-5.2
#   scripts/agent-gateway.sh codex claude-sonnet-5         # Codex on claude-sonnet-5
#   scripts/agent-gateway.sh claude gpt-5.2 -p "hi"        # extra args pass through to the agent
#   scripts/agent-gateway.sh --list                        # show registered models
#
# Env overrides: AIRLLM_URL (default http://127.0.0.1:8080),
#                AIRLLM_SMALL_MODEL (Claude Code background model, default = the main model).
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

usage() {
  echo "Registered models:"
  list_models | sed 's/^/  /' || echo "  (control plane unreachable — pass a model id anyway)"
  echo
  echo "usage: $0 <claude|codex> <model> [agent args...]"
  exit 0
}

command -v uv >/dev/null || die "uv not found on PATH"

agent="${1:-}"
case "$agent" in
  "" | -l | --list | -h | --help) usage ;;
  claude | codex) ;;
  *) die "unknown agent '$agent' (expected claude or codex)" ;;
esac
shift

model="${1:-}"
[ -n "$model" ] || usage
shift

api_key="$(env_value AIRLLM_INFERENCE_KEY)"
[ -n "$api_key" ] || die "AIRLLM_INFERENCE_KEY not in .env — run 'uv run airllm quickstart' first"

if models="$(list_models)" && [ -n "$models" ] && ! grep -qxF "$model" <<<"$models"; then
  echo "warning: '$model' is not in the catalog; starting anyway (requests may 404)" >&2
fi

case "$agent" in
  claude)
    command -v claude >/dev/null || die "claude not found on PATH (install Claude Code)"
    small="${AIRLLM_SMALL_MODEL:-$model}"
    # Claude Code appends /v1/messages to ANTHROPIC_BASE_URL and sends the auth token as a
    # bearer, which is what the gateway's Messages surface expects. x-api-key auth is unset so
    # it does not shadow the bearer.
    export ANTHROPIC_BASE_URL="$gateway/inf"
    export ANTHROPIC_AUTH_TOKEN="$api_key"
    export ANTHROPIC_MODEL="$model"
    export ANTHROPIC_SMALL_FAST_MODEL="$small"
    unset ANTHROPIC_API_KEY
    echo "claude -> $gateway/inf/v1/messages | model: $model | small: $small" >&2
    exec claude "$@"
    ;;
  codex)
    command -v codex >/dev/null || die "codex not found on PATH (install Codex)"
    # Codex reaches custom providers through a model_providers entry; the -c overrides build it
    # per run, so no config file changes. Codex 0.147 dropped the chat wire, so this needs the
    # gateway's /inf/v1/responses surface (the Responses dialect).
    export AIRLLM_INFERENCE_KEY="$api_key"
    echo "codex -> $gateway/inf/v1/responses | model: $model" >&2
    exec codex \
      -c model_provider=airllm \
      -c model_providers.airllm.name=airllm \
      -c "model_providers.airllm.base_url=$gateway/inf/v1" \
      -c model_providers.airllm.env_key=AIRLLM_INFERENCE_KEY \
      -c model_providers.airllm.wire_api=responses \
      -m "$model" "$@"
    ;;
esac
