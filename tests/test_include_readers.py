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
def test_outline_hidden_error_hint_excludes_the_printed_reader_refusal(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The not-shown count covers only findings the outline filter hid."""
    (rst_repo / "main.rst").write_text(_MAIN, encoding="utf-8")
    (rst_repo / "other.rst").write_text("#####\nOther\n#####\n\n.. include:: part.rst\n", encoding="utf-8")
    (rst_repo / "part.rst").write_text("Shared\n-----\n\nBody.\n", encoding="utf-8")
    _commit(rst_repo, "main.rst", "other.rst", "part.rst")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "outline", "part.rst")

    assert code == 1, out
    assert "outline cannot report one structure" in out
    assert "  (1 error(s) not shown — rerun with --with-findings to see them)" in out
    assert "check_rst: 1 file(s) checked, 2 error(s)" in out


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


@pytest.mark.integration
@pytest.mark.parametrize("nested", [True, False], ids=["nested-alias", "repeated-fragment"])
@pytest.mark.parametrize("command", ["outline", "context"])
def test_readers_refuse_when_only_one_of_two_same_source_occurrences_parses(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    nested: bool,
    command: str,
) -> None:
    """A surviving duplicate cannot be paired with a dropped occurrence.

    Docutils identifies both occurrences by the same physical source and line.
    The first occurs after an illegal level skip and is dropped; the second is
    a valid depth-5 section.  Whether the first arrives through a selected
    fragment or is another occurrence of that fragment, outline cannot prove
    which planned occurrence the one parsed section represents.
    """
    main = """######
Main
######

**********
Two
**********

=====
Three
=====

----
Four
----

=====
Back3
=====

.. include:: part.rst

-----
Four2
-----

.. include:: {last_include}
""".format(last_include="sub.rst" if nested else "part.rst")
    part = "Lead text.\n\n.. include:: sub.rst\n" if nested else "Deep\n~~~~\n"
    (rst_repo / "main.rst").write_text(main, encoding="utf-8")
    (rst_repo / "part.rst").write_text(part, encoding="utf-8")
    if nested:
        (rst_repo / "sub.rst").write_text("a\n\nb\n\nc\n\nDeep\n~~~~\n", encoding="utf-8")
        _commit(rst_repo, "main.rst", "part.rst", "sub.rst")
    else:
        _commit(rst_repo, "main.rst", "part.rst")
    monkeypatch.chdir(rst_repo)

    argv = (command, "sub:Deep", "part.rst") if command == "context" else (command, "part.rst")
    code, out = _run(monkeypatch, capsys, *argv)

    assert code == 1, out
    assert f"{command.capitalize()}: part.rst" not in out
    assert f"{command} cannot report one structure" in out
    assert "cannot be paired with its occurrence" in out
    if nested:
        assert "part.rst:3: ERROR:" in out
        assert "sub.rst:7" in out


@pytest.mark.integration
def test_outline_anchors_a_nested_context_disagreement_on_its_include(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A nested title's physical line must not become a line in its parent."""
    (rst_repo / "main.rst").write_text(_MAIN, encoding="utf-8")
    (rst_repo / "other.rst").write_text("#####\nOther\n#####\n\n.. include:: part.rst\n", encoding="utf-8")
    (rst_repo / "part.rst").write_text("Lead text.\n\n.. include:: sub.rst\n", encoding="utf-8")
    (rst_repo / "sub.rst").write_text("a\n\nb\n\nc\n\nDeep\n~~~~\n", encoding="utf-8")
    _commit(rst_repo, "main.rst", "other.rst", "part.rst", "sub.rst")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "outline", "part.rst")

    assert code == 1, out
    assert "part.rst:3: ERROR:" in out
    assert "sub.rst:7" in out
    assert "main.rst reports depth 3" in out
    assert "other.rst reports depth 2" in out


