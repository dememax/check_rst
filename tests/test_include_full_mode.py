# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Full-mode fix and diff of a file in its include contexts (CR-43, P4a) — check_rst project
"""Full fix and diff judge a file's titles in every context it has: each
document that includes it, composed as Docutils composes it, and its
standalone use when it has one.  A structural edit applies only when every
context needs the same edit, confined to that file; otherwise it is refused,
include.context-conflict.  A context check_rst cannot compose (an indented
include, :parser:, :encoding:, an unreadable target, a cycle) is
unavailable, and then only an edit that keeps the file's title model may
apply, include.context-unavailable.

Phase 1 still judges each fixed file standalone until P5, so these tests
assert bytes and refusal messages rather than exit statuses.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from check_rst import cli

if TYPE_CHECKING:
    from pathlib import Path

    import docutils.nodes

# CR-43's reproduction: part.rst's "=" title sits at level 3 in main.rst.
_MAIN = "######\nMain\n######\n\n*********\nSubtitle\n*********\n\n=======\nIntro\n=======\n\nText.\n\n.. include:: part.rst\n"
_PART = "========\nShared\n========\n\nBody.\n"
# Composed after main.rst's level-3 "=", an underline-only "-" is level 4,
# whose canonical style is "-o"; standalone it would be the page title "#o".
_DASH = "Shared\n------\n\nBody.\n"
_DASH_IN_MAIN = "--------\nShared\n--------\n\nBody.\n"


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


# ---------------------------------------------------------------------------
# Composed planning
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("scope", [("part.rst",), ()], ids=["explicit", "git-scope"])
def test_full_fix_keeps_a_fragment_title_its_includer_composes_consistently(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], scope: tuple[str, ...]
) -> None:
    """CR-43's reproduction in full mode: fix used to remap part.rst's "=" to
    "#", breaking main.rst, and report success."""
    paths = _files(rst_repo, main=_MAIN, part=_PART)
    _commit(rst_repo, "main.rst", "part.rst")
    paths["part"].write_text(_PART + "\nOne more body line.\n", encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    _code, out = _run(monkeypatch, capsys, "fix", *scope)

    assert paths["part"].read_text(encoding="utf-8") == _PART + "\nOne more body line.\n", out
    assert paths["main"].read_text(encoding="utf-8") == _MAIN


@pytest.mark.integration
def test_full_diff_previews_no_remap_for_a_consistently_composed_fragment(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _files(rst_repo, main=_MAIN, part=_PART)
    monkeypatch.chdir(rst_repo)

    _code, out = _run(monkeypatch, capsys, "diff", "part.rst")

    assert "+########" not in out
    assert "--- part.rst" not in out


@pytest.mark.integration
def test_full_fix_applies_an_edit_the_composed_document_confines_to_the_fragment(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _files(rst_repo, main=_MAIN, part=_DASH)
    monkeypatch.chdir(rst_repo)

    _code, out = _run(monkeypatch, capsys, "fix", "part.rst")

    assert paths["part"].read_text(encoding="utf-8") == _DASH_IN_MAIN, out
    assert paths["main"].read_text(encoding="utf-8") == _MAIN


@pytest.mark.integration
def test_two_includers_that_agree_let_the_edit_apply(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _files(rst_repo, main=_MAIN, other=_MAIN.replace("Main", "Other"), part=_DASH)
    monkeypatch.chdir(rst_repo)

    _code, out = _run(monkeypatch, capsys, "fix", "part.rst")

    assert paths["part"].read_text(encoding="utf-8") == _DASH_IN_MAIN, out


@pytest.mark.integration
def test_two_includers_that_disagree_refuse_with_a_context_conflict(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """main.rst places the fragment's title at level 4, other.rst at level
    2: no single style serves both."""
    paths = _files(rst_repo, main=_MAIN, other="#######\nOther\n#######\n\n.. include:: part.rst\n", part=_DASH)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "fix", "part.rst")

    assert code == 1, out
    assert (
        "part.rst:1: ERROR: its include contexts need different title styles here: main.rst needs '-o' and "
        "other.rst needs '*o', so fix cannot choose one — make the documents that include it agree"
    ) in out
    assert paths["part"].read_text(encoding="utf-8") == _DASH


@pytest.mark.integration
def test_a_standalone_declaration_adds_a_context_that_must_agree(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _files(rst_repo, main=_MAIN, part=_PART)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "--standalone", "part.rst", "fix", "part.rst")

    assert code == 1, out
    assert (
        "part.rst:2: ERROR: its include contexts need different title styles here: main.rst needs '=o' and "
        "standalone use needs '#o', so fix cannot choose one — make the documents that include it agree"
    ) in out
    assert paths["part"].read_text(encoding="utf-8") == _PART


@pytest.mark.integration
def test_an_edit_the_composed_document_needs_outside_the_file_refuses(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """main.rst's page title is not canonical, so the composed remap edits
    main.rst too, and fix changes only the selected file."""
    paths = _files(rst_repo, main="=====\nMain\n=====\n\n.. include:: part.rst\n", part=_DASH)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "fix", "part.rst")

    assert code == 1, out
    assert (
        "part.rst:1: ERROR: in the document main.rst composes, its title change also needs main.rst:1 to "
        "change, and fix changes only this file — make that document's titles consistent by hand"
    ) in out
    assert paths["part"].read_text(encoding="utf-8") == _DASH


@pytest.mark.integration
def test_an_includer_problem_does_not_block_a_fragment_that_needs_nothing(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Canonical in place: level 2 under main.rst's page title, length 8.
    part = "********\nShared\n********\n\nBody.\n"
    paths = _files(rst_repo, main="=====\nMain\n=====\n\n.. include:: part.rst\n", part=part)
    monkeypatch.chdir(rst_repo)

    _code, out = _run(monkeypatch, capsys, "fix", "part.rst")

    assert "its title change also needs" not in out
    assert paths["part"].read_text(encoding="utf-8") == part


@pytest.mark.integration
def test_a_clipped_include_composes_only_its_selected_lines(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    main = _MAIN.replace(".. include:: part.rst\n", ".. include:: part.rst\n   :start-after: .. start\n")
    paths = _files(rst_repo, main=main, part=".. start\n\n" + _DASH)
    monkeypatch.chdir(rst_repo)

    _code, out = _run(monkeypatch, capsys, "fix", "part.rst")

    assert paths["part"].read_text(encoding="utf-8") == ".. start\n\n" + _DASH_IN_MAIN, out


@pytest.mark.integration
def test_git_hunks_stay_in_the_fragment_coordinates(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Codex's coordinate boundary: the fragment's changed line 2 is not
    main.rst's line 2.  Only the fragment's own hunk gets geometry fixes,
    and main.rst's short adornment on its line 2 stays as it is."""
    main = "####\nMain\n####\n\n.. include:: part.rst\n"
    part = "********\nShared\n********\n\nBody.\n"
    paths = _files(rst_repo, main=main, part=part)
    _commit(rst_repo, "main.rst", "part.rst")
    paths["part"].write_text("*******\nShared\n*******\n\nBody.\n", encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    _code, out = _run(monkeypatch, capsys, "fix")

    assert paths["part"].read_text(encoding="utf-8") == part, out
    assert paths["main"].read_text(encoding="utf-8") == main


# ---------------------------------------------------------------------------
# The includer side (Q1, full mode)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_full_fix_proves_an_includer_edit_safe_where_fast_mode_refuses(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The conservative fast refusal: fast mode cannot prove that a
    title-free fragment adds nothing, while the composed document does."""
    main = "Main\n####\n\nText.\n\n.. include:: contact.rst\n"
    paths = _files(rst_repo, main=main, contact="Jane Doe\nphone: 0100\n")
    monkeypatch.chdir(rst_repo)

    fast_code, fast_out = _run(monkeypatch, capsys, "fix", "--fast", "main.rst")
    assert fast_code == 1, fast_out
    assert paths["main"].read_text(encoding="utf-8") == main

    _code, out = _run(monkeypatch, capsys, "fix", "main.rst")

    assert paths["main"].read_text(encoding="utf-8").startswith("######\nMain\n######\n"), out


@pytest.mark.integration
def test_an_includer_edit_that_also_needs_its_fragment_changed_refuses(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    main = "Main\n####\n\nText.\n\n.. include:: part.rst\n"
    paths = _files(rst_repo, main=main, part="Shared\n******\n\nBody.\n")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "fix", "main.rst")

    assert code == 1, out
    assert (
        "main.rst:1: ERROR: in the document main.rst composes, its title change also needs part.rst:1 to "
        "change, and fix changes only this file — make that document's titles consistent by hand"
    ) in out
    assert paths["main"].read_text(encoding="utf-8") == main


# ---------------------------------------------------------------------------
# Unavailable contexts
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    ("include", "line", "reason"),
    [
        (".. note::\n\n   .. include:: part.rst\n", 3, "indented inside another construct"),
        (".. include:: part.rst\n   :parser: rst\n", 1, "it sets :parser:"),
        (".. include:: part.rst\n   :encoding: latin-1\n", 1, "it sets :encoding:"),
        (".. include:: part.rst\n   :start-after: NO SUCH MARKER\n", 1, "its clipping options do not match its target"),
    ],
    ids=["indented", "parser", "encoding", "clip"],
)
def test_an_include_that_cannot_be_composed_makes_its_context_unavailable(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    include: str,
    line: int,
    reason: str,
) -> None:
    """Standalone, part.rst's "=" page title would become "#", a title-model
    change no available context supports."""
    paths = _files(rst_repo, main="######\nMain\n######\n\n" + include, part=_PART)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "fix", "part.rst")

    assert code == 1, out
    assert (
        f"part.rst:2: ERROR: its title levels depend on the include at main.rst:{line + 4}, which check_rst "
        f"cannot compose ({reason}) — edit its titles by hand in context"
    ) in out
    assert paths["part"].read_text(encoding="utf-8") == _PART


@pytest.mark.integration
def test_an_include_cycle_makes_the_context_unavailable(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _files(
        rst_repo,
        alpha="#######\nAlpha\n#######\n\n.. include:: beta.rst\n",
        beta="Beta\n====\n\n.. include:: alpha.rst\n",
    )
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "fix", "beta.rst")

    assert code == 1, out
    assert "the include at alpha.rst:5, which check_rst cannot compose (it is part of an include cycle)" in out
    assert paths["beta"].read_text(encoding="utf-8") == "Beta\n====\n\n.. include:: alpha.rst\n"


@pytest.mark.integration
def test_full_fix_refuses_a_declared_fragment_title_model_change(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _files(rst_repo, contact=_PART)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "--fragment", "contact.rst", "fix", "contact.rst")

    assert code == 1, out
    assert (
        "contact.rst:2: ERROR: this file is declared a fragment (--fragment 'contact.rst'), so its title "
        "levels depend on an includer check_rst cannot see"
    ) in out
    assert paths["contact"].read_text(encoding="utf-8") == _PART


@pytest.mark.integration
def test_full_fix_still_fixes_pure_geometry_beside_an_unavailable_context(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _files(rst_repo, contact="############\nShared\n############\n\nBody.\n")
    monkeypatch.chdir(rst_repo)

    _code, out = _run(monkeypatch, capsys, "--fragment", "contact.rst", "fix", "contact.rst")

    assert "declared a fragment" not in out
    assert paths["contact"].read_text(encoding="utf-8") == "########\nShared\n########\n\nBody.\n"


@pytest.mark.integration
def test_full_fix_refuses_a_file_outside_every_discovery_root(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    part = elsewhere / "part.rst"
    part.write_text(_PART, encoding="utf-8")
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))

    code, out = _run(monkeypatch, capsys, "fix", str(part))

    assert code == 1, out
    assert "this file lies outside every discovery root (" in out
    assert part.read_text(encoding="utf-8") == _PART


@pytest.mark.integration
def test_a_file_nothing_includes_is_fixed_in_full_mode_as_before(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _files(rst_repo, doc=_PART)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "fix", "doc.rst")

    assert code == 0, out
    assert paths["doc"].read_text(encoding="utf-8") == "########\nShared\n########\n\nBody.\n"


# ---------------------------------------------------------------------------
# Parse refutation (P4b): include-looking text is not an include
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    "example",
    [
        "#######\nExample\n#######\n\nSee::\n\n    .. include:: part.rst\n",
        "#######\nExample\n#######\n\n..\n   .. include:: part.rst\n",
    ],
    ids=["literal-block", "comment"],
)
def test_full_fix_proves_include_looking_text_is_no_include(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], example: str
) -> None:
    """The conservative fast refusal's other half: fast mode cannot rule
    the line out, while parsing its file proves it is text, so part.rst has
    no includer and is fixed as a standalone document."""
    paths = _files(rst_repo, example=example, part=_PART)
    monkeypatch.chdir(rst_repo)

    fast_code, fast_out = _run(monkeypatch, capsys, "fix", "--fast", "part.rst")
    assert fast_code == 1, fast_out
    assert paths["part"].read_text(encoding="utf-8") == _PART

    _code, out = _run(monkeypatch, capsys, "fix", "part.rst")

    assert "cannot compose" not in out
    assert paths["part"].read_text(encoding="utf-8") == "########\nShared\n########\n\nBody.\n", out


@pytest.mark.integration
def test_an_include_inside_an_unknown_directive_stays_unavailable(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Plain Docutils does not parse an unknown directive's content, but
    Sphinx may: its ``only`` directive does.  Nothing proves the line text."""
    paths = _files(rst_repo, main="######\nMain\n######\n\n.. only:: html\n\n   .. include:: part.rst\n", part=_PART)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "fix", "part.rst")

    assert code == 1, out
    assert (
        "its title levels depend on the include at main.rst:7, which check_rst cannot compose (indented inside "
        "another construct)"
    ) in out
    assert paths["part"].read_text(encoding="utf-8") == _PART


