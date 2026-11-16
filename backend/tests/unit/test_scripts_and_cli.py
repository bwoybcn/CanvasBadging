# SPDX-License-Identifier: AGPL-3.0-or-later
"""Small robustness gaps in the command line and the scripts (whole-product review,
16 Nov 2026, finding 19)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from opencredential.paths import REPO_DIR

SCRIPTS = Path(REPO_DIR) / "scripts"


def _licences() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_licences", SCRIPTS / "check_licences.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_python_dash_m_has_every_command_group() -> None:
    """``python -m opencredential.cli`` used to start before lti, canvas and admin were added."""
    out = subprocess.run(
        [sys.executable, "-m", "opencredential.cli", "--help"],
        capture_output=True,
        text=True,
        check=True,
        env={"OC_ENV": "test", "PATH": "/usr/bin:/bin", "COLUMNS": "200"},
    ).stdout
    for group in ("lti", "canvas", "admin", "openapi"):
        assert group in out


def test_licence_gate_fails_when_npm_lists_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A folder with no installed packages used to pass with "checked 0 packages"."""
    (tmp_path / "package.json").write_text('{"name": "empty", "version": "1.0.0"}')
    assert _licences().npm(str(tmp_path)) == 1
    assert "NOTHING CHECKED" in capsys.readouterr().out


def test_licence_gate_fails_on_an_empty_python_list(tmp_path: Path) -> None:
    listing = tmp_path / "licences.json"
    listing.write_text("[]")
    assert _licences().python(str(listing)) == 1


def test_licence_gate_still_passes_and_fails_on_real_lists(tmp_path: Path) -> None:
    listing = tmp_path / "licences.json"
    listing.write_text('[{"Name": "httpx", "License": "BSD-3-Clause"}]')
    assert _licences().python(str(listing)) == 0
    listing.write_text('[{"Name": "mystery", "License": "Proprietary"}]')
    assert _licences().python(str(listing)) == 1


def test_backup_folder_is_created_private() -> None:
    """The backup folder holds database dumps: the private file mode must be set before the
    folder is made, or the folder itself is readable by other accounts on the server."""
    lines = (SCRIPTS / "backup.sh").read_text().splitlines()
    umask = next(i for i, line in enumerate(lines) if line.strip().startswith("umask 077"))
    mkdir = next(i for i, line in enumerate(lines) if line.strip().startswith("mkdir -p"))
    assert umask < mkdir
