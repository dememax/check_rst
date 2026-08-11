# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Adornment, hierarchy, and structural-fix tests — check_rst project

from __future__ import annotations

import itertools
import json
import os
import subprocess
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

import docutils.nodes
import pygit2
import pytest
from _support import _BAD_BLOCK, _GOOD_BLOCK, _git, _rst

from check_rst import cli
from check_rst.cli import _document, _formatting, _helpers, _sphinx, _types

if TYPE_CHECKING:
    from collections.abc import Sequence

_APPENDED_THIRD_LEVEL = textwrap.dedent("""
    ----------------------
    Added
    ----------------------

    New text.
    """)


_WIDE_STARRED_DOC = textwrap.dedent("""\
    **********************
    Title
    **********************

    Intro text.

    ======================
    Section
    ======================

    Body text.
    """)


_APPENDED_UNDERLINE_ONLY = textwrap.dedent("""

    New Title
    ---------
    """)


_HIERARCHY_CHARS = '#*=-^"'


@pytest.mark.integration
def test_adornments_correct_block(tmp_path: Path) -> None:
    """A properly formed overline+underline title block raises no violations."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        #######
        Title
        #######

        More text.
        """,
    )
    assert _formatting.check_adornments(p, True) == []


@pytest.mark.integration
def test_adornments_underline_only_flagged(tmp_path: Path) -> None:
    """An underline-only title must be flagged."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        Title
        -------

        More text.
        """,
    )
    violations = _formatting.check_adornments(p, True)
    assert violations
    assert any("underline-only" in v for v in violations)


@pytest.mark.integration
def test_adornments_underline_shorter_than_title_flagged(tmp_path: Path) -> None:
    """An underline SHORTER than its title must still be flagged.

    Confirmed against real sphinx-build: a short adornment line glued
    directly to non-blank text (no blank line before it) is always parsed
    as a broken title-underline attempt, never silently accepted as a
    transition/divider — those require blank lines on both sides, which
    already excludes them from this detection path entirely.
    """
    p = _rst(
        tmp_path,
        """\
        Some text.

        bla-bla
        -----

        More text.
        """,
    )
    violations = _formatting.check_adornments(p, True)
    assert violations
    assert any("underline-only" in v for v in violations)


@pytest.mark.integration
def test_adornments_underline_below_absolute_minimum_not_flagged(
    tmp_path: Path,
) -> None:
    """An underline below MIN_UNDERLINE_ONLY_LEN (e.g. a single char) is not
    treated as an underline-only title candidate at all — too short to be
    distinguishable from something that isn't a title attempt."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        A Longer Title
        -

        More text.
        """,
    )
    assert _formatting.check_adornments(p, True) == []


@pytest.mark.integration
def test_adornments_underline_at_absolute_minimum_flagged(tmp_path: Path) -> None:
    """An underline exactly at MIN_UNDERLINE_ONLY_LEN is flagged."""
    p = _rst(
        tmp_path,
        f"""\
        Some text.

        A Longer Title
        {"-" * _helpers.MIN_UNDERLINE_ONLY_LEN}

        More text.
        """,
    )
    violations = _formatting.check_adornments(p, True)
    assert violations
    assert any("underline-only" in v for v in violations)


@pytest.mark.integration
def test_adornments_wrong_length_flagged(tmp_path: Path) -> None:
    """Adornment shorter than title+2 must be flagged."""
    # "Title" = 5 chars → expected = 7, "######" = 6 → violation
    p = _rst(
        tmp_path,
        """\
        Some text.

        ######
        Title
        ######

        More text.
        """,
    )
    violations = _formatting.check_adornments(p, True)
    assert violations
    assert any("must be 7 chars" in v for v in violations)


@pytest.mark.integration
def test_adornments_non_preferred_char_wrong_length_flagged(tmp_path: Path) -> None:
    """A valid-but-non-preferred adornment char (e.g. '~', outside the
    project's preferred #*=-^" hierarchy) still gets the same universal
    length rule applied — check_adornments enforces RST formatting rules on
    any real docutils adornment character, not just the preferred 6. Found
    via a real corpus differential test: downstream-project/docs used '~' as a
    heading underline, previously invisible to this check entirely."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        ~~~~~~
        Title
        ~~~~~~

        More text.
        """,
    )
    violations = _formatting.check_adornments(p, True)
    assert violations
    assert any("must be 7 chars" in v for v in violations)


@pytest.mark.integration
def test_adornments_non_preferred_char_underline_only_flagged(tmp_path: Path) -> None:
    """A non-preferred-char underline-only title (missing overline) is now
    flagged too — previously silently skipped entirely, not even reaching
    the '?' placeholder issue in --outline (this check applies before that)."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        Title
        ~~~~~

        More text.
        """,
    )
    violations = _formatting.check_adornments(p, True)
    assert violations
    assert any("underline-only" in v for v in violations)


@pytest.mark.integration
def test_adornments_title_leading_space_flagged(tmp_path: Path) -> None:
    """A title with a leading space must be flagged."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        ########
         Title
        ########

        More text.
        """,
    )
    violations = _formatting.check_adornments(p, True)
    assert violations
    assert any("leading or trailing spaces" in v for v in violations)


@pytest.mark.integration
def test_adornments_missing_blank_before_overline_flagged(tmp_path: Path) -> None:
    """Missing blank line before the overline must be flagged."""
    p = _rst(
        tmp_path,
        """\
        Some text.
        #######
        Title
        #######

        More text.
        """,
    )
    violations = _formatting.check_adornments(p, True)
    assert violations
    assert any("before the overline" in v for v in violations)


@pytest.mark.integration
def test_adornments_missing_blank_after_underline_flagged(tmp_path: Path) -> None:
    """Missing blank line after the underline must be flagged."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        #######
        Title
        #######
        More text.
        """,
    )
    violations = _formatting.check_adornments(p, True)
    assert violations
    assert any("after the underline" in v for v in violations)


@pytest.mark.integration
def test_adornments_mismatched_chars_flagged(tmp_path: Path) -> None:
    """Overline and underline using different characters must be flagged."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        #######
        Title
        =======

        More text.
        """,
    )
    violations = _formatting.check_adornments(p, True)
    assert violations
    assert any("differs" in v for v in violations)


@pytest.mark.integration
def test_hierarchy_valid_consecutive_sequence(tmp_path: Path) -> None:
    """# → * → = → - is a valid, consecutive hierarchy — no violations."""
    p = _rst(
        tmp_path,
        """\
        ######
        Top
        ######

        ******
        Mid
        ******

        =====
        Sub
        =====

        -----
        Low
        -----
        """,
    )
    assert _formatting.check_hierarchy(p) == []


@pytest.mark.integration
def test_hierarchy_all_six_levels_valid_sequence(tmp_path: Path) -> None:
    """The full project hierarchy # * = - ^ " used in order — no violations.

    test_hierarchy_valid_consecutive_sequence only exercises 4 of the 6
    project adornment characters (#*=-); this covers all six, including
    ^ and " which nothing else in the suite reaches.
    """
    p = _rst(
        tmp_path,
        """\
        ######
        Part
        ######

        *********
        Chapter
        *********

        =========
        Section
        =========

        ------------
        Subsection
        ------------

        ^^^^^^^^^^^^^^^
        Subsubsection
        ^^^^^^^^^^^^^^^

        \"\"\"\"\"\"\"\"\"\"\"
        Paragraph
        \"\"\"\"\"\"\"\"\"\"\"
        """,
    )
    assert _formatting.check_hierarchy(p) == []


@pytest.mark.integration
def test_hierarchy_twelve_levels_beyond_preferred_six(tmp_path: Path) -> None:
    """A 12-level-deep document — double the preferred hierarchy's 6 — using
    HIERARCHY[:12] in order is fully valid: no skipped-level ERRORs, proving
    the extended ranking genuinely supports depth beyond the preferred 6,
    not just up to it. The 6 characters past the preferred set (positions
    7-12) each get exactly one non-preferred-character WARNING, at their
    first (and in this test, only) appearance.
    """
    chars = _helpers.HIERARCHY[:12]
    titles = [f"Level {i}" for i in range(1, 13)]

    def block(ch: str, title: str) -> str:
        adorn = ch * (len(title) + 2)
        return f"{adorn}\n{title}\n{adorn}"

    content = "\n\n".join(block(ch, t) for ch, t in zip(chars, titles, strict=True)) + "\n"
    p = tmp_path / "test.rst"
    p.write_text(content, encoding="utf-8")

    violations = _formatting.check_hierarchy(p)
    errors = [v for v in violations if v.severity == "ERROR"]
    assert errors == []

    warnings = [v for v in violations if v.severity == "WARNING"]
    assert len(warnings) == 6  # positions 7-12: past the preferred 6


@pytest.mark.integration
def test_hierarchy_full_reverse_order_flagged(tmp_path: Path) -> None:
    """The full hierarchy used in exactly reverse order (" ^ - = * #):
    every character sits at the wrong document level, so all six must be
    flagged — the prefix rule reports one ERROR per remapped character,
    exactly mirroring what --fix's remap would rewrite."""
    p = _rst(
        tmp_path,
        """\
        \"\"\"\"\"\"\"\"\"\"\"
        Paragraph
        \"\"\"\"\"\"\"\"\"\"\"

        ^^^^^^^^^^^^^^^
        Subsubsection
        ^^^^^^^^^^^^^^^

        ------------
        Subsection
        ------------

        =========
        Section
        =========

        *********
        Chapter
        *********

        ######
        Part
        ######
        """,
    )
    violations = _formatting.check_hierarchy(p)
    assert len(violations) == 6
    assert all("--fix remaps" in v for v in violations)


@pytest.mark.integration
def test_hierarchy_skip_level_flagged(tmp_path: Path) -> None:
    """Using # then = (skipping *): '=' sits at document level 2, whose
    hierarchy character is '*' — flagged with the remap target."""
    p = _rst(
        tmp_path,
        """\
        ######
        Top
        ######

        =====
        Sub
        =====
        """,
    )
    violations = _formatting.check_hierarchy(p)
    assert violations
    assert any("hierarchy level 2 is '*'" in v for v in violations)


@pytest.mark.integration
def test_hierarchy_inconsistent_order_flagged(tmp_path: Path) -> None:
    """Using * then # (* first, # second): both characters sit at the wrong
    document level under the prefix rule — two ERRORs, one per remap pair."""
    p = _rst(
        tmp_path,
        """\
        ******
        First
        ******

        ######
        Second
        ######
        """,
    )
    violations = _formatting.check_hierarchy(p)
    assert len(violations) == 2
    assert all("--fix remaps" in v for v in violations)


@pytest.mark.integration
def test_hierarchy_single_level_ok(tmp_path: Path) -> None:
    """A document with a single adornment character has no hierarchy violations."""
    p = _rst(
        tmp_path,
        """\
        ######
        Top
        ######

        ######
        Also Top
        ########

        ######
        Again
        ######
        """,
    )
    # May have adornment-length violations but hierarchy must be clean
    assert _formatting.check_hierarchy(p) == []


