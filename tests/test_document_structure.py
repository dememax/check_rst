# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Document structure discovery and outline tests — check_rst project

from __future__ import annotations

import json
import textwrap
from typing import TYPE_CHECKING

import docutils.nodes
import pytest
from _support import _GOOD_BLOCK, _rst

from check_rst import cli
from check_rst.cli import _document, _formatting, _sphinx

if TYPE_CHECKING:
    from pathlib import Path

    from _support import BuildSphinxEnv


@pytest.mark.integration
def test_outline_overline_underline_title(tmp_path: Path) -> None:
    """A top-level overline+underline title is depth 1, char is the adornment used."""
    p = _rst(
        tmp_path,
        """\
        #######
        Root
        #######

        Some text.
        """,
    )
    entries = _document.build_outline(p)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.lineno == 2
    assert entry.depth == 1
    assert entry.char == "#"
    assert entry.title == "Root"


@pytest.mark.integration
def test_outline_nested_nesting_depth(tmp_path: Path) -> None:
    """Depth reflects this document's own nesting order, not the project's
    canonical hierarchy position of the adornment character."""
    p = _rst(
        tmp_path,
        """\
        Abc
        ***

        Some text.

        Xyz
        ===

        Another text.
        """,
    )
    entries = _document.build_outline(p)
    assert [(e.lineno, e.depth, e.char, e.title) for e in entries] == [
        (1, 1, "*", "Abc"),
        (6, 2, "=", "Xyz"),
    ]


@pytest.mark.integration
def test_bare_outline_exposes_include_boundary_and_foreign_blocks(tmp_path: Path) -> None:
    """Bare Docutils mode uses the same physical ownership model as Sphinx."""
    root = tmp_path / "index.rst"
    root.write_text("Index\n=====\n\n.. include:: fragment.rst\n", encoding="utf-8")
    (tmp_path / "fragment.rst").write_text(
        "Included\n--------\n\n.. note:: Included note.\n",
        encoding="utf-8",
    )
    document = _document.Document(root, tmp_path)

    included = next(entry for entry in document.outline if entry.title == "Included")
    assert included.provenance is not None
    assert included.provenance.source == "fragment.rst"
    assert str(document.includes[0]) == '    4: include "fragment.rst" (parsed)'
    assert str(document.admonitions[0]).lstrip().startswith("fragment.rst:4: admonition")
    assert document.comments == []  # the invisible include marker is not author content


@pytest.mark.integration
def test_outline_sibling_depth_resets_after_nested_child(tmp_path: Path) -> None:
    """A sibling section after a nested child must return to the parent's depth."""
    p = _rst(
        tmp_path,
        """\
        Chapter One
        ===========

        Some text.

        Sub A
        -----

        More.

        Chapter Two
        ===========

        Other text.
        """,
    )
    entries = _document.build_outline(p)
    assert [(e.depth, e.title) for e in entries] == [
        (1, "Chapter One"),
        (2, "Sub A"),
        (1, "Chapter Two"),
    ]


@pytest.mark.integration
def test_outline_empty_for_file_with_no_sections(tmp_path: Path) -> None:
    """A file with no section titles at all returns an empty outline."""
    p = _rst(tmp_path, "Just a plain paragraph, no headings.\n")
    assert _document.build_outline(p) == []


@pytest.mark.integration
def test_outline_str_format(tmp_path: Path) -> None:
    """str() of an entry matches the documented '{line}: Level {depth} (char): {title}' shape."""
    p = _rst(
        tmp_path,
        """\
        Abc
        ***

        Some text.

        Xyz
        ===

        Another text.
        """,
    )
    entries = _document.build_outline(p)
    # Lean format: line range, adornment char, title — depth is the
    # indentation (4 spaces per level); the char was omitted 2026-07-18
    # ("lives in the legend, not on every entry"), reversed 2026-07-20
    # after repeated real mistakes picking the wrong char for a new
    # heading — every entry now states its own char directly.
    assert str(entries[0]) == "1-9:* Abc [1 subsection]"
    assert str(entries[1]) == "    6-9:= Xyz"


@pytest.mark.integration
def test_outline_non_preferred_char_shown_not_placeholder(tmp_path: Path) -> None:
    """A heading using a valid-but-non-preferred adornment char (e.g. '~')
    now shows the real character, not the old '?' placeholder — this is
    the original real-corpus finding (downstream-project/docs/product-gui/
    product-yocto-readme.rst uses '~' as a heading underline) that this
    whole widened-recognition change exists to fix."""
    p = _rst(
        tmp_path,
        """\
        Title
        ~~~~~

        Some text.
        """,
    )
    entries = _document.build_outline(p)
    assert len(entries) == 1
    assert entries[0].char == "~"


@pytest.mark.integration
def test_code_blocks_language_and_no_language(
    build_sphinx_env: BuildSphinxEnv,
) -> None:
    """A code-block with a language and one without a-language-but-with-a-
    Sphinx-only-option (:caption:) are both found — the second is exactly
    the case that motivated this whole phase: bare docutils silently misses
    it, a real Sphinx env resolves it to the project's default highlight
    language instead of crashing or vanishing."""
    env, docname = build_sphinx_env(
        """\
        Title
        =====

        .. code-block::
           :caption: Adding code block sample

           commit 61e2bee8fd
           Author: X

        .. code-block:: bash

           echo hi
        """
    )
    entries = _sphinx.find_code_blocks(env, docname)
    assert [e.language for e in entries] == ["default", "bash"]


@pytest.mark.integration
def test_code_blocks_plain_literal_and_parsed_literal_excluded(
    build_sphinx_env: BuildSphinxEnv,
) -> None:
    """A plain '::' literal block and '.. parsed-literal::' are not code-blocks."""
    env, docname = build_sphinx_env(
        """\
        Title
        =====

        A plain literal block::

           just literal text, not a directive

        .. parsed-literal::

           *parsed* literal
        """
    )
    assert _sphinx.find_code_blocks(env, docname) == []


@pytest.mark.integration
def test_code_blocks_depth_matches_enclosing_section(
    build_sphinx_env: BuildSphinxEnv,
) -> None:
    """A code-block's depth is one level deeper than the section it's inside."""
    env, docname = build_sphinx_env(
        """\
        Chapter One
        ===========

        Sub A
        -----

        .. code-block:: python

           pass
        """
    )
    entries = _sphinx.find_code_blocks(env, docname)
    assert len(entries) == 1
    assert entries[0].depth == 3  # Chapter One=1, Sub A=2, code-block=3


