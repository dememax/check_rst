# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Plain (non-fixture) helpers and constants shared across the split test
# files — check_rst project
"""Shared, non-fixture test support: writing an .rst/git-tracked file,
building a real Sphinx env, and the couple of small canonical RST blocks
used by more than one of the split test files.

Split out of test_check_rst.py alongside conftest.py's own fixture split:
these five are plain functions/module constants, not pytest fixtures, so
they belong in an importable module rather than conftest.py (fixtures need
conftest.py's auto-discovery; plain helpers just need `from _support import
...` — confirmed available: pytest's default import mode prepends tests/ to
sys.path for every file it collects there, so a sibling module resolves the
same way for every split file, with no tests/__init__.py needed)."""

from __future__ import annotations

import subprocess
import textwrap
from collections.abc import Callable
from typing import TYPE_CHECKING

from check_rst.cli import _sphinx

if TYPE_CHECKING:
    from pathlib import Path

    import sphinx.environment


type BuildSphinxEnv = Callable[[str], tuple[sphinx.environment.BuildEnvironment, str]]


def _rst(tmp_path: Path, content: str) -> Path:
    """Write dedented RST content to a temp file and return its path."""
    p = tmp_path / "test.rst"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _build_multi_file_env(tmp_path: Path, files: dict[str, str]) -> sphinx.environment.BuildEnvironment:
    """Write conf.py + *files* (docname -> rst text) under tmp_path and
    return a real, in-process Sphinx env over them.

    root_doc is pinned to the first key — Sphinx requires ITS OWN master
    document to exist and defaults to "index", which these fixtures don't
    always define."""
    root_doc = next(iter(files))
    (tmp_path / "conf.py").write_text(
        f'project = "test"\nextensions = []\nroot_doc = "{root_doc}"\n',
        encoding="utf-8",
    )
    for docname, text in files.items():
        path = tmp_path / f"{docname}.rst"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")
    env, _warning_text = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    return env


# "Title" = 5 chars → expected adornment length 7; "######" is 6 → ERROR.
_BAD_BLOCK = textwrap.dedent("""\
    Some text.

    ######
    Title
    ######

    More text.
    """)

# Same block, correctly formed — no violations.
_GOOD_BLOCK = textwrap.dedent("""\
    Some text.

    #######
    Title
    #######

    More text.
    """)
