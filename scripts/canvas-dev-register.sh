#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Development helper: registers OpenCredential on a Canvas through Canvas's documented APIs
# (docs/integrations/canvas.md steps 1-5): LTI 1.3 developer key from /lti/config.json, binding
# on, account-level install by client id, REST API developer key with enforced scopes, optional
# course tab enabled, then `oc canvas register`.
#
#   CANVAS_ADMIN_TOKEN=<root admin access token> scripts/canvas-dev-register.sh [course_id]
#
# Environment: CANVAS_URL (default http://localhost:3000), OC_URL (default http://localhost:8000),
# OC_INSTITUTION (default uol-dev). Run from the repo root with the compose stack up.
set -euo pipefail
: "${CANVAS_ADMIN_TOKEN:?set CANVAS_ADMIN_TOKEN to a Canvas root-admin access token}"
C="${CANVAS_URL:-http://localhost:3000}"
OC="${OC_URL:-http://localhost:8000}"
INST="${OC_INSTITUTION:-uol-dev}"
COURSE="${1:-}"
H=(-H "Authorization: Bearer $CANVAS_ADMIN_TOKEN" -H "Content-Type: application/json")

CFG=$(curl -sf "$OC/lti/config.json")

# 1. LTI 1.3 developer key from JSON configuration
LTI=$(python3 - "$CFG" <<'EOF'
import json, sys
cfg = json.loads(sys.argv[1])
print(json.dumps({"developer_key": {"name": "OpenCredential (LTI)", "redirect_uris": cfg["target_link_uri"],
                                    "scopes": cfg["scopes"]},
                  "tool_configuration": {"settings": cfg}}))
EOF
)
LTI_RESP=$(curl -sf "${H[@]}" -X POST "$C/api/lti/accounts/self/developer_keys/tool_configuration" -d "$LTI")
LTI_ID=$(echo "$LTI_RESP" | python3 -c 'import json,sys; print(json.load(sys.stdin)["developer_key"]["id"])')
echo "lti developer key: $LTI_ID"
curl -sf "${H[@]}" -X POST "$C/api/v1/accounts/self/developer_keys/$LTI_ID/developer_key_account_bindings" \
  -d '{"developer_key_account_binding":{"workflow_state":"on"}}' >/dev/null

# 2. Deploy at account level -> tool id and deployment id. Current Canvas (LTI Registrations)
#    locks "install by client id" for keys created this way, so use the deployments API and fall
#    back to the classic external_tools endpoint on older Canvas.
REG=$(curl -sf "${H[@]}" "$C/api/v1/accounts/self/lti_registrations" 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin); d = d.get('data', d)
print(next((r['id'] for r in d if str(r.get('developer_key_id')) == '$LTI_ID'), ''))" || true)
if [ -n "$REG" ]; then
  DEP=$(curl -sf "${H[@]}" -X POST "$C/api/v1/accounts/self/lti_registrations/$REG/deployments" -d '{}')
  TOOL_ID=$(echo "$DEP" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
  DEP_ID=$(echo "$DEP" | python3 -c 'import json,sys; print(json.load(sys.stdin)["deployment_id"])')
else
  TOOL=$(curl -sf "${H[@]}" -X POST "$C/api/v1/accounts/self/external_tools" -d "{\"client_id\":\"$LTI_ID\"}")
  TOOL_ID=$(echo "$TOOL" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
  DEP_ID=$(echo "$TOOL" | python3 -c 'import json,sys; print(json.load(sys.stdin)["deployment_id"])')
fi
echo "tool $TOOL_ID deployment $DEP_ID"

# 3. REST API developer key, scopes enforced, redirect to our OAuth callback
API=$(OC="$OC" python3 - <<'EOF'
import json
scopes = [
    "url:GET|/api/v1/courses/:id",
    "url:GET|/api/v1/courses/:course_id/modules",
    "url:GET|/api/v1/courses/:course_id/modules/:module_id/items",
    "url:GET|/api/v1/courses/:course_id/assignments",
    "url:GET|/api/v1/courses/:course_id/students/submissions",
    "url:GET|/api/v1/courses/:course_id/enrollments",
    "url:GET|/api/v1/users/:user_id/profile",
]
import os
cb = os.environ["OC"] + "/api/v1/canvas/oauth/callback"
print(json.dumps({"developer_key": {"name": "OpenCredential (API)", "redirect_uri": cb, "redirect_uris": cb,
                                    "scopes": scopes, "require_scopes": True}}))
EOF
)
API_RESP=$(curl -sf "${H[@]}" -X POST "$C/api/v1/accounts/self/developer_keys" -d "$API")
API_ID=$(echo "$API_RESP" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
API_SECRET=$(echo "$API_RESP" | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"])')
curl -sf "${H[@]}" -X POST "$C/api/v1/accounts/self/developer_keys/$API_ID/developer_key_account_bindings" \
  -d '{"developer_key_account_binding":{"workflow_state":"on"}}' >/dev/null
echo "api developer key: $API_ID"

# 4. Course Navigation is default-disabled: optionally enable it in one course
if [ -n "$COURSE" ]; then
TAB=$(curl -sf "${H[@]}" "$C/api/v1/courses/$COURSE/tabs" | python3 -c "import json,sys; print([t['id'] for t in json.load(sys.stdin) if t['id'].endswith('_$TOOL_ID')][0])")
curl -sf "${H[@]}" -X PUT "$C/api/v1/courses/$COURSE/tabs/$TAB" -d '{"hidden":false}' >/dev/null
echo "course tab $TAB enabled"
fi

# 5. Record in OpenCredential (secret passed by env, never on the command line or in files)
docker compose exec -T -e OC_CANVAS_API_CLIENT_SECRET="$API_SECRET" api \
  oc canvas register --institution "$INST" --create-institution "University of Liverpool (Development)" \
  --base-url "$C" --client-id "$LTI_ID" --deployment-id "$DEP_ID" \
  --api-client-id "$API_ID" --name "Local Canvas"
