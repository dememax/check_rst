# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Source hygiene and whitespace-normalization tests — check_rst project

from __future__ import annotations

from typing import TYPE_CHECKING

import docutils.nodes
import pytest
from _support import _rst

from check_rst import cli
from check_rst.cli import _formatting, _helpers, _types

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.integration
def test_hygiene_clean_file_no_findings_unchanged(tmp_path: Path) -> None:
    """A clean LF-only file yields no hygiene findings and is never rewritten."""
    p = _rst(
        tmp_path,
        """\
        #######
        Title
        #######

        Text.
        """,
    )
    before = p.read_bytes()
    assert _formatting.check_hygiene(p) == []
    assert _formatting.fix_hygiene(p) is False
    assert p.read_bytes() == before


@pytest.mark.integration
def test_hygiene_crlf_flagged_and_fixed(tmp_path: Path) -> None:
    """CRLF line endings are an ERROR (policy: Unix LF) and --fix normalizes
    every line ending, preserving content."""
    p = tmp_path / "crlf.rst"
    p.write_bytes(b"#######\r\nTitle\r\n#######\r\n\r\nText.\r\n")

    findings = _formatting.check_hygiene(p)
    assert any("CRLF" in f for f in findings)
    # One coalesced finding per defect kind: the total count is in the
    # message, the anchor line is labeled as the first of them.
    assert any("on 5 line(s), first here" in f for f in findings)
    assert all(f.severity == "ERROR" for f in findings)

    assert _formatting.fix_hygiene(p) is True
    raw = p.read_bytes()
    assert b"\r" not in raw
    assert raw == b"#######\nTitle\n#######\n\nText.\n"
    assert _formatting.check_hygiene(p) == []


@pytest.mark.integration
def test_hygiene_lone_cr_flagged_and_fixed(tmp_path: Path) -> None:
    """A lone CR is a line break to Python/docutils but not to git — line
    numbering silently desynchronizes.  ERROR, fixed to LF."""
    p = tmp_path / "cr.rst"
    p.write_bytes(b"line one\rline two\n")

    findings = _formatting.check_hygiene(p)
    assert any("lone CR" in f for f in findings)

    assert _formatting.fix_hygiene(p) is True
    assert p.read_bytes() == b"line one\nline two\n"


@pytest.mark.integration
def test_hygiene_bom_flagged_and_fixed(tmp_path: Path) -> None:
    """A UTF-8 BOM is an ERROR (policy: no BOM) and --fix strips it."""
    p = tmp_path / "bom.rst"
    p.write_bytes(b"\xef\xbb\xbf#######\nTitle\n#######\n\nText.\n")

    findings = _formatting.check_hygiene(p)
    assert any("BOM" in f for f in findings)

    assert _formatting.fix_hygiene(p) is True
    raw = p.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw == b"#######\nTitle\n#######\n\nText.\n"


@pytest.mark.integration
def test_hygiene_exotic_separators_flagged_and_fixed(tmp_path: Path) -> None:
    """Exotic separators split lines for Python/docutils but not for git.
    U+2028/U+0085-class separators become LF; VT/FF become a space (docutils'
    own convert_whitespace semantics)."""
    p = tmp_path / "exotic.rst"
    p.write_bytes("line one\u2028line two\nalpha\x0cbeta\n".encode())

    findings = _formatting.check_hygiene(p)
    assert any("U+2028" in f for f in findings)
    assert any("U+000C" in f for f in findings)
    assert all("1 occurrence(s), first here" in f for f in findings)

    assert _formatting.fix_hygiene(p) is True
    assert p.read_bytes() == b"line one\nline two\nalpha beta\n"


@pytest.mark.integration
def test_hygiene_trailing_whitespace_on_adornment_flagged_and_fixed(
    tmp_path: Path,
) -> None:
    """Trailing whitespace on an adornment line hides it from every structure
    check (docutils itself strips it, so stripping is semantically free)."""
    p = tmp_path / "trailws.rst"
    p.write_bytes(b"####### \nTitle\n#######\n\nText.\n")

    findings = _formatting.check_hygiene(p)
    assert any("trailing whitespace" in f for f in findings)

    assert _formatting.fix_hygiene(p) is True
    assert p.read_bytes() == b"#######\nTitle\n#######\n\nText.\n"


