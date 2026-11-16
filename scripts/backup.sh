#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Back up everything OpenCredential needs to recover (docs/operations/backup-restore.md):
#   1. the whole PostgreSQL database (schemas app, jobs and keys) as a pg_dump custom archive,
#   2. the badge artwork store (OC_STORAGE_DIR).
# Secrets (SIGNER_KEK, OC_SECRET_KEY, OC_TOKEN_ENCRYPTION_KEY, role passwords) are NOT in the
# backup: keep them in your secret store. The archive holds issuer private keys encrypted under
# SIGNER_KEK, so treat it as confidential anyway, and encrypt it at rest.
#
# Usage: OC_BACKUP_DB_URL=postgresql://oc_owner:...@host:5432/opencredential \
#        OC_STORAGE_DIR=/var/lib/opencredential/assets scripts/backup.sh /backups/2026-11-13
set -euo pipefail
OUT="${1:?usage: backup.sh <output directory>}"
DB_URL="${OC_BACKUP_DB_URL:?set OC_BACKUP_DB_URL to a database URL that can read every schema}"
STORAGE="${OC_STORAGE_DIR:-}"
# Before the folder is made, so that it and everything in it is readable by this user only.
umask 077
mkdir -p "$OUT"

pg_dump --format=custom --no-owner --file "$OUT/opencredential.dump" "$DB_URL"
if [ -n "$STORAGE" ] && [ -d "$STORAGE" ]; then
  tar -C "$STORAGE" -czf "$OUT/assets.tar.gz" .
else
  echo "note: OC_STORAGE_DIR not set or missing; artwork store not included" >&2
fi
psql -X -At "$DB_URL" -c "select 'alembic_revision', version_num from app.alembic_version" \
  > "$OUT/manifest.txt" 2>/dev/null || true
{
  echo "created_at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  (cd "$OUT" && sha256sum opencredential.dump assets.tar.gz 2>/dev/null || sha256sum opencredential.dump)
} >> "$OUT/manifest.txt"
echo "backup written to $OUT"
cat "$OUT/manifest.txt"