@pytest.mark.integration
def test_outline_maps_an_unproven_clipped_section_to_its_physical_line(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Even a fail-closed section uses a physical, not clip-relative, anchor."""
    main = _MAIN.replace(".. include:: part.rst", ".. include:: part.rst\n   :start-line: 3")
    (rst_repo / "main.rst").write_text(main, encoding="utf-8")
    (rst_repo / "part.rst").write_text("Alpha\n=====\n\nShared\n------\n", encoding="utf-8")
    _commit(rst_repo, "main.rst", "part.rst")
    monkeypatch.chdir(rst_repo)
    monkeypatch.setattr("check_rst.cli._contexts._title_style_events", lambda _lines: [])

    code, out = _run(monkeypatch, capsys, "outline", "part.rst")

    assert code == 1, out
    assert "part.rst:4: ERROR:" in out
    assert "physical source line cannot be proven" in out


@pytest.mark.integration
@pytest.mark.parametrize(
    ("clip_option", "part", "shared_line"),
    [
        (":start-line: 3", "Alpha\n=====\n\nShared\n------\n\nBody.\n", 4),
        (":start-after: .. cut", "Alpha\n=====\n\n.. cut\nShared\n------\n\nBody.\n", 5),
    ],
)
@pytest.mark.parametrize("verified", [False, True], ids=["docutils", "sphinx"])
def test_outline_maps_a_clipped_title_back_to_its_physical_line(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clip_option: str,
    part: str,
    shared_line: int,
    verified: bool,
) -> None:
    """Docutils numbers a clipped include from one; outline must translate
    that coordinate through the composition rather than attach the depth to
    an earlier physical title with the same reported line."""
    main = _MAIN.replace(".. include:: part.rst", f".. include:: part.rst\n   {clip_option}")
    (rst_repo / "main.rst").write_text(main, encoding="utf-8")
    (rst_repo / "part.rst").write_text(part, encoding="utf-8")
    if verified:
        (rst_repo / "conf.py").write_text(
            "project = 'clip'\nmaster_doc = 'main'\nexclude_patterns = ['part.rst']\n",
            encoding="utf-8",
        )
        _commit(rst_repo, "main.rst", "part.rst", "conf.py")
    else:
        _commit(rst_repo, "main.rst", "part.rst")
    monkeypatch.chdir(rst_repo)

    prefix = ("--sphinx-src", ".") if verified else ()
    code, out = _run(monkeypatch, capsys, *prefix, "outline", "part.rst")

    assert code == 1, out
    assert "Outline: part.rst" in out
    assert f"\n          {shared_line}-" in out
    assert ":-u Shared\n" in out
    assert ":=u Alpha\n" not in out


@pytest.mark.integration
def test_outline_projects_nested_included_titles_into_the_outer_context(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every section contributed by the selected fragment is contextual,
    including a section whose physical source is a nested include target."""
    part = "Shared\n------\n\n.. include:: sub.rst\n"
    sub = "Deep\n~~~~\n\nBody.\n"
    (rst_repo / "main.rst").write_text(_MAIN, encoding="utf-8")
    (rst_repo / "part.rst").write_text(part, encoding="utf-8")
    (rst_repo / "sub.rst").write_text(sub, encoding="utf-8")
    _commit(rst_repo, "main.rst", "part.rst", "sub.rst")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "outline", "part.rst")

    assert code == 1, out
    assert "levels: 3 '-u' (1), 4 '~u' (1)" in out
    assert "\n          1-4:-u Shared" in out
    assert "\n              sub.rst:1-4:~u Deep" in out


@pytest.mark.integration
@pytest.mark.parametrize("verified", [False, True], ids=["docutils", "sphinx"])
def test_context_reports_a_fragment_title_at_its_effective_depth(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    verified: bool,
) -> None:
    """Context and outline must agree on a fragment title's surrounding rank."""
    (rst_repo / "main.rst").write_text(_MAIN, encoding="utf-8")
    (rst_repo / "part.rst").write_text(_PART, encoding="utf-8")
    names = ["main.rst", "part.rst"]
    if verified:
        (rst_repo / "conf.py").write_text(
            "project = 'context'\nmaster_doc = 'main'\nexclude_patterns = ['part.rst']\n",
            encoding="utf-8",
        )
        names.append("conf.py")
    _commit(rst_repo, *names)
    monkeypatch.chdir(rst_repo)

    prefix = ("--sphinx-src", ".") if verified else ()
    code, out = _run(monkeypatch, capsys, *prefix, "context", "part:Shared", "part.rst")

    assert code == 0, out
    assert "selector: part:Shared" in out
    assert "depth: 3" in out


@pytest.mark.integration
def test_context_maps_clipped_and_nested_titles_to_physical_sources(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Contextual depths key physical lines through clips and nested includes."""
    main = _MAIN.replace(".. include:: part.rst", ".. include:: part.rst\n   :start-line: 3")
    part = "Alpha\n=====\n\nShared\n------\n\n.. include:: sub.rst\n"
    (rst_repo / "main.rst").write_text(main, encoding="utf-8")
    (rst_repo / "part.rst").write_text(part, encoding="utf-8")
    (rst_repo / "sub.rst").write_text("Deep\n~~~~\n", encoding="utf-8")
    _commit(rst_repo, "main.rst", "part.rst", "sub.rst")
    monkeypatch.chdir(rst_repo)

    shared_code, shared = _run(monkeypatch, capsys, "context", "part:Shared", "part.rst")
    deep_code, deep = _run(monkeypatch, capsys, "context", "sub:Deep", "part.rst")

    assert shared_code == 0, shared
    assert "range: 4-7" in shared
    assert "depth: 3" in shared
    assert deep_code == 0, deep
    assert f"Context: {rst_repo / 'sub.rst'}" in deep
    assert "range: 1-2" in deep
    assert "depth: 4" in deep


@pytest.mark.integration
def test_context_keeps_a_leaf_under_its_contextually_deepened_section(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Changing a section's depth must carry its heterogeneous subtree."""
    (rst_repo / "main.rst").write_text(_MAIN, encoding="utf-8")
    (rst_repo / "part.rst").write_text("Shared\n------\n\n* Target item.\n", encoding="utf-8")
    _commit(rst_repo, "main.rst", "part.rst")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "context", "Target item.", "part.rst")

    assert code == 0, out
    assert "depth: 5" in out
    assert 'part:Shared — section "Shared"' in out
    assert "parent: part:bullet-list@4" in out


