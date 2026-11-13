# SPDX-License-Identifier: AGPL-3.0-or-later
"""W6 conformance step: what a *student* downloads or shares is what independent verifiers accept.

Against a running stack (after run-conformance.sh issued the demo credentials), for each demo
learner with an active credential:

1. sign in through development login and download the credential (student export endpoint);
2. turn on a public link and fetch ``/verify/<share>/credential.json`` without a session, the
   way a wallet's "add from URL" or an employer would;
3. check the public page is served with ``noindex`` and without the learner's name.

Both files go to ``$OUT/student`` for the DCC verifier-core and 1EdTech inspector steps.
Usage: ``uv run python ../tests/conformance/student_share.py OUT_DIR [BASE_URL]``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

DEMO = "demo-university"


def main(out: Path, base: str) -> int:
    out.mkdir(parents=True, exist_ok=True)
    api = httpx.Client(base_url=base, timeout=30)
    public = httpx.Client(base_url=base, timeout=30)
    written = 0
    for user in api.get(f"/dev/institutions/{DEMO}/users").raise_for_status().json():
        if "student" not in user["roles"]:
            continue
        token = (
            api.post("/dev/login", json={"institution": DEMO, "user_id": user["id"]})
            .raise_for_status()
            .json()["token"]
        )
        h = {"authorization": f"Bearer {token}"}
        for cred in api.get("/api/v1/learners/me/credentials", headers=h).raise_for_status().json():
            if cred["status"] != "active":
                continue
            export = api.get(f"/api/v1/credentials/{cred['id']}/export", headers=h)
            export.raise_for_status()
            (out / f"export-{cred['id']}.json").write_bytes(export.content)
            share = api.put(f"/api/v1/credentials/{cred['id']}/share", json={}, headers=h)
            share_id = share.raise_for_status().json()["share"]["url"].rsplit("/", 1)[1]
            page = public.get(f"/verify/{share_id}")
            page.raise_for_status()
            assert "noindex" in page.headers["x-robots-tag"], "share page must be noindex"
            name = user["display_name"]
            assert not name or name not in page.text, "learner name shown without consent"
            shared = public.get(f"/verify/{share_id}/credential.json").raise_for_status()
            assert json.loads(shared.content) == json.loads(export.content)
            (out / f"shared-{cred['id']}.json").write_bytes(shared.content)
            written += 2
    if written == 0:
        print("no active student credentials found", file=sys.stderr)
        return 1
    print(f"wrote {written} student-obtained credential files to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"))