@pytest.mark.integration
def test_an_includer_whose_include_is_only_literal_text_is_fixed(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    main = "Main\n####\n\nSee::\n\n    .. include:: part.rst\n"
    paths = _files(rst_repo, main=main, part=_PART)
    monkeypatch.chdir(rst_repo)

    _code, out = _run(monkeypatch, capsys, "fix", "main.rst")

    assert "cannot compose" not in out
    assert paths["main"].read_text(encoding="utf-8").startswith("######\nMain\n######\n"), out


# ---------------------------------------------------------------------------
# The Sphinx project's own facts (P4c)
# ---------------------------------------------------------------------------

_CONF = 'project = "p"\nexclude_patterns = ["part.rst"]\n'


def _sphinx_project(repo: Path, conf: str = _CONF, index: str = "index.rst") -> Path:
    docs = repo / "docs"
    docs.mkdir()
    (docs / "conf.py").write_text(conf, encoding="utf-8")
    (docs / index).write_text(_MAIN, encoding="utf-8")
    part = docs / "part.rst"
    part.write_text(_PART, encoding="utf-8")
    return part


def _run_verified(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *argv: str
) -> tuple[int, str]:
    monkeypatch.chdir(repo)
    return _run(monkeypatch, capsys, "--sphinx-src", "docs", "--build-dir", str(repo / "_build"), *argv)


@pytest.mark.integration
def test_verified_mode_composes_a_fragment_the_project_excludes(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    part = _sphinx_project(rst_repo)

    code, out = _run_verified(rst_repo, monkeypatch, capsys, "fix", "docs/part.rst")

    # CR-43 L6: the excluded fragment is no Sphinx build target, so the run
    # succeeds instead of aborting on its Sphinx membership.
    assert code == 0, out
    assert "need different title styles" not in out
    assert part.read_text(encoding="utf-8") == _PART, out


@pytest.mark.integration
def test_a_sphinx_document_has_a_standalone_context_that_must_agree(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """D9b's positive Sphinx evidence: a fragment the environment also reads
    as a document has a standalone context, where its "=" is the page title."""
    part = _sphinx_project(rst_repo, conf='project = "p"\n')

    code, out = _run_verified(rst_repo, monkeypatch, capsys, "fix", "docs/part.rst")

    assert code == 1, out
    assert (
        "docs/part.rst:2: ERROR: its include contexts need different title styles here: docs/index.rst needs "
        "'=o' and standalone use needs '#o'"
    ) in out
    assert part.read_text(encoding="utf-8") == _PART


@pytest.mark.integration
@pytest.mark.parametrize(
    ("setup", "evidence"),
    [
        ("app.connect('include-read', lambda *args: None)", "an include-read handler"),
        ("app.connect('source-read', lambda *args: None)", "a source-read handler"),
        (
            "from sphinx.directives.other import Include\n"
            "    app.add_directive('include', type('Mine', (Include,), {}), override=True)",
            "an extension's include directive",
        ),
    ],
    ids=["include-read", "source-read", "replaced-include"],
)
def test_a_project_that_may_transform_includes_makes_them_unavailable(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], setup: str, evidence: str
) -> None:
    """Q4: Sphinx may change what an include adds, so the lexical
    composition proves nothing.  Standalone, part.rst's "=" would become
    "#", a title-model change no context supports."""
    part = _sphinx_project(rst_repo, conf=_CONF + f"\n\ndef setup(app):\n    {setup}\n")

    code, out = _run_verified(rst_repo, monkeypatch, capsys, "fix", "docs/part.rst")

    assert code == 1, out
    assert (
        "docs/part.rst:2: ERROR: its title levels depend on include contexts this project's Sphinx "
        f"configuration may transform ({evidence}), so check_rst cannot compose them — edit its titles by hand "
        "in context"
    ) in out
    assert part.read_text(encoding="utf-8") == _PART


@pytest.mark.integration
def test_verified_mode_finds_an_includer_with_a_configured_source_suffix(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """D9d's population: in Sphinx mode, the project's own source suffixes.
    Unseen, index.txt's include left part.rst standalone, remapped to "#"."""
    conf = _CONF + 'source_suffix = {".rst": "restructuredtext", ".txt": "restructuredtext"}\n'
    part = _sphinx_project(rst_repo, conf=conf, index="index.txt")

    _code, out = _run_verified(rst_repo, monkeypatch, capsys, "fix", "docs/part.rst")

    assert part.read_text(encoding="utf-8") == _PART, out


# ---------------------------------------------------------------------------
# Topology revalidation (P4d)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_a_planned_edit_docutils_reads_as_another_section_tree_is_refused(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rule 5: every includer's topology is revalidated after the candidate.

    The planner is replaced by one whose output maps exactly onto part.rst
    but leaves "Shared" in a new style right after a return to level 2.
    Docutils rejects that inconsistent level, so the composed document
    would lose a section, and the edit must not apply."""
    from check_rst.cli import _contexts
    from check_rst.cli._formatting import _structure_plan as real_plan

    def inconsistent(lines: list[str], ranges: list[tuple[int, int]] | None) -> tuple[list[str], tuple[()]]:
        fixed, _refusals = real_plan(lines, ranges)
        if "Shared" in fixed:
            title = fixed.index("Shared")
            fixed[title - 1] = fixed[title + 1] = "-" * len(fixed[title + 1])
        return fixed, ()

    monkeypatch.setattr(_contexts, "_structure_plan", inconsistent)
    part = "*******\nAlpha\n*******\n\nShared\n------\n\nBody.\n"
    paths = _files(rst_repo, main=_MAIN, part=part)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "fix", "part.rst")

    assert code == 1, out
    assert (
        "in the document main.rst composes, Docutils would read the planned titles as a different section "
        "tree, so fix leaves them unchanged — edit its titles by hand in context"
    ) in out
    assert paths["part"].read_text(encoding="utf-8") == part


# ---------------------------------------------------------------------------
# Codex's P4 checkpoint
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_two_lexical_paths_to_one_root_are_two_contexts(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Finding 1: alias/source.rst is a symlink to real/source.rst, so both
    lexical paths are one canonical root.  Each includes its own directory's
    prefix.rst, so the child sits at level 2 in one and level 3 in the
    other, a disagreement that must refuse.  The canonical-keyed walk kept
    only the first lexical root and proposed its style."""
    (rst_repo / "real").mkdir()
    (rst_repo / "alias").mkdir()
    (rst_repo / "real" / "source.rst").write_text(
        ".. include:: prefix.rst\n\n.. include:: ../real/child.rst\n", encoding="utf-8"
    )
    (rst_repo / "alias" / "source.rst").symlink_to("../real/source.rst")
    (rst_repo / "real" / "prefix.rst").write_text("######\nTop\n######\n\n*****\nSub\n*****\n", encoding="utf-8")
    (rst_repo / "alias" / "prefix.rst").write_text("######\nTop\n######\n", encoding="utf-8")
    child = rst_repo / "real" / "child.rst"
    child.write_text("Child\n-----\n", encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "fix", "real/child.rst")

    assert code == 1, out
    assert (
        "real/child.rst:1: ERROR: its include contexts need different title styles here: alias/source.rst needs "
        "'*o' and real/source.rst needs '=o', so fix cannot choose one — make the documents that include it agree"
    ) in out
    assert child.read_text(encoding="utf-8") == "Child\n-----\n"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("files", "selected"),
    [
        (
            {
                "example": "#######\nExample\n#######\n\n.. counting::\n\n:counting:`x`\n\nSee::\n\n    .. include:: part.rst\n",
                "part": _PART,
            },
            "part.rst",
        ),
        (
            {"main": _MAIN.replace("Text.", ".. counting::\n\n:counting:`x`"), "part": _DASH},
            "part.rst",
        ),
    ],
    ids=["probe-parse", "revalidation-parse"],
)
def test_check_rst_parses_never_run_registered_directives_or_roles(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    files: dict[str, str],
    selected: str,
) -> None:
    """Finding 4: the probe and revalidation parses read files the user did
    not select.  Like CR-30's parse, they must run only Docutils' built-in
    directives and roles, never one an extension registered in the
    process."""
    from docutils.parsers.rst import Directive, directives, roles

    calls: list[str] = []

    class Counting(Directive):
        def run(self) -> list[docutils.nodes.Node]:
            calls.append("directive")
            return []

    def counting_role(*_args: object, **_kwargs: object) -> tuple[list[object], list[object]]:
        calls.append("role")
        return [], []

    monkeypatch.setitem(vars(directives)["_directives"], "counting", Counting)
    monkeypatch.setitem(vars(roles)["_roles"], "counting", counting_role)
    _files(rst_repo, **files)
    monkeypatch.chdir(rst_repo)

    _run(monkeypatch, capsys, "fix", selected)

    assert calls == []


_STANDALONE_PART = "########\nShared\n########\n\nBody.\n"


@pytest.mark.integration
@pytest.mark.parametrize(
    "include",
    [
        ".. include:: part.rst\n   :bogus: 1\n",
        ".. include:: part.rst\n\n   Content the directive does not take.\n",
        ".. include:: part.rst\n   :start-line: x\n",
    ],
    ids=["unknown-option", "content", "bad-option-value"],
)
def test_an_include_docutils_rejects_includes_nothing(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], include: str
) -> None:
    """Finding 2: Docutils (and Sphinx's include, which validates the same
    options) rejects the invocation, so nothing is included and part.rst is
    a standalone document.  The lexical composer took it for a context."""
    paths = _files(rst_repo, main="######\nMain\n######\n\n" + include, part=_PART)
    monkeypatch.chdir(rst_repo)

    _code, out = _run(monkeypatch, capsys, "fix", "part.rst")

    assert "cannot compose" not in out
    assert "include contexts" not in out
    assert paths["part"].read_text(encoding="utf-8") == _STANDALONE_PART, out


@pytest.mark.integration
@pytest.mark.parametrize(
    ("options", "width"),
    [("", 11), ("\n   :tab-width: 8", 11), ("\n   :tab-width: 4", 7)],
    ids=["default-width", "explicit-8", "width-4"],
)
def test_composition_expands_tabs_as_docutils_does(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], options: str, width: int
) -> None:
    """Codex's second P4 look: Docutils expands an inserted text's tabs, at
    the default width 8 too, so "A<TAB>B" is nine columns wide and needs an
    11-character adornment.  The composition kept the raw tab and planned 5.
    The title line itself keeps its tab: only the adornments change."""
    paths = _files(
        rst_repo, main=f"######\nMain\n######\n\n.. include:: part.rst{options}\n", part="A\tB\n---------\n\nBody.\n"
    )
    monkeypatch.chdir(rst_repo)

    _code, out = _run(monkeypatch, capsys, "fix", "part.rst")

    adornment = "*" * width
    assert paths["part"].read_text(encoding="utf-8") == f"{adornment}\nA\tB\n{adornment}\n\nBody.\n", out


