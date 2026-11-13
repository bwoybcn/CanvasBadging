# ADR-0018: Licence and dependency policy

Date: 2026-11-13 · Status: Accepted

## Decision
Project licence AGPL-3.0-or-later (SPDX headers in source files, `LICENSE` with the full text). Documentation CC BY-SA 4.0. Dependencies must be under one of: MIT, BSD-2/3-Clause, ISC, Apache-2.0, MPL-2.0, LGPL-2.1+/3.0, PSF-2.0, Python-2.0, HPND/MIT-CMU, Unlicense/0BSD, CC0, or GPL-3.0/AGPL-3.0 compatible. CI runs `pip-licenses` and `license-checker` against this allowlist (S-LIC-01). Badge template artwork must be original or CC0/CC BY, with a licence file next to it. No dependency may require a commercial service or licence key.