@pytest.mark.integration
def test_context_deepens_a_titleless_fragment_leaf(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A title is not required to prove a fragment's surrounding depth."""
    (rst_repo / "main.rst").write_text(_MAIN, encoding="utf-8")
    (rst_repo / "part.rst").write_text("* Target item.\n", encoding="utf-8")
    _commit(rst_repo, "main.rst", "part.rst")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "context", "Target item.", "part.rst")

    assert code == 0, out
    assert "depth: 4" in out
    assert "parent: part:bullet-list@1" in out


@pytest.mark.integration
def test_context_refuses_titleless_leaf_depths_that_disagree_between_includers(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Agreement covers leaf structure even when no title can expose it."""
    (rst_repo / "main.rst").write_text(_MAIN, encoding="utf-8")
    (rst_repo / "other.rst").write_text("#####\nOther\n#####\n\n.. include:: part.rst\n", encoding="utf-8")
    (rst_repo / "part.rst").write_text("* Target item.\n", encoding="utf-8")
    _commit(rst_repo, "main.rst", "other.rst", "part.rst")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "context", "Target item.", "part.rst")

    assert code == 1, out
    assert "Context:" not in out
    assert "part.rst:1: ERROR: context cannot report one structure" in out
    assert "main.rst reports depth 3" in out
    assert "other.rst reports depth 2" in out


@pytest.mark.integration
def test_context_omits_a_title_dropped_by_its_include_context(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A standalone section absent from the contextual tree is not resolvable."""
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
    (rst_repo / "main.rst").write_text(main, encoding="utf-8")
    (rst_repo / "part.rst").write_text("Shared\n*****\n\nBody.\n", encoding="utf-8")
    _commit(rst_repo, "main.rst", "part.rst")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "context", "part:Shared", "part.rst")

    assert code == 1, out
    assert "no exact entry match" in out
    assert "selector: part:Shared" not in out


@pytest.mark.integration
def test_context_refuses_nested_depths_that_disagree_between_includers(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A query must not select one standalone reading after contexts disagree."""
    (rst_repo / "main.rst").write_text(_MAIN, encoding="utf-8")
    (rst_repo / "other.rst").write_text("#####\nOther\n#####\n\n.. include:: part.rst\n", encoding="utf-8")
    (rst_repo / "part.rst").write_text("Lead text.\n\n.. include:: sub.rst\n", encoding="utf-8")
    (rst_repo / "sub.rst").write_text("a\n\nb\n\nc\n\nDeep\n~~~~\n", encoding="utf-8")
    _commit(rst_repo, "main.rst", "other.rst", "part.rst", "sub.rst")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "context", "sub:Deep", "part.rst")

    assert code == 1, out
    assert "Context:" not in out
    assert "part.rst:3: ERROR: context cannot report one structure" in out
    assert "main.rst reports depth 3" in out
    assert "other.rst reports depth 2" in out
    assert "title at sub.rst:7" in out


@pytest.mark.integration
def test_context_refuses_an_unavailable_fragment_context(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A declaration without a visible includer cannot yield one authority."""
    (rst_repo / "part.rst").write_text(_PART, encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(
        monkeypatch,
        capsys,
        "--fragment",
        "part.rst",
        "context",
        "part:Shared",
        "part.rst",
    )

    assert code == 1, out
    assert "Context:" not in out
    assert "part.rst:1: ERROR: context cannot report one structure" in out
    assert "this file is declared a fragment (--fragment 'part.rst')" in out


@pytest.mark.integration
def test_one_outline_refusal_does_not_hide_other_files_or_the_summary(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reader refusal belongs to one selected file.  Other files still get
    their outlines, and the command reports its complete multi-file result."""
    (rst_repo / "main.rst").write_text(_MAIN, encoding="utf-8")
    (rst_repo / "part.rst").write_text(_PART, encoding="utf-8")
    (rst_repo / "shallow.rst").write_text(
        "#######\nShallow\n#######\n\n.. include:: bad.rst\n",
        encoding="utf-8",
    )
    (rst_repo / "deep.rst").write_text(
        "####\nDeep\n####\n\n*****\nChild\n*****\n\n.. include:: bad.rst\n",
        encoding="utf-8",
    )
    (rst_repo / "bad.rst").write_text("Bad\n---\n", encoding="utf-8")
    _commit(rst_repo, "main.rst", "part.rst", "shallow.rst", "deep.rst", "bad.rst")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "outline", "part.rst", "bad.rst")

    assert code == 1, out
    assert "Outline: part.rst" in out
    assert "Outline: bad.rst" not in out
    assert "outline cannot report one structure" in out
    assert "shallow.rst reports depth 2" in out
    assert "deep.rst reports depth 3" in out
    assert "check_rst: 2 file(s) checked" in out
