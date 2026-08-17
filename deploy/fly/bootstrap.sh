#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <name>" >&2
  exit 2
fi

AIRLLM_NAME=$1
case "$AIRLLM_NAME" in
  "" | *[!a-z0-9-]* | -* | *-)
    echo "name must contain lowercase letters, numbers, and internal hyphens" >&2
    exit 2
    ;;
esac

FLYCTL=${FLYCTL:-flyctl}
GH=${GH:-gh}
PYTHON=${PYTHON:-python3}
FLY_REGION=${FLY_REGION:-sjc}
FLY_MPG_PLAN=${FLY_MPG_PLAN:-Basic}
FLY_MPG_VOLUME_SIZE=${FLY_MPG_VOLUME_SIZE:-10}
FLY_TOKEN_EXPIRY=${FLY_TOKEN_EXPIRY:-8760h}
FLY_BACKEND_APP=${AIRLLM_NAME}-backend
FLY_CONSOLE_APP=${AIRLLM_NAME}-frontend
FLY_MPG_CLUSTER=${AIRLLM_NAME}
AIRLLM_PUBLIC_URL=${AIRLLM_PUBLIC_URL:-https://${FLY_CONSOLE_APP}.fly.dev}
GITHUB_ENVIRONMENT=${GITHUB_ENVIRONMENT:-production}
SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH='' cd -- "$SCRIPT_DIR/../.." && pwd)

for command in "$FLYCTL" "$GH" "$PYTHON"; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "$command is required" >&2
    exit 1
  fi
done

single_org() {
  "$PYTHON" -c '
import json
import sys

orgs = json.load(sys.stdin)
print(next(iter(orgs)) if len(orgs) == 1 else "")
'
}

app_exists() {
  "$PYTHON" -c '
import json
import sys

name = sys.argv[1]
apps = json.load(sys.stdin)
raise SystemExit(0 if any((app.get("Name") or app.get("name")) == name for app in apps) else 1)
' "$1"
}

cluster_id_of() {
  "$PYTHON" -c '
import json
import sys

name = sys.argv[1]
matches = [item["id"] for item in json.load(sys.stdin) if item["name"] == name]
print(matches[0] if len(matches) == 1 else "")
' "$1"
}

cluster_status_of() {
  "$PYTHON" -c '
import json
import sys

print(json.load(sys.stdin)["data"]["status"])
'
}

pooled_url_of() {
  "$PYTHON" -c '
import json
import sys

print(json.load(sys.stdin)["credentials"]["pgbouncer_uri"])
'
}

direct_url_of() {
  "$PYTHON" -c '
import sys

url = sys.stdin.read()
marker = "@pgbouncer."
assert marker in url, "unexpected Managed Postgres URL"
print(url.replace(marker, "@direct.", 1))
'
}

cluster_has_app() {
  "$PYTHON" -c '
import json
import sys

cluster_id, app = sys.argv[1:]
cluster = next(item for item in json.load(sys.stdin) if item["id"] == cluster_id)
raise SystemExit(0 if any(item["name"] == app for item in (cluster.get("attached_apps") or [])) else 1)
' "$1" "$2"
}

github_has_secret() {
  "$PYTHON" -c '
import json
import sys

name = sys.argv[1]
raise SystemExit(0 if any(item["name"] == name for item in json.load(sys.stdin)) else 1)
' "$1"
}

if [ -z "${FLY_ORG:-}" ]; then
  orgs=$("$FLYCTL" orgs list --json)
  FLY_ORG=$(printf '%s' "$orgs" | single_org)
  unset orgs
  if [ -z "$FLY_ORG" ]; then
    echo "set FLY_ORG because this account has more than one organization" >&2
    exit 1
  fi
fi

if [ -z "${GH_REPO:-}" ]; then
  repository=$("$GH" repo view --json nameWithOwner)
  GH_REPO=$(printf '%s' "$repository" | "$PYTHON" -c 'import json, sys; print(json.load(sys.stdin)["nameWithOwner"])')
  unset repository
fi

apps=$("$FLYCTL" apps list --org "$FLY_ORG" --json)
for app in "$FLY_BACKEND_APP" "$FLY_CONSOLE_APP"; do
  if printf '%s' "$apps" | app_exists "$app"; then
    echo "Reusing Fly app $app"
  else
    echo "Creating Fly app $app"
    "$FLYCTL" apps create "$app" --org "$FLY_ORG" --yes
  fi
done
unset apps

clusters=$("$FLYCTL" mpg list --org "$FLY_ORG" --json)
cluster_id=$(printf '%s' "$clusters" | cluster_id_of "$FLY_MPG_CLUSTER")
unset clusters

