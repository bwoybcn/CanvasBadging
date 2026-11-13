#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dependency licence gate (ADR-0018, S-LIC-01).

Usage:
  check_licences.py python <pip-licenses --format=json output file>
  check_licences.py npm <path to package dir with node_modules>   (production deps only)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ALLOWED = {
    "MIT", "MIT-0", "MIT-CMU", "BSD", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD",
    "Apache-2.0", "Apache Software License", "MPL-2.0", "Mozilla Public License 2.0 (MPL 2.0)",
    "LGPL-2.1-or-later", "LGPL-3.0-only", "LGPL-3.0-or-later",
    "GNU Lesser General Public License v3 (LGPLv3)",
    "GNU Library or Lesser General Public License (LGPL)",
    "PSF-2.0", "Python-2.0", "Python Software Foundation License", "HPND", "Unlicense",
    "CC0-1.0", "BlueOak-1.0.0", "CC-BY-4.0", "GPL-3.0-or-later", "AGPL-3.0-or-later",
    "MIT License", "BSD License", "ISC License (ISCL)",
}
# Packages whose metadata is missing/odd but whose licence was checked by hand.
REVIEWED = {
    "opencredential": "AGPL-3.0-or-later (this project)",
    "jsonify": "Public Domain; transitive frontend dependency, compatible with AGPL",
}


def acceptable(expr: str) -> bool:
    expr = expr.strip()
    if expr.startswith("(") and expr.endswith(")"):
        expr = expr[1:-1]
    if not expr or expr == "UNKNOWN":
        return False
    for alternative in re.split(r"\s+OR\s+|;\s*", expr):
        parts = [p.strip() for p in re.split(r"\s+AND\s+", alternative)]
        if all(p in ALLOWED for p in parts):
            return True
    return False


def check(pairs: list[tuple[str, str]]) -> int:
    bad = [(n, lic) for n, lic in pairs if n not in REVIEWED and not acceptable(lic)]
    for name, lic in bad:
        print(f"DISALLOWED  {name}: {lic!r}")
    print(f"checked {len(pairs)} packages, {len(bad)} not on the allowlist")
    return 1 if bad else 0


def python(path: str) -> int:
    rows = json.loads(Path(path).read_text())
    return check([(r["Name"], r.get("License-Expression") or r["License"]) for r in rows])


def npm(pkg_dir: str) -> int:
    out = subprocess.run(
        ["npm", "ls", "--omit=dev", "--all", "--parseable"],
        cwd=pkg_dir, capture_output=True, text=True, check=False,
    ).stdout.splitlines()
    pairs = []
    for line in out[1:]:
        manifest = json.loads((Path(line) / "package.json").read_text())
        lic = manifest.get("license", "")
        if isinstance(lic, dict):
            lic = lic.get("type", "")
        pairs.append((manifest.get("name", line), lic))
    return check(sorted(set(pairs)))


if __name__ == "__main__":
    kind, arg = sys.argv[1], sys.argv[2]
    sys.exit(python(arg) if kind == "python" else npm(arg))
