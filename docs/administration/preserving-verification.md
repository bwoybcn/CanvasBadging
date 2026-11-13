# Keeping issued credentials verifiable (spec §7.7, §9.5)

Students keep their credentials as files. Those files stay verifiable only while the issuer's
**public verification infrastructure** stays online at the same addresses. The university
operates it. No student, alumni or Canvas access is needed.

## What must stay reachable

| Address (on the verification host) | Why |
|---|---|
| `/issuers/<slug>/did.json` (did:web issuers) | Public keys that verify signatures. Retired keys stay listed so older credentials keep verifying. |
| `/status/<slug>/<list id>` | Signed revocation lists. Re-signed daily by the worker; a list more than 30 days stale is refused (verifiers then report "unable to verify", not "revoked"). |
| `/achievements/<version id>` | Achievement descriptions referenced from credentials. |
| `/assets/public/<sha256>.<ext>` | Badge images referenced from credentials. |
| `/verify/<share id>` and `/verify/<share id>/credential.json` | Students' public links (only while the student keeps them on). |

## Choosing the verification host

Set `institutions.verification_host` before issuing in production (ADR-0004; the domain is still
to be decided). Every credential embeds URLs on that host, so pick a name the university can keep
for many years, independent of any product or vendor, for example `credentials.<university domain>`.
Production refuses to issue while the placeholder host is configured.

## Migration or shutdown

- **Moving to new software:** keep serving the paths above with the same content at the same host.
  Export `issuers`, `issuer_keys` (public parts), `status_lists`, `achievement_versions` and the
  badge asset store. Private keys are not needed for verification.
- **Shutting the service down:** publish static copies of the DID documents, the last signed status
  lists (re-signed with a long `validUntil` first, or accept that they will read as "unable to
  verify" after expiry), achievement JSON and images on the same host. Share pages may be retired:
  credential files do not depend on them.
- **Never** reuse a verification host or issuer slug for a different issuer.
- Key compromise is different: see [../security/key-compromise.md](../security/key-compromise.md).
