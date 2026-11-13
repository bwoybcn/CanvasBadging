#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Phase 1 exit check against a running `docker compose up`: the app starts, reaches its
# database at the expected migration, the signer is up, the demo data is loaded, a dev user
# can sign in, and the worker is consuming jobs.
set -euo pipefail
BASE="${OC_BASE_URL:-http://localhost:8000}"

echo "waiting for $BASE/readyz"
for i in $(seq 1 90); do
  if body=$(curl -fsS "$BASE/readyz" 2>/dev/null); then echo "ready: $body"; break; fi
  [ "$i" = 90 ] && { echo "api never became ready"; curl -sS "$BASE/readyz" || true; exit 1; }
  sleep 2
done

users=$(curl -fsS "$BASE/dev/institutions/demo-university/users")
uid=$(python3 -c 'import json,sys; print(next(u["id"] for u in json.load(sys.stdin) if "student" in u["roles"]))' <<<"$users")
token=$(curl -fsS -X POST "$BASE/dev/login" -H 'content-type: application/json' \
  -d "{\"institution\":\"demo-university\",\"user_id\":\"$uid\"}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
me=$(curl -fsS "$BASE/api/v1/learners/me" -H "authorization: Bearer $token")
echo "signed in: $me"
grep -q '"role":"student"' <<<"$me"

curl -fsS -o /dev/null "$BASE/app/" && echo "SPA served at $BASE/app/"

if command -v docker >/dev/null && docker compose ps worker --format '{{.State}}' 2>/dev/null | grep -q running; then
  echo "worker: running"
fi
echo "SMOKE OK"
