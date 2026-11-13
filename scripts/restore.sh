#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Restore a backup made by scripts/backup.sh into an EMPTY database (docs/operations/backup-restore.md).
# Stop the api, worker and signer first. The three roles (oc_owner, oc_app, oc_signer) must
# already exist (docker/postgres/init/01-roles.sh shows their shape): the dump carries the
# grants, row-level-security policies and SECURITY DEFINER functions that refer to them.
#
# Usage: OC_RESTORE_DB_URL=postgresql://oc_owner:...@host:5432/opencredential \
#        OC_STORAGE_DIR=/var/lib/opencredential/assets scripts/restore.sh /backups/2026-11-13
set -euo pipefail
IN="${1:?usage: restore.sh <backup directory>}"
DB_URL="${OC_RESTORE_DB_URL:?set OC_RESTORE_DB_URL to the (empty) target database as its owner}"
STORAGE="${OC_STORAGE_DIR:-}"

(cd "$IN" && grep -E '^[0-9a-f]{64} ' manifest.txt | sha256sum --check --quiet) \
  || { echo "checksum mismatch: refusing to restore" >&2; exit 1; }
tables=$(psql -X -At "$DB_URL" -c "select count(*) from pg_tables where schemaname in ('app','jobs','keys')")
if [ "$tables" != "0" ]; then
  echo "target database is not empty ($tables tables in app/jobs/keys): refusing to overwrite" >&2
  exit 1
fi
pg_restore --exit-on-error --no-owner --dbname "$DB_URL" "$IN/opencredential.dump"
if [ -f "$IN/assets.tar.gz" ] && [ -n "$STORAGE" ]; then
  mkdir -p "$STORAGE"
  tar -C "$STORAGE" -xzf "$IN/assets.tar.gz"
fi
echo "restored $(grep alembic_revision "$IN/manifest.txt" || echo 'database') from $IN"
echo "next: run 'oc migrate' (applies any migrations newer than the backup), then start signer, api, worker"
