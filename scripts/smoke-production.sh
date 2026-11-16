#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Proves the production kit (docker/compose.production.yaml) on one machine: generates
# throwaway secrets and a self-signed certificate, builds and starts the stack in production
# mode, and checks what a real installation relies on. Used by CI; safe to run by hand.
#
#   scripts/smoke-production.sh          # leaves the stack running
#   scripts/smoke-production.sh down     # stops it and deletes its volumes
set -euo pipefail
cd "$(dirname "$0")/.."
WORK="${OC_SMOKE_DIR:-$PWD/.smoke-production}"
HOST=badges.smoke.test
compose=(docker compose -p oc-prod-smoke -f docker/compose.production.yaml --env-file "$WORK/production.env")

if [ "${1:-}" = down ]; then
  "${compose[@]}" down -v
  rm -rf "$WORK"
  exit 0
fi

mkdir -p "$WORK/certs"
if [ ! -f "$WORK/production.env" ]; then
  hex() { openssl rand -hex 32; }
  cat > "$WORK/production.env" <<ENV
OC_VERSION=smoke
OC_HOSTNAME=$HOST
POSTGRES_PASSWORD=$(hex)
OC_OWNER_PASSWORD=$(hex)
OC_APP_PASSWORD=$(hex)
OC_SIGNER_PASSWORD=$(hex)
OC_SECRET_KEY=$(hex)
OC_SIGNER_SHARED_SECRET=$(hex)
OC_TOKEN_ENCRYPTION_KEY=$(hex)
SIGNER_KEK=$(openssl rand -base64 32)
OC_API_WORKERS=2
OC_TLS_DIR=$WORK/certs
ENV
  openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj "/CN=$HOST" \
    -addext "subjectAltName=DNS:$HOST" \
    -keyout "$WORK/certs/privkey.pem" -out "$WORK/certs/fullchain.pem" 2>/dev/null
  chmod 644 "$WORK/certs/"*.pem
fi

"${compose[@]}" up -d --build

get() { curl -sS --noproxy '*' --cacert "$WORK/certs/fullchain.pem" --resolve "$HOST:443:127.0.0.1" --resolve "$HOST:80:127.0.0.1" "$@"; }
code() { get -o /dev/null -w '%{http_code}' "$@"; }
fail() { echo "FAIL: $*" >&2; "${compose[@]}" ps >&2 || true; exit 1; }

echo "waiting for https://$HOST/readyz"
for i in $(seq 1 90); do
  if body=$(get -f "https://$HOST/readyz" 2>/dev/null); then echo "ready: $body"; break; fi
  [ "$i" = 90 ] && fail "the stack never became ready: $(get "https://$HOST/readyz" 2>&1 || true)"
  sleep 2
done

[ "$(code "http://$HOST/app/")" = 301 ] || fail "plain http is not redirected to https"
[ "$(code "https://$HOST/app/")" = 200 ] || fail "the app is not served"
[ "$(code "https://$HOST/verify")" = 200 ] || fail "the public checker page is not served"
[ "$(code "https://$HOST/lti/jwks")" = 200 ] || fail "the LTI key was not created"
get -D - -o /dev/null "https://$HOST/verify" | grep -qi '^strict-transport-security:' \
  || fail "HSTS is missing: the api does not see X-Forwarded-Proto"
echo "served over https, with the LTI key in place"

# Production mode: no development sign-in, no demonstration data.
[ "$(code -X POST -H 'content-type: application/json' -d '{}' "https://$HOST/dev/login")" = 404 ] \
  || fail "the development sign-in exists in production"
[ "$(code "https://$HOST/dev/institutions/demo-university/users")" = 404 ] \
  || fail "development routes exist in production"
echo "no development sign-in"

# Only the proxy is published.
for service_port in "api 8000" "signer 8790" "postgres 5432"; do
  # shellcheck disable=SC2086
  published=$("${compose[@]}" port $service_port 2>/dev/null || true)
  # Unpublished reads as nothing, ":0" or "0.0.0.0:0", depending on the Compose version.
  case "${published##*:}" in "" | 0) ;; *) fail "$service_port is published on the host at $published" ;; esac
done
echo "api, signer and database are not published"

# The worker is running and nothing has failed.
for i in $(seq 1 30); do
  jobs=$(get "https://$HOST/healthz/jobs")
  grep -q '"status":"ok"' <<<"$jobs" && break
  [ "$i" = 30 ] && fail "background work is not healthy: $jobs"
  sleep 2
done
echo "background work: $jobs"

# A burst at the public checker is refused with 429, by the proxy or by the app behind it.
refused=0
for i in $(seq 1 120); do
  [ "$(code -X POST -H 'content-type: application/json' -d '{}' "https://$HOST/api/v1/verify")" = 429 ] && refused=$((refused + 1))
done
[ "$refused" -gt 0 ] || fail "120 rapid requests to the public checker were all accepted"
echo "rate limit: $refused of 120 rapid checks refused"

echo "PRODUCTION SMOKE OK"