@pytest.mark.integration
def test_composition_expands_the_root_documents_tabs_too(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Docutils expands the including document's own lines at width 8, so
    the includer side composes them expanded as well."""
    paths = _files(rst_repo, main="A\tB\n####\n\n.. include:: contact.rst\n", contact="Jane Doe\nphone: 0100\n")
    monkeypatch.chdir(rst_repo)

    _code, out = _run(monkeypatch, capsys, "fix", "main.rst")

    adornment = "#" * 11
    assert paths["main"].read_text(encoding="utf-8").startswith(f"{adornment}\nA\tB\n{adornment}\n"), out


@pytest.mark.integration
@pytest.mark.parametrize(
    "include",
    [".. include:: part.rst\n   :tab-width: 4\n", ".. include::\n   part.rst\n"],
    ids=["tab-width-without-tabs", "continued-argument"],
)
def test_a_confirmed_include_that_composes_exactly_is_a_context(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], include: str
) -> None:
    """Guards for the confirmation: a tab width with no tab to expand changes
    nothing, and an argument continued on the next line is still probed."""
    paths = _files(rst_repo, main=_MAIN.replace(".. include:: part.rst\n", include), part=_PART)
    monkeypatch.chdir(rst_repo)

    _code, out = _run(monkeypatch, capsys, "fix", "part.rst")

    assert "cannot compose" not in out
    assert paths["part"].read_text(encoding="utf-8") == _PART, out


@pytest.mark.integration
@pytest.mark.parametrize(
    ("setting", "evidence"),
    [("rst_prolog", "an rst_prolog"), ("rst_epilog", "an rst_epilog")],
)
def test_a_prolog_or_epilog_makes_include_contexts_unavailable(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], setting: str, evidence: str
) -> None:
    """Finding 3, K2: Sphinx adds the prolog or epilog to every document it
    parses, where a title in it shifts the first-encounter ranking.  The
    lexical composition and the bare-Docutils revalidation both prove a
    document Sphinx never parses."""
    part = _sphinx_project(rst_repo, conf=_CONF + f'{setting} = ".. |x| replace:: y\\n"\n')

    code, out = _run_verified(rst_repo, monkeypatch, capsys, "fix", "docs/part.rst")

    assert code == 1, out
    assert f"this project's Sphinx configuration may transform ({evidence})" in out
    assert part.read_text(encoding="utf-8") == _PART


@pytest.mark.integration
def test_revalidation_proves_which_titles_became_sections(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Finding 5: equal depth sequences do not prove the same titles.

    The parser-free model reads CR-45's comment above an adornment as a
    title, which Docutils does not.  Docutils reads two backslashes over
    "==" as a title, which the model does not.  Both give depths 1, 2, 3
    and 4, but from different lines.  The planner is replaced by one that
    makes a harmless edit of the file's own, so revalidation runs on exactly
    that text and must compare each section's source line too."""
    from check_rst.cli import _contexts
    from check_rst.cli._formatting import _structure_plan as real_plan

    def harmless(lines: list[str], ranges: list[tuple[int, int]] | None) -> tuple[list[str], tuple[()]]:
        if "Body." not in lines:
            return real_plan(lines, ranges)[0], ()
        edited = list(lines)
        edited[edited.index("Body.")] = "Body text."
        return edited, ()

    monkeypatch.setattr(_contexts, "_structure_plan", harmless)
    part = ".. a comment\n=======\n\n\\\\\n==\n\nBody.\n"
    paths = _files(rst_repo, main=_MAIN, part=part)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "fix", "part.rst")

    assert code == 1, out
    assert "Docutils would read the planned titles as a different section tree" in out
    assert paths["part"].read_text(encoding="utf-8") == part