@pytest.mark.integration
def test_hierarchy_non_preferred_char_alone_warns_and_errors(tmp_path: Path) -> None:
    """A valid-but-non-preferred adornment char ('~', outside #*=-^") used
    alone gets the non-preferred-character WARNING *and* a prefix-rule
    ERROR: '~' is this document's level 1, whose hierarchy character is
    '#' — exactly what --fix's remap rewrites, so the check must say so
    (previously the check was silent and --fix rewrote a clean-checked
    file; the rst-formatting.md '~-only document' remap was already
    documented as deliberate)."""
    p = _rst(
        tmp_path,
        """\
        ~~~~~
        Title
        ~~~~~
        """,
    )
    violations = _formatting.check_hierarchy(p)
    warnings = [v for v in violations if v.severity == "WARNING"]
    errors = [v for v in violations if v.severity == "ERROR"]
    assert len(warnings) == 1
    assert any("preferred hierarchy" in v for v in warnings)
    assert len(errors) == 1
    assert any("hierarchy level 1 is '#'" in v for v in errors)


@pytest.mark.integration
def test_hierarchy_non_preferred_char_warned_once_per_char(tmp_path: Path) -> None:
    """The non-preferred-char WARNING fires once per distinct character
    (first appearance), same convention as hierarchy-order tracking — not
    once per every repeated use. Uses '~' at a single, consistent length so
    there's no length-driven ERROR noise to filter out."""
    p = _rst(
        tmp_path,
        """\
        ~~~~~
        First
        ~~~~~

        ~~~~~~
        Second
        ~~~~~~

        ~~~~~
        Third
        ~~~~~
        """,
    )
    violations = _formatting.check_hierarchy(p)
    assert len([v for v in violations if "preferred hierarchy" in v]) == 1


@pytest.mark.integration
def test_hierarchy_non_preferred_char_participates_in_order_check(
    tmp_path: Path,
) -> None:
    """A non-preferred char now participates in the SAME order-check ERROR
    as preferred ones — HIERARCHY ranks all 32 valid characters uniformly.
    '~' following '#' sits at document level 2, whose hierarchy character
    is '*' — an ERROR carrying the remap target, not silently ignored."""
    p = _rst(
        tmp_path,
        """\
        ######
        Top
        ######

        ~~~~~~
        Aside
        ~~~~~~
        """,
    )
    violations = _formatting.check_hierarchy(p)
    errors = [v for v in violations if v.severity == "ERROR"]
    assert errors
    assert any("hierarchy level 2 is '*'" in v for v in errors)


@pytest.mark.integration
def test_single_top_level_one_section_ok(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        #####
        Title
        #####

        Sub
        ===

        Body.
        """,
    )
    assert _formatting.check_single_top_level(p) == []


@pytest.mark.integration
def test_single_top_level_empty_document_ok(tmp_path: Path) -> None:
    p = _rst(tmp_path, "Just a paragraph, no titles at all.\n")
    assert _formatting.check_single_top_level(p) == []


@pytest.mark.integration
def test_single_top_level_two_sections_flagged(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        #####
        First
        #####

        Body one.

        ######
        Second
        ######

        Body two.
        """,
    )
    violations = _formatting.check_single_top_level(p)
    assert len(violations) == 1
    assert violations[0].severity == "ERROR"
    assert violations[0].fixable is False
    assert "'Second'" in violations[0].text
    assert "'First'" in violations[0].text
    assert violations[0].lineno == 8  # the second occurrence's own title line


@pytest.mark.integration
def test_single_top_level_three_sections_flags_second_and_third(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        #####
        First
        #####

        ######
        Second
        ######

        #####
        Third
        #####
        """,
    )
    violations = _formatting.check_single_top_level(p)
    assert len(violations) == 2
    assert [v.lineno for v in violations] == [6, 10]


@pytest.mark.integration
def test_single_top_level_underline_only_titles_also_counted(tmp_path: Path) -> None:
    """The same event scan as check_hierarchy's own
    _first_appearance_adornments — underline-only top-level titles are not
    a loophole."""
    p = _rst(
        tmp_path,
        """\
        First
        #####

        Second
        #####
        """,
    )
    violations = _formatting.check_single_top_level(p)
    assert len(violations) == 1
    assert violations[0].lineno == 4


@pytest.mark.integration
def test_single_top_level_non_preferred_char_also_flagged(tmp_path: Path) -> None:
    """The rule is about whichever character is THIS document's own rank-1
    adornment, not hardcoded to '#'."""
    p = _rst(
        tmp_path,
        """\
        ~~~~~
        First
        ~~~~~

        ~~~~~~
        Second
        ~~~~~~
        """,
    )
    violations = _formatting.check_single_top_level(p)
    assert len(violations) == 1
    assert "'~'" in violations[0].text


@pytest.mark.integration
def test_single_top_level_repeated_subsection_char_not_flagged(tmp_path: Path) -> None:
    """Only the LEVEL-1 character is ever singular; repeating a deeper
    level's character across many sibling subsections is normal and must
    stay silent."""
    p = _rst(
        tmp_path,
        """\
        #####
        Title
        #####

        One
        ===

        Two
        ===

        Three
        ===
        """,
    )
    assert _formatting.check_single_top_level(p) == []


@pytest.mark.integration
def test_single_top_level_hint_repair_shape_converges(tmp_path: Path) -> None:
    """A human-chosen wrapper title plus an unused placeholder is fixable."""
    p = _rst(
        tmp_path,
        """\
        Page title
        ~~~~~~~~~

        #####
        First
        #####

        ######
        Second
        ######
        """,
    )

    assert _formatting.check_single_top_level(p) == []
    assert _formatting.fix_structure(p, True)
    assert _formatting.check_single_top_level(p) == []
    assert [(entry.depth, entry.char, entry.title) for entry in _document.build_outline(p)] == [
        (1, "#", "Page title"),
        (2, "*", "First"),
        (2, "*", "Second"),
    ]


@pytest.mark.integration
def test_single_top_level_counts_extension_generated_section_without_line(tmp_path: Path) -> None:
    p = _rst(tmp_path, "#######\nTitle\n#######\n")
    document = _document.Document(p, tmp_path)
    generated = docutils.nodes.section(ids=["generated"])
    generated += docutils.nodes.title("", "Generated")
    document.doctree += generated

    findings = _formatting.check_single_top_level(p, doc=document)

    assert len(findings) == 1
    assert findings[0].lineno == 0
    assert "Generated" in findings[0].text


@pytest.mark.integration
def test_cli_bold_opener_rationale_printed_once_per_run(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Max, 2026-07-20: 'it repeats [the rationale]... long. Can we inform
    this as a separate line only once?' — five bold-opener findings in one
    file must print the shared rationale line exactly once, not once per
    finding, while each finding's own line still names its own text."""
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\n"
        "**First point.**  Detail one.\n\n"
        "**Second point.**  Detail two.\n\n"
        "**Third point.**  Detail three.\n\n"
        "**Fourth point.**  Detail four.\n\n"
        "**Fifth point.**  Detail five.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    rationale = "AI documents often use this pattern as an informal heading; consider a proper section title"
    assert out.count(rationale) == 1
    for point in (
        "First point",
        "Second point",
        "Third point",
        "Fourth point",
        "Fifth point",
    ):
        assert point in out
    assert out.count("WARNING:") == 5  # five finding lines; the rationale is not one of them


@pytest.mark.integration
def test_cli_bold_opener_rationale_resets_between_runs(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """'Once per run' must mean once per invocation of main(), not once
    ever — a fresh run (a fresh process, ordinarily; a fresh main() call
    here, since pytest doesn't restart the process) must show the
    rationale again."""
    p = rst_repo / "test.rst"
    p.write_text("#######\nTitle\n#######\n\n**A point.**  Detail.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", str(p)])

    with pytest.raises(SystemExit):
        cli.main()
    capsys.readouterr()  # discard first run's output

    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "AI documents often use this pattern" in out


@pytest.mark.integration
def test_fix_never_changes_prose_content_lines(tmp_path: Path) -> None:
    """Every prose line survives --fix byte-for-byte, in order, regardless
    of how many adornment lines around it get inserted, resized, or
    remapped.  Deliberately exercises every fixer path in one document:
    an underline-only title (needs overline synthesis), a wrong-length
    full block, a hierarchy-violating character (needs remapping), and a
    BOM + CRLF line ending (Phase 0 hygiene) — none of which may touch
    the prose lines interleaved between them."""
    original_bytes = (
        b"\xef\xbb\xbf"  # BOM — Phase 0 strips it
        b"Weather station\r\n"  # CRLF — Phase 0 converts to LF
        b"#########\r\n"
        b"\r\n"
        b"\xd0\x91\xd0\xb0\xd0\xbb\xd0\xba\xd0\xbe\xd0\xbd\xd0\xbd\xd0\xb0\xd1\x8f "
        b"\xd0\xbc\xd0\xb5\xd1\x82\xd0\xb5\xd0\xbe\xd1\x81\xd1\x82\xd0\xb0\xd0\xbd\xd1\x86\xd0\xb8\xd1\x8f.\r\n"
        b"\r\n"
        b"Sensors\r\n"
        b"*********\r\n"  # underline-only, needs overline synthesis
        b"\r\n"
        b"The sensor reports temperature over MQTT; it drops\r\n"
        b"a reading occasionally when the battery is low.\r\n"
        b"\r\n"
        b"##\r\n"  # wrong-length full block (should be title+2)
        b"Deep\r\n"
        b"##\r\n"
        b"\r\n"
        b"Deep body text right here, between two adornment blocks.\r\n"
        b"\r\n"
        b"History\r\n"
        b"~~~~~~~~~\r\n"  # non-preferred char, needs hierarchy remap
        b"\r\n"
        b"Coming later.\r\n"
    )
    p = tmp_path / "test.rst"
    p.write_bytes(original_bytes)

    original_text = original_bytes.decode("utf-8").lstrip("﻿").replace("\r\n", "\n")

    def prose_lines(text: str) -> list[str]:
        return [line for line in text.splitlines() if line.strip() and not _helpers._is_adornment(line.rstrip())]

    before = prose_lines(original_text)

    _formatting.fix_hygiene(p)
    _formatting.fix_structure(p, True)

    after = prose_lines(p.read_text(encoding="utf-8"))
    assert after == before
    assert before  # sanity: the fixture actually has prose to compare


@pytest.mark.integration
def test_heuristic_literalinclude_with_language_option_detected(tmp_path: Path) -> None:
    """'.. literalinclude::' is a fourth Sphinx source of code-block-like
    content, found by a real corpus differential test against Journal's own
    calendar/2026/05/2026-05-04/Notes.rst: the real detector counts ANY
    literal_block with a 'language' attribute, regardless of which directive
    produced it, so a literalinclude with an explicit :language: option must
    be detected too, with that exact language value."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. literalinclude:: some-file.txt
            :lines: 1-5
            :language: none
        """,
    )
    entries = _document.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].language == "none"


