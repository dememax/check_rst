# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Title-model contract: mutation fidelity, topology safety, idempotence — check_rst project
"""The parser-free title model that check, fix and diff share.

Every case runs through the same CLI paths an author uses, in each selection
scope: an explicit file (whole-file), bare (changed Git hunks), and
``--git-scope``.  Three properties are asserted separately:

* mutation fidelity — a refusal is reported by ``check`` as a non-fixable
  ERROR, and no finding in that file claims a fix that ``fix`` will not make;
* topology safety — a refused file keeps its bytes, and an accepted fix
  keeps the section tree Docutils reads, or produces the tree a title-block
  placeholder declares;
* idempotence — after an accepted fix, ``check`` is clean and a second fix
  changes nothing.

The section-tree oracle is Docutils itself, never check_rst's own outline.
"""

from __future__ import annotations

import dataclasses
import json
import textwrap
from typing import TYPE_CHECKING, Any

import docutils.core
import docutils.nodes
import pytest
from _support import _git

from check_rst import cli

if TYPE_CHECKING:
    from pathlib import Path

SCOPES = ("explicit", "bare", "git-scope")


@dataclasses.dataclass(frozen=True, slots=True)
class Case:
    """One title-model scenario: a committed base and the author's edit."""

    name: str
    base: str | None
    edited: str
    refusal: str | None
    tree: tuple[tuple[int, str], ...] = ()


def _scope_args(scope: str) -> list[str]:
    if scope == "explicit":
        return ["doc.rst"]
    if scope == "git-scope":
        return ["--git-scope", "doc.rst"]
    return []


def _tree(text: str) -> tuple[tuple[int, str], ...]:
    """Return Docutils' own (depth, title) section tree for *text*."""
    document = docutils.core.publish_doctree(
        text,
        settings_overrides={"report_level": 5, "halt_level": 5, "doctitle_xform": False},
    )
    found: list[tuple[int, str]] = []

    def walk(node: docutils.nodes.Element, depth: int) -> None:
        for child in node.children:
            if isinstance(child, docutils.nodes.section):
                title = child.next_node(docutils.nodes.title)
                found.append((depth, title.astext() if title is not None else ""))
                walk(child, depth + 1)

    walk(document, 1)
    return tuple(found)


def _run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--no-config", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return int(exc.value.code or 0), capsys.readouterr().out


def _prepare(repo: Path, case: Case) -> Path:
    path = repo / "doc.rst"
    if case.base is not None:
        path.write_text(case.base, encoding="utf-8")
        _git(repo, "add", path.name)
        _git(repo, "commit", "-m", f"base for {case.name}")
    path.write_text(case.edited, encoding="utf-8")
    return path


def _json_findings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], scope: str
) -> tuple[int, list[dict[str, Any]]]:
    code, out = _run(monkeypatch, capsys, "check", "--format=json", *_scope_args(scope))
    data = json.loads(out)
    return code, [finding for record in data["files"] for finding in record["findings"]]