# ---------------------------------------------------------------------------
# Effective clipped input (Codex's third P4 look)
# ---------------------------------------------------------------------------

_NEST_ROOT = "######\nRoot\n######\n\n*****\nSub\n*****\n\n"
# At level 3 in the root, child.rst's "=o" is consistent; standalone it is
# the page title, which fix would remap to "#o".
_CHILD = "=======\nChild\n=======\n\nBody.\n"


@pytest.mark.integration
@pytest.mark.parametrize("mode", [("fix", "--fast"), ("fix",)], ids=["fast", "full"])
def test_a_start_after_clip_exposes_a_nested_include(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], mode: tuple[str, ...]
) -> None:
    """Docutils clips before parsing: after ":start-after: PREFIX", the text
    of mid.rst is ".. include:: child.rst", though no physical line of it
    starts an include.  Discovery scanned the physical file, so it never saw
    the edge, and both modes remapped child.rst as a standalone document."""
    root = _NEST_ROOT + ".. include:: mid.rst\n   :start-after: PREFIX\n"
    paths = _files(rst_repo, root=root, mid="PREFIX.. include:: child.rst\n", child=_CHILD)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, *mode, "child.rst")

    assert paths["child"].read_text(encoding="utf-8") == _CHILD, out
    if mode == ("fix", "--fast"):
        assert code == 1, out
        assert "this file may be included by mid.rst:1" in out