@pytest.mark.integration
def test_heuristic_literalinclude_language_option_is_case_insensitive(tmp_path: Path) -> None:
    """Docutils normalizes directive option names before option lookup."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. literalinclude:: some-file.py
            :Language: python
        """,
    )

    entries = _document.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].language == "python"


@pytest.mark.integration
def test_heuristic_literalinclude_capitalized_directive_detected(tmp_path: Path) -> None:
    """Docutils resolves directive names case-insensitively (confirmed:
    directive lookup normalizes the name via .lower() before the registry
    match), so '.. LiteralInclude::' is exactly as valid RST as
    '.. literalinclude::' and must not silently vanish just because the raw
    text uses different letter casing."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. LiteralInclude:: some-file.txt
            :lines: 1-5
            :language: none
        """,
    )
    entries = _document.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].language == "none"


@pytest.mark.integration
def test_heuristic_literalinclude_without_language_or_diff_excluded(
    tmp_path: Path,
) -> None:
    """A literalinclude with no :language: and no :diff: option must be
    EXCLUDED entirely, not included with language=None — confirmed by
    reading sphinx.directives.code.LiteralInclude.run() directly: unlike
    CodeBlock, it has no config/env fallback and simply never sets the
    'language' attribute in this case, so the real Sphinx-based detector
    also skips it (its `if lang is None: continue` guard). A real corpus
    differential test against calendar/2026/05/2026-05-10/Notes.rst first
    caught this the other way around: the heuristic reported 6 entries the
    real detector didn't, all bare literalincludes like this one."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. literalinclude:: some-file.py
            :lines: 1-5
        """,
    )
    assert _document.find_code_blocks_heuristic(p) == []


@pytest.mark.integration
def test_heuristic_literalinclude_diff_option_is_udiff(tmp_path: Path) -> None:
    """A literalinclude with :diff: (and no :language:) is still found,
    with language 'udiff' — LiteralInclude.run() sets this explicitly as a
    special case, the one exception to "no :language: means excluded"."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. literalinclude:: some-file.py
            :diff: other-file.py
        """,
    )
    entries = _document.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].language == "udiff"


@pytest.mark.integration
def test_heuristic_literalinclude_diff_option_is_case_insensitive(tmp_path: Path) -> None:
    """A differently cased diff option still forces the udiff language."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. literalinclude:: some-file.py
            :Diff: other-file.py
        """,
    )

    entries = _document.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].language == "udiff"


@pytest.mark.integration
def test_heuristic_literalinclude_depth_matches_enclosing_section(
    tmp_path: Path,
) -> None:
    """depth for a literalinclude entry follows the same convention as
    code-block entries: one level deeper than the nearest preceding heading."""
    p = _rst(
        tmp_path,
        """\
        Chapter One
        ===========

        .. literalinclude:: some-file.txt
            :language: none
        """,
    )
    entries = _document.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].depth == 2


@pytest.mark.integration
def test_fix_wrong_length(tmp_path: Path) -> None:
    """Wrong adornment length is corrected to title_len + 2."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        ######
        Title
        ######

        More text.
        """,
    )
    changed = _formatting.fix_structure(p, True)
    assert changed
    assert "#######\nTitle\n#######" in p.read_text(encoding="utf-8")
    assert _formatting.check_adornments(p, True) == []


@pytest.mark.integration
def test_fix_mismatched_chars(tmp_path: Path) -> None:
    """Mismatched underline character is replaced with the overline character."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        #######
        Title
        =======

        More text.
        """,
    )
    _formatting.fix_structure(p, True)
    assert "#######\nTitle\n#######" in p.read_text(encoding="utf-8")
    assert _formatting.check_adornments(p, True) == []


@pytest.mark.integration
def test_fix_missing_blank_before_overline(tmp_path: Path) -> None:
    """Missing blank line before the overline is inserted."""
    p = _rst(
        tmp_path,
        """\
        Some text.
        #######
        Title
        #######

        More text.
        """,
    )
    _formatting.fix_structure(p, True)
    assert _formatting.check_adornments(p, True) == []


@pytest.mark.integration
def test_fix_missing_blank_after_underline(tmp_path: Path) -> None:
    """Missing blank line after the underline is inserted."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        #######
        Title
        #######
        More text.
        """,
    )
    _formatting.fix_structure(p, True)
    assert _formatting.check_adornments(p, True) == []


@pytest.mark.integration
def test_fix_title_spaces(tmp_path: Path) -> None:
    """Leading/trailing spaces in the title are stripped."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        ########
         Title
        ########

        More text.
        """,
    )
    _formatting.fix_structure(p, True)
    content = p.read_text(encoding="utf-8")
    assert " Title" not in content
    assert _formatting.check_adornments(p, True) == []


@pytest.mark.integration
def test_fix_combined_errors(tmp_path: Path) -> None:
    """All fixable errors in one block are corrected in a single pass."""
    p = _rst(
        tmp_path,
        """\
        Some text.
        ######
         Title
        =======
        More text.
        """,
    )
    _formatting.fix_structure(p, True)
    assert _formatting.check_adornments(p, True) == []


@pytest.mark.integration
def test_fix_correct_file_unchanged(tmp_path: Path) -> None:
    """A file with no adornment errors is not modified."""
    original = textwrap.dedent("""\
        Some text.

        #######
        Title
        #######

        More text.
        """)
    p = tmp_path / "test.rst"
    p.write_text(original, encoding="utf-8")
    changed = _formatting.fix_structure(p, True)
    assert not changed
    assert p.read_text(encoding="utf-8") == original


@pytest.mark.integration
def test_fix_underline_only(tmp_path: Path) -> None:
    """Underline-only title gets a matching overline added (char inferred from underline)."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        Title
        -------

        More text.
        """,
    )
    _formatting.fix_structure(p, True)
    assert _formatting.check_adornments(p, True) == []
    content = p.read_text(encoding="utf-8")
    # The lone '-' is this document's level 1, so the same pass remaps it
    # to '#' (this was always the CLI's end state — fix_hierarchy used to
    # do it right after fix_adornments; the composition makes the single
    # pass produce it directly).
    assert "#######\nTitle\n#######" in content


@pytest.mark.integration
def test_fix_underline_shorter_than_title(tmp_path: Path) -> None:
    """--fix corrects an underline SHORTER than its title the same way as a
    too-long one: synthesizes the overline and recomputes both to title+2,
    regardless of the original (too-short) underline's length."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        bla-bla
        -----

        More text.
        """,
    )
    _formatting.fix_structure(p, True)
    assert _formatting.check_adornments(p, True) == []
    content = p.read_text(encoding="utf-8")
    assert "\nbla-bla\n" in content
    # 'bla-bla' is 7 chars -> expected adornment length 9.
    lines = content.splitlines()
    idx = lines.index("bla-bla")
    assert len(lines[idx - 1]) == len(lines[idx + 1]) == 9


@pytest.mark.integration
def test_fix_multiple_blocks(tmp_path: Path) -> None:
    """Multiple broken blocks in one file are all fixed."""
    p = _rst(
        tmp_path,
        """\
        ######
        First
        ######

        ****
        Second
        ****

        """,
    )
    _formatting.fix_structure(p, True)
    assert _formatting.check_adornments(p, True) == []


@pytest.mark.integration
def test_diff_structure_returns_diff(tmp_path: Path) -> None:
    """diff_structure returns a unified diff when fixes are needed."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        ######
        Title
        ######

        More text.
        """,
    )
    diff = _formatting.diff_structure(p, True)
    assert diff
    assert "---" in diff
    assert "Title" in diff
    assert "######\nTitle\n######" in p.read_text(encoding="utf-8")


@pytest.mark.integration
def test_diff_structure_clean_file_empty(tmp_path: Path) -> None:
    """diff_structure returns empty string when no fixes are needed."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        #######
        Title
        #######

        More text.
        """,
    )
    assert _formatting.diff_structure(p, True) == ""


@pytest.mark.integration
def test_fix_hierarchy_skipped_level(tmp_path: Path) -> None:
    """Skipped hierarchy level is fixed by remapping the wrong char."""
    p = _rst(
        tmp_path,
        """\
        ######
        Top
        ######

        =====
        Sub
        =====
        """,
    )
    _formatting.fix_structure(p, True)
    assert _formatting.check_hierarchy(p) == []
    content = p.read_text(encoding="utf-8")
    assert "=====" not in content
    assert "*****\nSub\n*****" in content


@pytest.mark.integration
def test_fix_hierarchy_wrong_order(tmp_path: Path) -> None:
    """Swapped hierarchy chars are corrected to the project order."""
    p = _rst(
        tmp_path,
        """\
        ******
        First
        ******

        ######
        Second
        ######
        """,
    )
    _formatting.fix_structure(p, True)
    assert _formatting.check_hierarchy(p) == []
    content = p.read_text(encoding="utf-8")
    assert "#######\nFirst\n#######" in content
    assert "********\nSecond\n********" in content


@pytest.mark.integration
def test_fix_hierarchy_correct_unchanged(tmp_path: Path) -> None:
    """A file with correct hierarchy is not modified."""
    original = textwrap.dedent("""\
        #####
        Top
        #####

        *****
        Mid
        *****

        =====
        Sub
        =====
        """)
    p = tmp_path / "test.rst"
    p.write_text(original, encoding="utf-8")
    changed = _formatting.fix_structure(p, True)
    assert not changed
    assert p.read_text(encoding="utf-8") == original


@pytest.mark.integration
def test_fix_hierarchy_single_level_unchanged(tmp_path: Path) -> None:
    """A file with only one level (no hierarchy violations possible) is not modified."""
    original = textwrap.dedent("""\
        #######
        Title
        #######
        """)
    p = tmp_path / "test.rst"
    p.write_text(original, encoding="utf-8")
    assert not _formatting.fix_structure(p, True)


@pytest.mark.integration
def test_fix_hierarchy_remaps_lone_non_preferred_char_to_preferred(
    tmp_path: Path,
) -> None:
    """A document using only a non-preferred char ('~') throughout — no
    preferred char at all — IS remapped by --fix, to '#' (HIERARCHY[:1]).
    Deliberate, explicit choice: since HIERARCHY ranks all 32 characters
    uniformly, --fix's existing "remap to match rank" behavior (already
    established for the preferred 6 — see rst-formatting.md, "Hierarchy
    remap in --fix") now applies the same way to every valid character,
    rather than special-casing non-preferred ones as untouchable."""
    original = textwrap.dedent("""\
        ~~~~~
        Title
        ~~~~~
        """)
    p = tmp_path / "test.rst"
    p.write_text(original, encoding="utf-8")
    assert _formatting.fix_structure(p, True)
    fixed = p.read_text(encoding="utf-8")
    assert "#######\nTitle\n#######" in fixed