@pytest.mark.integration
def test_hygiene_trailing_whitespace_on_text_line_flagged_and_fixed(
    tmp_path: Path,
) -> None:
    """Docutils right-strips every input line before parsing, so retaining
    spaces or tabs at the end of an ordinary text line has no RST meaning."""
    p = tmp_path / "textws.rst"
    p.write_bytes(b"#######\nTitle\n#######\n\nSome text. \t\n")

    findings = _formatting.check_hygiene(p)
    assert len(findings) == 1
    assert findings[0].lineno == 5
    assert "trailing whitespace" in findings[0]

    assert _formatting.fix_hygiene(p) is True
    assert p.read_bytes().endswith(b"Some text.\n")
    assert _formatting.check_hygiene(p) == []


@pytest.mark.integration
def test_hygiene_trailing_whitespace_on_section_title_and_body_is_parser_invisible(
    tmp_path: Path,
) -> None:
    """string2lines right-strips before the title/paragraph states run, so
    section text and simple body text have the same before/after doctree."""
    before = "#######\nTitle  \n#######\n\nSimple text block. \t\n"
    after = "#######\nTitle\n#######\n\nSimple text block.\n"
    p = tmp_path / "title-and-body.rst"
    p.write_text(before, encoding="utf-8")
    before_tree = _helpers._parse_rst(p, text=before).pformat()

    assert len(_formatting.check_hygiene(p)) == 2
    assert _formatting.fix_hygiene(p) is True

    assert p.read_text(encoding="utf-8") == after
    assert _helpers._parse_rst(p, text=after).pformat() == before_tree


@pytest.mark.integration
def test_hygiene_trailing_whitespace_safe_in_whitespace_preserving_blocks(
    tmp_path: Path,
) -> None:
    """The source cleanup matches docutils' pre-parse rstrip even where the
    resulting node otherwise preserves whitespace: literal, parsed-literal,
    line-block, and raw content.  Whitespace-only separator lines become empty
    but are not removed, so the source line count is stable."""
    before = (
        "Paragraph tail.  \n"
        " \t\n"
        "Example::\n\n"
        "   literal tail   \n\n"
        ".. parsed-literal::\n\n"
        "   parsed tail\t\n\n"
        "| line tail   \n\n"
        ".. raw:: html\n\n"
        "   <span>raw tail</span>  \n"
    )
    after = (
        "Paragraph tail.\n"
        "\n"
        "Example::\n\n"
        "   literal tail\n\n"
        ".. parsed-literal::\n\n"
        "   parsed tail\n\n"
        "| line tail\n\n"
        ".. raw:: html\n\n"
        "   <span>raw tail</span>\n"
    )
    p = tmp_path / "contexts.rst"
    p.write_text(before, encoding="utf-8")
    before_tree = _helpers._parse_rst(p, text=before).pformat()

    findings = _formatting.check_hygiene(p)
    assert len(findings) == 6
    assert _formatting.fix_hygiene(p) is True

    assert p.read_text(encoding="utf-8") == after
    assert _helpers._parse_rst(p, text=after).pformat() == before_tree


@pytest.mark.integration
def test_hygiene_trailing_whitespace_preserves_missing_final_newline(
    tmp_path: Path,
) -> None:
    """Right-stripping the final line must not invent a final newline."""
    p = tmp_path / "no-final-newline.rst"
    p.write_bytes(b"Text without final newline \t")

    assert len(_formatting.check_hygiene(p)) == 1
    assert _formatting.fix_hygiene(p) is True
    assert p.read_bytes() == b"Text without final newline"


@pytest.mark.unit
def test_hygiene_trailing_whitespace_structured_count() -> None:
    """Fix-only output needs one stable count of affected source lines."""
    normalized, findings, counts = _helpers._normalize_source_detailed("one  \n \t\nthree\t\n")

    assert normalized == "one\n\nthree\n"
    assert len(findings) == 3
    assert counts.trailing_whitespace == 3
    assert counts.describe() == "trailing whitespace lines 3"


