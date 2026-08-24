# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Black-box tests for registry-driven manual installation — check_rst project
"""Verify private-prefix and staged-package manual installation."""

from __future__ import annotations

import os
import runpy
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = PROJECT_ROOT / "tools" / "install_man_pages.py"


def _registered_outputs() -> set[Path]:
    config: dict[str, Any] = runpy.run_path(str(PROJECT_ROOT / "docs" / "conf.py"))
    return {
        Path(f"man{section}") / f"{target}.{section}"
        for _source, target, _description, _authors, section in config["man_pages"]
    }


def _fake_makewhatis(tmp_path: Path, *, exit_code: int = 0) -> tuple[dict[str, str], Path]:
    executable_dir = tmp_path / "bin"
    executable_dir.mkdir()
    log = tmp_path / "makewhatis.log"
    executable = executable_dir / "makewhatis"
    executable.write_text(
        f'#!/bin/sh\nprintf \'%s\\n\' "$@" > "$CHECK_RST_INDEX_LOG"\nexit {exit_code}\n',
        encoding="utf-8",
    )
    executable.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = os.pathsep.join((str(executable_dir), environment["PATH"]))
    environment["CHECK_RST_INDEX_LOG"] = str(log)
    return environment, log


def _run_installer(*arguments: str, environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(INSTALLER), *arguments],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )


@pytest.mark.integration
def test_installer_builds_private_prefix_and_updates_its_index(tmp_path: Path) -> None:
    prefix = tmp_path / "opt"
    build_dir = tmp_path / "build"
    environment, index_log = _fake_makewhatis(tmp_path)

    result = _run_installer(
        "--prefix",
        str(prefix),
        "--build-dir",
        str(build_dir),
        environment=environment,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    man_root = prefix / "share" / "man"
    installed = {path.relative_to(man_root) for path in man_root.glob("man*/*") if path.is_file()}
    assert installed == _registered_outputs()
    assert all(stat.S_IMODE((man_root / path).stat().st_mode) == 0o644 for path in installed)
    assert all('.TH "' in (man_root / path).read_text(encoding="utf-8") for path in installed)
    assert index_log.read_text(encoding="utf-8").strip() == str(man_root)
    assert f"installed {len(_registered_outputs())} manual page(s)" in result.stdout
    assert "updated manual index" in result.stdout
    assert result.stderr == ""


@pytest.mark.integration
def test_installer_stages_destdir_without_updating_host_index(tmp_path: Path) -> None:
    destination_root = tmp_path / "package"
    build_dir = tmp_path / "build"
    environment, index_log = _fake_makewhatis(tmp_path, exit_code=99)

    result = _run_installer(
        "--prefix",
        "/usr",
        "--destdir",
        str(destination_root),
        "--build-dir",
        str(build_dir),
        environment=environment,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    man_root = destination_root / "usr" / "share" / "man"
    installed = {path.relative_to(man_root) for path in man_root.glob("man*/*") if path.is_file()}
    assert installed == _registered_outputs()
    assert not index_log.exists()
    assert f"staged under {destination_root}" in result.stdout
    assert "manual index skipped for DESTDIR" in result.stdout
    assert result.stderr == ""


@pytest.mark.integration
def test_installer_skip_build_rejects_missing_generated_pages(tmp_path: Path) -> None:
    build_dir = tmp_path / "incomplete-build"
    build_dir.mkdir()
    generated = sorted(path.name for path in _registered_outputs())
    for filename in generated[:-1]:
        (build_dir / filename).write_text("generated page\n", encoding="utf-8")

    prefix = tmp_path / "opt"
    result = _run_installer(
        "--prefix",
        str(prefix),
        "--build-dir",
        str(build_dir),
        "--skip-build",
        "--no-index",
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "generated manual page is missing" in result.stderr
    assert "Traceback" not in result.stderr
    assert not prefix.exists()