@pytest.mark.integration
def test_fix_hierarchy_remaps_non_preferred_char_mixed_with_preferred(
    tmp_path: Path,
) -> None:
    """Mixed preferred + non-preferred chars: ALL of them are candidates for
    remapping now, uniformly, not just the preferred ones — first-appearance
    order here is '*', '~', '#', but correct order is '#', '*', '=', so
    every one of the three actually changes."""
    original = textwrap.dedent("""\
        ******
        Mid
        ******

        ~~~~~~
        Aside
        ~~~~~~

        #######
        Top
        #######
        """)
    p = tmp_path / "test.rst"
    p.write_text(original, encoding="utf-8")
    assert _formatting.fix_structure(p, True)
    fixed = p.read_text(encoding="utf-8")
    # '*' (1st seen) -> '#' (1st correct), at canonical width (3+2)
    assert "#####\nMid\n#####" in fixed
    # '~' (2nd seen) -> '*' (2nd correct), at canonical width (5+2)
    assert "*******\nAside\n*******" in fixed
    # '#' (3rd seen) -> '=' (3rd correct), at canonical width (3+2)
    assert "=====\nTop\n=====" in fixed


@pytest.mark.unit
def test_first_appearance_adornments_sees_short_underline_only_titles() -> None:
    """The exact repro: two short (3-char), never-promoted underline-only
    titles must be visible to first-appearance detection, in document
    order, ahead of a later, longer, already-promotable title."""
    lines = ["Doc", "###", "", "Sub", "***", "", "Deep", "===="]
    seen = _formatting._first_appearance_adornments(lines)
    assert seen == [("#", 1), ("*", 4), ("=", 7)]


