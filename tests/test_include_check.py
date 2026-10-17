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

# CR-43's main.rst, as its reproduction fixes it first: an includer that
# joins the check (P5c) must itself be clean for these assertions.
_MAIN = "######\nMain\n######\n\n**********\nSubtitle\n**********\n\n=======\nIntro\n=======\n\nText.\n\n.. include:: part.rst\n"
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


# ---------------------------------------------------------------------------
# Unavailable contexts (P5b): rules 2, 3 and 5
# ---------------------------------------------------------------------------

_DECLARED = (
    "WARNING: this file is declared a fragment (--fragment 'contact.rst'), so its title levels depend on an "
    "includer check_rst cannot see"
)


@pytest.mark.integration
def test_check_warns_once_for_a_fragment_it_cannot_judge(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rule 5: one WARNING, on the first title, and normally exit 0.  No
    context proves the standalone remap, so it is not reported."""
    _files(rst_repo, contact=_PART)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "--fragment", "contact.rst", "check", "contact.rst")

    assert code == 0, out
    assert out.count(f"contact.rst:2: {_DECLARED}") == 1, out
    assert _STANDALONE_REMAP not in out


@pytest.mark.integration
def test_a_title_free_fragment_gets_no_warning(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _files(rst_repo, contact="Jane Doe\nphone: 0100\n")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "--fragment", "contact.rst", "check", "contact.rst")

    assert code == 0, out
    assert "declared a fragment" not in out


@pytest.mark.integration
def test_an_unavailable_context_makes_a_proven_finding_non_fixable(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rules 2 and 3: main.rst proves the overline the fragment needs, but
    the declared, unseen includer may disagree, so fix refuses it and check
    no longer calls it fixable."""
    _files(rst_repo, main=_MAIN, part=_DASH)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "--fragment", "part.rst", "check", "--skip-fixable", "part.rst")

    assert code == 1, out
    assert "part.rst:2: ERROR: in the document main.rst composes, underline-only title" in out
    assert "part.rst:1: WARNING: this file is declared a fragment (--fragment 'part.rst')" in out


@pytest.mark.integration
def test_a_nested_include_warns_on_its_own_directive(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The uncertainty comes only through main.rst's nested include, so the
    includer's WARNING sits on that directive; the fragment's sits on its
    first title, and its standalone remap is proven nowhere."""
    _files(rst_repo, main="######\nMain\n######\n\n.. note::\n\n   .. include:: part.rst\n", part=_PART)
    monkeypatch.chdir(rst_repo)
    reason = "which check_rst cannot compose (indented inside another construct)"

    main_code, main_out = _run(monkeypatch, capsys, "check", "main.rst")
    part_code, part_out = _run(monkeypatch, capsys, "check", "part.rst")

    assert main_code == 0, main_out
    assert f"main.rst:7: WARNING: its title levels depend on the include at main.rst:7, {reason}" in main_out
    assert part_code == 0, part_out
    assert f"part.rst:2: WARNING: its title levels depend on the include at main.rst:7, {reason}" in part_out
    assert _STANDALONE_REMAP not in part_out


@pytest.mark.integration
def test_an_uncovered_file_proven_error_is_no_longer_fixable(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Mutation fidelity: fix refuses the uncovered file's remap (D9d step
    5), so --skip-fixable must not hide it."""
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    part = elsewhere / "part.rst"
    part.write_text(_PART, encoding="utf-8")
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))

    code, out = _run(monkeypatch, capsys, "check", "--skip-fixable", str(part))

    assert code == 1, out
    assert _STANDALONE_REMAP in out
    assert "WARNING: this file lies outside every discovery root (" in out


