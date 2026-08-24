# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED/GREEN tests for the entitle verb, built in isolated stages before
# CLI wiring — check_rst project
"""Tests for the ``entitle`` verb (docs/roadmap.rst, "Wrap a document
under a new top-level title"): insert a new depth-1 title above a
document's existing content, demoting whatever was there into its
children, then renormalize the whole document with the same
hierarchy/adornment engine ``fix`` already uses.

Staged the same way ``list-table`` was: the pure computation
(``_formatting._compute_entitle_lines`` and its two helpers) is tested
standalone here before any CLI wiring exists, then the CLI-level tests
in this same file drive ``cli.main()`` once that wiring lands.
"""

from __future__ import annotations

import subprocess
import textwrap
from typing import TYPE_CHECKING

import pytest
from _support import _git, _rst

from check_rst import cli
from check_rst.cli import _formatting

if TYPE_CHECKING:
    from pathlib import Path


def _depths(lines: list[str]) -> dict[str, int]:
    """char -> established depth, for asserting structural facts about
    entitle's output without pinning every literal adornment line."""
    return {char: depth for char, _lineno, depth in _formatting._established_depths(lines)}


def _titles(lines: list[str]) -> list[str]:
    """Title text of every title block/underline-only candidate, in
    document order — lets a test assert *which* text ended up at which
    position without caring about adornment characters or widths."""
    return [lines[idx] for idx, _char in _formatting._title_char_events(lines)]


# ------------------------------------------------------------------
# _compute_entitle_lines — pure function, no filesystem or CLI at all
# ------------------------------------------------------------------


@pytest.mark.unit
def test_entitle_wraps_a_titleless_document_exactly() -> None:
    """No existing sections at all: the new title becomes the document's
    sole depth-1 section, and the prose becomes its body verbatim."""
    lines = ["Just some prose.", "", "More prose."]

    result = _formatting._compute_entitle_lines(lines, "New Title")

    assert result == [
        "###########",
        "New Title",
        "###########",
        "",
        "Just some prose.",
        "",
        "More prose.",
    ]


@pytest.mark.unit
def test_entitle_demotes_a_single_existing_top_level_section() -> None:
    """One existing top-level section, with its own child, both shift
    down by exactly one depth — the new title becomes depth 1, the old
    title and its child become depths 2 and 3."""
    lines = textwrap.dedent(
        """\
        Old Title
        #########

        Intro.

        Child
        *****

        Child body.
        """
    ).splitlines()

    result = _formatting._compute_entitle_lines(lines, "New Title")

    depths = _depths(result)
    assert depths["#"] == 1  # the new title always claims the top rank
    assert depths["*"] == 2  # "Old Title" — demoted by exactly one level
    assert depths["="] == 3  # "Child" — remapped into the next free rank
    assert _titles(result) == ["New Title", "Old Title", "Child"]


@pytest.mark.unit
def test_entitle_demotes_both_same_styled_top_level_titles_as_siblings() -> None:
    """The actual `second effective top-level title` shape: two titles
    sharing one adornment style are docutils' only way to end up at the
    same depth without a common parent.  Both must become depth-2
    siblings under the new title, not nest one inside the other."""
    lines = textwrap.dedent(
        """\
        Title One
        #########

        First body.

        Title Two
        #########

        Second body.
        """
    ).splitlines()

    result = _formatting._compute_entitle_lines(lines, "New Title")

    depths = _depths(result)
    assert depths["#"] == 1
    assert depths["*"] == 2  # both old titles share this one remapped rank
    assert _titles(result) == ["New Title", "Title One", "Title Two"]


@pytest.mark.unit
def test_entitle_leaves_leading_front_matter_outside_the_new_title() -> None:
    """A leading comment (this project's own copyright-header shape)
    stays above the new title — it is never absorbed into the new
    section's body."""
    lines = textwrap.dedent(
        """\
        .. Copyright (C) 2026 Someone
        .. SPDX-License-Identifier: GPL-3.0-only

        Old Title
        #########

        Body.
        """
    ).splitlines()

    result = _formatting._compute_entitle_lines(lines, "New Title")

    assert result[0] == ".. Copyright (C) 2026 Someone"
    assert result[1] == ".. SPDX-License-Identifier: GPL-3.0-only"
    assert _titles(result) == ["New Title", "Old Title"]
    assert _depths(result) == {"#": 1, "*": 2}


@pytest.mark.unit
def test_entitle_places_front_matter_above_a_titleless_document_too() -> None:
    """The front-matter guarantee does not depend on an existing title."""
    lines = [
        ".. a leading comment",
        "",
        ".. _home: https://example.com",
        "",
        ".. |project| replace:: check_rst",
        "",
        "Some prose about |project|.",
    ]

    result = _formatting._compute_entitle_lines(lines, "New Title")

    assert result[:6] == lines[:6]
    assert result[6:10] == ["###########", "New Title", "###########", ""]
    assert result[10:] == ["Some prose about |project|."]