@pytest.mark.unit
def test_normalize_blank_lines_collapses_parser_equivalent_block_separators(
    tmp_path: Path,
) -> None:
    before = (
        "Document\n========\n\n\n\n"
        "First paragraph.\n\n\n"
        "Second paragraph.\n\n\n\n"
        "Section\n-------\n\n\n"
        "* one\n* two\n\n\n"
        "+---+---+\n| A | B |\n+===+===+\n| 1 | 2 |\n+---+---+\n\n\n"
        "Final paragraph.\n"
    )
    after = (
        "Document\n========\n\n"
        "First paragraph.\n\n"
        "Second paragraph.\n\n"
        "Section\n-------\n\n"
        "* one\n* two\n\n"
        "+---+---+\n| A | B |\n+===+===+\n| 1 | 2 |\n+---+---+\n\n"
        "Final paragraph.\n"
    )
    path = tmp_path / "blocks.rst"

    normalized, removed = _formatting._normalize_blank_lines(path, before)

    assert normalized == after
    assert removed == 8
    assert _helpers._parse_rst(path, text=normalized).pformat() == _helpers._parse_rst(path, text=before).pformat()
    assert _formatting._normalize_blank_lines(path, normalized) == (normalized, 0)


@pytest.mark.unit
def test_normalize_blank_lines_preserves_content_in_literal_like_blocks(
    tmp_path: Path,
) -> None:
    before = (
        "Before.\n\n\n"
        "Example::\n\n"
        "   literal one\n\n\n"
        "   literal two\n\n\n"
        ".. parsed-literal::\n\n"
        "   parsed one\n\n\n"
        "   parsed two\n\n\n"
        ".. raw:: html\n\n"
        "   <p>raw one</p>\n\n\n"
        "   <p>raw two</p>\n\n\n"
        "After.\n"
    )
    expected = (
        "Before.\n\n"
        "Example::\n\n"
        "   literal one\n\n\n"
        "   literal two\n\n"
        ".. parsed-literal::\n\n"
        "   parsed one\n\n\n"
        "   parsed two\n\n"
        ".. raw:: html\n\n"
        "   <p>raw one</p>\n\n\n"
        "   <p>raw two</p>\n\n"
        "After.\n"
    )
    path = tmp_path / "literal-like.rst"

    normalized, removed = _formatting._normalize_blank_lines(path, before)

    assert normalized == expected
    assert removed == 4
    assert "literal one\n\n\n   literal two" in normalized
    assert "parsed one\n\n\n   parsed two" in normalized
    assert "raw one</p>\n\n\n   <p>raw two" in normalized


@pytest.mark.unit
def test_normalize_blank_lines_normalizes_document_edges_and_final_newline_state(
    tmp_path: Path,
) -> None:
    before = "\n\nAlpha.\n\n\nBeta.\n\n"

    normalized, removed = _formatting._normalize_blank_lines(tmp_path / "edges.rst", before)

    assert normalized == "Alpha.\n\nBeta.\n"
    assert removed == 4
    assert normalized.endswith("Beta.\n")

    without_final_newline, removed = _formatting._normalize_blank_lines(
        tmp_path / "no-final-newline.rst", "Alpha.\n\n\nBeta."
    )
    assert without_final_newline == "Alpha.\n\nBeta."
    assert removed == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    ("before", "after", "removed"),
    [
        ("Alpha.\n", "Alpha.\n", 0),
        ("\nAlpha.\n", "Alpha.\n", 1),
        ("\n\nAlpha.\n", "Alpha.\n", 2),
        ("\n\nTitle\n=====\n\nBody.\n", "Title\n=====\n\nBody.\n", 2),
        ("\n\n.. raw:: html\n\n   <p>x</p>\n", ".. raw:: html\n\n   <p>x</p>\n", 2),
        ("\n\n", "\n\n", 0),
    ],
)
def test_normalize_blank_lines_removes_empty_lines_before_first_element(
    tmp_path: Path,
    before: str,
    after: str,
    removed: int,
) -> None:
    path = tmp_path / "leading.rst"
    before_tree = _helpers._parse_rst(path, text=before).pformat()

    normalized, actual_removed = _formatting._normalize_blank_lines(path, before)

    assert normalized == after
    assert actual_removed == removed
    assert _helpers._parse_rst(path, text=normalized).pformat() == before_tree