@pytest.mark.integration
def test_code_blocks_nested_fake_marker_not_double_counted(
    build_sphinx_env: BuildSphinxEnv,
) -> None:
    """A '.. code-block::' line quoted as example text inside a real
    code-block must not be counted as a second, separate entry — Sphinx
    never re-parses literal content, so this must stay at exactly one."""
    env, docname = build_sphinx_env(
        """\
        Title
        =====

        .. code-block:: rst

           .. code-block:: python

              print("hi")

        Text after.
        """
    )
    entries = _sphinx.find_code_blocks(env, docname)
    assert len(entries) == 1
    assert entries[0].language == "rst"


@pytest.mark.integration
def test_code_blocks_with_linenos_option_still_found(
    build_sphinx_env: BuildSphinxEnv,
) -> None:
    """A code-block carrying a Sphinx-only option (:linenos:) alongside an
    explicit language is still detected — no crash, no silent miss."""
    env, docname = build_sphinx_env(
        """\
        Title
        =====

        .. code-block:: python
           :linenos:

           pass
        """
    )
    entries = _sphinx.find_code_blocks(env, docname)
    assert len(entries) == 1
    assert entries[0].language == "python"


@pytest.mark.integration
def test_code_blocks_str_format(
    build_sphinx_env: BuildSphinxEnv,
) -> None:
    """str() matches the documented '{line}: code-block (lang): preview' shape."""
    env, docname = build_sphinx_env(
        """\
        Title
        =====

        .. code-block:: bash

           echo hi
        """
    )
    entries = _sphinx.find_code_blocks(env, docname)
    assert str(entries[0]) == "    4: code-block (bash): echo hi"


@pytest.mark.integration
def test_code_blocks_preview_whitespace_collapsed(
    build_sphinx_env: BuildSphinxEnv,
) -> None:
    """The real (Sphinx AST) detector's preview collapses multi-line content
    to one space-joined line, same contract as the heuristic detector."""
    env, docname = build_sphinx_env(
        """\
        Title
        =====

        .. code-block:: python

           x = 1
           y   =    2
        """
    )
    entries = _sphinx.find_code_blocks(env, docname)
    assert entries[0].preview == "x = 1 y = 2"


@pytest.mark.integration
def test_heuristic_code_blocks_short_alias_code_detected(tmp_path: Path) -> None:
    """'.. code::' (the short alias) must be detected, not just the long
    '.. code-block::' form — confirmed by direct testing that a real Sphinx
    env treats both identically (same 'language' attribute on the node),
    and that a real project (downstream-project/docs) uses '.. code::'
    exclusively: the original regex matched 0 of 75 real code-blocks
    there because it only recognized the long form."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. code:: bash

           echo hi
        """,
    )
    entries = _document.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].language == "bash"


@pytest.mark.integration
def test_heuristic_code_blocks_sourcecode_alias_detected(tmp_path: Path) -> None:
    """'.. sourcecode::' is a third alias Sphinx treats identically to
    'code-block' (confirmed by direct testing) and must also be detected."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. sourcecode:: python

           print("hi")
        """,
    )
    entries = _document.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].language == "python"


@pytest.mark.integration
def test_heuristic_code_blocks_language_and_bare(tmp_path: Path) -> None:
    """A code-block with a language and a bare one (no language, no options)
    are both found, in order. language is None for the bare one — heuristic
    mode has no conf.py to resolve a default highlight_language against, and
    must not pretend to know one."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. code-block:: bash

           echo hi

        .. code-block::

           no language here
        """,
    )
    entries = _document.find_code_blocks_heuristic(p)
    assert [e.language for e in entries] == ["bash", None]


@pytest.mark.integration
def test_heuristic_code_blocks_with_caption_no_language_still_found(
    tmp_path: Path,
) -> None:
    """A code-block with a Sphinx-only option (:caption:) and no language —
    the exact case bare docutils silently drops entirely — is still found:
    this is the whole reason the heuristic exists."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. code-block::
           :caption: Adding code block sample

           commit 61e2bee8fd
           Author: X
        """,
    )
    entries = _document.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].language is None


@pytest.mark.integration
def test_heuristic_code_blocks_with_linenos_option_still_found(tmp_path: Path) -> None:
    """A code-block carrying :linenos: alongside an explicit language is
    still found and its language is still read correctly."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. code-block:: python
           :linenos:

           pass
        """,
    )
    entries = _document.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].language == "python"


@pytest.mark.integration
def test_heuristic_code_blocks_plain_literal_and_parsed_literal_excluded(
    tmp_path: Path,
) -> None:
    """A plain '::' literal block and '.. parsed-literal::' don't match the
    '.. code-block::' marker at all, so they're excluded same as before."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        A plain literal block::

           just literal text, not a directive

        .. parsed-literal::

           *parsed* literal
        """,
    )
    assert _document.find_code_blocks_heuristic(p) == []


@pytest.mark.integration
def test_heuristic_code_blocks_depth_from_build_outline(tmp_path: Path) -> None:
    """depth comes from the nearest preceding heading in build_outline, one
    level deeper — same convention as the real Sphinx-based detector."""
    p = _rst(
        tmp_path,
        """\
        Chapter One
        ===========

        Sub A
        -----

        .. code-block:: python

           pass
        """,
    )
    entries = _document.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].depth == 3  # Chapter One=1, Sub A=2, code-block=3


@pytest.mark.integration
def test_heuristic_code_blocks_no_preceding_heading_is_depth_1(tmp_path: Path) -> None:
    """A code-block with no heading above it at all is depth 1 (top-level)."""
    p = _rst(
        tmp_path,
        """\
        .. code-block:: bash

           echo hi
        """,
    )
    entries = _document.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].depth == 1


@pytest.mark.integration
def test_heuristic_code_blocks_nested_fake_marker_is_double_counted(
    tmp_path: Path,
) -> None:
    """KNOWN, ACCEPTED limitation: a '.. code-block::' quoted as example text
    inside another real code-block IS double-counted — there is no AST here
    to guard against it, unlike the real Sphinx-based find_code_blocks. This
    test documents the limitation as a deliberate, reviewed trade-off, not a
    bug to silently fix later without noticing the behavior changed."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. code-block:: rst

           .. code-block:: python

              print("hi")

        Text after.
        """,
    )
    entries = _document.find_code_blocks_heuristic(p)
    assert len(entries) == 2
    assert [e.language for e in entries] == ["rst", "python"]


@pytest.mark.integration
def test_heuristic_code_blocks_str_format(tmp_path: Path) -> None:
    """str() matches the same '{range}: code-block (lang): preview' shape as the real detector."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. code-block:: bash

           echo hi
        """,
    )
    entries = _document.find_code_blocks_heuristic(p)
    assert str(entries[0]) == "    4-6: code-block (bash): echo hi"


