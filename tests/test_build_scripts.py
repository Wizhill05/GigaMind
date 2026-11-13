"""The failure check itself must reject a broken deployment build."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("broken", [False, True])
def test_build_failure_check_detects_swallowed_failures(tmp_path, broken):
    scripts = tmp_path / "scripts"
    shutil.copytree(ROOT / "scripts", scripts)
    build = scripts / "build.sh"
    if broken:
        build.write_text("#!/bin/sh\nexit 0\n")
    result = subprocess.run(
        [str(scripts / "check-build-failure.sh")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == (1 if broken else 0), result.stdout + result.stderr