@pytest.mark.integration
@pytest.mark.parametrize(
    ("mid", "include_options"),
    [
        (".. include:: child.rst\n   :bogus: 1\n", "\n   :end-line: 1"),
        (".. include:: child.rst\n\t:bogus: 1\n", "\n   :tab-width: 0"),
    ],
    ids=["end-line-drops-a-bad-option", "tab-width-moves-an-option-out"],
)
@pytest.mark.parametrize("mode", [("fix", "--fast"), ("fix",)], ids=["fast", "full"])
def test_an_effective_variant_validates_a_nested_include_the_whole_file_rejects(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mid: str,
    include_options: str,
    mode: tuple[str, ...],
) -> None:
    """Read whole, mid.rst's nested include carries an unknown option and
    is rejected.  In root.rst's variant the option is gone: ":end-line: 1"
    drops its line, and ":tab-width: 0" removes the tab that placed it in
    the directive's block.  The whole-file verdict must not remove the
    edge from that variant."""
    root = _NEST_ROOT + f".. include:: mid.rst{include_options}\n"
    paths = _files(rst_repo, root=root, mid=mid, child=_CHILD)
    monkeypatch.chdir(rst_repo)

    _code, out = _run(monkeypatch, capsys, *mode, "child.rst")

    assert paths["child"].read_text(encoding="utf-8") == _CHILD, out