@pytest.mark.integration
def test_heuristic_code_block_preview_skips_options_and_blank_separator(
    tmp_path: Path,
) -> None:
    """The preview is the block's own CONTENT — the directive's ':caption:'
    option line and the blank separator before the code starts are never
    mistaken for content (Max, 2026-07-20)."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. code-block:: bash
           :caption: Example
           :linenos:

           echo hi
        """,
    )
    entries = _document.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].preview == "echo hi"
    assert "Example" not in entries[0].preview


@pytest.mark.integration
def test_heuristic_code_block_preview_whitespace_collapsed(tmp_path: Path) -> None:
    """Leading/trailing indentation and internal multi-space/multi-line gaps
    all collapse to single spaces — cut unnecessary spaces before output
    (Max, 2026-07-20)."""
    p = _rst(
        tmp_path,
        "Title\n=====\n\n.. code-block:: python\n\n    x = 1\n\n    y   =    2\n",
    )
    entries = _document.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].preview == "x = 1 y = 2"


@pytest.mark.integration
def test_heuristic_code_block_preview_truncated(tmp_path: Path) -> None:
    """The preview is bounded at 74 chars, truncated with '...' — a quick
    identity, not the block's full content."""
    long_line = "x = 1  # " + "word " * 20
    p = _rst(tmp_path, f"Title\n=====\n\n.. code-block:: python\n\n    {long_line}\n")
    entries = _document.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].preview.endswith("...")
    assert len(entries[0].preview) <= 77