@pytest.mark.integration
def test_the_unavailable_context_warning_is_retainable_and_goes_stale(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Retention identity is the path, the code, and the anchor line's
    digest: a reviewed WARNING stays hidden until its unique anchor
    changes."""
    import hashlib

    contact = _files(rst_repo, contact="========\nUnique anchor title\n========\n\nBody.\n")["contact"]
    digest = hashlib.sha256(b"Unique anchor title").hexdigest()
    (rst_repo / ".check_rst-retained.toml").write_text(
        f'version = 1\n\n[[retain]]\npath = "contact.rst"\ncode = "include.context-unavailable"\n'
        f'source-sha256 = "{digest}"\nreason = "Reviewed: a fragment of an external template."\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(rst_repo)

    def run() -> str:
        monkeypatch.setattr("sys.argv", ["check_rst.py", "--fragment", "contact.rst", "check", "contact.rst"])
        with pytest.raises(SystemExit):
            cli.main()
        return capsys.readouterr().out

    retained = run()
    contact.write_text("========\nA changed anchor\n========\n\nBody.\n", encoding="utf-8")
    stale = run()

    assert "declared a fragment" not in retained, retained
    assert "1 retained WARNING(s)" in retained, retained
    assert "retain entry 1 (contact.rst, include.context-unavailable) matches no current WARNING" in stale
    assert "contact.rst:2: WARNING: this file is declared a fragment" in stale


# ---------------------------------------------------------------------------
# Includers join the check set (P5c)
# ---------------------------------------------------------------------------

# The edit fix --fast used to make: part.rst's "=" title remapped to "#",
# which in main.rst is a second top-level title.
_BROKEN_PART = "########\nShared\n########\n\nBody.\n"
_SECOND_TITLE = "part.rst:2: ERROR: second effective top-level title 'Shared' follows 'Main'"
_HINT = "'Shared' comes through the include at main.rst:15, so check main.rst"


@pytest.mark.integration
@pytest.mark.parametrize("scope", [("part.rst",), ()], ids=["explicit", "git-scope"])
def test_an_includer_broken_by_a_fragment_edit_turns_check_red(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], scope: tuple[str, ...]
) -> None:
    """The includers of a selected fragment join the check set, read-only and
    whole-file: the fragment is consistent with itself, but main.rst now has
    two document titles.  The validation loop's third step must turn red,
    in Git hunk scope too."""
    paths = _files(rst_repo, main=_MAIN, part=_PART)
    _commit(rst_repo, "main.rst", "part.rst")
    paths["part"].write_text(_BROKEN_PART, encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "check", *scope)

    assert code == 1, out
    assert "check_rst: also checking main.rst, which includes part.rst" in out
    assert _SECOND_TITLE in out
    assert paths["main"].read_text(encoding="utf-8") == _MAIN


@pytest.mark.integration
def test_the_second_title_hint_names_the_includer(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _files(rst_repo, main=_MAIN, part=_BROKEN_PART)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "check", "main.rst")

    assert code == 1, out
    assert _SECOND_TITLE in out
    assert _HINT in out


# ---------------------------------------------------------------------------
# K6 (P5d): a clip-boundary edit is judged in context, not on the whole file
# ---------------------------------------------------------------------------

_CLIPPING_MAIN = _MAIN.replace(".. include:: part.rst\n", ".. include:: part.rst\n   :start-line: 2\n")
_CLIPPED_PART = "skipped one\nskipped two\nShared\n------\n\nBody.\n"
_CLIPPED_FIXED = "skipped one\nskipped two\n--------\nShared\n--------\n\nBody.\n"


@pytest.mark.integration
def test_a_clip_boundary_edit_is_judged_in_its_context(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Codex's K6 ruling.  The overline fix inserts above the first selected
    title lands, physically, right after a clipped-away line, so read whole
    the file has a shared adornment line.  Every visible context clips that
    line away, and nothing declares or builds the file as a document, so
    the whole-file reading has no authority: fix applies the edit, and
    check judges the result clean."""
    paths = _files(rst_repo, main=_CLIPPING_MAIN, part=_CLIPPED_PART)
    monkeypatch.chdir(rst_repo)

    fix_code, fix_out = _run(monkeypatch, capsys, "fix", "part.rst")
    check_code, check_out = _run(monkeypatch, capsys, "check", "part.rst")

    assert paths["part"].read_text(encoding="utf-8") == _CLIPPED_FIXED, fix_out
    assert fix_code == 0, fix_out
    assert check_code == 0, check_out
    assert "adornment.shared-line" not in check_out
    assert "is both the underline of" not in check_out


@pytest.mark.integration
@pytest.mark.parametrize("command", ["fix", "check"])
def test_a_standalone_context_makes_the_clip_boundary_disagree(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    """The other half of K6: declared standalone, the whole-file reading is a
    context, which disagrees with the clipped one, so both commands refuse."""
    paths = _files(rst_repo, main=_CLIPPING_MAIN, part=_CLIPPED_PART)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "--standalone", "part.rst", command, "part.rst")

    assert code == 1, out
    assert "its include contexts need different title edits here: main.rst and standalone use disagree" in out
    assert paths["part"].read_text(encoding="utf-8") == _CLIPPED_PART


# ---------------------------------------------------------------------------
# Codex's P5 review
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_a_lexical_alias_of_an_includer_joins_the_check(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """alias.rst is a symlink to shared/mid.rst, whose ".. include::
    part.rst" names the selected part.rst only through alias.rst; through
    shared/mid.rst it names shared/part.rst.  The canonical walk joined
    shared/mid.rst, which is fine, and missed alias.rst, which the edit
    broke, so check exited 0."""
    (rst_repo / "shared").mkdir()
    (rst_repo / "shared" / "mid.rst").write_text("#####\nMid\n#####\n\n.. include:: part.rst\n", encoding="utf-8")
    (rst_repo / "alias.rst").symlink_to("shared/mid.rst")
    (rst_repo / "shared" / "part.rst").write_text("*****\nSub\n*****\n", encoding="utf-8")
    part = rst_repo / "part.rst"
    part.write_text("******\nPart\n******\n", encoding="utf-8")
    _commit(rst_repo, "shared/mid.rst", "alias.rst", "shared/part.rst", "part.rst")
    part.write_text("######\nPart\n######\n", encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "check", "part.rst")

    assert code == 1, out
    assert "check_rst: also checking alias.rst, which includes part.rst" in out
    assert "also checking shared/mid.rst" not in out
    assert "'Part' comes through the include at alias.rst:5, so check alias.rst" in out


def _sphinx_includer(repo: Path, conf: str, main_extra: str = "") -> Path:
    """A Sphinx project whose selected document part.rst is included by
    main.rst; the base is committed, then part.rst is broken."""
    docs = repo / "docs"
    docs.mkdir()
    (docs / "conf.py").write_text(conf, encoding="utf-8")
    (docs / "index.rst").write_text("#######\nIndex\n#######\n", encoding="utf-8")
    (docs / "main.rst").write_text(_MAIN + main_extra, encoding="utf-8")
    part = docs / "part.rst"
    part.write_text(_PART, encoding="utf-8")
    _commit(repo, "docs")
    part.write_text(_BROKEN_PART, encoding="utf-8")
    return docs / "main.rst"


@pytest.mark.integration
def test_an_excluded_joined_includer_gets_the_bare_structural_check(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Codex's P5 review, L4.  main.rst is excluded from the Sphinx project,
    so it is no Sphinx document: joined, it must get Docutils' structural
    check in Phase 1, never become a Phase 2 target that aborts the run."""
    _sphinx_includer(rst_repo, 'project = "p"\nexclude_patterns = ["main.rst"]\n')
    monkeypatch.chdir(rst_repo)

    code, out = _run(
        monkeypatch, capsys, "--sphinx-src", "docs", "--build-dir", str(rst_repo / "_build"), "check", "docs/part.rst"
    )

    assert code == 1, out
    assert "not part of the --sphinx-src environment" not in out
    assert "second effective top-level title 'Shared' follows 'Main'" in out


@pytest.mark.integration
def test_a_joined_sphinx_document_is_checked_without_becoming_a_build_target(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """main.rst is a Sphinx document: its effective structure is Phase 2's to
    check, from the environment, but it is no requested build target, so
    its own Sphinx build warnings are not this run's."""
    _sphinx_includer(rst_repo, 'project = "p"\n', main_extra="\nSee :doc:`missing`.\n")
    monkeypatch.chdir(rst_repo)

    code, out = _run(
        monkeypatch, capsys, "--sphinx-src", "docs", "--build-dir", str(rst_repo / "_build"), "check", "docs/part.rst"
    )

    assert code == 1, out
    assert "second effective top-level title 'Shared' follows 'Main'" in out
    assert "unknown document: 'missing'" not in out


@pytest.mark.integration
def test_a_title_free_fragment_whose_include_adds_titles_warns_on_the_include(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Codex's P5 review, L3: contact.rst has no title of its own, but its
    include of titled.rst adds one, so its effective content has
    context-sensitive structure.  The WARNING sits on that include line,
    and a contact block with no include still gets none."""
    _files(rst_repo, contact="Intro text.\n\n.. include:: titled.rst\n", titled="========\nTitled\n========\n\nBody.\n")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "--fragment", "contact.rst", "check", "contact.rst")

    assert code == 0, out
    assert f"contact.rst:3: {_DECLARED}" in out


@pytest.mark.integration
def test_a_finding_names_every_context_that_proves_it(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Codex's P5 review: rule 2 names the contexts in which a proven
    finding holds.  Both includers need the same overline, so the one
    physical finding names both."""
    other = _MAIN.replace("######\nMain\n######", "#######\nOther\n#######")
    _files(rst_repo, main=_MAIN, other=other, part=_DASH)
    monkeypatch.chdir(rst_repo)

    _code, out = _run(monkeypatch, capsys, "check", "part.rst")

    assert out.count("part.rst:2: ERROR:") == 1, out
    assert "part.rst:2: ERROR: in the documents main.rst and other.rst compose, underline-only title" in out