def _assert_contract(
    repo: Path,
    case: Case,
    scope: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(repo)
    path = _prepare(repo, case)
    before = path.read_bytes()

    check_exit, findings = _json_findings(monkeypatch, capsys, scope)
    diff_exit, diff_out = _run(monkeypatch, capsys, "diff", "--fast", *_scope_args(scope))
    fix_exit, fix_out = _run(monkeypatch, capsys, "fix", "--fast", *_scope_args(scope))

    if case.refusal is not None:
        refusals = [finding for finding in findings if finding["code"] == case.refusal]
        # Mutation fidelity: the refusal is visible under --skip-fixable, and
        # nothing else in the refused file claims a fix that fix will not make.
        assert refusals, findings
        assert all(f["severity"] == "ERROR" and not f["fixable"] for f in refusals)
        assert not [finding for finding in findings if finding["fixable"]], findings
        assert check_exit == 1
        # diff and fix report the refusal instead of presenting a guess.
        assert diff_exit == 1
        assert "@@" not in diff_out, diff_out
        assert "fix refused" in diff_out
        assert fix_exit == 1
        assert "fix refused" in fix_out, fix_out
        # Topology safety: the refused file keeps its bytes.
        assert path.read_bytes() == before
        return

    # Topology safety: the accepted fix yields the declared section tree.
    assert fix_exit == 0, fix_out
    assert _tree(path.read_text(encoding="utf-8")) == case.tree
    # Idempotence: check is clean and a second fix changes nothing.
    fixed = path.read_bytes()
    assert _run(monkeypatch, capsys, "check", *_scope_args(scope))[0] == 0
    assert _run(monkeypatch, capsys, "fix", "--fast", *_scope_args(scope))[0] == 0
    assert path.read_bytes() == fixed


_NOTES_BASE = textwrap.dedent("""\
    #######
    Notes
    #######

    *******
    First
    *******

    Text.
    """)

SHARED_LINE = Case(
    name="title block directly after a text line",
    base=_NOTES_BASE,
    edited=_NOTES_BASE + "*********\nSecond section\n*********\n\nMore text.\n",
    refusal="adornment.shared-line",
)


@pytest.mark.integration
@pytest.mark.parametrize("scope", SCOPES)
def test_shared_adornment_line_is_refused(
    rst_repo: Path,
    scope: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One adornment line cannot be both a text line's underline and a block's
    overline: Docutils reads the underline, the placeholder convention the
    overline, so fix must not turn the text line into a heading (CR-40)."""
    _assert_contract(rst_repo, SHARED_LINE, scope, monkeypatch, capsys)


_AFTER_COMMENT = "##########\n Top\n##########\n\n.. a comment\nSub title\n*********\n\nBody text.\n"
_AFTER_FIELD_LIST = "##########\n Top\n##########\n\n:field: value\nSub title\n*********\n\nBody text.\n"
_REWRITES_CORRECT_HEADING = textwrap.dedent("""\
    #####
    Top
    #####

    :field: value
    Sub
    ***

    Body.

    =======
    Deeper
    =======

    More body.
    """)

UNSEPARATED_TITLES = (
    Case("title directly after a comment", None, _AFTER_COMMENT, "adornment.unseparated-title"),
    Case("title directly after a field list", None, _AFTER_FIELD_LIST, "adornment.unseparated-title"),
    Case("unseparated title beside a correct heading", None, _REWRITES_CORRECT_HEADING, "adornment.unseparated-title"),
)


@pytest.mark.integration
@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("case", UNSEPARATED_TITLES, ids=lambda case: case.name)
def test_unseparated_title_blocks_structural_fixes(
    rst_repo: Path,
    case: Case,
    scope: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Docutils reads a title right after a field list or comment, but the
    parser-free model cannot prove it.  Check used to call it fixable while
    fix ignored it, and fix rewrote a correct heading around it (CR-29)."""
    _assert_contract(rst_repo, case, scope, monkeypatch, capsys)


@pytest.mark.integration
def test_unseparated_title_is_a_non_fixable_error_even_when_nothing_else_changes(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With nothing else to fix there is nothing to refuse, but check still
    reports the title fix cannot prove, and fix leaves the file alone."""
    monkeypatch.chdir(rst_repo)
    source = "#####\nTop\n#####\n\n.. a comment\nSub title\n*********\n\nBody text.\n"
    path = rst_repo / "doc.rst"
    path.write_text(source, encoding="utf-8")

    check_exit, findings = _json_findings(monkeypatch, capsys, "explicit")
    fix_exit, fix_out = _run(monkeypatch, capsys, "fix", "--fast", "doc.rst")

    assert check_exit == 1
    assert [(f["lineno"], f["code"], f["severity"], f["fixable"]) for f in findings] == [
        (6, "adornment.unseparated-title", "ERROR", False)
    ]
    assert "Docutils reads 'Sub title' as a section title" in findings[0]["text"]
    assert fix_exit == 0
    assert "fix refused" not in fix_out
    assert path.read_text(encoding="utf-8") == source


_AFTER_PARAGRAPH = _NOTES_BASE + "Second section\n*********\n\nMore text.\n"

PARAGRAPH_CANDIDATE_BLOCKING = Case(
    name="title directly after a paragraph line, with another fix pending",
    base=None,
    edited=_AFTER_PARAGRAPH.replace("*******\nFirst\n*******", "***\nFirst\n***"),
    refusal="adornment.unseparated-title",
)


@pytest.mark.integration
@pytest.mark.parametrize("scope", SCOPES)
def test_paragraph_read_candidate_blocks_a_pending_fix(
    rst_repo: Path,
    scope: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """While it blocks a fix, a candidate Docutils reads as paragraph text is
    a refusal like any other unseparated title (refused since CR-29)."""
    _assert_contract(rst_repo, PARAGRAPH_CANDIDATE_BLOCKING, scope, monkeypatch, capsys)


@pytest.mark.integration
@pytest.mark.parametrize("scope", SCOPES)
def test_paragraph_read_candidate_is_a_visible_warning(
    rst_repo: Path,
    scope: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A section written right under a paragraph line is silently lost to
    Docutils.  Check must say so in its own words, not through an unrelated
    nested-bold warning about the adornment line (CR-41)."""
    monkeypatch.chdir(rst_repo)
    case = Case("title directly after a paragraph line", _NOTES_BASE, _AFTER_PARAGRAPH, None)
    path = _prepare(rst_repo, case)

    check_exit, findings = _json_findings(monkeypatch, capsys, scope)
    fix_exit, fix_out = _run(monkeypatch, capsys, "fix", "--fast", *_scope_args(scope))

    assert [(f["lineno"], f["code"], f["severity"], f["fixable"]) for f in findings] == [
        (10, "adornment.unseparated-title", "WARNING", False)
    ]
    assert "Docutils reads them as paragraph text" in findings[0]["text"]
    assert check_exit == 0
    assert fix_exit == 0
    assert "fix refused" not in fix_out
    assert path.read_text(encoding="utf-8") == _AFTER_PARAGRAPH
