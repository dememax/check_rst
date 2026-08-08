# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Shared pytest fixtures — check_rst project
"""Shared fixtures for the standalone check_rst regression suite.

check_rst/rst_repo/build_sphinx_env/_isolated_project_root moved here from
test_check_rst.py when that file was split along the same module boundaries
as src/check_rst/cli/ (found by code review: every one of these four is used
across many of the split files, not just one topic area — check_rst and
rst_repo by nearly every test in the whole suite, so a per-file duplicate
would drift; _isolated_project_root is autouse=True, so centralizing it here
is what keeps that isolation applying uniformly to every split file, not an
optional convenience)."""

from __future__ import annotations

import subprocess
import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import types
    from collections.abc import Callable
    from pathlib import Path


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """Create an isolated Git repository with one empty baseline commit."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test User"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "Initial commit"],
        check=True,
        capture_output=True,
    )
    return tmp_path


@pytest.fixture(scope="session")
def check_rst() -> types.ModuleType:
    """Return the installed-layout implementation module once per session."""
    from check_rst import cli

    return cli


@pytest.fixture
def rst_repo(check_rst: types.ModuleType, tmp_git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point check_rst's PROJECT_ROOT at the temp git repo for git-scoped checks."""
    monkeypatch.setattr(check_rst._helpers, "PROJECT_ROOT", tmp_git_repo)
    return tmp_git_repo


@pytest.fixture
def build_sphinx_env(check_rst: types.ModuleType, tmp_path: Path) -> Callable[[str], tuple[object, str]]:
    """Return build(rst_text) -> (env, docname) for tmp_path/index.rst.

    Writes a minimal conf.py once, then on each call writes rst_text to
    index.rst and runs a real in-process Sphinx 'dummy' build (resolves the
    full environment/doctree, writes no HTML) against it.
    """
    (tmp_path / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")

    def _build(rst_text: str) -> tuple[object, str]:
        (tmp_path / "index.rst").write_text(textwrap.dedent(rst_text), encoding="utf-8")
        env, _ = check_rst._build_sphinx_env(tmp_path, tmp_path / "_build")
        docname = check_rst._docname_for(env, tmp_path / "index.rst")
        assert docname is not None
        return env, docname

    return _build


@pytest.fixture(autouse=True)
def _isolated_project_root(check_rst: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every test from the real repository's .check_rst.toml.

    PROJECT_ROOT is captured at import time — under pytest that is the
    Journal itself, which now carries a real config declaring sphinx-src.
    Without this guard, every CLI test that doesn't patch PROJECT_ROOT
    silently picks up that config and runs a FULL Journal Sphinx build.
    Found via the CALL_COUNTS instrumentation (Max's counters idea): a
    "heuristic-mode" test showed _build_sphinx_env=1, run_sphinx=1 —
    deterministic proof, where wall-clock only raised suspicion.  Autouse
    fixtures run before explicitly requested ones, so rst_repo's own
    PROJECT_ROOT patch still wins for tests that use it.
    """
    monkeypatch.setattr(check_rst._helpers, "PROJECT_ROOT", tmp_path)
    check_rst.CALL_COUNTS.clear()  # each test starts from zero — counts are assertable