@pytest.mark.unit
def test_entitle_wraps_leading_prose_before_the_first_existing_section() -> None:
    """Ordinary prose before the first heading is body, not front matter."""
    lines = [
        "Intro before any section.",
        "",
        "Old Section",
        "===========",
        "",
        "Body.",
    ]

    result = _formatting._compute_entitle_lines(lines, "New Title")

    assert result[:4] == ["###########", "New Title", "###########", ""]
    assert result[4:6] == ["Intro before any section.", ""]
    assert _titles(result) == ["New Title", "Old Section"]
    assert _depths(result) == {"#": 1, "*": 2}


@pytest.mark.unit
def test_entitle_wraps_titleless_bibliographic_fields_below_the_new_title() -> None:
    """A field list must follow the title to become document metadata."""
    lines = [":Author: Example Writer", "", "Document body."]

    result = _formatting._compute_entitle_lines(lines, "New Title")

    assert result[:4] == ["###########", "New Title", "###########", ""]
    assert result[4:] == lines


@pytest.mark.unit
@pytest.mark.parametrize(
    "options",
    [(), ("   :literal:",)],
    ids=["parsed", "literal"],
)
def test_entitle_refuses_an_include_without_following_it(
    tmp_path: Path,
    options: tuple[str, ...],
) -> None:
    """Refusal must preserve entitle's one-file read boundary."""
    included = tmp_path / "missing.rst"
    lines = [".. leading comment", "", f".. include:: {included}", *options]

    with pytest.raises(
        ValueError,
        match="top-level include composition is outside entitle's one-file safety boundary",
    ):
        _formatting._compute_entitle_lines(lines, "New Title")


@pytest.mark.unit
def test_entitle_remaps_a_preexisting_hash_title_and_a_non_preferred_one() -> None:
    """An existing title already at HIERARCHY[0] ('#') and one using a
    non-preferred character both remap correctly once demoted."""
    lines = textwrap.dedent(
        """\
        Old Title
        #########

        Intro.

        Odd Child
        ~~~~~~~~~

        Body.
        """
    ).splitlines()

    result = _formatting._compute_entitle_lines(lines, "New Title")

    depths = _depths(result)
    assert depths["#"] == 1
    assert depths["*"] == 2
    assert depths["="] == 3


@pytest.mark.unit
def test_entitle_is_idempotent_and_adds_a_third_level_each_time() -> None:
    """Entitling an already-entitled document always wraps again rather
    than refusing — there is no 'already has one title' special case."""
    lines = ["Original.", ""]

    once = _formatting._compute_entitle_lines(lines, "First Wrap")
    twice = _formatting._compute_entitle_lines(once, "Second Wrap")

    assert _titles(twice) == ["Second Wrap", "First Wrap"]
    assert _depths(twice) == {"#": 1, "*": 2}


