# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Regression tests for the check_rst.cli package split itself — check_rst project
"""Pin the shared-state guarantee the src/check_rst/cli.py package split needs.

Module-level state read from more than one submodule (PROJECT_ROOT is
   the sharpest example: read from _config/_document/_helpers/_reports/
   _sphinx) is looked up through a qualified `module.NAME` reference, not
   a captured `from .module import NAME` copy — the split broke ~40
   existing monkeypatch.setattr(check_rst, "PROJECT_ROOT", ...)-style
   tests this exact way (a captured copy is a separate binding, invisible
   to a patch applied to a different module's namespace) before that was
   found and fixed.

This is invisible until a cleanup reverts a qualified
``_helpers.PROJECT_ROOT`` access to a captured bare import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from check_rst.cli import _config, _document, _helpers

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_project_root_monkeypatch_observed_by_document_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_document.py reads PROJECT_ROOT via a qualified _helpers.PROJECT_ROOT
    lookup specifically so a patch applied to _helpers is visible
    here, in a completely different submodule — this is the Document-facade
    half of the fix; _load_config's own consumer is pinned separately below."""
    monkeypatch.setattr(_helpers, "PROJECT_ROOT", tmp_path)
    document = _document.Document(tmp_path / "irrelevant.rst")
    assert document.project_root == tmp_path


@pytest.mark.unit
def test_project_root_monkeypatch_observed_by_load_config_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_config.py's own consumer of the same qualified PROJECT_ROOT lookup:
    with no explicit path and no discoverable config file, _load_config's
    final fallback roots the LoadedConfig at PROJECT_ROOT -- must be
    *this* patched tmp_path, not the real cwd _helpers.PROJECT_ROOT
    defaulted to at process start."""
    monkeypatch.setattr(_helpers, "PROJECT_ROOT", tmp_path)
    loaded = _config._load_config()
    assert loaded.root == tmp_path.resolve()