@pytest.mark.integration
def test_variants_of_one_file_are_judged_apart(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """whole.rst includes mid.rst whole, where the nested include is
    rejected and adds nothing; clipped.rst includes the variant where it
    runs.  child.rst's one context is clipped.rst's, and agrees."""
    paths = _files(
        rst_repo,
        clipped=_NEST_ROOT + ".. include:: mid.rst\n   :end-line: 1\n",
        whole=_NEST_ROOT.replace("Root", "Whol") + ".. include:: mid.rst\n",
        mid=".. include:: child.rst\n   :bogus: 1\n",
        child=_CHILD,
    )
    monkeypatch.chdir(rst_repo)

    _code, out = _run(monkeypatch, capsys, "fix", "child.rst")

    assert "include contexts need different" not in out
    assert paths["child"].read_text(encoding="utf-8") == _CHILD, out


@pytest.mark.integration
@pytest.mark.parametrize(
    ("mid", "include_options", "line"),
    [
        ("..\vinclude:: child.rst\n", "", 1),
        ("..\finclude:: child.rst\n", "", 1),
        ("intro\vmore\n.. include:: child.rst\n", "\n   :start-line: 2", 2),
    ],
    ids=["vertical-tab", "form-feed", "line-clip-counts-a-vertical-tab"],
)
@pytest.mark.parametrize("mode", [("fix", "--fast"), ("fix",)], ids=["fast", "full"])
def test_control_whitespace_follows_docutils_order(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mid: str,
    include_options: str,
    line: int,
    mode: tuple[str, ...],
) -> None:
    """Codex's fourth P4 look: Python's splitlines() breaks at a vertical tab
    or a form feed, while Docutils' string2lines turns both into spaces
    first, so "..<VT>include:: child.rst" is an include.  But a line clip
    counts lines with a raw splitlines(), so under ":start-line: 2" the
    vertical tab does split "intro<VT>more", and the include is the third
    line.  Discovery must follow that exact order: converting first misses
    the second case as surely as splitting first misses the first."""
    root = _NEST_ROOT + f".. include:: mid.rst{include_options}\n"
    paths = _files(rst_repo, root=root, mid=mid, child=_CHILD)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, *mode, "child.rst")

    assert paths["child"].read_text(encoding="utf-8") == _CHILD, out
    if mode == ("fix", "--fast"):
        assert code == 1, out
        assert f"this file may be included by mid.rst:{line}" in out


