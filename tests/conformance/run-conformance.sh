#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Issue real credentials from a running stack, revoke one, and lay them out for the independent
# verifiers: $OUT/active/*.json and $OUT/revoked/*.json (downloaded copies, made before revocation).
# Expects: database migrated and seeded, signer and API running, OC_* settings in the environment.
set -euo pipefail
OUT=${1:?usage: run-conformance.sh OUT_DIR}
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$OUT/all" "$OUT/active" "$OUT/revoked"
(cd "$here/../../backend" && uv run oc issue-demo --out "$OUT/all" >/dev/null)
mapfile -t files < <(ls "$OUT"/all/*.json)
test "${#files[@]}" -ge 2 || { echo "expected at least two issued credentials" >&2; exit 1; }
revoked=${files[0]}
cp "$revoked" "$OUT/revoked/"
cp "${files[@]:1}" "$OUT/active/"
(cd "$here/../../backend" && uv run oc revoke "$(basename "$revoked" .json)" \
  --reason-code issued_in_error --reason-text "conformance run")
# Our own verifier must agree before we ask anyone else.
(cd "$here/../../backend" && for f in "$OUT"/active/*.json; do uv run oc verify "$f" >/dev/null; done)
(cd "$here/../../backend" && ! uv run oc verify "$OUT"/revoked/*.json >/dev/null)
echo "issued ${#files[@]}; revoked $(basename "$revoked")"
