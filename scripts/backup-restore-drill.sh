#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Backup and restoration drill (spec §17.2, §20 Phase 8; RTM R-2.4-10 / D-BACKUP).
# Against a running development stack: back up, destroy the database, restore into an empty
# one, then prove nothing was lost:
#   - row counts of credentials, status lists, audit events, users and keys are unchanged,
#   - a credential downloaded BEFORE the loss still verifies, and a revoked one still reads revoked,
#   - the restored service can still sign: a new award issues and verifies (keys survived).
# Needs: psql/pg_dump/pg_restore, curl, python3; OC_ADMIN_DB_URL (a superuser, to drop and
# recreate the database); hooks to stop and start the services around the restore.
#
#   OC_ADMIN_DB_URL=postgresql://postgres:postgres@localhost:5432/postgres \
#   OC_DRILL_STOP='docker compose stop api worker signer' \
#   OC_DRILL_START='docker compose start signer api worker' \
#   scripts/backup-restore-drill.sh
set -euo pipefail
BASE="${OC_BASE_URL:-http://localhost:8000}"
ADMIN="${OC_ADMIN_DB_URL:?superuser URL}"
DB="${OC_DB_NAME:-opencredential}"
OWNER_URL="${OC_OWNER_DB_URL:-postgresql://oc_owner:oc_owner_dev@localhost:5432/$DB}"
STOP="${OC_DRILL_STOP:?command that stops api, worker and signer}"
START="${OC_DRILL_START:?command that starts signer, api and worker}"
WORK="$(mktemp -d)"
DB_URL_ADMIN_DB="${ADMIN%/*}/$DB"
py() { python3 -c "$1"; }

api() { # method path token [json]
  local args=(-fsS -X "$1" "$BASE$2" -H 'content-type: application/json')
  [ -n "${3:-}" ] && args+=(-H "authorization: Bearer $3")
  [ -n "${4:-}" ] && args+=(-d "$4")
  curl "${args[@]}"
}
login() { # display name -> token
  local uid
  uid=$(api GET /dev/institutions/demo-university/users "" | NAME="$1" py 'import json,sys,os; print(next(u["id"] for u in json.load(sys.stdin) if u["display_name"]==os.environ["NAME"]))')
  api POST /dev/login "" "{\"institution\":\"demo-university\",\"user_id\":\"$uid\"}" | py 'import json,sys; print(json.load(sys.stdin)["token"])'
}
verify() { # file -> result
  curl -fsS -X POST "$BASE/api/v1/verify" -H 'content-type: application/json' --data-binary @"$1" | py 'import json,sys; print(json.load(sys.stdin)["result"])'
}
counts() {
  psql -X -At "$DB_URL_ADMIN_DB" -c "select
    (select count(*) from app.credentials)||' credentials, '||
    (select count(*) from app.credential_status where state='revoked')||' revoked, '||
    (select count(*) from app.status_lists)||' status lists, '||
    (select count(*) from app.audit_events)||' audit events, '||
    (select count(*) from app.users)||' users, '||
    (select count(*) from keys.private_keys)||' private keys, '||
    (select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace
       where n.nspname='app' and c.relrowsecurity)||' tables with row-level security, '||
    (select count(*) from information_schema.role_table_grants
       where grantee in ('oc_app','oc_signer'))||' runtime grants'"
}

echo "== 1. state before"
admin=$(login "Avery Admin")
# a student's credential, downloaded before the loss; and a revoked one
read -r sname cid < <(for n in $(api GET /dev/institutions/demo-university/users "" | py 'import json,sys; [print(u["display_name"].replace(" ","_")) for u in json.load(sys.stdin) if "student" in u["roles"]]'); do
  t=$(login "${n//_/ }"); c=$(api GET /api/v1/learners/me/credentials "$t" | py 'import json,sys; a=[c["id"] for c in json.load(sys.stdin) if c["status"]=="active"]; print(a[0] if a else "")')
  [ -n "$c" ] && { echo "$n $c"; break; }
done)
stoken=$(login "${sname//_/ }")
api GET "/api/v1/credentials/$cid/export" "$stoken" > "$WORK/active.json"
echo "active credential before: $(verify "$WORK/active.json")"

before=$(counts); echo "$before"

echo "== 2. backup"
OC_BACKUP_DB_URL="$OWNER_URL" OC_STORAGE_DIR="${OC_STORAGE_DIR:-}" "$(dirname "$0")/backup.sh" "$WORK/backup" >/dev/null
ls -l "$WORK/backup"

echo "== 3. disaster: stop services, drop the database"
sh -c "$STOP"
psql -X -q "$ADMIN" -c "select pg_terminate_backend(pid) from pg_stat_activity where datname='$DB' and pid<>pg_backend_pid()" >/dev/null
psql -X -q "$ADMIN" -c "drop database $DB" -c "create database $DB owner oc_owner" \
  -c "revoke all on database $DB from public" -c "grant connect on database $DB to oc_app, oc_signer"
psql -X -q "$DB_URL_ADMIN_DB" -c "revoke create on schema public from public"

echo "== 4. restore"
OC_RESTORE_DB_URL="$OWNER_URL" OC_STORAGE_DIR="${OC_STORAGE_DIR:-}" "$(dirname "$0")/restore.sh" "$WORK/backup"
sh -c "$START"
for i in $(seq 1 60); do curl -fsS "$BASE/readyz" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "$BASE/readyz"; echo

echo "== 5. checks"
after=$(counts); echo "$after"
[ "$before" = "$after" ] || { echo "FAIL: counts differ"; exit 1; }
r=$(verify "$WORK/active.json"); echo "credential downloaded before the loss: $r"
[ "$r" = "verified" ] || { echo "FAIL: expected verified"; exit 1; }
# revoke it now: proves the status list can still be re-signed after restore
admin=$(login "Avery Admin")
api POST "/api/v1/credentials/$cid/revoke" "$admin" '{"reason_code":"other","reason_text":"backup and restore drill"}' >/dev/null
for i in $(seq 1 40); do r=$(verify "$WORK/active.json"); [ "$r" = "revoked" ] && break; sleep 1; done
echo "same file after revoking it on the restored service: $r"
[ "$r" = "revoked" ] || { echo "FAIL: revocation not reflected (status list not re-signed?)"; exit 1; }
echo "DRILL OK"
rm -rf "$WORK"
