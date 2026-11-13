# Backup, restore and incident recovery

OpenCredential has two things to keep: the PostgreSQL database and the badge artwork store.
Everything else (the SPA, the services) is rebuilt from the release. The secrets are kept
separately (see below).

## What a backup holds

| Item | In the backup | Notes |
|---|---|---|
| Database: schemas `app` (records), `jobs` (queue), `keys` (issuer private keys) | Yes, `opencredential.dump` (`pg_dump` custom format, grants included) | The keys are encrypted under `SIGNER_KEK`. Treat the archive as confidential anyway, and encrypt it at rest. |
| Artwork store (`OC_STORAGE_DIR`) | Yes, `assets.tar.gz` | |
| Schema revision and checksums | `manifest.txt` | `restore.sh` refuses a backup whose checksums do not match |
| `SIGNER_KEK`, `OC_SECRET_KEY`, `OC_SIGNER_SHARED_SECRET`, `OC_TOKEN_ENCRYPTION_KEY`, role passwords | **No** | Keep them in your secret store, backed up separately. Without `SIGNER_KEK` the issuer keys cannot be decrypted, and the institution has to rotate to new keys (old credentials still verify, because their public keys are published). |
| LTI tool private key (`OC_LTI_PRIVATE_KEY_FILE`) | **No** | Back it up with the secrets, or generate a new one with `oc lti keygen` and let Canvas fetch the new JWKS |

## Taking a backup

```bash
OC_BACKUP_DB_URL=postgresql://oc_owner:<password>@db:5432/opencredential \
OC_STORAGE_DIR=/var/lib/opencredential/assets \
scripts/backup.sh /backups/$(date -u +%Y-%m-%d)
```

Run it at least daily from a host that can reach the database as `oc_owner`. Keep the copies
off the database host. For a point-in-time recovery objective shorter than a day, also use
PostgreSQL WAL archiving (for example pgBackRest). The logical dump stays the portable copy.

## Restoring

1. Stop the api, worker and signer.
2. Create an **empty** database owned by `oc_owner`. The roles `oc_owner`, `oc_app` and
   `oc_signer` must exist, as in `docker/postgres/init/01-roles.sh`.
3. Restore:

   ```bash
   OC_RESTORE_DB_URL=postgresql://oc_owner:<password>@db:5432/opencredential \
   OC_STORAGE_DIR=/var/lib/opencredential/assets \
   scripts/restore.sh /backups/2026-11-13
   ```

4. Run `oc migrate` (this applies any migrations newer than the backup).
5. Start the signer, then the api and worker. Check that `GET /readyz` reports `ok`.
6. Status lists republish within the hour (or at once from Administration, Failed issuance,
   "Retry"). Any issuance that was in flight at backup time shows up under Administration,
   Reconciliation.

## Restoration drill (tested)

`scripts/backup-restore-drill.sh` runs a destructive drill, and CI runs it on every pull request
(job "End-to-end scenarios and accessibility", step "Backup and restoration drill"). It:

1. downloads an issued credential, as a student would;
2. takes a backup and records counts of credentials, revocations, status lists, audit events,
   users, private keys, tables with row-level security, and runtime grants;
3. stops the services and **drops the database**;
4. restores it and starts the services;
5. checks that every count matches, that the downloaded credential verifies as `verified`, and,
   after revoking it on the restored service, that the same file verifies as `revoked`.

Last local run, 13 November 2026: `DRILL OK`. 44 credentials, 4 revoked, 1 status list, 574 audit
events, 15 users, 1 private key, 36 tables with row-level security, 172 runtime grants. All
matched after the restore. Log: [../reports/evidence/backup-restore-drill.log](../reports/evidence/backup-restore-drill.log).

Run the drill on each production installation before go-live and then every quarter, against a
copy of the database, never against the live one.

## Incident recovery

| Incident | What to do |
|---|---|
| Database lost or corrupted | Restore the latest backup (above). Credentials issued since that backup are still valid in learners' hands, because they are signed and their public keys are published, but their records are gone. Learners can still verify them. Re-issue only on request. |
| Signer host compromised, or `SIGNER_KEK` exposed | Follow [key-compromise.md](../security/key-compromise.md) |
| Canvas token leaked | Revoke it in Canvas (Admin, Developer Keys, or the user's Approved Integrations), then re-authorise in OpenCredential, Administration, Canvas |
| Wrong credentials issued (for example, a misconfigured rule) | Fix the badge (a new version), revoke the wrong credentials with reason `issued_in_error`, and re-evaluate the course |
| Status lists stale (verifiers say "Unable to verify") | Check the worker and signer. Retry the failed jobs from Administration, Failed issuance. The hourly job republishes every list. |
| Worker down | Nothing is lost. Jobs wait in the queue and run when the worker comes back. Stalled jobs are recovered automatically. |
