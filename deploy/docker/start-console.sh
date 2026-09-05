#!/usr/bin/env sh
set -eu
NGINX_RESOLVER=${NGINX_RESOLVER:-$(awk '$1 == "nameserver" { print $2; exit }' /etc/resolv.conf)}
case "$NGINX_RESOLVER" in
  \[*\]) ;;
  *:*) NGINX_RESOLVER="[$NGINX_RESOLVER]" ;;
esac
PUBLIC_SCHEME=${GW_CONSOLE_URL%%:*}
case "$PUBLIC_SCHEME" in
  http|https) ;;
  *) echo 'GW_CONSOLE_URL must start with http:// or https://' >&2; exit 1 ;;
esac
export NGINX_RESOLVER PUBLIC_SCHEME
envsubst '${CONTROL_PLANE_UPSTREAM} ${DATA_PLANE_UPSTREAM} ${NGINX_RESOLVER} ${PUBLIC_SCHEME}' \
  < /app/deploy/docker/nginx.conf.template > /tmp/airllm-nginx.conf
exec nginx -c /tmp/airllm-nginx.conf -g 'daemon off;'