@pytest.mark.unit
@pytest.mark.parametrize(
    ("before", "after", "removed"),
    [
        ("Alpha.", "Alpha.", 0),
        ("Alpha.\n", "Alpha.\n", 0),
        ("Alpha.\n\n", "Alpha.\n", 1),
        ("Alpha.\n\n\n", "Alpha.\n", 2),
        ("\n\n", "\n\n", 0),
        ("Example::\n\n   literal\n\n\n", "Example::\n\n   literal\n", 2),
    ],
)
def test_normalize_blank_lines_removes_duplicate_empty_lines_at_eof(
    tmp_path: Path,
    before: str,
    after: str,
    removed: int,
) -> None:
    path = tmp_path / "eof.rst"
    before_tree = _helpers._parse_rst(path, text=before).pformat()

    normalized, actual_removed = _formatting._normalize_blank_lines(path, before)

    assert normalized == after
    assert actual_removed == removed
    assert _helpers._parse_rst(path, text=normalized).pformat() == before_tree


@pytest.mark.integration
def test_cli_normalize_blank_lines_is_opt_in_and_composes_with_fix(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    original = "\n\n##########\nDocument\n##########\n\n\nBody.\n\n\n"
    document.write_text(original, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", str(document)])
    with pytest.raises(SystemExit):
        cli.main()
    assert document.read_text(encoding="utf-8") == original

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "fix", "--normalize-blank-lines", str(document)],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert document.read_text(encoding="utf-8") == "##########\nDocument\n##########\n\nBody.\n"
    assert "5 redundant blank lines removed" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_normalize_blank_lines_diff_previews_without_writing(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    original = "##########\nDocument\n##########\n\n\nBody.\n"
    document.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "diff", "--normalize-blank-lines", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert document.read_text(encoding="utf-8") == original
    output = capsys.readouterr().out
    assert f"--- {document}" in output
    assert "1 file(s) would change" in output


@pytest.mark.integration
def test_cli_normalize_blank_lines_absent_from_check_verb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Under the subcommand redesign (docs/roadmap.rst, "Subcommands:
    flag-soup incompatibilities become verbs"), --normalize-blank-lines only
    exists on fix's/diff's own parser — check simply doesn't define it, so
    this is now an ordinary argparse "unrecognized argument" (exit 2), not
    this project's own logic to pin a message for."""
    document = tmp_path / "test.rst"
    document.write_text("Alpha.\n\n\nBeta.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--normalize-blank-lines", str(document)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2


@pytest.mark.integration
@pytest.mark.parametrize("verb", ["fix", "diff"])
def test_cli_normalize_blank_lines_rejected_under_fast(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    verb: str,
) -> None:
    document = tmp_path / "test.rst"
    document.write_text("Alpha.\n\n\nBeta.\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", verb, "--fast", "--normalize-blank-lines", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert f"{verb} --fast is self-contained" in capsys.readouterr().out


@pytest.mark.unit
def test_collapse_title_spaces_changes_only_visible_title_text(tmp_path: Path) -> None:
    before = (
        "###############################\n"
        "Title  outside ``two  spaces``\n"
        "###############################\n\n"
        "Paragraph  remains.\n"
    )
    expected = before.replace("Title  outside", "Title outside")
    path = tmp_path / "title.rst"
    before_doc = _helpers._parse_rst(path, text=before)

    normalized, counts = _formatting._normalize_text_spaces(
        path,
        before,
        collapse_titles=True,
        single_space_prose=False,
    )

    after_doc = _helpers._parse_rst(path, text=normalized)
    assert normalized == expected
    assert counts.title_runs == 1
    assert counts.prose_runs == 0
    assert "``two  spaces``" in normalized
    assert "Paragraph  remains." in normalized
    assert [section["ids"] for section in before_doc.findall(docutils.nodes.section)] == [
        section["ids"] for section in after_doc.findall(docutils.nodes.section)
    ]


@pytest.mark.unit
def test_collapse_title_spaces_is_a_fixed_point_and_leaves_prose_only_document(
    tmp_path: Path,
) -> None:
    source = "Alpha.  Beta.\n"
    path = tmp_path / "prose-only.rst"

    normalized, counts = _formatting._normalize_text_spaces(
        path,
        source,
        collapse_titles=True,
        single_space_prose=False,
    )

    assert normalized == source
    assert counts.title_runs == 0
    assert counts.prose_runs == 0


@pytest.mark.integration
def test_cli_collapse_title_spaces_is_opt_in_and_resizes_adornments(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    original = "#############\nTitle  text\n#############\n\nBody.\n"
    document.write_text(original, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", str(document)])
    with pytest.raises(SystemExit):
        cli.main()
    assert document.read_text(encoding="utf-8") == original

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "fix", "--collapse-title-spaces", str(document)],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert document.read_text(encoding="utf-8") == "############\nTitle text\n############\n\nBody.\n"
    assert "1 title space run collapsed" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_collapse_title_spaces_absent_from_check_verb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """See test_cli_normalize_blank_lines_absent_from_check_verb: same
    structural elimination, --collapse-title-spaces only exists on fix's/
    diff's own parser now."""
    document = tmp_path / "test.rst"
    document.write_text("Title  text\n===========\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--collapse-title-spaces", str(document)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2


@pytest.mark.integration
@pytest.mark.parametrize("verb", ["fix", "diff"])
def test_cli_collapse_title_spaces_rejected_under_fast(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    verb: str,
) -> None:
    document = tmp_path / "test.rst"
    document.write_text("Title  text\n===========\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", verb, "--fast", "--collapse-title-spaces", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert f"{verb} --fast is self-contained" in capsys.readouterr().out


@pytest.mark.unit
def test_single_space_prose_accepts_only_accounted_visible_text_deltas(
    tmp_path: Path,
) -> None:
    before = (
        "#############\nTitle  text\n#############\n\n"
        "Alpha.  Beta with *two  words*, ``fixed  text``, "
        ":math:`x  + y`, and `link  label <https://example.test/a>`_.\n\n"
        "*  item  prose\n\n"
        "Max  20 h 01\n\n"
        "Example::\n\n"
        "   fixed  columns\n\n"
        ".. raw:: html\n\n"
        "   <span>raw  payload</span>\n\n"
        "=====  =====\n"
        "A      B\n"
        "=====  =====\n"
    )
    expected = (
        "#############\nTitle  text\n#############\n\n"
        "Alpha. Beta with *two words*, ``fixed  text``, "
        ":math:`x  + y`, and `link label <https://example.test/a>`_.\n\n"
        "*  item prose\n\n"
        "Max 20 h 01\n\n"
        "Example::\n\n"
        "   fixed  columns\n\n"
        ".. raw:: html\n\n"
        "   <span>raw  payload</span>\n\n"
        "=====  =====\n"
        "A      B\n"
        "=====  =====\n"
    )
    path = tmp_path / "prose.rst"

    normalized, counts = _formatting._normalize_text_spaces(
        path,
        before,
        collapse_titles=False,
        single_space_prose=True,
    )

    assert normalized == expected
    assert counts.title_runs == 0
    assert counts.prose_runs == 5
    assert _formatting._normalize_text_spaces(
        path,
        normalized,
        collapse_titles=False,
        single_space_prose=True,
    ) == (normalized, _types.TextSpaceCounts())


@pytest.mark.unit
def test_single_space_prose_preserves_tabs_unicode_spaces_and_title_scope(
    tmp_path: Path,
) -> None:
    source = (
        "#############\nTitle  text\n#############\n\n"
        "Tab\tseparated; non-breaking\u00a0\u00a0spaces; ordinary  prose.\n"
    )

    normalized, counts = _formatting._normalize_text_spaces(
        tmp_path / "characters.rst",
        source,
        collapse_titles=False,
        single_space_prose=True,
    )

    assert normalized == source.replace("ordinary  prose", "ordinary prose")
    assert counts == _types.TextSpaceCounts(prose_runs=1)


@pytest.mark.unit
def test_title_and_prose_space_options_compose_with_separate_counts(
    tmp_path: Path,
) -> None:
    source = "#############\nTitle  text\n#############\n\nAlpha.  Beta.\n"

    normalized, counts = _formatting._normalize_text_spaces(
        tmp_path / "combined.rst",
        source,
        collapse_titles=True,
        single_space_prose=True,
    )

    assert normalized == source.replace("Title  text", "Title text").replace("Alpha.  Beta", "Alpha. Beta")
    assert counts == _types.TextSpaceCounts(title_runs=1, prose_runs=1)


@pytest.mark.integration
def test_cli_single_space_prose_is_opt_in_and_preserves_literal_payload(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    original = "##########\nDocument\n##########\n\nAlpha.  Beta with ``fixed  text``.\n"
    document.write_text(original, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", str(document)])
    with pytest.raises(SystemExit):
        cli.main()
    assert document.read_text(encoding="utf-8") == original

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "fix", "--single-space-prose", str(document)],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert document.read_text(encoding="utf-8") == original.replace("Alpha.  Beta", "Alpha. Beta")
    assert "1 prose space run collapsed" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_editorial_space_options_compose_in_diff_without_writing(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    original = "#############\nTitle  text\n#############\n\nAlpha.  Beta.\n"
    document.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "diff",
            "--collapse-title-spaces",
            "--single-space-prose",
            str(document),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert document.read_text(encoding="utf-8") == original
    output = capsys.readouterr().out
    assert "-Title  text" in output
    assert "+Title text" in output
    assert "-Alpha.  Beta." in output
    assert "+Alpha. Beta." in output


@pytest.mark.integration
def test_cli_single_space_prose_absent_from_check_verb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """See test_cli_normalize_blank_lines_absent_from_check_verb: same
    structural elimination, --single-space-prose only exists on fix's/
    diff's own parser now."""
    document = tmp_path / "test.rst"
    document.write_text("Alpha.  Beta.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--single-space-prose", str(document)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2


@pytest.mark.integration
@pytest.mark.parametrize("verb", ["fix", "diff"])
def test_cli_single_space_prose_rejected_under_fast(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    verb: str,
) -> None:
    document = tmp_path / "test.rst"
    document.write_text("Alpha.  Beta.\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", verb, "--fast", "--single-space-prose", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert f"{verb} --fast is self-contained" in capsys.readouterr().out


@pytest.mark.integration
def test_fix_bom_and_hygiene_then_adornments_no_duplicate_overline(
    tmp_path: Path,
) -> None:
    """End-to-end fix order: hygiene first, then adornments — the result is a
    single valid block, not the historical corrupted double-overline."""
    p = tmp_path / "bom_fix.rst"
    p.write_bytes(b"\xef\xbb\xbf#########\n Title A \n#########\n\nText.\n")

    _formatting.fix_hygiene(p)
    _formatting.fix_structure(p, True)

    assert p.read_bytes() == b"#########\nTitle A\n#########\n\nText.\n"
    assert _formatting.check_hygiene(p) == []
    assert _formatting.check_adornments(p, whole_file=True) == []


@pytest.mark.integration
def test_cli_hygiene_error_reported_and_exit_1(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A CRLF file fails the default check loudly (exit 1, CRLF named), and
    --skip-fixable suppresses it (hygiene findings are all --fix-able)."""
    p = rst_repo / "test.rst"
    p.write_bytes(b"#######\r\nTitle\r\n#######\r\n\r\nText.\r\n")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "CRLF" in out

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--skip-fixable", str(p)])
    with pytest.raises(SystemExit) as exc2:
        cli.main()
    assert exc2.value.code == 0
    out2 = capsys.readouterr().out
    assert "CRLF" not in out2


@pytest.mark.integration
def test_cli_fix_resolves_hygiene_and_recheck_is_clean(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--fix on a BOM + CRLF file with a real adornment error repairs
    everything in one pass; the re-check exits 0 on a LF-only, BOM-free file."""
    p = rst_repo / "test.rst"
    p.write_bytes(b"\xef\xbb\xbf#########\r\n Title A \r\n#####\r\n\r\nText.\r\n")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "hygiene fix applied" in out

    raw = p.read_bytes()
    assert b"\r" not in raw
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw == b"#########\nTitle A\n#########\n\nText.\n"

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as exc2:
        cli.main()
    assert exc2.value.code == 0


@pytest.mark.integration
def test_cli_diff_previews_hygiene_changes(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--diff must show Phase 0 edits, not merely count the affected file."""
    p = rst_repo / "test.rst"
    p.write_bytes(b"####### \nTitle\n#######\n\nText.\n")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "diff", str(p)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    out = capsys.readouterr().out
    assert exc.value.code == 1
    assert f"--- {p}" in out
    assert f"+++ {p}" in out
    assert "-####### \n" in out
    assert "+#######\n" in out
