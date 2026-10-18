# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Reader commands report a fragment only when its include contexts agree — check_rst project
"""P6: ``outline`` and ``context`` never present one fragment reading as
authoritative when an include context is unavailable or the available
contexts disagree.  The first pair establishes outline's contextual result
and fail-closed boundary; later P6 pairs apply the same contract to context.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from check_rst import cli

if TYPE_CHECKING:
    from pathlib import Path


_MAIN = "######\nMain\n######\n\n**********\nSubtitle\n**********\n\n.. include:: part.rst\n"
_PART = "Shared\n------\n\nBody.\n"


def _commit(repo: Path, *names: str) -> None:
    subprocess.run(["git", "-C", str(repo), "add", *names], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)


def _run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--no-config", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    code = exc.value.code
    return (code if isinstance(code, int) else 1), capsys.readouterr().out


@pytest.mark.integration
def test_outline_refuses_an_unavailable_fragment_context(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A declaration says an unseen includer exists.  Outline must name that
    unavailable context and print no standalone outline as if authoritative."""
    (rst_repo / "part.rst").write_text(_PART, encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "--fragment", "part.rst", "outline", "part.rst")

    assert code == 1, out
    assert "Outline:" not in out
    assert "outline cannot report one structure" in out
    assert "this file is declared a fragment (--fragment 'part.rst')" in out


@pytest.mark.integration
def test_outline_refuses_contexts_with_different_effective_depths(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same physical title is depth 3 through main.rst and depth 2
    through other.rst.  Naming both contexts is safer than printing the
    fragment's unrelated standalone depth."""
    (rst_repo / "main.rst").write_text(_MAIN, encoding="utf-8")
    (rst_repo / "other.rst").write_text("#####\nOther\n#####\n\n.. include:: part.rst\n", encoding="utf-8")
    (rst_repo / "part.rst").write_text(_PART, encoding="utf-8")
    _commit(rst_repo, "main.rst", "other.rst", "part.rst")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "outline", "part.rst")

    assert code == 1, out
    assert "Outline:" not in out
    assert "outline cannot report one structure" in out
    assert "main.rst reports depth 3" in out
    assert "other.rst reports depth 2" in out


@pytest.mark.integration
def test_outline_reports_the_effective_depth_from_one_include_context(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A fragment has no standalone hierarchy authority: the one visible
    includer places its section at depth 3, not standalone depth 1."""
    (rst_repo / "main.rst").write_text(_MAIN, encoding="utf-8")
    (rst_repo / "part.rst").write_text(_PART, encoding="utf-8")
    _commit(rst_repo, "main.rst", "part.rst")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "outline", "part.rst")

    # The source still has contextual hierarchy findings; this assertion is
    # about the reader's reported tree, not check's error status.
    assert code == 1, out
    assert "levels: 3 '-u' (1)" in out
    assert "\n          1-4:-u Shared\n" in out


@pytest.mark.integration
def test_outline_omits_a_fragment_title_the_context_does_not_parse(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A new fifth style inside a level-3 section is an illegal skip.
    Docutils drops the fragment heading, so its standalone section must not
    survive in the contextual outline."""
    main = """##########
Main
##########

**********
Level 2
**********

==========
Level 3
==========

----------
Level 4
----------

==========
Back to 3
==========

.. include:: part.rst
"""
    part = "Shared\n*****\n\nBody.\n"
    (rst_repo / "main.rst").write_text(main, encoding="utf-8")
    (rst_repo / "part.rst").write_text(part, encoding="utf-8")
    _commit(rst_repo, "main.rst", "part.rst")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "outline", "part.rst")

    assert code == 1, out
    assert "Outline: part.rst" in out
    assert ":*u Shared" not in out
