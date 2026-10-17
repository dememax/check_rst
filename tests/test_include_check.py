# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# check judges a file's titles in its include contexts (CR-43, P5) — check_rst project
"""check, like full fix, judges a file meant for inclusion in the documents
that compose it, never as a standalone document it is not (contract rule 2,
and Codex's K5).  Its structural findings are those of each composed
context, mapped back to its own lines; contexts that disagree give the
plan's one include.context-conflict ERROR (rule 4).
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from check_rst import cli

if TYPE_CHECKING:
    from pathlib import Path

_MAIN = "######\nMain\n######\n\n*********\nSubtitle\n*********\n\n=======\nIntro\n=======\n\nText.\n\n.. include:: part.rst\n"
_PART = "========\nShared\n========\n\nBody.\n"
_DASH = "Shared\n------\n\nBody.\n"
_STANDALONE_REMAP = "fix remaps '=' to '#'"


def _commit(repo: Path, *names: str) -> None:
    subprocess.run(["git", "-C", str(repo), "add", *names], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)


def _run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--no-config", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    code = exc.value.code
    return (code if isinstance(code, int) else 1), capsys.readouterr().out


def _files(repo: Path, **texts: str) -> dict[str, Path]:
    paths = {}
    for name, text in texts.items():
        path = repo / f"{name}.rst"
        path.write_text(text, encoding="utf-8")
        paths[name] = path
    return paths


@pytest.mark.integration
@pytest.mark.parametrize("scope", [("part.rst",), ()], ids=["explicit", "git-scope"])
def test_check_judges_a_fragment_in_its_includer_not_as_standalone(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], scope: tuple[str, ...]
) -> None:
    """K5: CR-43's fragment is consistent at level 3 in main.rst.  check used
    to report it as a standalone page title fix would remap."""
    paths = _files(rst_repo, main=_MAIN, part=_PART)
    _commit(rst_repo, "main.rst", "part.rst")
    paths["part"].write_text(_PART + "\nOne more body line.\n", encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "check", *scope)

    assert code == 0, out
    assert _STANDALONE_REMAP not in out


@pytest.mark.integration
def test_full_fix_of_a_consistent_fragment_reports_nothing_false(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """K5's interim state ends: full fix keeps the fragment's "=" and its
    Phase 1 no longer claims fix would remap it."""
    paths = _files(rst_repo, main=_MAIN, part=_PART)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "fix", "part.rst")

    assert code == 0, out
    assert _STANDALONE_REMAP not in out
    assert paths["part"].read_text(encoding="utf-8") == _PART


@pytest.mark.integration
def test_check_reports_the_composed_finding_fix_makes(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Level 4 in main.rst, the fragment's underline-only "-" needs its
    overline: a fixable finding of the composed document, not the
    standalone remap to "#"."""
    _files(rst_repo, main=_MAIN, part=_DASH)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "check", "part.rst")
    skip_code, skip_out = _run(monkeypatch, capsys, "check", "--skip-fixable", "part.rst")

    assert code == 1, out
    assert "part.rst:2: ERROR: in the document main.rst composes, underline-only title" in out
    assert "is this document's level 1" not in out
    assert skip_code == 0, skip_out


@pytest.mark.integration
def test_check_drops_a_fragment_false_second_top_level_title(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CR-43's second symptom: two sections at the fragment's top are two
    level-3 sections in main.rst, not two document titles."""
    part = "========\nShared\n========\n\nBody.\n\n======\nAlso\n======\n\nMore.\n"
    _files(rst_repo, main=_MAIN, part=part)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "check", "part.rst")

    assert code == 0, out
    assert "second effective top-level title" not in out


@pytest.mark.integration
def test_check_reports_disagreeing_contexts_as_one_conflict(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rule 4: the contexts need different styles, so check reports fix's one
    non-fixable conflict, and no finding claims a fix."""
    _files(rst_repo, main=_MAIN, other="#######\nOther\n#######\n\n.. include:: part.rst\n", part=_DASH)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "check", "--skip-fixable", "part.rst")

    assert code == 1, out
    assert (
        "part.rst:1: ERROR: its include contexts need different title styles here: main.rst needs '-o' and "
        "other.rst needs '*o', so fix cannot choose one — make the documents that include it agree"
    ) in out
    assert "underline-only title" not in out


@pytest.mark.integration
def test_check_reports_an_includer_edit_fix_must_refuse(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The includer side: main.rst's own underline-only title would need its
    fragment's "*" changed too, so fix refuses, and check says so instead of
    offering a fixable finding."""
    _files(rst_repo, main="Main\n####\n\nText.\n\n.. include:: part.rst\n", part="Shared\n******\n\nBody.\n")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "check", "--skip-fixable", "main.rst")

    assert code == 1, out
    assert "its title change also needs part.rst:1 to change, and fix changes only this file" in out