_BAD = _PART  # standalone "=o" page title, remapped to "#o" when it is no fragment


@pytest.mark.integration
@pytest.mark.parametrize("mode", [("fix", "--fast"), ("fix",)], ids=["fast", "full"])
def test_two_parsed_sites_on_one_physical_line_keep_their_own_verdicts(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], mode: tuple[str, ...]
) -> None:
    """Codex's fifth P4 look: under ":end-line: 4", Docutils' raw splitlines()
    splits one physical line at its vertical tabs into an include of
    child.rst, a blank line, and an include of bad.rst whose option is
    unknown.  Docutils runs the first and rejects the second.  Keyed by
    their shared physical line, the rejection removed both edges, and full
    mode remapped child.rst as standalone."""
    root = _NEST_ROOT + ".. include:: mid.rst\n   :end-line: 4\n"
    mid = ".. include:: child.rst\v\v.. include:: bad.rst\n   :bogus:\n"
    paths = _files(rst_repo, root=root, mid=mid, child=_CHILD, bad=_BAD)
    monkeypatch.chdir(rst_repo)

    _code, out = _run(monkeypatch, capsys, *mode, "child.rst")

    assert paths["child"].read_text(encoding="utf-8") == _CHILD, out


@pytest.mark.integration
def test_a_rejected_site_before_a_running_one_is_not_kept_for_it(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other order on the shared physical line: the rejected include of
    bad.rst first, then the running include of child.rst.  child.rst keeps
    its context, and bad.rst, which nothing really includes, is fixed as the
    standalone document it is: neither a false retention nor a needless
    refusal."""
    root = _NEST_ROOT + ".. include:: mid.rst\n   :end-line: 4\n"
    mid = ".. include:: bad.rst\v   :bogus:\v\v.. include:: child.rst\n"
    paths = _files(rst_repo, root=root, mid=mid, child=_CHILD, bad=_BAD)
    monkeypatch.chdir(rst_repo)

    _code, child_out = _run(monkeypatch, capsys, "fix", "child.rst")
    _code, bad_out = _run(monkeypatch, capsys, "fix", "bad.rst")

    assert paths["child"].read_text(encoding="utf-8") == _CHILD, child_out
    assert "cannot compose" not in bad_out
    assert paths["bad"].read_text(encoding="utf-8") == _STANDALONE_PART, bad_out


@pytest.mark.integration
@pytest.mark.parametrize("mode", [("fix", "--fast"), ("fix",)], ids=["fast", "full"])
def test_every_unresolved_rooted_site_keeps_the_graph_incomplete(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], mode: tuple[str, ...]
) -> None:
    """Codex's sixth P4 look.  Under ":start-line: 1", one physical line of
    mid.rst holds two rooted includes: "/bad.rst", which Docutils rejects
    for its unknown option, and "/child.rst", which runs.  With no Sphinx
    source known, the running one makes the graph incomplete.  The
    unresolved list was de-duplicated by physical line, so it kept only the
    rejected site; confirmation then removed it, and full mode remapped
    child.rst.  The PREFIX keeps the whole-file scan from finding another
    unresolved site that would mask the defect."""
    root = _NEST_ROOT + ".. include:: mid.rst\n   :start-line: 1\n"
    mid = "PREFIX\v.. include:: /bad.rst\v   :bogus:\v\v.. include:: /child.rst\n"
    paths = _files(rst_repo, root=root, mid=mid, child=_CHILD)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, *mode, "child.rst")

    assert code == 1, out
    assert "the include graph is incomplete: mid.rst:1 includes '/" in out
    if mode == ("fix",):
        assert "the include graph is incomplete: mid.rst:1 includes '/child.rst'" in out
    assert paths["child"].read_text(encoding="utf-8") == _CHILD