@pytest.mark.unit
def test_hierarchy_error_describes_the_depth_aware_rule(tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n=====\n")

    findings = _formatting.check_hierarchy(p)

    assert len(findings) == 1
    assert "established nesting depth must follow the hierarchy" in findings[0].text
    assert "first-appearance order" not in findings[0].text


@pytest.mark.unit
def test_compute_structure_fixes_does_not_collide_short_titles() -> None:
    """The full regression: composing the fix must not remap a later,
    correctly-ranked character into collision with an earlier, short,
    not-yet-promoted title using a DIFFERENT character at a DIFFERENT
    rank.  '=' (rank 3, correct for "Deep") must stay '=', never get
    "corrected" to '#' (already used, invisibly, by "Doc")."""
    lines = ["Doc", "###", "", "Sub", "***", "", "Deep", "===="]
    fixed = "\n".join(_formatting._compute_structure_fixes(lines, None))
    assert "######\nDoc\n######" not in fixed  # never remap Doc away from '#'
    assert "\n======\nDeep\n======" in fixed  # Deep stays '=', at canonical width


@pytest.mark.integration
def test_cli_fix_short_titles_converge_with_no_inconsistent_style(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """End to end, verified against a REAL, toctree-nested sphinx-build —
    not just check_rst's own bare-docutils Phase 1, and deliberately not
    just a standalone Document() parse either: found by direct probe that
    a bare, non-nested parse of the SAME broken content reports no
    inconsistency at all — a document's title-style stack only collides
    with an EARLIER, invisible short title once Sphinx resolves it as a
    toctree CHILD, nested under its parent's own heading.  That nested
    context is exactly what the real repro needed and a standalone parse
    would silently miss, so this test builds one."""
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text("Index\n#####\n\n.. toctree::\n\n   doc\n", encoding="utf-8")
    p = rst_repo / "doc.rst"
    p.write_text("Doc\n###\n\nSub\n***\n\nDeep\n====\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "--build-dir",
            str(rst_repo / "_build"),
            "fix",
            str(p),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    capsys.readouterr()

    result = subprocess.run(
        ["sphinx-build", "--builder", "html", str(rst_repo), str(rst_repo / "_verify")],
        capture_output=True,
        text=True,
    )
    assert "Inconsistent title style" not in result.stdout + result.stderr


def _hierarchy_chain_block(ch: str, title: str) -> str:
    """One title block (`ch` repeated to the title's width) — the shared
    building block for every linear-chain hierarchy test below."""
    adorn = ch * (len(title) + 2)
    return f"{adorn}\n{title}\n{adorn}"


def _hierarchy_chain_doc(chars: Sequence[str]) -> str:
    """A strictly linear chain of len(chars) titles, one distinct character
    per level, each nested exactly one level deeper than the last — the
    skeleton every "any permutation of characters converges to the
    standard order" case below builds on.

    This skeleton can NEVER exercise the sibling-branching bug fixed
    alongside this test (see
    test_fix_hierarchy_sibling_branch_does_not_corrupt_an_already_correct_child):
    a linear chain's first-appearance ORDER and nesting DEPTH always
    coincide by construction — level 1 is always seen first, level 2
    second, and so on — for every possible assignment of characters to
    slots. Misalignment between order and depth only appears once a
    document branches (two sibling subtrees independently reaching the
    same depth via different characters), which no permutation of THIS
    skeleton's characters can ever produce. That is exactly why the
    sibling-branch case has its own, separate, non-permuted test rather
    than being folded into the permutations here (confirmed live,
    2026-08-10: the project owner asked directly whether "a good
    permutation" of this skeleton should be able to reproduce that bug —
    it cannot, for the topology reason above).
    """
    titles = [f"Level {i}" for i in range(1, len(chars) + 1)]
    return "\n\n".join(_hierarchy_chain_block(ch, t) for ch, t in zip(chars, titles, strict=True)) + "\n"


def _swapped(chars: Sequence[str], i: int, j: int) -> tuple[str, ...]:
    """`chars` as a tuple with positions i and j exchanged — builds an
    "almost entirely correct" hierarchy case for the corner-case tests
    below. Takes any Sequence[str] (a str, or an already-swapped tuple
    from a previous call), not just a str, so swaps can be chained."""
    out = list(chars)
    out[i], out[j] = out[j], out[i]
    return tuple(out)


def _assert_hierarchy_structurally_correct(p: Path) -> None:
    """No ERROR-severity hierarchy finding remains — the structure (order,
    no skipped levels) is correct. A WARNING for a valid-but-not-preferred
    character (see PREFERRED_HIERARCHY) is expected and correct once a
    chain runs past the 6 preferred characters, which every depth-10 case
    below deliberately does — unlike the old depth-6-only test, this can
    no longer assert an empty findings list."""
    findings = _formatting.check_hierarchy(p)
    assert all(f.severity != _types.Severity.ERROR for f in findings), findings


@pytest.mark.integration
@pytest.mark.parametrize("perm", list(itertools.permutations(_HIERARCHY_CHARS)))
def test_fix_hierarchy_any_permutation_converges_to_standard_order(tmp_path: Path, perm: tuple[str, ...]) -> None:
    """Exhaustive: for every one of the 6! = 720 orderings of the 6
    preferred characters at levels 1-6 of a depth-10 linear chain (levels
    7-10 fixed at HIERARCHY's own next 4 characters, already correct),
    fix_structure converges to the exact same single canonical depth-10
    result (HIERARCHY[:10] in document order) — a mechanical remap keyed
    only on each character's first-appearance DEPTH, independent of which
    characters the document originally happened to use for each level.

    Extended from depth 6 to depth 10, 2026-08-10, at the project owner's
    request, once the sibling-branch bug below showed that first-appearance
    order and nesting depth can disagree once a document branches: this
    skeleton is still purely linear (see _hierarchy_chain_doc's docstring
    for why that can't reach the branching case itself), but extending its
    depth past the 6 preferred characters exercises the remap against the
    other 26 valid-but-not-preferred HIERARCHY characters too, which the
    depth-6 version never touched. Full 10! exhaustive enumeration
    (3,628,800 cases) is infeasible; only the 6 preferred levels are
    exhaustively permuted here — the other corner cases (non-preferred-only,
    reversed, already-correct, interleaved, mostly-correct-with-a-few-swaps)
    are covered by the separate parametrized test right below instead of by
    brute enumeration.
    """
    assert _helpers.PREFERRED_HIERARCHY == _HIERARCHY_CHARS
    assert _helpers.HIERARCHY[: len(_HIERARCHY_CHARS)] == _HIERARCHY_CHARS

    tail = _helpers.HIERARCHY[len(_HIERARCHY_CHARS) : 10]
    original_chars = perm + tuple(tail)
    expected_chars = tuple(_helpers.HIERARCHY[:10])

    p = tmp_path / "test.rst"
    p.write_text(_hierarchy_chain_doc(original_chars), encoding="utf-8")

    _formatting.fix_structure(p, True)

    assert p.read_text(encoding="utf-8") == _hierarchy_chain_doc(expected_chars)
    _assert_hierarchy_structurally_correct(p)


_HIERARCHY_10 = _helpers.HIERARCHY[:10]
_NON_PREFERRED_10 = _helpers.HIERARCHY[6:16]

_HIERARCHY_10_CORNER_CASES = [
    pytest.param(tuple(_HIERARCHY_10), id="already_preferred_order"),
    pytest.param(tuple(_NON_PREFERRED_10), id="only_non_preferred_canonical_order"),
    pytest.param(tuple(reversed(_NON_PREFERRED_10)), id="only_non_preferred_reversed"),
    pytest.param(tuple(reversed(_HIERARCHY_10)), id="fully_reversed_standard_order"),
    pytest.param(
        tuple(itertools.chain.from_iterable(zip(_helpers.HIERARCHY[:5], _helpers.HIERARCHY[6:11], strict=True))),
        id="mixed_interleaved_preferred_and_non_preferred",
    ),
    pytest.param(_swapped(_HIERARCHY_10, 2, 3), id="mostly_correct_one_adjacent_swap"),
    pytest.param(_swapped(_HIERARCHY_10, 0, 9), id="mostly_correct_one_distant_swap"),
    pytest.param(
        (*_helpers.HIERARCHY[:5], _helpers.HIERARCHY[20], *_helpers.HIERARCHY[6:10]),
        id="mostly_correct_single_substitution",
    ),
]


@pytest.mark.integration
@pytest.mark.parametrize("chars", _HIERARCHY_10_CORNER_CASES)
def test_fix_hierarchy_depth_ten_corner_cases_converge_to_standard_order(
    tmp_path: Path, chars: tuple[str, ...]
) -> None:
    """Depth-10 corner cases the 720-case exhaustive test above can't reach
    on its own (it only ever permutes the 6 preferred characters, holding
    levels 7-10 fixed): documents using only non-preferred characters,
    already in the correct order, fully reversed, interleaved
    preferred/non-preferred, and — closest in spirit to the real sagui bug,
    short of its branching topology (see _hierarchy_chain_doc's docstring)
    — a chain that is ALREADY almost entirely correct with just one or two
    characters wrong. Every case shares the same linear-chain skeleton as
    the test above, and every one must converge to the identical depth-10
    canonical result.
    """
    assert len(set(chars)) == 10, "corner case must use 10 distinct characters"

    p = tmp_path / "test.rst"
    p.write_text(_hierarchy_chain_doc(chars), encoding="utf-8")

    _formatting.fix_structure(p, True)

    assert p.read_text(encoding="utf-8") == _hierarchy_chain_doc(tuple(_helpers.HIERARCHY[:10]))
    _assert_hierarchy_structurally_correct(p)


_FULL_ALPHABET = tuple(_helpers.HIERARCHY)

_HIERARCHY_FULL_ALPHABET_CORNER_CASES = [
    pytest.param(tuple(reversed(_FULL_ALPHABET)), id="full_alphabet_fully_reversed_order"),
    pytest.param(_FULL_ALPHABET[16:] + _FULL_ALPHABET[:16], id="full_alphabet_rotated_by_half"),
    pytest.param(
        tuple(_helpers.HIERARCHY[6:]) + tuple(_helpers.HIERARCHY[:6]),
        id="full_alphabet_non_preferred_characters_first",
    ),
    pytest.param(
        _swapped(_swapped(_FULL_ALPHABET, 2, 3), 29, 30),
        id="full_alphabet_mostly_correct_two_distant_swaps",
    ),
]


@pytest.mark.integration
@pytest.mark.parametrize("chars", _HIERARCHY_FULL_ALPHABET_CORNER_CASES)
def test_fix_hierarchy_full_alphabet_wrong_order_converges_to_standard_order(
    tmp_path: Path, chars: tuple[str, ...]
) -> None:
    """The absolute ceiling case: a linear chain using EVERY one of the
    len(VALID_ADORNMENT_CHARS) == 32 valid RST adornment characters, in a
    variety of deliberately wrong orders. Confirms directly (2026-08-10,
    prompted by the project owner asking whether fixing such a document
    could fail for running out of characters to remap onto) that the
    remap never runs out of target slots: HIERARCHY is built FROM
    VALID_ADORNMENT_CHARS itself (see _helpers.py's own construction),
    so len(HIERARCHY) == len(VALID_ADORNMENT_CHARS) is an invariant of
    that construction, not a coincidence of the current docutils version
    -- and _established_depths can never mint a depth deeper than the
    count of distinct characters a document uses, which is hard-capped at
    that same 32. There is no possible 33rd level for any valid RST
    document to reach: a 33rd heading has no unused character left to
    introduce, so it necessarily reuses one of the 32 already-established
    ones, which is an ordinary "return to an established depth" event,
    not a new failure mode.
    """
    assert len(chars) == len(_helpers.HIERARCHY) == len(_helpers.VALID_ADORNMENT_CHARS)
    assert len(set(chars)) == len(chars), "corner case must use every character exactly once"

    p = tmp_path / "test.rst"
    p.write_text(_hierarchy_chain_doc(chars), encoding="utf-8")

    _formatting.fix_structure(p, True)

    assert p.read_text(encoding="utf-8") == _hierarchy_chain_doc(_FULL_ALPHABET)
    _assert_hierarchy_structurally_correct(p)


@pytest.mark.integration
def test_fix_hierarchy_sibling_branch_does_not_corrupt_an_already_correct_child(tmp_path: Path) -> None:
    """Real bug, found live (sagui, 2026-08-10, re-syncing a pandoc-converted
    document): two `*`-level sibling sections, each with exactly one child
    heading. The first sibling's child is still in pandoc's own native
    style (underline-only, '~' -- not yet promoted to this project's
    convention). The second sibling's child was freshly hand-authored
    using the objectively CORRECT character for its depth ('=') directly,
    exactly per this project's own "declare intent with the correct
    character" workflow (docs/guide.rst).

    _compute_hierarchy_remap has no concept of nesting depth -- only
    first-appearance ORDER. Since '~' (destined to become '=', correct for
    this shared depth) appears earlier in raw document order than the
    already-correct '=' on the second sibling's child, the remap assigns
    '~' -> '=' (right, by luck of position) and then has NO SLOT left for
    the already-correct '=' except '-' (rank 4) -- silently corrupting an
    already-valid heading into one that skips a level. A real Sphinx build
    of the "fixed" output then rejects it: "Inconsistent title style: skip
    from level 2 to 4." Minimal repro, confirmed by direct computation
    (_compute_hierarchy_remap on the two-sibling shape alone returns
    {'~': '=', '=': '-'}) before writing this test.
    """
    p = _rst(
        tmp_path,
        """
        #####
        Title
        #####

        *********
        Section A
        *********

        ~~~~~~
        Sub A1
        ~~~~~~

        *********
        Section B
        *********

        ==========
        Composants
        ==========
        """,
    )

    _formatting.fix_structure(p, True)

    fixed = p.read_text(encoding="utf-8")
    assert "==========\nComposants\n==========" in fixed, (
        "the already-correct '=' heading must survive fix unchanged, not be remapped to '-'"
    )
    assert _formatting.check_hierarchy(p) == []


_MULTIWAY_BRANCH_ORDERS = list(itertools.permutations(("A", "B", "C")))

_MULTIWAY_BRANCH_CHARACTER_SETS = [
    pytest.param(
        {
            "root": ("#",),
            "fork": ("*",),
            "A": ("~",),
            "B": ("=", "-"),
            "C": ("^", '"', "!"),
        },
        id="mirrors_the_real_bug_preferred_plus_one_not_yet_promoted",
    ),
    pytest.param(
        {
            "root": ("#",),
            "fork": ("*",),
            "A": ("!",),
            "B": ("$", "%"),
            "C": ("&", "'", "("),
        },
        id="all_branch_local_characters_non_preferred",
    ),
]


def _multiway_branch_doc(order: Sequence[str], chars: dict[str, tuple[str, ...]]) -> str:
    """One root title, then — in `order` — three sibling sections all
    correctly reusing `chars["fork"]` (so all three are genuinely
    recognized as the SAME real depth, exactly as true sibling headings
    must: docutils infers depth from character reuse, not from visual
    tree position — see the sibling-branch test above), each followed by
    its own descending chain of new, never-before-seen characters going 1,
    2, and 3 levels deeper respectively ("A" shallowest, "C" deepest).

    This is the general, multi-way form of that same test's two-sibling
    shape: branches "A"/"B"/"C"'s first descendants all collide at the
    same real depth (three-way, not just two), and "B"/"C"'s second
    descendants collide one level deeper again (two-way) — regardless of
    which order the three branches are laid out in the file, which is
    exactly the axis the original bug was sensitive to (it keyed the
    remap on raw first-appearance ORDER).
    """
    parts = [_hierarchy_chain_block(chars["root"][0], "Root")]
    for name in order:
        parts.append(_hierarchy_chain_block(chars["fork"][0], f"Branch {name}"))
        branch_chars = chars[name]
        titles = [f"Branch {name} Level {i}" for i in range(1, len(branch_chars) + 1)]
        parts.extend(_hierarchy_chain_block(ch, t) for ch, t in zip(branch_chars, titles, strict=True))
    return "\n\n".join(parts) + "\n"


@pytest.mark.integration
@pytest.mark.parametrize("order", _MULTIWAY_BRANCH_ORDERS)
@pytest.mark.parametrize("chars", _MULTIWAY_BRANCH_CHARACTER_SETS)
def test_fix_hierarchy_multiway_branch_collisions_converge_regardless_of_branch_order(
    tmp_path: Path, chars: dict[str, tuple[str, ...]], order: tuple[str, ...]
) -> None:
    """Generalizes the single hand-picked sibling-branch case above: three
    sibling branches ("A" 1 level deep, "B" 2, "C" 3) collide three-way at
    their shared first-descendant depth and two-way one level deeper,
    exhaustively over all 3! = 6 orders the branches can appear in the
    file — the axis the original bug was actually sensitive to — crossed
    with two different character assignments for extra confidence.

    Deliberately does NOT exhaustively permute character identity the way
    the linear-chain test does: _established_depths never branches on a
    character's identity, only on "have I seen this exact character
    before" (a dict lookup), so for a fixed document layout the result is
    invariant under relabeling which literal character fills which slot —
    permuting labels here would add cases without adding coverage.
    Permuting file ORDER does add coverage, because the bug this guards
    against was specifically about raw scan position leaking into the
    remap.
    """
    expected_chars: dict[str, tuple[str, ...]] = {
        "root": (_helpers.HIERARCHY[0],),
        "fork": (_helpers.HIERARCHY[1],),
        "A": (_helpers.HIERARCHY[2],),
        "B": (_helpers.HIERARCHY[2], _helpers.HIERARCHY[3]),
        "C": (_helpers.HIERARCHY[2], _helpers.HIERARCHY[3], _helpers.HIERARCHY[4]),
    }

    p = tmp_path / "test.rst"
    p.write_text(_multiway_branch_doc(order, chars), encoding="utf-8")

    _formatting.fix_structure(p, True)

    assert p.read_text(encoding="utf-8") == _multiway_branch_doc(order, expected_chars)
    _assert_hierarchy_structurally_correct(p)


@pytest.mark.integration
def test_diff_structure_hierarchy_returns_diff(tmp_path: Path) -> None:
    """diff_structure returns a unified diff when hierarchy fixes are needed."""
    p = _rst(
        tmp_path,
        """\
        ######
        Top
        ######

        =====
        Sub
        =====
        """,
    )
    diff = _formatting.diff_structure(p, True)
    assert diff
    assert "---" in diff
    assert "-=====" in diff  # original underline in diff
    assert "+*****" in diff  # replacement in diff
    assert "=====\nSub\n=====" in p.read_text(encoding="utf-8")  # file not modified


@pytest.mark.integration
def test_diff_structure_hierarchy_clean_empty(tmp_path: Path) -> None:
    """diff_structure returns empty string when no fixes are needed."""
    p = _rst(
        tmp_path,
        """\
        #####
        Top
        #####

        *****
        Mid
        *****
        """,
    )
    assert _formatting.diff_structure(p, True) == ""


@pytest.mark.integration
def test_changed_rst_files_decodes_git_quoted_non_ascii_path(rst_repo: Path) -> None:
    """Bare discovery must return the real path, not Git's octal escapes."""
    _git(rst_repo, "config", "core.quotePath", "true")
    p = rst_repo / "документ.rst"
    p.write_text("", encoding="utf-8")

    assert _helpers._changed_rst_files() == [p]


@pytest.mark.integration
def test_changed_rst_files_skips_deleted_paths(rst_repo: Path) -> None:
    """A deleted document has no working-tree file left for check_rst to read."""
    p = rst_repo / "deleted.rst"
    p.write_text("", encoding="utf-8")
    _git(rst_repo, "add", "deleted.rst")
    _git(rst_repo, "commit", "-m", "add document")
    p.unlink()

    assert _helpers._changed_rst_files() == []


@pytest.mark.integration
def test_changed_rst_files_works_before_any_commit_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A brand-new repository with zero commits (unborn HEAD) is a real,
    legitimate state to run check_rst in — bucketed with the pygit2 migration
    since Git status needs no HEAD to exist, but a same-shaped diff-based
    query does (confirmed live: it raises KeyError, not a tolerable
    failure), so this scenario must keep using the status-based path, not
    silently regress onto the diff-based non-UTF-8-filename fallback."""
    _git(tmp_path, "init")
    monkeypatch.setattr(_helpers, "PROJECT_ROOT", tmp_path)
    p = tmp_path / "new.rst"
    p.write_text("", encoding="utf-8")
    _git(tmp_path, "add", "new.rst")

    assert _helpers._changed_rst_files() == [p]


@pytest.mark.integration
def test_changed_rst_files_supports_non_utf8_path_before_any_commit_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The non-UTF-8 status fallback must not require an existing HEAD."""
    _git(tmp_path, "init")
    monkeypatch.setattr(_helpers, "PROJECT_ROOT", tmp_path)
    raw_path = os.fsencode(tmp_path) + b"/non_utf8_\xff.rst"
    fd = os.open(raw_path, os.O_WRONLY | os.O_CREAT, 0o600)
    os.close(fd)
    path = Path(os.fsdecode(raw_path))
    _git(tmp_path, "add", path.name)

    assert _helpers._changed_rst_files() == [path]


@pytest.mark.integration
def test_changed_rst_files_staged_rename_returns_only_the_new_path(rst_repo: Path) -> None:
    """A staged ``git mv`` reports one porcelain "R" entry carrying both the
    new and the dead original path; only the new (existing) path must survive
    into the returned list — pinned as a characterization test ahead of the
    pygit2 migration, since no prior test exercised a rename."""
    original = rst_repo / "original.rst"
    original.write_text("", encoding="utf-8")
    _git(rst_repo, "add", "original.rst")
    _git(rst_repo, "commit", "-m", "add document")
    _git(rst_repo, "mv", "original.rst", "renamed.rst")

    assert _helpers._changed_rst_files() == [rst_repo / "renamed.rst"]


@pytest.mark.integration
def test_changed_rst_files_from_nested_directory_uses_worktree_root(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Porcelain -z paths are worktree-root-relative, even from a subdirectory."""
    p = rst_repo / "changed.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    _git(rst_repo, "add", "changed.rst")
    _git(rst_repo, "commit", "-m", "add document")
    p.write_text(_GOOD_BLOCK + "\nChanged.\n", encoding="utf-8")
    nested = rst_repo / "nested"
    nested.mkdir()
    monkeypatch.setattr(_helpers, "PROJECT_ROOT", nested)

    assert _helpers._changed_rst_files() == [p]


@pytest.mark.integration
def test_changed_rst_files_supports_non_utf8_git_filename(rst_repo: Path) -> None:
    """Git filenames are byte strings; porcelain -z must use surrogateescape."""
    raw_path = os.fsencode(rst_repo) + b"/non_utf8_\xff.rst"
    fd = os.open(raw_path, os.O_WRONLY | os.O_CREAT, 0o600)
    os.close(fd)

    assert _helpers._changed_rst_files() == [Path(os.fsdecode(raw_path))]


@pytest.mark.integration
def test_changed_rst_files_preserves_non_repository_git_failure(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A corrupt index is not falsely diagnosed as 'not a git repository'."""

    def _raise_corrupt_index(self: pygit2.Repository, **_kwargs: object) -> dict[str, int]:
        raise pygit2.GitError("index file corrupt")

    monkeypatch.setattr(pygit2.Repository, "status", _raise_corrupt_index)

    with pytest.raises(SystemExit) as exc:
        _helpers._changed_rst_files()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "git status failed" in out
    assert "index file corrupt" in out
    assert "not a git repository" not in out


@pytest.mark.integration
def test_whole_file_catches_preexisting_error_in_committed_file(rst_repo: Path) -> None:
    """A fully committed file with no pending changes: diff-scoped (default
    for auto-detected files) finds nothing, whole_file=True (what the CLI
    uses for explicitly-named files) finds the pre-existing adornment error."""
    p = rst_repo / "test.rst"
    p.write_text(_BAD_BLOCK, encoding="utf-8")
    _git(rst_repo, "add", "test.rst")
    _git(rst_repo, "commit", "-m", "add file with a pre-existing error")

    assert _formatting.check_adornments(p, whole_file=False) == []

    violations = _formatting.check_adornments(p, whole_file=True)
    assert violations
    assert any("must be 7 chars" in v for v in violations)


@pytest.mark.integration
def test_default_ignores_committed_error_but_catches_unstaged_addition(
    rst_repo: Path,
) -> None:
    """Diff-scoped (whole_file=False) restricts to changed lines: a new
    unstaged addition is flagged, but a pre-existing committed error
    elsewhere in the same file is left alone; whole_file=True catches both."""
    p = rst_repo / "test.rst"
    p.write_text(_BAD_BLOCK, encoding="utf-8")
    _git(rst_repo, "add", "test.rst")
    _git(rst_repo, "commit", "-m", "add file with a pre-existing error")

    # Unstaged working-tree edit: append a new, differently-broken title.
    p.write_text(_BAD_BLOCK + _APPENDED_UNDERLINE_ONLY, encoding="utf-8")

    default_violations = _formatting.check_adornments(p, whole_file=False)
    assert any("underline-only" in v for v in default_violations)
    assert not any("must be 7 chars" in v for v in default_violations)

    all_violations = _formatting.check_adornments(p, whole_file=True)
    assert any("underline-only" in v for v in all_violations)
    assert any("must be 7 chars" in v for v in all_violations)


@pytest.mark.integration
def test_default_catches_error_in_staged_change(rst_repo: Path) -> None:
    """A staged (git add, not committed) change is diffed against HEAD, so
    diff-scoped (whole_file=False) still catches its errors."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    _git(rst_repo, "add", "test.rst")
    _git(rst_repo, "commit", "-m", "add clean file")

    p.write_text(_GOOD_BLOCK + _APPENDED_UNDERLINE_ONLY, encoding="utf-8")
    _git(rst_repo, "add", "test.rst")  # staged, not committed

    assert _formatting.check_adornments(p, whole_file=False) != []


@pytest.mark.integration
def test_default_catches_error_in_unstaged_change(rst_repo: Path) -> None:
    """A tracked file edited but not staged is still diffed against HEAD, so
    diff-scoped (whole_file=False) catches errors in the unstaged edit."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    _git(rst_repo, "add", "test.rst")
    _git(rst_repo, "commit", "-m", "add clean file")

    p.write_text(_GOOD_BLOCK + _APPENDED_UNDERLINE_ONLY, encoding="utf-8")  # unstaged

    assert _formatting.check_adornments(p, whole_file=False) != []


@pytest.mark.integration
def test_default_catches_error_in_untracked_new_file(rst_repo: Path) -> None:
    """An untracked (never git-added) file is always checked in full, even
    with whole_file=False — there is no HEAD state to diff against."""
    p = rst_repo / "new.rst"
    p.write_text(_BAD_BLOCK, encoding="utf-8")  # not added to git at all

    violations = _formatting.check_adornments(p, whole_file=False)
    assert any("must be 7 chars" in v for v in violations)


@pytest.mark.integration
def test_cli_explicit_file_is_whole_file_auto_detect_is_diff_scoped(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """End-to-end CLI rule: main() sets whole_file from bool(args.files).

    Auto-detected (no file args, git status) stays diff-scoped; naming the
    same file explicitly on the command line checks it in full instead —
    there is no --all flag, the file list itself is the signal.
    """
    p = rst_repo / "test.rst"
    p.write_text(_BAD_BLOCK, encoding="utf-8")
    _git(rst_repo, "add", "test.rst")
    _git(rst_repo, "commit", "-m", "add file with a pre-existing error")

    # Unstaged addition — the file reappears in `git status`, but the
    # pre-existing "must be 7 chars" error sits outside the changed lines.
    p.write_text(_BAD_BLOCK + _APPENDED_UNDERLINE_ONLY, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check"])
    with pytest.raises(SystemExit) as auto_exit:
        cli.main()
    assert auto_exit.value.code == 1
    auto_out = capsys.readouterr().out
    assert "underline-only" in auto_out
    assert "must be 7 chars" not in auto_out

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as explicit_exit:
        cli.main()
    assert explicit_exit.value.code == 1
    explicit_out = capsys.readouterr().out
    assert "underline-only" in explicit_out
    assert "must be 7 chars" in explicit_out


@pytest.mark.integration
def test_cli_deduplicates_repeated_explicit_file_arguments(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "doc.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(document), str(document.resolve())])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert "1 file(s) checked" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_git_scope_fix_changes_only_selected_changed_file(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An explicit allowlist keeps bare Git scoping without selecting an
    unrelated dirty RST file from the shared worktree."""
    selected = rst_repo / "selected.rst"
    unrelated = rst_repo / "unrelated.rst"
    for path in (selected, unrelated):
        path.write_text(_GOOD_BLOCK, encoding="utf-8")
    _git(rst_repo, "add", "selected.rst", "unrelated.rst")
    _git(rst_repo, "commit", "-m", "clean base")
    selected.write_text(_BAD_BLOCK, encoding="utf-8")
    unrelated.write_text(_BAD_BLOCK, encoding="utf-8")
    unrelated_before = unrelated.read_bytes()
    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", "--git-scope", str(selected)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert selected.read_text(encoding="utf-8") == _GOOD_BLOCK
    assert unrelated.read_bytes() == unrelated_before
    assert str(unrelated) not in capsys.readouterr().out


@pytest.mark.integration
def test_cli_git_scope_preserves_diff_scope_for_selected_file(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Naming a file with --git-scope must not expose its committed,
    pre-existing formatting error to a whole-file check."""
    selected = rst_repo / "selected.rst"
    selected.write_text(_BAD_BLOCK, encoding="utf-8")
    _git(rst_repo, "add", "selected.rst")
    _git(rst_repo, "commit", "-m", "historical error")
    selected.write_text(_BAD_BLOCK + "\nChanged.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--git-scope", str(selected)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert "must be 7 chars" not in capsys.readouterr().out


@pytest.mark.integration
def test_cli_git_scope_fix_fails_closed_when_diff_is_unavailable(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A Git failure must not turn selective mutation into a whole-file fix."""
    document = rst_repo / "document.rst"
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    _git(rst_repo, "add", "document.rst")
    _git(rst_repo, "commit", "-m", "committed historical defect")
    original = _BAD_BLOCK + "\nChanged prose.\n"
    document.write_text(original, encoding="utf-8")

    def fail_diff(self: pygit2.Repository, *_args: object, **_kwargs: object) -> object:
        raise pygit2.GitError("object database corrupt")

    monkeypatch.setattr(pygit2.Repository, "diff", fail_diff)
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "fix", "--git-scope", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert document.read_text(encoding="utf-8") == original
    output = capsys.readouterr().out
    assert "git diff failed" in output
    assert "object database corrupt" in output
    assert "0 file(s) fixed" in output


@pytest.mark.integration
@pytest.mark.parametrize("selection", ["bare", "git-scope"])
@pytest.mark.parametrize("verb_tail", [["fix"], ["fix", "--fast"]], ids=["fix", "fix-fast"])
def test_git_scoped_fix_reflows_adornments_when_only_title_text_changed(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    selection: str,
    verb_tail: list[str],
) -> None:
    document = rst_repo / "selected.rst"
    document.write_text("#######\nTitle\n#######\n", encoding="utf-8")
    _git(rst_repo, "add", "selected.rst")
    _git(rst_repo, "commit", "-m", "clean title")
    document.write_text("#######\nLonger Title\n#######\n", encoding="utf-8")
    argv = ["check_rst.py", *verb_tail]
    if selection == "git-scope":
        argv.extend(["--git-scope", str(document)])
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    expected = "#" * (len("Longer Title") + 2)
    assert document.read_text(encoding="utf-8") == (f"{expected}\nLonger Title\n{expected}\n")


@pytest.mark.integration
def test_cli_git_scope_unchanged_file_is_not_selected(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    selected = rst_repo / "selected.rst"
    selected.write_text(_BAD_BLOCK, encoding="utf-8")
    _git(rst_repo, "add", "selected.rst")
    _git(rst_repo, "commit", "-m", "unchanged historical file")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--git-scope", str(selected)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "no selected changed .rst files" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_cli_git_scope_rejects_file_outside_selected_worktree_before_fix(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    selected = rst_repo / "selected.rst"
    selected.write_text(_GOOD_BLOCK, encoding="utf-8")
    _git(rst_repo, "add", "selected.rst")
    _git(rst_repo, "commit", "-m", "clean base")
    selected_original = "\ufeff" + _GOOD_BLOCK
    selected.write_text(selected_original, encoding="utf-8")
    outside = rst_repo.parent / "outside.rst"
    outside.write_text(_BAD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "fix", "--git-scope", str(selected), str(outside)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert selected.read_text(encoding="utf-8") == selected_original
    out = capsys.readouterr().out
    assert "outside the selected Git worktree" in out
    assert "Phase 1" not in out


@pytest.mark.unit
def test_compute_structure_fixes_remapped_lines_join_scope() -> None:
    """When the remap fires, the blocks it rewrites get canonical geometry
    in the SAME pass, even though they sit outside the changed ranges."""
    lines = (_WIDE_STARRED_DOC + _APPENDED_THIRD_LEVEL).splitlines()
    appended_start = len(_WIDE_STARRED_DOC.splitlines()) + 1
    ranges = [(appended_start, appended_start + 6)]

    fixed = "\n".join(_formatting._compute_structure_fixes(lines, ranges))

    assert "#######\nTitle\n#######" in fixed
    assert "*********\nSection\n*********" in fixed
    assert "=======\nAdded\n=======" in fixed
    assert "*" * 22 not in fixed
    assert "=" * 22 not in fixed


@pytest.mark.unit
def test_compute_structure_fixes_no_remap_keeps_diff_scope() -> None:
    """No remap → the diff-scope promise holds unchanged: a pre-existing
    wrong-width block outside the changed ranges stays untouched."""
    base = textwrap.dedent("""\
        ##########
        Title
        ##########

        Text.
        """)
    appended = textwrap.dedent("""
        ******
        Sub
        ******

        More.
        """)
    lines = (base + appended).splitlines()
    appended_start = len(base.splitlines()) + 1
    ranges = [(appended_start, appended_start + 6)]

    fixed = "\n".join(_formatting._compute_structure_fixes(lines, ranges))

    assert "##########\nTitle\n##########" in fixed  # out of scope: kept
    assert "*****\nSub\n*****" in fixed  # in scope: width fixed


@pytest.mark.integration
def test_cli_bare_fix_converges_in_one_pass_when_remap_fires(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The downstream-project two-pass defect, end to end: commit a wide '*'-rooted doc,
    append a section, run bare --fix ONCE — the immediately following bare
    check (step 3 of the loop) must already be clean."""
    p = rst_repo / "doc.rst"
    p.write_text(_WIDE_STARRED_DOC, encoding="utf-8")
    _git(rst_repo, "add", "doc.rst")
    _git(rst_repo, "commit", "-m", "wide starred doc")
    p.write_text(_WIDE_STARRED_DOC + _APPENDED_THIRD_LEVEL, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix"])
    with pytest.raises(SystemExit) as fix_exit:
        cli.main()
    assert fix_exit.value.code == 0
    capsys.readouterr()

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check"])
    with pytest.raises(SystemExit) as check_exit:
        cli.main()
    out = capsys.readouterr().out
    assert "ERROR" not in out
    assert check_exit.value.code == 0


@pytest.mark.integration
def test_cli_bare_diff_previews_composed_result(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--diff must preview what one --fix run would produce: remapped chars
    AT canonical widths, never the remap-only intermediate state."""
    p = rst_repo / "doc.rst"
    p.write_text(_WIDE_STARRED_DOC, encoding="utf-8")
    _git(rst_repo, "add", "doc.rst")
    _git(rst_repo, "commit", "-m", "wide starred doc")
    p.write_text(_WIDE_STARRED_DOC + _APPENDED_THIRD_LEVEL, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "diff"])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out

    assert "+#######\n" in out  # Title block, remapped AND resized
    assert "+" + "#" * 22 not in out  # the intermediate must not appear


@pytest.mark.integration
def test_skip_fixable_suppresses_width_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Width-mismatch errors are suppressed from output with --skip-fixable."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        ######
        Title
        ######

        More text.
        """,
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--skip-fixable", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "must be 7 chars" not in out
    assert "adornments + hierarchy OK" not in out
    assert "1 auto-fixable finding(s) suppressed" in out


@pytest.mark.integration
def test_skip_fixable_suppresses_underline_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Underline-only title errors are suppressed with --skip-fixable."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        Title
        -------

        More text.
        """,
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--skip-fixable", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "underline-only" not in out


@pytest.mark.integration
def test_skip_fixable_suppresses_hierarchy_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Hierarchy-order errors (prefix-rule violations) are suppressed with
    --skip-fixable — they are exactly what --fix's remap resolves."""
    p = _rst(
        tmp_path,
        """\
        ######
        Top
        ######

        =====
        Sub
        =====
        """,
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--skip-fixable", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--fix remaps" not in out


@pytest.mark.integration
def test_skip_fixable_preserves_single_top_level_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A second top-level title is not --fix-fixable (which section should
    demote is a content decision), so --skip-fixable must not swallow it —
    so severity and fixability must remain independent."""
    p = _rst(
        tmp_path,
        """\
        #####
        First
        #####

        ######
        Second
        ######
        """,
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--skip-fixable", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "top-level" in out
    assert "ERROR:" in out
    assert "nine-character" in out
    assert "unused" in out
    assert "check_rst fix" in out


@pytest.mark.integration
def test_cli_json_single_top_level_error_is_non_fixable(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "#####\nFirst\n#####\n\n######\nSecond\n######\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    data = json.loads(capsys.readouterr().out)
    findings = data["files"][0]["findings"]
    assert any(f["severity"] == "ERROR" and f["fixable"] is False and "top-level" in f["text"] for f in findings)


@pytest.mark.integration
def test_skip_fixable_mixed_shows_only_warnings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """File with both a width error and a bold heading: only WARNING shown, exit 0."""
    p = _rst(
        tmp_path,
        """\
        ######
        Title
        ######

        **Bold Heading**

        Some text.
        """,
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--skip-fixable", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "must be 7 chars" not in out
    assert "WARNING:" in out


@pytest.mark.integration
def test_skip_fixable_suppresses_sphinx_structural_duplicate_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verified pre-fix output keeps a broken reference for human review,
    but not Sphinx's duplicate of a Phase-1 auto-fixable title defect."""
    (tmp_path / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    document = tmp_path / "index.rst"
    document.write_text(
        "######\nTitle\n######\n\nText.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        _sphinx,
        "run_sphinx",
        lambda *_args: [
            _types.Finding(1, _types.Severity.WARNING, "index.rst: Title overline too short."),
            _types.Finding(
                5,
                _types.Severity.WARNING,
                "index.rst: toctree contains reference to nonexisting document 'missing'",
            ),
        ],
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(tmp_path),
            "--build-dir",
            str(tmp_path / "_build"),
            "check",
            "--skip-fixable",
            str(document),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Title overline too short" not in out
    assert "Title underline too short" not in out
    assert "nonexisting document" in out
    assert "1 warning(s)" in out


@pytest.mark.integration
def test_without_skip_fixable_width_error_exits_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without --skip-fixable, width errors are shown and exit code is 1 (regression guard)."""
    p = _rst(
        tmp_path,
        """\
        Some text.

        ######
        Title
        ######

        More text.
        """,
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "must be 7 chars" in out


@pytest.mark.integration
def test_adornments_bom_file_no_false_underline_only(tmp_path: Path) -> None:
    """Regression: a BOM glued to a valid overline made the overline invisible,
    the title was misdiagnosed as underline-only, and --fix inserted a
    duplicate overline.  Adornment checks now see BOM-stripped text."""
    p = tmp_path / "bom.rst"
    p.write_bytes(b"\xef\xbb\xbf#######\nTitle\n#######\n\nText.\n")

    assert _formatting.check_adornments(p, whole_file=True) == []
    assert _formatting.diff_structure(p, True) == ""


@pytest.mark.integration
def test_adornments_trailing_ws_overline_no_false_underline_only(
    tmp_path: Path,
) -> None:
    """Regression: '####### ' (trailing space) was not recognized as an
    overline — docutils strips it and accepts the title, but check_rst
    misdiagnosed underline-only and --fix inserted a duplicate overline."""
    p = tmp_path / "trailws.rst"
    p.write_bytes(b"####### \nTitle\n#######\n\nText.\n")

    violations = _formatting.check_adornments(p, whole_file=True)
    assert not any("underline-only" in v for v in violations)
    assert violations == []


@pytest.mark.integration
def test_adornments_cjk_title_uses_column_width(tmp_path: Path) -> None:
    """Regression: '日本語入門' is 5 code points but 10 columns; len()+2 = 7
    passed check_rst while docutils itself warned 'Title overline too short'.
    The +2 rule must use column width: expected adornment is 12."""
    bad = tmp_path / "cjk_bad.rst"
    bad.write_text("#######\n日本語入門\n#######\n\nText.\n", encoding="utf-8")
    violations = _formatting.check_adornments(bad, whole_file=True)
    assert any("must be 12 chars" in v for v in violations)

    good = tmp_path / "cjk_good.rst"
    good.write_text("############\n日本語入門\n############\n\nText.\n", encoding="utf-8")
    assert _formatting.check_adornments(good, whole_file=True) == []


@pytest.mark.integration
def test_fix_cjk_title_adornment_width(tmp_path: Path) -> None:
    """--fix on a CJK placeholder title produces column-width+2 adornments —
    output that docutils/Phase 3 accepts, so the fix loop converges."""
    p = tmp_path / "cjk_fix.rst"
    p.write_text("日本語入門\n---------\n\nText.\n", encoding="utf-8")

    assert _formatting.fix_structure(p, True) is True
    lines = p.read_text(encoding="utf-8").splitlines()
    # The lone '-' is the document's level 1, remapped to '#' in the same
    # pass — what the CLI always produced; the width is the point here.
    assert lines[0] == "#" * 12
    assert lines[1] == "日本語入門"
    assert lines[2] == "#" * 12


@pytest.mark.integration
def test_adornments_combining_accents_use_column_width(tmp_path: Path) -> None:
    """NFD combining accents: 'resume naive francais' written with NFD
    combining acute accents, diaeresis, and cedilla is 25 code points but
    21 columns — docutils counts combining marks as width 0.  A 23-char
    adornment (column width + 2) must be accepted; the historical len()+2
    rule demanded 27."""
    p = tmp_path / "nfd.rst"
    # NFD: acute, diaeresis, and cedilla as combining marks
    title = "re\u0301sume\u0301 nai\u0308ve franc\u0327ais"
    assert len(title) == 25  # 25 code points, 21 columns
    adorn = "#" * 23
    p.write_text(f"{adorn}\n{title}\n{adorn}\n\nText.\n", encoding="utf-8")
    assert _formatting.check_adornments(p, whole_file=True) == []


@pytest.mark.integration
def test_hierarchy_star_only_document_flagged(tmp_path: Path) -> None:
    """Regression: a document whose only level uses '*' (rank 2, never '#')
    passed check_hierarchy with NO finding, while fix_hierarchy rewrote
    every heading to '#' — a silent rewrite of a clean-checked file.
    The prefix rule flags it: '*' is document level 1, hierarchy level 1
    is '#'."""
    p = _rst(
        tmp_path,
        """\
        *********
        Title A
        *********

        Text.

        *********
        Title B
        *********
        """,
    )
    violations = _formatting.check_hierarchy(p)
    errors = [v for v in violations if v.severity == "ERROR"]
    assert len(errors) == 1
    assert any("hierarchy level 1 is '#'" in v for v in errors)
    assert _formatting.diff_structure(p, True) != ""


@pytest.mark.integration
def test_hierarchy_offset_consecutive_sequence_flagged(tmp_path: Path) -> None:
    """Regression: '*' then '=' is consecutive in HIERARCHY but offset from
    the top — the old transition-only check passed it while --fix remapped
    both characters.  The prefix rule reports one ERROR per remap pair."""
    p = _rst(
        tmp_path,
        """\
        *******
        First
        *******

        ========
        Second
        ========
        """,
    )
    errors = [v for v in _formatting.check_hierarchy(p) if v.severity == "ERROR"]
    assert len(errors) == 2


@pytest.mark.integration
@pytest.mark.parametrize(
    "content",
    [
        pytest.param("#######\nTitle\n#######\n", id="single-hash-clean"),
        pytest.param("#####\nTop\n#####\n\n*****\nMid\n*****\n", id="two-level-clean"),
        pytest.param("*******\nTitle\n*******\n", id="star-only-offset"),
        pytest.param("*****\nFirst\n*****\n\n=====\nSecond\n=====\n", id="offset-pair"),
        pytest.param("=====\nFirst\n=====\n\n#####\nSecond\n#####\n", id="reordered-pair"),
        pytest.param("~~~~~\nTitle\n~~~~~\n", id="non-preferred-only"),
    ],
)
def test_hierarchy_check_and_fix_agree(tmp_path: Path, content: str) -> None:
    """The unification invariant: check_hierarchy reports an ERROR if and
    only if the composed fixer would modify the file (the fixtures here are
    geometrically canonical, so any diff is the remap's) — and after fixing,
    the check is clean.  Both sides consume _compute_hierarchy_remap, so
    this holds by construction; the test pins it against regression."""
    p = tmp_path / "test.rst"
    p.write_text(content, encoding="utf-8")

    errors = [v for v in _formatting.check_hierarchy(p) if v.severity == "ERROR"]
    diff = _formatting.diff_structure(p, True)
    assert bool(errors) == bool(diff)

    _formatting.fix_structure(p, True)
    assert [v for v in _formatting.check_hierarchy(p) if v.severity == "ERROR"] == []


@pytest.mark.integration
def test_adornments_spaced_title_expected_width_is_stripped(tmp_path: Path) -> None:
    """Regression: for ' Title A ' with 9-char adornments the checker
    demanded 'must be 11 chars' (unstripped width) while --fix stripped the
    title and kept 9 — a target the fixer never produces.  The canonical
    rule measures the stripped title: 9 is already correct, so only the
    title-spaces error remains."""
    p = tmp_path / "spaced.rst"
    p.write_text("#########\n Title A \n#########\n\nText.\n", encoding="utf-8")

    violations = _formatting.check_adornments(p, whole_file=True)
    assert any("leading or trailing spaces" in v for v in violations)
    assert not any("must be" in v for v in violations)


@pytest.mark.integration
def test_adornments_spaced_title_wrong_length_reports_stripped_target(
    tmp_path: Path,
) -> None:
    """When a spaced title's adornments match its UNSTRIPPED width (11),
    the reported target must be the canonical one --fix produces (9),
    not the unstripped measurement."""
    p = tmp_path / "spaced.rst"
    p.write_text("###########\n Title A \n###########\n\nText.\n", encoding="utf-8")

    violations = _formatting.check_adornments(p, whole_file=True)
    assert any("must be 9 chars" in v for v in violations)
    assert any("leading or trailing spaces" in v for v in violations)


@pytest.mark.integration
def test_adornments_check_and_fix_agree_on_spaced_title(tmp_path: Path) -> None:
    """After fix_structure, the checker must be fully satisfied — the
    canonical values it validated are the ones the fixer applied."""
    p = tmp_path / "spaced.rst"
    p.write_text("###########\n Title A \n###########\n\nText.\n", encoding="utf-8")

    assert _formatting.fix_structure(p, True) is True
    assert _formatting.check_adornments(p, whole_file=True) == []
    assert p.read_text(encoding="utf-8") == "#########\nTitle A\n#########\n\nText.\n"


@pytest.mark.integration
def test_cli_summary_reports_line_statistics(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Footer statistics from Phase 0's read (Max, 2026-07-18): total lines
    and empty lines with their ratio.  Empty lines are RST's block
    delimiter, so the ratio is a quick structure signal (Max: "empty /
    total shows something as well"); the total tells an AI whether the
    file fits a full read before it opens it."""
    p = rst_repo / "test.rst"
    # _GOOD_BLOCK: 7 lines, 2 of them empty.
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    # Two-line footer (Max, 2026-07-18): run facts + character totals on
    # line 1, everything about lines on line 2 — no mixture.  lines:/
    # words: are --verbose-only (Max, 2026-07-20: verbosity-level
    # inventory).
    assert (
        "check_rst: 1 file(s) checked, 0 error(s), 0 warning(s), 46 char(s) (= bytes, 15 distinct, 7 once), 2 space(s) (4%)"
        in out
    )
    assert "lines: 7 total (2 empty, 29%), length min/avg/max 5/8/10 chars (= bytes)" in out
    # Word statistics (Max, 2026-07-19) — a raw-text Phase 0 measure:
    # whitespace-separated tokens, markup included ('#######' is a token).
    assert "words: 7 total, 5 distinct (3 once), length min/avg/max 4/5/7" in out


@pytest.mark.integration
def test_cli_summary_line_statistics_aggregate_across_files(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p1 = rst_repo / "a.rst"
    p2 = rst_repo / "b.rst"
    p1.write_text(_GOOD_BLOCK, encoding="utf-8")  # 7 lines, 2 empty
    p2.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p1), str(p2)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    # Two identical files: same repertoire, nothing occurs once anymore.
    assert "92 char(s) (= bytes, 15 distinct, 0 once), 4 space(s) (4%)" in out
    assert "lines: 14 total (4 empty, 29%), length min/avg/max 5/8/10 chars (= bytes)" in out
    assert "words: 14 total, 5 distinct (0 once), length min/avg/max 4/5/7" in out


@pytest.mark.integration
def test_cli_non_utf8_file_clean_error_not_traceback(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A non-UTF-8 file must produce a clean per-file ERROR and exit 1 —
    found by probe (2026-07-18): Phase 0's decode crashed with a raw
    UnicodeDecodeError traceback, the same traceback-instead-of-diagnostic
    class as the not-a-git-repo case."""
    p = rst_repo / "latin1.rst"
    p.write_bytes(b"Title\n=====\n\nLatin-1 caf\xe9 here.\n")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "not valid UTF-8" in out
    # Line number computed from the raw bytes (no decoding needed), and the
    # remedy shape handed to the human with the one fact only they have —
    # the source encoding — left blank.  Detection is the tool's half;
    # choosing the encoding is the human's half, so this ERROR is never
    # --fix-able and survives --skip-fixable.
    assert "byte offset 24, line 4" in out
    assert "iconv -f <encoding> -t utf-8" in out


@pytest.mark.integration
def test_cli_summary_shows_bytes_when_differs_from_chars(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Symbols vs bytes (Max, 2026-07-18): two numbers when they differ
    (non-ASCII content), one with '(= bytes)' when they coincide — the
    ASCII case is pinned by the tests above."""
    p = rst_repo / "test.rst"
    p.write_text("########\nR\u00e9sum\u00e9\n########\n\nCaf\u00e9.\n", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "char(s) (" in out  # distinct/once detail binds to chars
    assert "byte(s)" in out
    assert "= bytes" not in out  # differ form: bytes shown, no collapse note
    # Line-length spread differs too (Cyrillic-free but non-ASCII lines):
    # both triples shown, no collapse.  lines:/words: are --verbose-only
    # (Max, 2026-07-20: verbosity-level inventory).
    assert " chars / " in out


@pytest.mark.integration
def test_cli_json_lists(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text("Title\n#####\n\n* One.\n* Two.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    data = json.loads(capsys.readouterr().out)
    lists = data["files"][0]["lists"]
    assert len(lists) == 3  # 1 container + 2 items
    assert lists[0]["kind"] == "bullet"
    assert lists[0]["item_count"] == 2


@pytest.mark.integration
def test_cli_json_tables(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "Title\n=====\n\n=====  =====\nA      B\n=====  =====\n1      2\n=====  =====\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    data = json.loads(capsys.readouterr().out)
    tables = data["files"][0]["tables"]
    assert len(tables) == 1
    assert tables[0]["kind"] == "simple"
    assert tables[0]["dims"] == [2, 2]
    assert tables[0]["preview"] == "A B 1 2"