if [ -z "$cluster_id" ]; then
  echo "Creating Managed Postgres cluster $FLY_MPG_CLUSTER"
  "$FLYCTL" mpg create \
    --name "$FLY_MPG_CLUSTER" \
    --org "$FLY_ORG" \
    --region "$FLY_REGION" \
    --plan "$FLY_MPG_PLAN" \
    --volume-size "$FLY_MPG_VOLUME_SIZE" \
    >/dev/null
  discovery_attempt=0
  while [ -z "$cluster_id" ]; do
    clusters=$("$FLYCTL" mpg list --org "$FLY_ORG" --json)
    cluster_id=$(printf '%s' "$clusters" | cluster_id_of "$FLY_MPG_CLUSTER")
    unset clusters
    if [ -n "$cluster_id" ]; then
      break
    fi
    discovery_attempt=$((discovery_attempt + 1))
    if [ "$discovery_attempt" -ge 12 ]; then
      echo "Managed Postgres cluster $FLY_MPG_CLUSTER was created but could not be discovered" >&2
      exit 1
    fi
    sleep 5
  done
else
  echo "Reusing Managed Postgres cluster $FLY_MPG_CLUSTER"
fi

attempt=0
while :; do
  cluster=$("$FLYCTL" mpg status "$cluster_id" --json)
  cluster_status=$(printf '%s' "$cluster" | cluster_status_of)
  if [ "$cluster_status" = ready ]; then
    break
  fi
  case "$cluster_status" in
    failed | deleted)
      echo "Managed Postgres cluster $FLY_MPG_CLUSTER is $cluster_status" >&2
      exit 1
      ;;
  esac
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 120 ]; then
    echo "timed out waiting for Managed Postgres cluster $FLY_MPG_CLUSTER" >&2
    exit 1
  fi
  echo "Waiting for Managed Postgres cluster $FLY_MPG_CLUSTER ($cluster_status)"
  sleep 5
done

pooled_url=$(printf '%s' "$cluster" | pooled_url_of)
direct_url=$(printf '%s' "$pooled_url" | direct_url_of)
unset cluster cluster_status

clusters=$("$FLYCTL" mpg list --org "$FLY_ORG" --json)
if printf '%s' "$clusters" | cluster_has_app "$cluster_id" "$FLY_BACKEND_APP"; then
  echo "Managed Postgres is already attached to $FLY_BACKEND_APP"
else
  echo "Attaching Managed Postgres to $FLY_BACKEND_APP"
  "$FLYCTL" mpg attach "$cluster_id" --app "$FLY_BACKEND_APP" >/dev/null
fi
unset clusters

printf 'DATABASE_URL=%s\nDIRECT_DATABASE_URL=%s\n' "$pooled_url" "$direct_url" \
  | "$FLYCTL" secrets import --app "$FLY_BACKEND_APP" --stage
unset direct_url pooled_url

"$GH" api --method PUT "repos/${GH_REPO}/environments/${GITHUB_ENVIRONMENT}" >/dev/null

github_secrets=$("$GH" secret list --repo "$GH_REPO" --env "$GITHUB_ENVIRONMENT" --json name)
for entry in "FLY_BACKEND_API_TOKEN:$FLY_BACKEND_APP" "FLY_CONSOLE_API_TOKEN:$FLY_CONSOLE_APP"; do
  secret_name=${entry%%:*}
  app=${entry#*:}
  if ! printf '%s' "$github_secrets" | github_has_secret "$secret_name"; then
    echo "Installing GitHub deploy secret $secret_name"
    token=$("$FLYCTL" tokens create deploy --app "$app" --name github-actions --expiry "$FLY_TOKEN_EXPIRY")
    "$GH" secret set "$secret_name" --repo "$GH_REPO" --env "$GITHUB_ENVIRONMENT" --body "$token"
    unset token
  else
    echo "Reusing GitHub deploy secret $secret_name"
  fi
done
unset github_secrets

for entry in \
  "FLY_BACKEND_APP:$FLY_BACKEND_APP" \
  "FLY_CONSOLE_APP:$FLY_CONSOLE_APP" \
  "FLY_REGION:$FLY_REGION" \
  "AIRLLM_PUBLIC_URL:$AIRLLM_PUBLIC_URL"; do
  variable_name=${entry%%:*}
  value=${entry#*:}
  "$GH" variable set "$variable_name" --repo "$GH_REPO" --env "$GITHUB_ENVIRONMENT" --body "$value"
done

export AIRLLM_PUBLIC_URL FLY_BACKEND_APP FLY_CONSOLE_APP FLY_REGION FLYCTL
cd "$REPO_ROOT"
"$SCRIPT_DIR/deploy.sh"

echo
echo "airllm is deployed at $AIRLLM_PUBLIC_URL"
echo "Run quickstart once to create the first account and connect the data plane:"
echo "uv run airllm quickstart --control-plane-url $AIRLLM_PUBLIC_URL --console-url $AIRLLM_PUBLIC_URL --gateway-url $AIRLLM_PUBLIC_URL"
