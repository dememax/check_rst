# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Regression tests for the check_rst.cli package split itself — check_rst project
"""Pins the two structural guarantees the src/check_rst/cli.py -> package
split depended on, both of which were only verified by hand (a one-off
dir()-parity diff, a post-hoc test-suite run) when the split landed:

1. check_rst.cli re-exports every function/class its submodules define —
   the split's whole backward-compatibility contract for existing callers
   (tests included) that reach a name via check_rst.cli.<name> rather than
   the submodule directly.
2. Module-level state read from more than one submodule (PROJECT_ROOT is
   the sharpest example: read from _config/_document/_helpers/_reports/
   _sphinx) is looked up through a qualified `module.NAME` reference, not
   a captured `from .module import NAME` copy — the split broke ~40
   existing monkeypatch.setattr(check_rst, "PROJECT_ROOT", ...)-style
   tests this exact way (a captured copy is a separate binding, invisible
   to a patch applied to a different module's namespace) before that was
   found and fixed.

Neither property is something a normal behavioral test would ever
exercise — both are invisible until some future edit (a new checker added
without updating __init__.py's re-export list, a "cleanup" that reverts a
qualified _helpers.PROJECT_ROOT access back to a bare import) quietly
breaks them again.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import types
    from pathlib import Path

_SUBMODULE_NAMES = (
    "_types",
    "_helpers",
    "_output",
    "_config",
    "_document",
    "_checks",
    "_sphinx",
    "_reports",
)


@pytest.mark.unit
def test_cli_package_reexports_every_submodule_function_and_class(check_rst: types.ModuleType) -> None:
    """Every function/class actually DEFINED in one of the 8 submodules
    (checked via __module__, not just present via some other submodule's
    own cross-import) must also resolve as check_rst.cli.<name>, as the
    exact same object -- not a same-named replacement. Constants/regex
    patterns/frozensets are deliberately not checked here: they have no
    reliable __module__ provenance to distinguish "defined here" from
    "imported here", so this covers what a missed re-export would most
    likely be — a newly added check_*/fix_*/find_* function or dataclass."""
    missing: list[str] = []
    for modname in _SUBMODULE_NAMES:
        submodule = getattr(check_rst, modname)
        expected_module = f"check_rst.cli.{modname}"
        for name, obj in vars(submodule).items():
            if name.startswith("__"):
                continue
            if not (inspect.isfunction(obj) or inspect.isclass(obj)):
                continue
            if getattr(obj, "__module__", None) != expected_module:
                continue  # defined elsewhere, merely visible here via its own import
            if getattr(check_rst, name, None) is not obj:
                missing.append(f"{modname}.{name}")
    assert missing == []


@pytest.mark.unit
def test_project_root_monkeypatch_observed_by_document_construction(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_document.py reads PROJECT_ROOT via a qualified _helpers.PROJECT_ROOT
    lookup specifically so a patch applied to check_rst._helpers is visible
    here, in a completely different submodule — this is the Document-facade
    half of the fix; _load_config's own consumer is pinned separately below."""
    monkeypatch.setattr(check_rst._helpers, "PROJECT_ROOT", tmp_path)
    document = check_rst.Document(tmp_path / "irrelevant.rst")
    assert document.project_root == tmp_path


@pytest.mark.unit
def test_project_root_monkeypatch_observed_by_load_config_fallback(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_config.py's own consumer of the same qualified PROJECT_ROOT lookup:
    with no explicit path and no discoverable config file, _load_config's
    final fallback roots the LoadedConfig at PROJECT_ROOT -- must be
    *this* patched tmp_path, not the real cwd _helpers.PROJECT_ROOT
    defaulted to at process start."""
    monkeypatch.setattr(check_rst._helpers, "PROJECT_ROOT", tmp_path)
    loaded = check_rst._load_config()
    assert loaded.root == tmp_path.resolve()