@pytest.mark.unit
def test_entitle_fails_closed_when_every_adornment_character_is_used() -> None:
    """Never silently reuse an already-established character — fail with
    a clear diagnostic instead of risking an incorrect nesting."""
    from check_rst.cli._helpers import HIERARCHY

    lines: list[str] = []
    for depth, char in enumerate(HIERARCHY, start=1):
        title = f"Level {depth}"
        lines += [title, char * (len(title) + 2), ""]

    with pytest.raises(ValueError, match="every adornment character"):
        _formatting._compute_entitle_lines(lines, "One More")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "match"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("Two\nLines", "single line"),
        ("----", "indistinguishable from an adornment"),
        ("########", "indistinguishable from an adornment"),
    ],
)
def test_entitle_rejects_a_name_that_cannot_become_a_title(name: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _formatting._compute_entitle_lines(["Prose."], name)


@pytest.mark.unit
def test_entitle_accepts_a_name_that_merely_contains_adornment_characters() -> None:
    """Only a name that IS entirely one repeated character collides with
    the adornment-line pattern; ordinary punctuation inside real prose
    must not be rejected."""
    result = _formatting._compute_entitle_lines(["Prose."], "C++ Guide -- Q&A")
    assert _titles(result) == ["C++ Guide -- Q&A"]


# ------------------------------------------------------------------
# diff_entitle / fix_entitle — file-level wrappers
# ------------------------------------------------------------------


@pytest.mark.unit
def test_diff_entitle_previews_without_writing(tmp_path: Path) -> None:
    path = _rst(tmp_path, "Old Title\n#########\n\nBody.\n")
    original = path.read_text(encoding="utf-8")

    diff = _formatting.diff_entitle(path, "New Title")

    assert "New Title" in diff
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.unit
def test_fix_entitle_writes_the_computed_result(tmp_path: Path) -> None:
    path = _rst(tmp_path, "Old Title\n#########\n\nBody.\n")

    changed = _formatting.fix_entitle(path, "New Title")

    assert changed is True
    written = path.read_text(encoding="utf-8")
    assert "New Title" in written
    assert _depths(written.splitlines())["*"] == 2


@pytest.mark.unit
def test_diff_entitle_previews_the_exact_raw_to_applied_transformation(tmp_path: Path) -> None:
    """Preview includes Phase-0 normalization and final-newline behavior."""
    path = tmp_path / "doc.rst"
    original = b"Old Title   \r\n#########\r\n\r\nBody.   "
    path.write_bytes(original)

    diff = _formatting.diff_entitle(path, "New Title")
    _formatting.fix_entitle(path, "New Title")
    applied = path.read_bytes()

    assert "-Old Title   \r\n" in diff
    assert "-Body.   " in diff
    assert "+Old Title\n" in diff
    assert diff.endswith("+Body.\n\\ No newline at end of file\n")
    assert applied == b"###########\nNew Title\n###########\n\n***********\nOld Title\n***********\n\nBody."


# ------------------------------------------------------------------
# CLI-level tests — added once cli.main() wires the "entitle" verb
# ------------------------------------------------------------------


@pytest.mark.integration
def test_cli_entitle_preview_prints_diff_and_exits_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _rst(tmp_path, "Old Title\n#########\n\nBody.\n")
    original = path.read_text(encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "entitle", "New Title", str(path)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "New Title" in out
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.integration
def test_cli_entitle_apply_writes_and_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _rst(tmp_path, "Old Title\n#########\n\nBody.\n")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "entitle", "New Title", str(path), "--apply"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "New Title" in path.read_text(encoding="utf-8")
    assert str(path) in out


@pytest.mark.integration
def test_cli_entitle_apply_quiet_suppresses_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _rst(tmp_path, "Old Title\n#########\n\nBody.\n")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "entitle", "New Title", str(path), "--apply", "--quiet"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert capsys.readouterr().out == ""
    assert "New Title" in path.read_text(encoding="utf-8")


@pytest.mark.integration
def test_cli_entitle_rejects_non_utf8_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "doc.rst"
    path.write_bytes(b"Title\n#####\n\n\xff\xfe bad bytes\n")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "entitle", "New Title", str(path)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert "not valid UTF-8" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_entitle_rejects_unresolved_merge_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A genuine unresolved index conflict from a real merge — the same
    construction as test_cli_pipeline.py's
    test_cli_unmerged_file_stops_before_fix_and_preserves_markers."""
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    path = tmp_path / "conflict.rst"
    path.write_text("Base\n####\n", encoding="utf-8")
    _git(tmp_path, "add", "conflict.rst")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "checkout", "-b", "other")
    path.write_text("Theirs\n######\n", encoding="utf-8")
    _git(tmp_path, "add", "conflict.rst")
    _git(tmp_path, "commit", "-m", "theirs")
    _git(tmp_path, "checkout", "-")
    path.write_text("Ours\n####\n", encoding="utf-8")
    _git(tmp_path, "add", "conflict.rst")
    _git(tmp_path, "commit", "-m", "ours")
    merge = subprocess.run(
        ["git", "-C", str(tmp_path), "merge", "other"],
        capture_output=True,
        check=False,
    )
    assert merge.returncode != 0
    original = path.read_bytes()
    assert b"<<<<<<<" in original
    monkeypatch.setattr("sys.argv", ["check_rst.py", "entitle", "New Title", str(path)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert path.read_bytes() == original
    assert "unresolved Git merge conflict" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_entitle_rejects_missing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing.rst"
    monkeypatch.setattr("sys.argv", ["check_rst.py", "entitle", "New Title", str(missing)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert "file not found" in capsys.readouterr().out


@pytest.mark.integration
@pytest.mark.parametrize("flag", ["--config", "--sphinx-src", "--build-dir"])
def test_cli_entitle_rejects_project_identity_flags(
    flag: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _rst(tmp_path, "Old Title\n#########\n\nBody.\n")
    value = str(tmp_path) if flag != "--config" else str(tmp_path / "check_rst.toml")
    monkeypatch.setattr("sys.argv", ["check_rst.py", flag, value, "entitle", "New Title", str(path)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert "entitle is self-contained" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_entitle_result_reports_no_second_top_level_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The end-to-end proof: entitling a document with two same-styled
    top-level titles clears the ``second effective top-level title``
    ERROR entirely, and outline shows exactly one depth-1 section."""
    path = _rst(
        tmp_path,
        """\
        Title One
        #########

        First body.

        Title Two
        #########

        Second body.
        """,
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "entitle", "New Title", str(path), "--apply", "--quiet"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(path)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert "second effective top-level title" not in capsys.readouterr().out

    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", str(path)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "levels: 1 '#' (1), 2 '*' (2), 3 sections total" in out