@pytest.mark.integration
def test_adornments_dot_comment_pair_not_title(tmp_path: Path) -> None:
    """Regression: two '..' comment lines around an indented note matched the
    over/title/under shape ('.' is a valid adornment char) and --fix rewrote
    the comment into a dotted section title — a destructive content change.
    docutils parses '..' as a comment marker, never a title adornment."""
    p = _rst(
        tmp_path,
        """\
        ##########
         Chapter
        ##########

        ..
           internal note, not for output
        ..

        Real text.
        """,
    )
    violations = _formatting.check_adornments(p, whole_file=True)
    assert not any("internal note" in v for v in violations)

    # The title block above the comment is deliberately broken, so a diff
    # exists — but the comment itself must only ever appear as unchanged
    # context, never on a +/- line, and no dotted adornment may be added.
    diff = _formatting.diff_structure(p, True)
    changed = [
        line for line in diff.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    assert not any("internal note" in line for line in changed)
    assert not any(set(line[1:]) == {"."} for line in changed)


@pytest.mark.integration
def test_fix_dot_comment_pair_unchanged(tmp_path: Path) -> None:
    """--fix must leave a '..' comment block byte-identical."""
    content = textwrap.dedent("""\
        #########
        Chapter
        #########

        ..
           internal note, not for output
        ..

        Real text.
        """)
    p = tmp_path / "comments.rst"
    p.write_text(content, encoding="utf-8")

    assert _formatting.fix_structure(p, True) is False
    assert p.read_text(encoding="utf-8") == content


@pytest.mark.integration
def test_outline_children_counts(tmp_path: Path) -> None:
    """Every heading reports its number of DIRECT subsections."""
    p = _rst(
        tmp_path,
        """\
        Root
        ####

        Sub A
        *****

        Leaf A1
        =======

        Sub B
        *****
        """,
    )
    entries = _document.build_outline(p)
    assert [(e.title, e.children) for e in entries] == [
        ("Root", 2),
        ("Sub A", 1),
        ("Leaf A1", 0),
        ("Sub B", 0),
    ]


@pytest.mark.integration
def test_outline_str_shows_subsection_count(tmp_path: Path) -> None:
    """str() appends '[N subsection(s)]' for parents; leaves stay unchanged
    — zero-children entries keep the exact historical format."""
    p = _rst(
        tmp_path,
        """\
        Root
        ####

        Sub A
        *****

        Sub B
        *****
        """,
    )
    entries = _document.build_outline(p)
    assert str(entries[0]) == "1-8:# Root [2 subsections]"
    assert str(entries[1]) == "    4-5:* Sub A"  # trailing blank trimmed


@pytest.mark.integration
def test_cli_outline_depth_limits_levels(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--outline-depth N hides deeper headings and reports how many were
    hidden — bounded output, never silent truncation."""
    p = rst_repo / "test.rst"
    p.write_text(
        "Root\n####\n\nSub\n***\n\nDeep\n====\n\nDeeper\n------\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "outline", "--with-findings", "--outline-depth", "2", str(p)],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "Root" in out
    assert "Sub" in out
    # The legend always describes the WHOLE document (Max: "output all
    # information, it's not heavy") — under a depth limit it reveals what
    # exists below the cut, composing with the hidden-entries note; only
    # the entries themselves are trimmed.
    assert "levels: 1 '#' (1), 2 '*' (1), 3 '=' (1), 4 '-' (1)" in out
    assert "Deep" not in out.replace("Deeper", "").replace("deeper", "")
    assert "Deeper" not in out
    assert "2 deeper entries hidden" in out


@pytest.mark.integration
def test_cli_outline_depth_hides_deep_code_blocks(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The depth limit applies to code-block entries too — they carry the
    same nesting depth as headings.  Runs with --quiet (composition of the
    two flags), which also keeps the Phase 2 banner's own 'code-block'
    wording out of the assertion's way."""
    p = rst_repo / "test.rst"
    p.write_text(
        "Root\n####\n\nSub\n***\n\n.. code-block:: python\n\n    x = 1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "outline",
            "--with-findings",
            "--quiet",
            "--outline-depth",
            "2",
            str(p),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "Sub" in out
    assert "code-block" not in out
    assert "1 deeper entry hidden" in out


@pytest.mark.integration
def test_cli_outline_legend_line_replaces_per_entry_level_info(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The depth-to-char mapping is per-document constant (docutils fixes a
    char's level at first appearance), so --outline states it ONCE in a
    legend line instead of repeating 'Level N (c)' on every entry (Max,
    2026-07-18: 'too many Level N').  Depth stays recoverable from a lone
    grepped line via its indentation — 4 spaces per level.  The char
    itself, however, IS repeated on every entry again since 2026-07-20
    (reversed: picking the right char for a NEW heading needs it directly,
    not cross-referenced against the legend) — this test's name predates
    that reversal but still pins the legend's own dedup, which stands."""
    p = rst_repo / "test.rst"
    p.write_text(
        "Root\n####\n\nSub A\n*****\n\nDeep\n====\n\nSub B\n*****\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", "--quiet", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "levels: 1 '#' (1), 2 '*' (2), 3 '=' (1)" in out
    assert "Level" not in out.replace("levels:", "")
    assert "  1-11:# Root [2 subsections]" in out
    assert "      4-8:* Sub A [1 subsection]" in out
    assert "          7-8:= Deep" in out


@pytest.mark.integration
def test_cli_outline_legend_shows_total_sections(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The levels legend also states the document's total section count —
    a plain sum of the per-level counts, so a reader doesn't have to add
    '1 + 2 + 1' by hand (Max, 2026-07-20)."""
    p = rst_repo / "test.rst"
    p.write_text(
        "Root\n####\n\nSub A\n*****\n\nDeep\n====\n\nSub B\n*****\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", "--quiet", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "levels: 1 '#' (1), 2 '*' (2), 3 '=' (1), 4 sections total" in out


@pytest.mark.integration
def test_cli_outline_blocks_summary_line(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Apart from levels (sections), --outline also reports the document's
    total code-block and blockquote counts (Max, 2026-07-20) — a single
    summary line, singular/plural worded, shown only when either exists."""
    p = rst_repo / "test.rst"
    p.write_text(
        "Root\n####\n\n"
        ".. code-block:: bash\n\n   echo one\n\n"
        ".. code-block:: bash\n\n   echo two\n\n"
        "He wrote:\n\n    Quoted line.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "outline", "--with-findings", "--quiet", "--verbose", str(p)],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "blocks: 2 code blocks, 1 blockquote" in out


@pytest.mark.integration
def test_cli_outline_blocks_summary_absent_without_blocks(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No code-blocks or blockquotes anywhere: the 'blocks:' line is
    omitted entirely, matching the 'levels:' line's own guard when there
    are no sections."""
    p = rst_repo / "test.rst"
    p.write_text("Root\n####\n\nJust a plain paragraph.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", "--quiet", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "blocks:" not in out


@pytest.mark.integration
def test_cli_outline_section_bracket_shows_cumulative_code_and_quote_counts(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A section's bracket note counts code-blocks/blockquotes CUMULATIVELY
    — everything in its line range, including its subsections' own content
    (Max, 2026-07-20: chose whole-subtree totals over direct-children-only).
    Root's own text has none directly, but its subsection's code-block and
    blockquote roll up into Root's count."""
    p = rst_repo / "test.rst"
    p.write_text(
        "Root\n####\n\nSub\n***\n\n.. code-block:: bash\n\n   echo hi\n\nHe wrote:\n\n    Quoted line.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", "--quiet", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    root_line = next(ln for ln in out.splitlines() if "Root" in ln)
    sub_line = next(ln for ln in out.splitlines() if "Sub" in ln and "Root" not in ln)
    assert "[1 subsection, 1 code block, 1 blockquote]" in root_line
    assert "[1 code block, 1 blockquote]" in sub_line


@pytest.mark.integration
def test_block_quotes_found_with_preview_and_depth(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        Intro paragraph.

            **The Parsing Bug** — quoted answer.

        Sub
        ---

        He wrote:

            Short quote.
        """,
    )
    entries = _document.find_block_quotes(p)
    assert [(e.lineno, e.depth) for e in entries] == [(6, 2), (13, 3)]
    assert entries[0].preview.startswith("The Parsing Bug")
    assert entries[1].preview == "Short quote."


@pytest.mark.integration
def test_block_quotes_no_preceding_heading_is_depth_1(tmp_path: Path) -> None:
    """A blockquote with no enclosing section at all is depth 1 (top-level),
    same convention as test_heuristic_code_blocks_no_preceding_heading_is_depth_1."""
    p = _rst(
        tmp_path,
        """\
        Intro paragraph, no title above it at all.

            A quote with no enclosing section.
        """,
    )
    entries = _document.find_block_quotes(p)
    assert len(entries) == 1
    assert entries[0].depth == 1


@pytest.mark.integration
def test_block_quote_preview_truncated(tmp_path: Path) -> None:
    """The preview is a LIMITED beginning — one collapsed line, truncated
    with '...' — a quick identity, not the quote's content."""
    long_text = "word " * 40
    p = _rst(tmp_path, f"Intro.\n\n    {long_text}\n")
    entries = _document.find_block_quotes(p)
    assert len(entries) == 1
    assert entries[0].preview.endswith("...")
    assert len(entries[0].preview) <= 77


@pytest.mark.integration
def test_block_quote_str_format(tmp_path: Path) -> None:
    p = _rst(tmp_path, "Intro.\n\n    Quoted line.\n")
    entries = _document.find_block_quotes(p)
    assert str(entries[0]) == '3: blockquote "Quoted line."'


@pytest.mark.integration
def test_block_quote_nested_quote_single_entry(tmp_path: Path) -> None:
    """A quote within a quote reports once — the outer entry's preview
    already covers the subtree; a second entry would double-count."""
    p = _rst(tmp_path, "Intro.\n\n    Outer quote.\n\n        Inner quote.\n")
    entries = _document.find_block_quotes(p)
    assert len(entries) == 1
    assert entries[0].preview.startswith("Outer quote.")


@pytest.mark.integration
def test_block_quote_in_literal_block_not_reported(tmp_path: Path) -> None:
    """Indented text inside a real code-block is literal content, never
    parsed as a blockquote — automatic, pinned."""
    p = _rst(tmp_path, ".. code:: text\n\n    looks like\n\n        a quote\n")
    assert _document.find_block_quotes(p) == []


@pytest.mark.integration
def test_cli_outline_includes_blockquotes_in_order(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\nHe wrote:\n\n    Quoted answer text.\n\nAfter.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", "--quiet", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert 'blockquote "Quoted answer text."' in out
    assert out.index("2-9:# Title") < out.index('blockquote "Quoted answer text."')


@pytest.mark.integration
def test_cli_outline_depth_trims_blockquotes_too(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\nSub\n***\n\n    Deep quote.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "outline",
            "--with-findings",
            "--quiet",
            "--outline-depth",
            "2",
            str(p),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    # The aggregate legend and the parent section's cumulative bracket both
    # legitimately still mention "blockquote" (Max: totals are never hidden
    # by --outline-depth) — what must actually be absent is the entry
    # ITSELF, i.e. its quoted content.
    assert "Deep quote" not in out
    assert "1 deeper entry hidden" in out


@pytest.mark.integration
def test_cli_outline_only_pure_structure_with_honest_footer(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--outline-only shows outline + footer, nothing else — but it is a
    DISPLAY filter under the 'trims display, never information' contract:
    findings are still counted in the footer and the exit code stays
    honest."""
    p = rst_repo / "test.rst"
    p.write_text(
        "Title\n#####\n\n**Bold Heading**\n\nHe wrote:\n\n    Quoted.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1  # the underline-only ERROR still counts
    out = capsys.readouterr().out
    assert "Outline:" in out
    assert "levels: 1 '#'" in out
    assert 'blockquote "Quoted."' in out
    assert "✗" not in out
    assert "⚠" not in out
    assert "Phase 1" not in out
    assert "1 error(s), 1 warning(s)" in out  # footer keeps the truth


@pytest.mark.integration
def test_cli_outline_only_implies_outline_and_quiet(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No need to also pass --outline or --quiet — one flag is the point."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Outline:" in out
    assert "4-7:# Title" in out  # heading entry with extent (_GOOD_BLOCK)
    assert "Phase 2" not in out


@pytest.mark.integration
def test_cli_outline_only_composes_with_outline_depth(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text("Root\n####\n\nSub\n***\n\nDeep\n====\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "outline", "--outline-depth", "2", str(p)],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "levels: 1 '#' (1), 2 '*' (1), 3 '=' (1)" in out
    assert "Deep" not in out
    assert "1 deeper entry hidden" in out


@pytest.mark.integration
def test_admonitions_named_kind_no_title(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. important::

           If you read nothing else: check the outline first.
        """,
    )
    entries = _document.find_admonitions(p)
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == "important"
    assert e.title is None
    assert e.preview == "If you read nothing else: check the outline first."
    assert e.lineno == 4  # the directive's own line


@pytest.mark.integration
def test_admonitions_generic_form_carries_a_title(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. admonition:: Custom Title

           Body text, custom kind.
        """,
    )
    entries = _document.find_admonitions(p)
    assert len(entries) == 1
    assert entries[0].kind == "admonition"
    assert entries[0].title == "Custom Title"
    assert entries[0].preview == "Body text, custom kind."


@pytest.mark.integration
def test_admonitions_all_ten_kinds_recognized(tmp_path: Path) -> None:
    kinds = [
        "attention",
        "caution",
        "danger",
        "error",
        "hint",
        "important",
        "note",
        "tip",
        "warning",
    ]
    body = "Title\n=====\n\n" + "\n\n".join(f".. {k}::\n\n   Body for {k}." for k in kinds)
    p = _rst(tmp_path, body)
    entries = _document.find_admonitions(p)
    assert [e.kind for e in entries] == kinds


@pytest.mark.integration
def test_admonitions_preview_collapsed_and_truncated(tmp_path: Path) -> None:
    long_body = " ".join(f"word{i}" for i in range(30))
    p = _rst(
        tmp_path,
        f"Title\n=====\n\n.. note::\n\n   {long_body}\n",
    )
    preview = _document.find_admonitions(p)[0].preview
    assert preview.endswith("...")
    assert len(preview) <= _document._OUTLINE_PREVIEW_LEN + 3


@pytest.mark.integration
def test_admonitions_depth_counts_enclosing_sections(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        Root
        ####

        Sub
        ***

        .. note::

           Nested under Sub.
        """,
    )
    e = _document.find_admonitions(p)[0]
    assert e.depth == 3  # Root=1, Sub=2, admonition=3 — same convention as tables


@pytest.mark.integration
def test_cli_outline_admonitions_counted_in_blocks_legend_and_section_brackets(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "Title\n#####\n\n.. important::\n\n   Read this.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "outline", "--with-findings", "--quiet", "--verbose", str(p)],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "blocks: 1 admonition" in out
    assert "[1 admonition]" in out  # the enclosing Title section's own bracket count
    assert "admonition (important): Read this." in out


@pytest.mark.integration
def test_cli_json_admonitions(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "Title\n#####\n\n.. admonition:: Custom\n\n   Body.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    data = json.loads(capsys.readouterr().out)
    admonitions = data["files"][0]["admonitions"]
    assert len(admonitions) == 1
    assert admonitions[0]["kind"] == "admonition"
    assert admonitions[0]["title"] == "Custom"
    assert admonitions[0]["preview"] == "Body."


@pytest.mark.integration
def test_comments_found_with_preview_and_depth(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. An ordinary comment, not a directive typo.
        """,
    )
    entries = _document.find_comments(p)
    assert len(entries) == 1
    e = entries[0]
    assert e.preview == "An ordinary comment, not a directive typo."
    assert e.lineno == 4  # the comment's own line
    assert e.depth == 2  # Title=1, comment=2
    assert e.suspicious is False


@pytest.mark.integration
def test_comments_no_preceding_heading_is_depth_1(tmp_path: Path) -> None:
    """Same top-level convention as
    test_heuristic_code_blocks_no_preceding_heading_is_depth_1 and
    test_block_quotes_no_preceding_heading_is_depth_1."""
    p = _rst(tmp_path, ".. A comment with no enclosing section at all.\n")
    entries = _document.find_comments(p)
    assert len(entries) == 1
    assert entries[0].depth == 1


@pytest.mark.integration
def test_comments_preview_collapsed_and_truncated(tmp_path: Path) -> None:
    long_body = " ".join(f"word{i}" for i in range(30))
    p = _rst(tmp_path, f"Title\n=====\n\n.. {long_body}\n")
    preview = _document.find_comments(p)[0].preview
    assert preview.endswith("...")
    assert len(preview) <= _document._OUTLINE_PREVIEW_LEN + 3


@pytest.mark.integration
def test_comments_suspicious_flag_false_for_todo_comment(tmp_path: Path) -> None:
    """'todo' is deliberately excluded from the heuristic (too common a
    genuine idiom) — the comment is still visible, just not tagged."""
    p = _rst(tmp_path, ".. TODO: fix this later\n")
    e = _document.find_comments(p)[0]
    assert e.suspicious is False
    assert "suspicious" not in str(e)


@pytest.mark.integration
def test_cli_outline_comments_counted_in_blocks_legend_and_section_brackets(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "Title\n#####\n\n.. code: bash\n\n    echo hi\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "outline", "--with-findings", "--quiet", "--verbose", str(p)],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "blocks: 1 comment" in out
    assert "[1 comment]" in out  # the enclosing Title section's own bracket count
    assert "suspicious" in out


@pytest.mark.integration
def test_cli_json_comments(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "Title\n#####\n\n.. An ordinary comment.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    data = json.loads(capsys.readouterr().out)
    comments = data["files"][0]["comments"]
    assert len(comments) == 1
    assert comments[0]["preview"] == "An ordinary comment."
    assert comments[0]["suspicious"] is False


@pytest.mark.integration
def test_lists_bullet_container_and_items(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        * First item.
        * Second item.
        * Third item.
        """,
    )
    entries = _document.find_lists(p)
    assert len(entries) == 4  # 1 container + 3 items
    container = entries[0]
    assert container.kind == "bullet"
    assert container.marker == "*"
    assert container.item_count == 3
    assert container.depth == 2
    assert container.lineno == 4
    items = entries[1:]
    assert [i.preview for i in items] == ["First item.", "Second item.", "Third item."]
    assert all(i.depth == 3 and i.item_count is None for i in items)


@pytest.mark.integration
def test_lists_bullet_marker_reflects_actual_bullet_char(tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n=====\n\n- One.\n- Two.\n")
    entries = _document.find_lists(p)
    assert all(e.marker == "-" for e in entries)


@pytest.mark.integration
def test_lists_enumerated_arabic_markers(tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n=====\n\n1. One.\n2. Two.\n3. Three.\n")
    entries = _document.find_lists(p)
    container, *items = entries
    assert container.kind == "enumerated"
    assert container.marker == "1."
    assert container.item_count == 3
    assert [i.marker for i in items] == ["1.", "2.", "3."]


@pytest.mark.integration
def test_lists_enumerated_auto_number(tmp_path: Path) -> None:
    """'#.' auto-numbering renders as plain arabic digits — docutils never
    stores '#' as the item's own marker, only enumtype='arabic'."""
    p = _rst(tmp_path, "Title\n=====\n\n#. One.\n#. Two.\n")
    entries = _document.find_lists(p)
    _container, *items = entries
    assert [i.marker for i in items] == ["1.", "2."]


@pytest.mark.integration
def test_lists_enumerated_alpha_markers(tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n=====\n\na) First.\nb) Second.\n")
    entries = _document.find_lists(p)
    _container, *items = entries
    assert [i.marker for i in items] == ["a)", "b)"]


@pytest.mark.integration
def test_lists_definition_items_standalone_no_container(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        Term One
            Definition of term one.
        Term Two
            Definition of term two.
        """,
    )
    entries = _document.find_lists(p)
    assert len(entries) == 2  # no container entry, unlike bullet/enumerated
    assert [e.kind for e in entries] == ["definition", "definition"]
    assert [e.marker for e in entries] == ["Term One", "Term Two"]
    assert [e.preview for e in entries] == [
        "Definition of term one.",
        "Definition of term two.",
    ]
    assert all(e.item_count is None for e in entries)


@pytest.mark.integration
def test_lists_nested_bullet_list_depth_increments(tmp_path: Path) -> None:
    """A sub-list nested inside an item lands one level deeper than that
    item, not merely level with the outer container (the exact bug this
    entry kind's depth formula was caught and fixed for, 2026-07-26)."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        * Outer item one.

          * Inner item A.
          * Inner item B.

        * Outer item two.
        """,
    )
    entries = _document.find_lists(p)
    by_lineno = {e.lineno: e for e in entries if e.item_count is not None}
    outer_container = by_lineno[4]
    inner_container = by_lineno[6]
    assert outer_container.depth == 2
    assert inner_container.depth == 4  # outer item (3) + 1, not outer container (2) + 1


@pytest.mark.integration
def test_lists_item_extent_includes_continuation_paragraph(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        * First item.
        * Second item.

          Continuation paragraph in second item.

        * Third.
        """,
    )
    entries = _document.find_lists(p)
    items = {e.lineno: e for e in entries if e.item_count is None}
    assert items[5].end == 7  # "Second item." through its continuation paragraph
    assert items[4].end == 4  # single-line item, no continuation


@pytest.mark.integration
def test_lists_preview_collapsed_and_truncated(tmp_path: Path) -> None:
    long_text = " ".join(f"word{i}" for i in range(30))
    p = _rst(tmp_path, f"Title\n=====\n\n* {long_text}\n")
    _container, item = _document.find_lists(p)
    assert item.preview.endswith("...")
    assert len(item.preview) <= _document._OUTLINE_PREVIEW_LEN + 3


@pytest.mark.integration
def test_cli_outline_lists_counted_in_blocks_legend_and_section_brackets(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text("Title\n#####\n\n* One.\n* Two.\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "outline", "--with-findings", "--quiet", "--verbose", str(p)],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "blocks: 1 list" in out
    assert "[1 list]" in out  # the enclosing Title section's own bracket count
    assert "bullet list ('*', 2 items)" in out


@pytest.mark.integration
def test_cli_outline_depth_hides_list_items_keeps_container(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--outline-depth trims display, never information (house rule) — the
    container (at the section's own child depth) stays visible even when
    its items (one level deeper) are hidden."""
    p = rst_repo / "test.rst"
    p.write_text("Title\n#####\n\n* One.\n* Two.\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "outline",
            "--with-findings",
            "--quiet",
            "--outline-depth",
            "2",
            str(p),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "bullet list" in out
    assert "One." not in out
    assert "deeper entr" in out  # hidden-entries note, never silent truncation


@pytest.mark.integration
def test_cli_sections_only_hides_leaf_entries_keeps_headings(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "Title\n#####\n\n* One.\n* Two.\n\n.. code-block:: python\n\n   pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "outline",
            "--with-findings",
            "--quiet",
            "--sections-only",
            str(p),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "Title" in out
    assert "bullet list" not in out
    assert "One." not in out
    assert "code-block" not in out


@pytest.mark.integration
def test_cli_sections_only_keeps_bracket_counts_and_legend(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A display filter trims display, never information: the section's own
    bracketed subtree count and the verbose blocks: legend still reflect
    the leaf entries that are no longer individually shown."""
    p = rst_repo / "test.rst"
    p.write_text("Title\n#####\n\n* One.\n* Two.\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "outline",
            "--with-findings",
            "--quiet",
            "--verbose",
            "--sections-only",
            str(p),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "[1 list]" in out
    assert "blocks: 1 list" in out


@pytest.mark.integration
def test_cli_sections_only_hidden_note_wording(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A kind-filtered entry isn't necessarily 'deeper', so the note drops
    that word specifically when --sections-only is involved."""
    p = rst_repo / "test.rst"
    p.write_text("Title\n#####\n\n* One.\n* Two.\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "outline",
            "--with-findings",
            "--quiet",
            "--sections-only",
            str(p),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "entries hidden — --sections-only" in out
    assert "deeper entr" not in out


@pytest.mark.integration
def test_cli_sections_only_composes_with_outline_depth(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "Title\n#####\n\nSub\n===\n\n* One.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "outline",
            "--with-findings",
            "--quiet",
            "--sections-only",
            "--outline-depth",
            "1",
            str(p),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "Title" in out
    assert "Sub" not in out  # depth 2, cut by --outline-depth 1
    assert "bullet list" not in out  # cut by --sections-only
    assert "--outline-depth 1" in out
    assert "--sections-only" in out


@pytest.mark.integration
def test_cli_sections_only_works_with_outline_only(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text("Title\n#####\n\n* One.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--sections-only", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "Title" in out
    assert "bullet list" not in out


@pytest.mark.integration
def test_admonitions_depth_accounts_for_enclosing_list_item(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        * Item one.

          .. note::

             Nested admonition inside a list item.
        """,
    )
    e = _document.find_admonitions(p)[0]
    assert e.depth == 4  # Title=1, bullet list=2, item=3, admonition=4


@pytest.mark.integration
def test_block_quotes_depth_accounts_for_enclosing_list_item(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        * Item one.

          He wrote:

              A nested quote inside a list item.
        """,
    )
    e = _document.find_block_quotes(p)[0]
    assert e.depth == 4  # Title=1, bullet list=2, item=3, blockquote=4


@pytest.mark.integration
def test_comments_depth_accounts_for_enclosing_list_item(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        * Item one.

          .. A nested comment inside a list item.
        """,
    )
    e = _document.find_comments(p)[0]
    assert e.depth == 4  # Title=1, bullet list=2, item=3, comment=4


@pytest.mark.integration
def test_tables_depth_accounts_for_enclosing_list_item(tmp_path: Path) -> None:
    """The exact real case that surfaced this bug: a list-table added
    inside a bullet item."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        * Item one.

          .. list-table::
             :header-rows: 1

             * - A
               - B
             * - 1
               - 2
        """,
    )
    e = _document.find_tables(p)[0]
    assert e.depth == 4  # Title=1, bullet list=2, item=3, table=4


@pytest.mark.integration
def test_heuristic_code_blocks_depth_ignores_enclosing_list_item(
    tmp_path: Path,
) -> None:
    """KNOWN, ACCEPTED limitation #3 (see find_code_blocks_heuristic's own
    docstring): unlike the other five block finders, this one never
    touches the doctree at all — depth comes purely from build_outline's
    heading positions, "nearest preceding heading + 1" — so it has no way
    to see that a code-block sits inside a list item.  Pinned here as
    accepted, not silently different: depth stays 2 (Title=1, +1), not 4."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        * Item one.

          .. code-block:: python

             pass
        """,
    )
    e = _document.find_code_blocks_heuristic(p)[0]
    assert e.depth == 2


@pytest.mark.integration
def test_heuristic_nested_code_block_range_stops_before_list_item_sibling(
    tmp_path: Path,
) -> None:
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        * Item

          .. code-block:: text

             payload

          Following prose in the list item.

        * Next item
        """,
    )

    entry = _document.find_code_blocks_heuristic(p)[0]

    assert entry.end == 8
    assert entry.preview == "payload"


@pytest.mark.integration
def test_code_blocks_depth_accounts_for_enclosing_list_item(
    build_sphinx_env: BuildSphinxEnv,
) -> None:
    env, docname = build_sphinx_env(
        """\
        Title
        =====

        * Item one.

          .. code-block:: python

             pass
        """
    )
    entries = _sphinx.find_code_blocks(env, docname)
    assert len(entries) == 1
    assert entries[0].depth == 4  # Title=1, bullet list=2, item=3, code-block=4


@pytest.mark.integration
def test_tables_grid_table_no_caption(tmp_path: Path) -> None:
    """A bare grid table has no directive at all — kind and the true start
    (the TOP border, not the header content row the AST itself locates)
    both come from scanning the raw source."""
    p = _rst(
        tmp_path,
        "Title\n=====\n\n+-----+-----+\n| G1  | G2  |\n+=====+=====+\n| x   | y   |\n+-----+-----+\n",
    )
    entries = _document.find_tables(p)
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == "grid"
    assert e.caption is None
    assert e.dims == (2, 2)
    assert e.preview == "G1 G2 x y"  # both rows chained, header first
    assert (e.lineno, e.end) == (4, 8)


@pytest.mark.integration
def test_tables_simple_table_no_caption(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        "Title\n=====\n\n=====  =====\nA      B\n=====  =====\n1      2\n=====  =====\n",
    )
    entries = _document.find_tables(p)
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == "simple"
    assert e.caption is None
    assert e.dims == (2, 2)
    assert e.preview == "A B 1 2"  # both rows chained, header first
    assert (e.lineno, e.end) == (4, 8)


@pytest.mark.integration
def test_tables_csv_table_detected(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. csv-table:: CSV Caption
           :header: "H1", "H2"

           "a", "b"
        """,
    )
    entries = _document.find_tables(p)
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == "csv"
    assert e.caption == "CSV Caption"
    assert e.dims == (2, 2)
    assert e.preview == "H1 H2 a b"  # both rows chained, header first


@pytest.mark.integration
def test_captionless_csv_fallback_ignores_marker_text_in_literal_blocks(tmp_path: Path) -> None:
    """The compatibility path for a table node without its own source line
    must locate a parsed directive, not an earlier marker-shaped literal."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. code-block:: rst

           .. csv-table::
              :header: "Fake"

              "not", "a real table"

        .. csv-table::
           :header: "A", "B"

           "1", "2"
        """,
    )
    document = _document.Document(p)
    for table in document.doctree.findall(docutils.nodes.table):
        table.line = None

    entries = _document.find_tables(p, document)

    assert len(entries) == 1
    assert (entries[0].lineno, entries[0].end) == (11, 14)


@pytest.mark.integration
def test_captionless_csv_fallback_stops_at_its_relative_directive_indent(tmp_path: Path) -> None:
    """A nested directive ends before following prose at its marker's own
    indentation, even though that prose remains indented within a list."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        * Item

          .. csv-table::
             :header: "A", "B"

             "1", "2"

          This paragraph belongs to the list item, not to the CSV directive.

        * Next item
        """,
    )
    document = _document.Document(p)
    for table in document.doctree.findall(docutils.nodes.table):
        table.line = None

    entries = _document.find_tables(p, document)

    assert len(entries) == 1
    assert (entries[0].lineno, entries[0].end) == (6, 9)


@pytest.mark.integration
def test_tables_headerless_chains_all_rows(tmp_path: Path) -> None:
    """No :header-rows: means no <thead> at all — the preview still chains
    every row's cells (there's no header row to prefer), same as any
    other table (Max, 2026-07-20: 'the same principle as for snippets for
    code blocks' — the whole table, not a single privileged row)."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. list-table::
           :header-rows: 0

           * - a
             - b
           * - c
             - d
        """,
    )
    entries = _document.find_tables(p)
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == "list"  # recovered via the indentation scan, no caption needed
    assert e.caption is None
    assert e.preview == "a b c d"


@pytest.mark.integration
def test_tables_end_extends_through_multiline_final_row(tmp_path: Path) -> None:
    """Found live building list-table's acceptance fixture from a real
    grid table whose last row spans two physical lines: docutils' own
    .line tracking only reports a multi-line cell's FIRST physical line,
    so the old approach (extend last_content_line through a trailing
    border only) stopped at that first line instead of the row's real
    continuation and the border past it — silently truncating the
    table's own reported end for any table whose last row is multi-line,
    not just for list-table's own use of it."""
    p = _rst(
        tmp_path,
        "Title\n#####\n\n"
        "+-----+-----+\n| A   | B   |\n+=====+=====+\n| 1   | 2   |\n+-----+-----+\n| x   | y   |\n| ext |     |\n+-----+-----+\n",
    )
    entries = _document.find_tables(p)
    assert len(entries) == 1
    assert (entries[0].lineno, entries[0].end) == (4, 11)


@pytest.mark.integration
def test_simple_table_end_extends_through_multiline_final_row(tmp_path: Path) -> None:
    """Simple-table continuation lines do not start with ``|``.  Their
    exact end therefore comes from the same matching-rule predicate
    Docutils uses to isolate a simple table, not from AST line metadata."""
    p = _rst(
        tmp_path,
        "Title\n#####\n\n"
        "=====  ==========\n"
        "A      B\n"
        "=====  ==========\n"
        "1      first line\n"
        "       second line\n"
        "=====  ==========\n",
    )

    entries = _document.find_tables(p)

    assert len(entries) == 1
    assert (entries[0].lineno, entries[0].end) == (4, 9)


@pytest.mark.integration
def test_directive_simple_table_end_extends_through_multiline_final_row(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        "Title\n#####\n\n"
        ".. table:: Caption\n\n"
        "   =====  ==========\n"
        "   A      B\n"
        "   =====  ==========\n"
        "   1      first line\n"
        "          second line\n"
        "   =====  ==========\n",
    )

    entries = _document.find_tables(p)

    assert len(entries) == 1
    assert (entries[0].lineno, entries[0].end) == (4, 11)


@pytest.mark.unit
def test_table_end_stops_at_closing_border_not_past_it() -> None:
    """Found by code review of the fix above: extending through bare
    '|'-led continuation lines with no stopping condition after the
    closing border is found would absorb an unrelated '|'-led construct
    immediately following the table into the table's own reported end
    too. Exercised directly against _table_end rather than through a
    full file parse: RST itself requires a blank line after a table, so
    a real '|'-led line block genuinely adjacent to a table with no
    separator is malformed input docutils itself flags with a system
    message before find_tables' own logic ever matters (confirmed by
    direct probe) — this is a pure-function robustness property of
    _table_end's own two-phase extension (continuation lines, then the
    border, never back to continuation lines afterward), not a
    reachable-on-valid-input scenario, and is worth pinning as such."""
    lines = [
        "+-----+-----+",
        "| A   | B   |",
        "+=====+=====+",
        "| 1   | 2   |",
        "+-----+-----+",
        "| Verse line one",
        "| Verse line two",
    ]
    assert _document._table_end(lines, last_content_line=4) == 5


@pytest.mark.integration
def test_tables_depth_matches_enclosing_section(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        Chapter One
        ===========

        Sub A
        -----

        =====  =====
        A      B
        =====  =====
        1      2
        =====  =====
        """,
    )
    entries = _document.find_tables(p)
    assert len(entries) == 1
    assert entries[0].depth == 3  # Chapter One=1, Sub A=2, table=3


@pytest.mark.integration
def test_tables_str_format_with_caption(tmp_path: Path) -> None:
    """str() matches '{range}: Table (kind, RxC), "caption": preview'."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. list-table:: My Caption
           :header-rows: 1

           * - A
             - B
           * - x
             - y
        """,
    )
    entries = _document.find_tables(p)
    assert str(entries[0]) == '    4-10: Table (list, 2x2), "My Caption": A B x y'


@pytest.mark.integration
def test_tables_str_format_no_caption(tmp_path: Path) -> None:
    """Without a caption, the '"caption"' clause is omitted entirely —
    same optional-clause contract as code-block's preview."""
    p = _rst(tmp_path, "Title\n=====\n\n=====  =====\nA      B\n=====  =====\n")
    entries = _document.find_tables(p)
    assert str(entries[0]) == "    4-6: Table (simple, 1x2): A B"


@pytest.mark.integration
def test_tables_preview_whitespace_collapsed_and_truncated(tmp_path: Path) -> None:
    long_header = " ".join(f"Column{i}   with   extra   spaces" for i in range(6))
    p = _rst(
        tmp_path,
        f"Title\n=====\n\n.. list-table::\n   :header-rows: 1\n\n   * - {long_header}\n   * - x\n",
    )
    entries = _document.find_tables(p)
    assert len(entries) == 1
    preview = entries[0].preview
    assert "  " not in preview  # no doubled internal spaces
    assert not preview.startswith(" ")
    assert preview.endswith("...")
    assert len(preview) <= 77


@pytest.mark.integration
def test_tables_preview_chains_many_short_rows_then_truncates(tmp_path: Path) -> None:
    """Many rows of short cells chain into ONE line ('A1 A2 A3 B1 B2 B3
    C1 C2 C3 ...', Max, 2026-07-20) before the 74-char/'...' bound ever
    kicks in — confirms truncation is a property of the WHOLE chained
    preview, not of any single row."""
    rows = "".join(f"   * - {r}1\n     - {r}2\n     - {r}3\n" for r in "ABCDEFGHIJ")
    p = _rst(tmp_path, f"Title\n=====\n\n.. list-table::\n   :header-rows: 0\n\n{rows}")
    entries = _document.find_tables(p)
    assert len(entries) == 1
    preview = entries[0].preview
    assert preview.startswith("A1 A2 A3 B1 B2 B3 C1 C2 C3")
    assert preview.endswith("...")
    assert len(preview) <= 77


@pytest.mark.integration
def test_cli_outline_blocks_summary_includes_tables(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "Root\n####\n\n=====  =====\nA      B\n=====  =====\n1      2\n=====  =====\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "outline", "--with-findings", "--quiet", "--verbose", str(p)],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "blocks: 1 table" in out


@pytest.mark.integration
def test_cli_outline_section_bracket_cumulative_tables(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A table inside a subsection rolls up into the parent's cumulative
    bracket count too, same contract as code-blocks/blockquotes."""
    p = rst_repo / "test.rst"
    p.write_text(
        "Root\n####\n\nSub\n***\n\n=====  =====\nA      B\n=====  =====\n1      2\n=====  =====\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", "--quiet", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    root_line = next(ln for ln in out.splitlines() if "Root" in ln)
    assert "[1 subsection, 1 table]" in root_line
