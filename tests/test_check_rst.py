# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Regression suite for check_rst.cli — check_rst project
"""Tests for check_rst.cli — adornment, hierarchy, and directive checking.

Zones:
  unit        — _is_adornment: pure function, no I/O
  integration — check_adornments / check_hierarchy / check_directives:
                write minimal .rst content to tmp_path and assert violations
"""

from __future__ import annotations

import itertools
import json
import os
import re
import subprocess
import sys
import textwrap
import types
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any


@pytest.fixture(scope="session")
def check_rst() -> types.ModuleType:
    """Return the installed-layout implementation module once per session."""
    from check_rst import cli

    return cli


def _rst(tmp_path: Path, content: str) -> Path:
    """Write dedented RST content to a temp file and return its path."""
    p = tmp_path / "test.rst"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# _is_adornment — pure function → Zone 1
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("#####", True),
        ("***", True),
        ("===", True),
        ("---", True),
        ("^^^", True),
        ('"""', True),
        ("#", True),  # single char is valid
        ("", False),
        ("abc", False),
        ("# #", False),  # mixed content
        ("~~~~", True),  # valid RST (docutils nonalphanum7bit), outside the project's
        ("++++", True),  # own preferred hierarchy #*=-^" — still a real adornment
        ("````", True),  # (see check_hierarchy's WARNING for this distinction)
        ("——", False),  # em-dash: non-alphanumeric but non-ASCII, outside docutils'
        (" ###", False),  # leading space
        ("..", False),  # exactly the docutils comment marker — explicit markup takes
        ("...", True),  # precedence over a title line, so '..' is never an adornment;
        ("....", True),  # three or more dots don't match the comment pattern and stay valid
    ],
)
def test_is_adornment(check_rst: types.ModuleType, line: str, expected: bool) -> None:
    assert check_rst._is_adornment(line) == expected


# ---------------------------------------------------------------------------
# check_adornments — reads a file → Zone 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_adornments_correct_block(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    assert check_rst.check_adornments(p, True) == []


@pytest.mark.integration
def test_adornments_underline_only_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_adornments(p, True)
    assert violations
    assert any("underline-only" in v for v in violations)


@pytest.mark.integration
def test_adornments_underline_shorter_than_title_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_adornments(p, True)
    assert violations
    assert any("underline-only" in v for v in violations)


@pytest.mark.integration
def test_adornments_underline_below_absolute_minimum_not_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    assert check_rst.check_adornments(p, True) == []


@pytest.mark.integration
def test_adornments_underline_at_absolute_minimum_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """An underline exactly at MIN_UNDERLINE_ONLY_LEN is flagged."""
    p = _rst(
        tmp_path,
        f"""\
        Some text.

        A Longer Title
        {"-" * check_rst.MIN_UNDERLINE_ONLY_LEN}

        More text.
        """,
    )
    violations = check_rst.check_adornments(p, True)
    assert violations
    assert any("underline-only" in v for v in violations)


@pytest.mark.integration
def test_adornments_wrong_length_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_adornments(p, True)
    assert violations
    assert any("must be 7 chars" in v for v in violations)


@pytest.mark.integration
def test_adornments_non_preferred_char_wrong_length_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_adornments(p, True)
    assert violations
    assert any("must be 7 chars" in v for v in violations)


@pytest.mark.integration
def test_adornments_non_preferred_char_underline_only_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_adornments(p, True)
    assert violations
    assert any("underline-only" in v for v in violations)


@pytest.mark.integration
def test_adornments_title_leading_space_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_adornments(p, True)
    assert violations
    assert any("leading or trailing spaces" in v for v in violations)


@pytest.mark.integration
def test_adornments_missing_blank_before_overline_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_adornments(p, True)
    assert violations
    assert any("before the overline" in v for v in violations)


@pytest.mark.integration
def test_adornments_missing_blank_after_underline_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_adornments(p, True)
    assert violations
    assert any("after the underline" in v for v in violations)


@pytest.mark.integration
def test_adornments_mismatched_chars_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_adornments(p, True)
    assert violations
    assert any("differs" in v for v in violations)


# ---------------------------------------------------------------------------
# check_hierarchy — reads a file → Zone 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_hierarchy_valid_consecutive_sequence(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    assert check_rst.check_hierarchy(p) == []


@pytest.mark.integration
def test_hierarchy_all_six_levels_valid_sequence(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    assert check_rst.check_hierarchy(p) == []


@pytest.mark.integration
def test_hierarchy_twelve_levels_beyond_preferred_six(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A 12-level-deep document — double the preferred hierarchy's 6 — using
    HIERARCHY[:12] in order is fully valid: no skipped-level ERRORs, proving
    the extended ranking genuinely supports depth beyond the preferred 6,
    not just up to it. The 6 characters past the preferred set (positions
    7-12) each get exactly one non-preferred-character WARNING, at their
    first (and in this test, only) appearance.
    """
    chars = check_rst.HIERARCHY[:12]
    titles = [f"Level {i}" for i in range(1, 13)]

    def block(ch: str, title: str) -> str:
        adorn = ch * (len(title) + 2)
        return f"{adorn}\n{title}\n{adorn}"

    content = "\n\n".join(block(ch, t) for ch, t in zip(chars, titles, strict=True)) + "\n"
    p = tmp_path / "test.rst"
    p.write_text(content, encoding="utf-8")

    violations = check_rst.check_hierarchy(p)
    errors = [v for v in violations if v.severity == "ERROR"]
    assert errors == []

    warnings = [v for v in violations if v.severity == "WARNING"]
    assert len(warnings) == 6  # positions 7-12: past the preferred 6


@pytest.mark.integration
def test_hierarchy_full_reverse_order_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_hierarchy(p)
    assert len(violations) == 6
    assert all("--fix remaps" in v for v in violations)


@pytest.mark.integration
def test_hierarchy_skip_level_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_hierarchy(p)
    assert violations
    assert any("hierarchy level 2 is '*'" in v for v in violations)


@pytest.mark.integration
def test_hierarchy_inconsistent_order_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_hierarchy(p)
    assert len(violations) == 2
    assert all("--fix remaps" in v for v in violations)


@pytest.mark.integration
def test_hierarchy_single_level_ok(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    assert check_rst.check_hierarchy(p) == []


@pytest.mark.integration
def test_hierarchy_non_preferred_char_alone_warns_and_errors(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_hierarchy(p)
    warnings = [v for v in violations if v.severity == "WARNING"]
    errors = [v for v in violations if v.severity == "ERROR"]
    assert len(warnings) == 1
    assert any("preferred hierarchy" in v for v in warnings)
    assert len(errors) == 1
    assert any("hierarchy level 1 is '#'" in v for v in errors)


@pytest.mark.integration
def test_hierarchy_non_preferred_char_warned_once_per_char(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_hierarchy(p)
    assert len([v for v in violations if "preferred hierarchy" in v]) == 1


@pytest.mark.integration
def test_hierarchy_non_preferred_char_participates_in_order_check(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_hierarchy(p)
    errors = [v for v in violations if v.severity == "ERROR"]
    assert errors
    assert any("hierarchy level 2 is '*'" in v for v in errors)


# ---------------------------------------------------------------------------
# check_single_top_level — a document may have only one level-1 title
# (Max, 2026-07-23: "the level-1 heading can only be one — it represents the
# document's title").  docutils accepts a second top-level section as
# perfectly valid syntax (confirmed live, 2026-07-26: a real sphinx-build at
# -vv/-n emits nothing), but neither section then gets promoted to the
# document's own <title> — confirmed by direct probe: the file's toctree
# entry in a real HTML build showed BOTH sections as separate toctree-l1
# entries instead of one.  WARNING, not ERROR: unlike adornment/hierarchy
# ERRORs, --fix cannot resolve this on its own (demoting one of the two
# sections is a real content decision), so it follows check_directives'
# severity convention, not check_hierarchy's.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_single_top_level_one_section_ok(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    assert check_rst.check_single_top_level(p) == []


@pytest.mark.integration
def test_single_top_level_empty_document_ok(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(tmp_path, "Just a paragraph, no titles at all.\n")
    assert check_rst.check_single_top_level(p) == []


@pytest.mark.integration
def test_single_top_level_two_sections_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_single_top_level(p)
    assert len(violations) == 1
    assert violations[0].severity == "WARNING"
    assert "Second" not in violations[0].text or "'#'" in violations[0].text
    assert violations[0].lineno == 8  # the second occurrence's own title line


@pytest.mark.integration
def test_single_top_level_three_sections_flags_second_and_third(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_single_top_level(p)
    assert len(violations) == 2
    assert [v.lineno for v in violations] == [6, 10]


@pytest.mark.integration
def test_single_top_level_underline_only_titles_also_counted(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_single_top_level(p)
    assert len(violations) == 1
    assert violations[0].lineno == 4


@pytest.mark.integration
def test_single_top_level_non_preferred_char_also_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_single_top_level(p)
    assert len(violations) == 1
    assert "'~'" in violations[0].text


@pytest.mark.integration
def test_single_top_level_repeated_subsection_char_not_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    assert check_rst.check_single_top_level(p) == []


# ---------------------------------------------------------------------------
# check_homoglyphs — a word mixing Cyrillic and Latin letters where EVERY
# minority-script letter is a known visual twin of a majority-script one
# (Max, 2026-07-24: "when letters look similar, but only one letter is from
# another alphabet").  "Line" was considered and rejected as the unit — this
# corpus is deliberately trilingual, so Cyrillic and Latin coexist on nearly
# every line; "word" (no punctuation/space inside it) is where a real
# keyboard-layout slip actually shows up.  Confirmed by a real corpus scan,
# 2026-07-26: of 14 total mixed-script words across the whole calendar, the
# genuine confusable typos ('Аuthor', 'вcе', 'Сalibration' x2, 'сpp') all  # noqa: RUF003
# have EVERY minority letter in the confusables table; the non-typos
# ('VPNом', 'кодbase', 'jьmati') each have at least one minority letter with  # noqa: RUF003
# no confusable counterpart at all (м, к, д, ь) — the "every minority letter
# must be confusable" rule separates them for free, not by a hand-tuned
# exception list.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_homoglyph_words_flags_confusable_minority(check_rst: types.ModuleType) -> None:
    # Cyrillic А (U+0410) + Latin "uthor" — the real corpus catch.  # noqa: RUF003
    matches = list(check_rst._homoglyph_words_in("See Аuthor for details."))  # noqa: RUF001
    assert len(matches) == 1
    assert matches[0][2] == "Аuthor"  # noqa: RUF001


@pytest.mark.unit
def test_homoglyph_words_ignores_pure_single_script(check_rst: types.ModuleType) -> None:
    assert list(check_rst._homoglyph_words_in("Purely English text here.")) == []
    assert list(check_rst._homoglyph_words_in("Совсем русский текст здесь.")) == []


@pytest.mark.unit
def test_homoglyph_words_ignores_non_confusable_minority_letter(
    check_rst: types.ModuleType,
) -> None:
    """'VPNом' — Latin majority 'VPN' + Cyrillic minority 'ом'; 'о' is
    confusable but 'м' is not, so NOT every minority letter qualifies."""  # noqa: RUF002
    assert list(check_rst._homoglyph_words_in("используя VPNом провод")) == []  # noqa: RUF001


@pytest.mark.unit
def test_homoglyph_words_ignores_tied_script_counts(check_rst: types.ModuleType) -> None:
    # One Cyrillic confusable + one Latin letter: 1-vs-1 is ambiguous, skip.
    assert list(check_rst._homoglyph_words_in("аb")) == []  # noqa: RUF001


@pytest.mark.unit
def test_homoglyph_words_ignores_legitimate_non_confusable_notation(
    check_rst: types.ModuleType,
) -> None:
    # 'jьmati' — Proto-Slavic notation; Cyrillic ь has no Latin confusable.
    assert list(check_rst._homoglyph_words_in("jьmati")) == []


@pytest.mark.integration
def test_check_homoglyphs_flags_known_confusable_typo(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n=====\n\nSee Аuthor for details.\n")  # noqa: RUF001
    violations = check_rst.check_homoglyphs(p)
    assert len(violations) == 1
    assert violations[0].severity == "WARNING"
    assert "Аuthor" in violations[0].text  # noqa: RUF001


@pytest.mark.integration
def test_check_homoglyphs_ignores_clean_trilingual_prose(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Cyrillic and Latin coexisting on the same line/paragraph — this
    corpus's normal case — must stay silent; only a single mixed-script
    WORD is ever suspicious."""
    p = _rst(
        tmp_path,
        "Title\n=====\n\nЗапустил check_rst и Sphinx, всё собралось чисто.\n",  # noqa: RUF001
    )
    assert check_rst.check_homoglyphs(p) == []


@pytest.mark.integration
def test_check_homoglyphs_skips_literal_block_content(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        "Title\n=====\n\n::\n\n    Аuthor in a code block.\n",  # noqa: RUF001
    )
    assert check_rst.check_homoglyphs(p) == []


@pytest.mark.integration
def test_check_homoglyphs_skips_comment_content(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n=====\n\n.. Аuthor in a comment.\n")  # noqa: RUF001
    assert check_rst.check_homoglyphs(p) == []


@pytest.mark.integration
def test_check_homoglyphs_does_not_skip_block_quote(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Unlike check_directives' bold/rubric exemption, quoted material is
    still checked — a garbled word is still garbled regardless of who
    originally typed it."""
    p = _rst(
        tmp_path,
        "Title\n=====\n\nHe wrote:\n\n    See Аuthor for details.\n",  # noqa: RUF001
    )
    assert len(check_rst.check_homoglyphs(p)) == 1


@pytest.mark.integration
def test_check_homoglyphs_lineno_precise_within_multiline_paragraph(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    """A docutils Text node spans the WHOLE paragraph, so the base line
    from _node_line alone would only ever report the paragraph's first
    line; the exact line comes from counting embedded newlines up to the
    match position within that node's own text."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        Line one of a paragraph that just keeps
        going for a while, and then eventually
        on this very line we hit Аuthor as a typo.
        """,  # noqa: RUF001
    )
    violations = check_rst.check_homoglyphs(p)
    assert len(violations) == 1
    assert violations[0].lineno == 6


@pytest.mark.integration
def test_check_homoglyphs_multiple_occurrences_all_reported(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        "Title\n=====\n\nАuthor wrote about Сalibration twice.\n",  # noqa: RUF001
    )
    assert len(check_rst.check_homoglyphs(p)) == 2


@pytest.mark.integration
def test_cli_homoglyphs_warning_shown(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = _rst(tmp_path, "Title\n=====\n\nSee Аuthor for details.\n")  # noqa: RUF001
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "WARNING:" in out
    assert "Аuthor" in out  # noqa: RUF001


@pytest.mark.integration
def test_cli_json_homoglyphs_included(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text("Title\n#####\n\nSee Аuthor for details.\n", encoding="utf-8")  # noqa: RUF001
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    findings = data["files"][0]["findings"]
    assert any(
        f["severity"] == "WARNING" and "Аuthor" in f["text"]  # noqa: RUF001
        for f in findings
    )


# ---------------------------------------------------------------------------
# check_directives — reads a file → Zone 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_directives_rubric_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A .. rubric:: directive must be flagged as a heading substitute."""
    p = _rst(tmp_path, ".. rubric:: My Heading\n\nSome text.\n")
    violations = check_rst.check_directives(p, True)
    assert violations
    assert any("rubric" in v for v in violations)


@pytest.mark.integration
def test_directives_indented_rubric_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """.. rubric:: inside a directive body must also be flagged.

    The fixture is a real directive body (a note admonition).  The
    original fixture was a bare indented rubric at document start —
    which docutils parses as a *blockquote*, not a directive body, so
    the test passed on a false premise; the blockquote exemption
    (quoted material is never a heading substitute) exposed it."""
    p = _rst(tmp_path, ".. note::\n\n   .. rubric:: My Heading\n\nSome text.\n")
    violations = check_rst.check_directives(p, True)
    assert violations
    assert any("rubric" in v for v in violations)


@pytest.mark.integration
def test_directives_bold_standalone_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A line consisting entirely of bold text must be flagged, by the
    actual text it names (see test_directives_standalone_bold_default_
    shows_actual_text — no generic '**...**' placeholder any more)."""
    p = _rst(tmp_path, "**Section Heading**\n\nSome text.\n")
    violations = check_rst.check_directives(p, True)
    assert violations
    assert any("Section Heading" in v for v in violations)


@pytest.mark.integration
def test_directives_bold_inline_ok(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Bold text within a sentence must NOT be flagged."""
    p = _rst(tmp_path, "Use **bold** for inline emphasis only.\n")
    assert check_rst.check_directives(p, True) == []


@pytest.mark.integration
def test_nested_inline_markup_mid_sentence_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """The dominant real corpus shape must not depend on paragraph position.

    Pandoc preserves Markdown's bold-around-code nesting even though RST does
    not render the inner role.  The old bold-opener check was silent when the
    malformed span occurred mid-sentence, which is where most corpus examples
    occur.
    """
    p = _rst(tmp_path, "Use **``XGrabServer()``** to lock the server.\n")

    findings = check_rst.check_nested_inline_markup(p, True)

    assert len(findings) == 1
    assert findings[0].severity == "WARNING"
    assert "nested inline markup in bold span" in findings[0].text
    assert "contains inline literal" in findings[0].text
    assert "XGrabServer" in findings[0].text


@pytest.mark.integration
def test_nested_inline_markup_reports_its_physical_line(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A multiline paragraph must not collapse every inline finding to line 1."""
    p = _rst(tmp_path, "The paragraph starts here\nand uses **``nested``** markup here.\n")

    findings = check_rst.check_nested_inline_markup(p, True)

    assert len(findings) == 1
    assert findings[0].lineno == 2


@pytest.mark.integration
def test_nested_inline_markup_diff_scope_uses_physical_line(check_rst: types.ModuleType, rst_repo: Path) -> None:
    """A new span on line 2 is in scope; an unchanged line-1 span is not."""
    p = rst_repo / "nested.rst"
    p.write_text("**``old``** starts this paragraph\nand continues plainly.\n", encoding="utf-8")
    _git(rst_repo, "add", "nested.rst")
    _git(rst_repo, "commit", "-m", "add nested fixture")
    p.write_text("**``old``** starts this paragraph\nand adds **``new``** markup.\n", encoding="utf-8")

    findings = check_rst.check_nested_inline_markup(p, False)

    assert len(findings) == 1
    assert findings[0].lineno == 2
    assert "new" in findings[0].text


@pytest.mark.integration
def test_nested_inline_markup_supersedes_heading_diagnosis(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A more specific syntax diagnosis must suppress misleading advice.

    Before this rule, a leading or standalone ``**``code``**`` span was
    reported as a heading substitute.  Promoting it to a section would not
    repair the lost inline styling, so check_directives must leave this node
    to the nested-markup finding.
    """
    p = _rst(tmp_path, "**``image->data``**\n")

    nested = check_rst.check_nested_inline_markup(p, True)
    directives = check_rst.check_directives(p, True)

    assert len(nested) == 1
    assert directives == []


@pytest.mark.integration
@pytest.mark.parametrize(
    ("source", "outer", "inner"),
    [
        ("``code **bold** code``\n", "inline literal", "bold"),
        ("*emphasized ``code`` text*\n", "emphasis", "inline literal"),
        ("**:strong:`role text`**\n", "bold", "bold"),
        ("**`Markdown title reference`**\n", "bold", "interpreted text"),
    ],
)
def test_nested_inline_markup_detects_both_directions_and_role_syntax(
    check_rst: types.ModuleType,
    tmp_path: Path,
    source: str,
    outer: str,
    inner: str,
) -> None:
    """Delegate delimiter and role recognition to docutils' own grammar."""
    p = _rst(tmp_path, source)

    findings = check_rst.check_nested_inline_markup(p, True)

    assert len(findings) == 1
    assert f"in {outer} span" in findings[0].text
    assert f"contains {inner}" in findings[0].text


@pytest.mark.unit
def test_findall_node_types_uses_callable_condition_for_docutils_022(check_rst: types.ModuleType) -> None:
    """Docutils 0.22 rejects a tuple passed directly as Node.findall's
    condition; the compatibility adapter must use the callable form accepted
    by both 0.22 and 0.23."""
    strong = check_rst.docutils.nodes.strong()
    emphasis = check_rst.docutils.nodes.emphasis()
    paragraph = check_rst.docutils.nodes.paragraph("", "plain")
    document = check_rst.docutils.utils.new_document("test")
    document.extend([strong, emphasis, paragraph])

    found = list(
        check_rst._findall_node_types(
            document,
            (check_rst.docutils.nodes.strong, check_rst.docutils.nodes.emphasis),
        )
    )

    assert found == [strong, emphasis]


@pytest.mark.integration
@pytest.mark.parametrize(
    "source",
    [
        "``int** ptr``\n",  # C++ double pointer: invalid as nested RST strong markup.
        "``x**y``\n",  # Unbalanced/non-boundary delimiters remain plain text.
        "``**``\n",  # An unmatched start string is problematic, not nested markup.
        "``https://example.com/path``\n",  # Implicit URI recognition has no nested delimiters.
        "``author@example.com``\n",  # The same precision rule for implicit email links.
    ],
)
def test_nested_inline_markup_ignores_non_markup_reparse_results(
    check_rst: types.ModuleType, tmp_path: Path, source: str
) -> None:
    """Only successful explicit inline constructs count as nested markup."""
    p = _rst(tmp_path, source)

    assert check_rst.check_nested_inline_markup(p, True) == []


@pytest.mark.integration
def test_nested_inline_markup_inside_literal_block_is_not_source_markup(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    """An RST example in a code block is captured text, not parsed structure."""
    p = _rst(tmp_path, ".. code-block:: rst\n\n   Use **``nested``** here.\n")

    assert check_rst.check_nested_inline_markup(p, True) == []


@pytest.mark.integration
def test_nested_inline_markup_inside_block_quote_still_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Quoted imports still render incorrectly even though they are not headings."""
    p = _rst(tmp_path, "An imported answer said:\n\n   Use **``nested``** here.\n")

    findings = check_rst.check_nested_inline_markup(p, True)

    assert len(findings) == 1
    assert check_rst.check_directives(p, True) == []


@pytest.mark.integration
def test_cli_nested_inline_markup_reports_each_span_and_one_shared_hint(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI exposes every occurrence without repeating its rationale."""
    p = _rst(tmp_path, "Use **``one``** and **``two``** here.\n")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out.count("WARNING: nested inline markup in bold span") == 2
    assert out.count("reStructuredText renders only the outer inline role") == 1


@pytest.mark.integration
def test_cli_no_directives_does_not_disable_nested_inline_markup(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--no-directives skips its named lint, not this independent rule."""
    p = _rst(tmp_path, "Use **``nested``** here.\n")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--no-directives", str(p)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    assert "WARNING: nested inline markup" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_json_includes_nested_inline_markup(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Automation receives the same specific finding as text mode."""
    p = _rst(tmp_path, "Use **``nested``** here.\n")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    findings = json.loads(capsys.readouterr().out)["files"][0]["findings"]
    assert any(f["severity"] == "WARNING" and f["text"].startswith("nested inline markup ") for f in findings)


@pytest.mark.integration
def test_nested_inline_reparse_is_cached_across_warning_consumers(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A Document probes each outer span once even when two checks need it."""
    p = _rst(tmp_path, "Use **``one``** and ``plain literal`` here.\n")
    document = check_rst.Document(p)
    check_rst.CALL_COUNTS.clear()

    assert len(check_rst.check_nested_inline_markup(p, True, doc=document)) == 1
    assert check_rst.check_directives(p, True, doc=document) == []

    assert check_rst.CALL_COUNTS["_nested_inline_reparse"] == 2


@pytest.mark.integration
def test_directives_bold_opener_in_list_item_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Reversed 2026-07-20 (Max: "check_rst must warn about those bold
    texts... it's up to the AI - accept or not"): a bold paragraph opener
    inside a list item is exactly the same AI-writing-habit anti-pattern
    the rule exists to catch outside lists — this project converted two
    such lists to real subsections THIS SAME SESSION after independently
    judging them worth restructuring, which is the tool's own philosophy
    ("What the tool deliberately leaves to you") applied to exactly this
    shape: the tool flags, the human/AI decides — it must not
    auto-silence the decision for list items specifically.  The old
    blanket 'any list_item parent is exempt' rule could not distinguish
    a short 'term:' label from a full bold-sentence-plus-prose opener
    using tree shape alone (both are 'bold first child, more children
    follow') — so it silenced both.  No shape-based exemption survives:
    every list-item bold opener now gets the same WARNING a non-list one
    would."""
    p = _rst(
        tmp_path,
        "* **A finding you believe is wrong.**  The tool models docutils;\n  the model can drift from the reality.\n",
    )
    findings = check_rst.check_directives(p, True)
    assert len(findings) == 1
    assert findings[0].severity == "WARNING"
    assert "bold paragraph opener" in findings[0].text


@pytest.mark.integration
def test_directives_bold_term_in_list_item_also_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """The short 'term:' idiom is structurally identical (bold first
    child, more children follow) to the opener-plus-prose shape above —
    there is no tree-shape test that tells them apart, and per the
    reversed design neither is auto-exempt any more: judgment stays
    with the AI/human, uniformly, list item or not."""
    p = _rst(tmp_path, "* **term**: definition of the term\n")
    findings = check_rst.check_directives(p, True)
    assert len(findings) == 1
    assert findings[0].severity == "WARNING"
    assert "bold paragraph opener" in findings[0].text


@pytest.mark.integration
def test_directives_bold_standalone_in_block_quote_ok(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A standalone bold line inside a blockquote is quoted material, not a heading substitute."""
    p = _rst(
        tmp_path,
        "Он ответил:\n\n    **The Parsing Bug**\n\n    Some quoted explanation.\n",
    )
    assert check_rst.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_bold_opener_in_block_quote_ok(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A bold paragraph opener inside a blockquote is quoted material, not a heading substitute."""
    p = _rst(
        tmp_path,
        "He wrote:\n\n    **Note:** this is quoted, not my own heading.\n",
    )
    assert check_rst.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_rubric_in_block_quote_ok(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A rubric inside a blockquote is quoted material too — the same
    rationale as quoted bold (promoting it would de-indent the quote,
    misrepresenting a quotation as the author's structure) applies to
    every heading-substitute pattern, so the whole blockquote subtree is
    exempt via SkipNode, the same idiom as literal blocks."""
    p = _rst(
        tmp_path,
        "He wrote:\n\n    .. rubric:: Quoted Heading\n\n    Quoted body.\n",
    )
    assert check_rst.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_bold_in_accidental_indent_silent_known_limitation(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    """KNOWN, ACCEPTED limitation of the blockquote exemption: RST turns
    any accidentally indented paragraph into a blockquote, so a bold
    pseudo-heading that is merely mis-indented is silently exempt too —
    the tool cannot distinguish quotation intent from stray indentation.
    Accepted because in this corpus indented material is overwhelmingly
    genuine quotation (AI answers, email bodies).  This test pins the
    trade-off so a future change that revisits it does so deliberately."""
    p = _rst(
        tmp_path,
        "Intro paragraph.\n\n  **Setup.** Do the thing.\n",
    )
    assert check_rst.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_bold_not_first_child_ok(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Bold text that is not the first element in a paragraph must NOT be flagged."""
    p = _rst(tmp_path, "See **bold term** for details.\n")
    assert check_rst.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_bold_opener_period_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A bold paragraph opener ending with a period must be flagged (AI heading pattern)."""
    p = _rst(tmp_path, "**Memory layout.** Zephyr stores the kernel state here.\n")
    violations = check_rst.check_directives(p, True)
    assert violations
    assert any("bold paragraph opener" in v for v in violations)


@pytest.mark.integration
def test_directives_bold_opener_default_shows_actual_text(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Max, 2026-07-20: 'without informing the original text, it's hard to
    judge in one step' — the DEFAULT (non-verbose) message must name the
    actual bold text, not a generic '**...** text' placeholder every
    finding shared, indistinguishable from every other one in a
    19-finding review pass.  Every OTHER directive finding already does
    this by default (rubric shows its own text, the mistyped-directive
    warning shows the actual name) — bold was the inconsistent one."""
    p = _rst(tmp_path, "**Memory layout.** Zephyr stores the kernel state here.\n")
    violations = check_rst.check_directives(p, True)
    assert any("Memory layout" in v for v in violations)


@pytest.mark.integration
def test_directives_standalone_bold_default_shows_actual_text(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Same fix, the other bold-as-heading shape (nothing else in the
    paragraph)."""
    p = _rst(tmp_path, "**Section Heading**\n\nSome text.\n")
    violations = check_rst.check_directives(p, True)
    assert any("Section Heading" in v for v in violations)


@pytest.mark.integration
def test_directives_bold_opener_colon_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A bold paragraph opener ending with a colon must be flagged (heading substitute pattern)."""
    p = _rst(tmp_path, "**Как сбросить:** Command Palette → ``Python: Clear Workspace Interpreter Setting``.\n")
    violations = check_rst.check_directives(p, True)
    assert violations
    assert any("bold paragraph opener" in v for v in violations)


@pytest.mark.integration
def test_directives_bold_note_colon_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """**Note:** opener is the same colon pattern and must also be flagged."""
    p = _rst(tmp_path, "**Note:** this is a warning paragraph.\n")
    violations = check_rst.check_directives(p, True)
    assert violations
    assert any("bold paragraph opener" in v for v in violations)


@pytest.mark.integration
def test_directives_bold_opener_no_punctuation_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A bold paragraph opener with no terminal punctuation must also be flagged."""
    p = _rst(tmp_path, "**Overview** This section explains the architecture.\n")
    violations = check_rst.check_directives(p, True)
    assert violations
    assert any("bold paragraph opener" in v for v in violations)


@pytest.mark.integration
def test_directives_bold_opener_quoted_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A bold paragraph opener ending with a closing quote must also be flagged."""
    p = _rst(tmp_path, '**"raw mode"** leaves the terminal in a broken state.\n')
    violations = check_rst.check_directives(p, True)
    assert violations
    assert any("bold paragraph opener" in v for v in violations)


@pytest.mark.integration
def test_directives_clean_rst_ok(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A file with no forbidden directives returns an empty violation list."""
    p = _rst(
        tmp_path,
        """\
        Some text with **inline bold** emphasis.

        - A bullet with **bold term**: inline only.
        - Another item.
        """,
    )
    assert check_rst.check_directives(p, True) == []


# ---------------------------------------------------------------------------
# check_directives --verbose — extra detail on WARNING findings → Zone 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_directives_default_verbose_false_unchanged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Omitting verbose must be identical to passing verbose=False explicitly."""
    p = _rst(tmp_path, "**Note:** this is a warning paragraph.\n")
    assert check_rst.check_directives(p, True) == check_rst.check_directives(p, True, False)


@pytest.mark.integration
def test_directives_rubric_verbose_shows_text_and_section(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Verbose rubric findings must include the rubric text and enclosing section title."""
    p = _rst(
        tmp_path,
        """\
        Chapter One
        ===========

        .. rubric:: See also

        Some text.
        """,
    )
    violations = check_rst.check_directives(p, True, True)
    assert violations
    assert any("See also" in v and "Chapter One" in v for v in violations)


@pytest.mark.integration
def test_directives_bold_standalone_verbose_shows_text(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Verbose standalone-bold findings must include the actual bold text."""
    p = _rst(tmp_path, "**Section Heading**\n\nSome text.\n")
    violations = check_rst.check_directives(p, True, True)
    assert violations
    assert any("Section Heading" in v for v in violations)


@pytest.mark.integration
def test_directives_bold_opener_verbose_shows_text_preview_and_section(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    """Verbose bold-opener findings must include the bold text, trailing
    paragraph preview, and enclosing section title."""
    p = _rst(
        tmp_path,
        """\
        Outer
        =====

        Inner
        -----

        **Overview** This section explains the architecture.
        """,
    )
    violations = check_rst.check_directives(p, True, True)
    assert violations
    opener = next(v for v in violations if "bold paragraph opener" in v)
    assert "Overview" in opener
    assert "This section explains the architecture" in opener
    assert "Inner" in opener


@pytest.mark.integration
def test_cli_bold_opener_rationale_printed_once_per_run(
    check_rst: types.ModuleType,
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
        check_rst.main()
    out = capsys.readouterr().out
    rationale = "AI documents often use this pattern as an informal heading; consider a proper section title"
    assert out.count(rationale) == 1
    for point in ("First point", "Second point", "Third point", "Fourth point", "Fifth point"):
        assert point in out
    assert out.count("WARNING:") == 5  # five finding lines; the rationale is not one of them


@pytest.mark.integration
def test_cli_bold_opener_rationale_resets_between_runs(
    check_rst: types.ModuleType,
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
        check_rst.main()
    capsys.readouterr()  # discard first run's output

    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "AI documents often use this pattern" in out


@pytest.mark.integration
def test_directives_verbose_no_enclosing_section(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Verbose findings with no enclosing section must say so rather than
    silently omitting the section clause."""
    p = _rst(tmp_path, "**Overview** This section explains the architecture.\n")
    violations = check_rst.check_directives(p, True, True)
    assert violations
    assert any("no enclosing section" in v for v in violations)


@pytest.mark.integration
def test_directives_non_verbose_omits_extra_detail(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Non-verbose findings must stay exactly as terse as before — no bold
    text, no preview, no section title leaking into the default message."""
    p = _rst(
        tmp_path,
        """\
        Chapter One
        ===========

        **Overview** This section explains the architecture.
        """,
    )
    violations = check_rst.check_directives(p, True, False)
    assert violations
    assert not any("Chapter One" in v for v in violations)
    assert not any("This section explains the architecture" in v for v in violations)


# ---------------------------------------------------------------------------
# build_outline — --outline structural dump → Zone 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_outline_overline_underline_title(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.build_outline(p)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.lineno == 2
    assert entry.depth == 1
    assert entry.char == "#"
    assert entry.title == "Root"


@pytest.mark.integration
def test_outline_nested_nesting_depth(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.build_outline(p)
    assert [(e.lineno, e.depth, e.char, e.title) for e in entries] == [
        (1, 1, "*", "Abc"),
        (6, 2, "=", "Xyz"),
    ]


@pytest.mark.integration
def test_outline_sibling_depth_resets_after_nested_child(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.build_outline(p)
    assert [(e.depth, e.title) for e in entries] == [
        (1, "Chapter One"),
        (2, "Sub A"),
        (1, "Chapter Two"),
    ]


@pytest.mark.integration
def test_outline_empty_for_file_with_no_sections(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A file with no section titles at all returns an empty outline."""
    p = _rst(tmp_path, "Just a plain paragraph, no headings.\n")
    assert check_rst.build_outline(p) == []


@pytest.mark.integration
def test_outline_str_format(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.build_outline(p)
    # Lean format: line range, adornment char, title — depth is the
    # indentation (4 spaces per level); the char was omitted 2026-07-18
    # ("lives in the legend, not on every entry"), reversed 2026-07-20
    # after repeated real mistakes picking the wrong char for a new
    # heading — every entry now states its own char directly.
    assert str(entries[0]) == "1-9:* Abc [1 subsection]"
    assert str(entries[1]) == "    6-9:= Xyz"


@pytest.mark.integration
def test_outline_non_preferred_char_shown_not_placeholder(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.build_outline(p)
    assert len(entries) == 1
    assert entries[0].char == "~"


# ---------------------------------------------------------------------------
# _build_sphinx_env / _docname_for / find_code_blocks — Phase 2: Python
# Sphinx rules → Zone 2 (spawns a real, in-process Sphinx 'dummy' build)
#
# Bare docutils (Phase 1) cannot parse Sphinx-only code-block options like
# :caption:/:linenos: — the directive fails and falls back to an unclassed
# literal_block, silently invisible to any bare-docutils detector. A real
# Sphinx environment resolves these correctly (confirmed by direct spike:
# Sphinx's own CodeBlock.run() needs self.env, which only exists inside a
# genuine Sphinx application, never a bare docutils parse).
# ---------------------------------------------------------------------------


@pytest.fixture
def build_sphinx_env(check_rst: types.ModuleType, tmp_path: Path) -> Callable[[str], tuple[object, str]]:
    """Return build(rst_text) -> (env, docname) for tmp_path/index.rst.

    Writes a minimal conf.py once, then on each call writes rst_text to
    index.rst and runs a real in-process Sphinx 'dummy' build (resolves the
    full environment/doctree, writes no HTML) against it.
    """
    (tmp_path / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")

    def _build(rst_text: str) -> tuple[object, str]:
        (tmp_path / "index.rst").write_text(textwrap.dedent(rst_text), encoding="utf-8")
        env, _ = check_rst._build_sphinx_env(tmp_path, tmp_path / "_build")
        docname = check_rst._docname_for(env, tmp_path / "index.rst")
        assert docname is not None
        return env, docname

    return _build


@pytest.mark.integration
def test_docname_for_unreachable_file_returns_none(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A file outside the Sphinx project's source tree resolves to None,
    not a crash — Phase 2 must be able to skip it gracefully."""
    (tmp_path / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (tmp_path / "index.rst").write_text("Title\n=====\n", encoding="utf-8")
    env, _ = check_rst._build_sphinx_env(tmp_path, tmp_path / "_build")
    outside = tmp_path.parent / "not_in_this_project.rst"
    assert check_rst._docname_for(env, outside) is None


@pytest.mark.integration
def test_cli_verified_mode_accepts_orphan_inside_sphinx_source(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Toctree reachability is not Sphinx membership: orphans are still parsed."""
    (tmp_path / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    (tmp_path / "index.rst").write_text("Index\n=====\n", encoding="utf-8")
    orphan = tmp_path / "orphan.rst"
    orphan.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(tmp_path), "check", "--quiet", str(orphan)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    assert "not part of" not in capsys.readouterr().out


@pytest.mark.integration
def test_cli_verified_mode_rejects_file_excluded_by_sphinx_environment(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Inside srcdir is insufficient when Sphinx itself excluded the source."""
    (tmp_path / "conf.py").write_text(
        'project = "test"\nexclude_patterns = ["excluded.rst"]\n',
        encoding="utf-8",
    )
    (tmp_path / "index.rst").write_text("Index\n=====\n", encoding="utf-8")
    excluded = tmp_path / "excluded.rst"
    excluded.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(tmp_path), "check", "--quiet", str(excluded)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "not part of the --sphinx-src environment" in out
    assert "no warnings or errors in the checked files" not in out


# ---------------------------------------------------------------------------
# Phase 2's own build warnings must not be lost between Phase 2 and Phase 3
# (Max, 2026-07-20) — found in the field on check_rst.rst itself: reusing an
# adornment character at the wrong depth is a real docutils ERROR
# ("Inconsistent title style"), but Phase 2's in-process build captured it
# into an io.StringIO() nothing read, and since Phase 2/Phase 3 share
# --build-dir, Phase 2's freshly-written doctree made Phase 3's separate
# sphinx-build subprocess skip re-parsing the file — the warning vanished
# between the two phases, confirmed missing on three separate live runs.
# ---------------------------------------------------------------------------

# '-' is fixed at level 4 by "L4 under 3" (nested #->*->=->-); "L reused
# wrongly" then reuses '-' directly under a level-2 parent ("L2 B"),
# skipping the already-established level 3 ('=') — a real docutils ERROR,
# confirmed by direct probe: "Inconsistent title style: skip from level 2
# to 4."
_INCONSISTENT_TITLE_STYLE_RST = textwrap.dedent("""\
    Title
    #####

    L2 A
    ****

    L3 under A
    ==========

    L4 under 3
    ----------

    L2 B
    ****

    L reused wrongly
    ----------------
    """)


@pytest.mark.unit
def test_find_findings_from_sphinx_output_parses_console_lines(
    check_rst: types.ModuleType,
) -> None:
    """_findings_from_sphinx_output (shared by run_sphinx's subprocess
    parsing and Phase 2's captured-warning parsing) turns a raw
    'path:line: LEVEL: msg' console line into a Finding, filtered to the
    given files."""
    raw = "/some/repo/index.rst:16: ERROR: Inconsistent title style: skip from level 2 to 4.\n"
    findings = check_rst._findings_from_sphinx_output(raw, [Path("/some/repo/index.rst")])
    assert len(findings) == 1
    assert findings[0].severity == "ERROR"
    assert "Inconsistent title style" in findings[0].text


@pytest.mark.unit
def test_findings_from_sphinx_output_accepts_warning_without_line_number(
    check_rst: types.ModuleType,
) -> None:
    """Sphinx emits some file-scoped diagnostics without ``:line:``.

    ``toc.not_included`` is a common example.  It still references the
    checked file and must not disappear merely because Sphinx has no more
    precise source anchor to report.
    """
    raw = "/some/repo/orphan.rst: WARNING: document isn't included in any toctree [toc.not_included]\n"

    findings = check_rst._findings_from_sphinx_output(raw, [Path("/some/repo/orphan.rst")])

    assert len(findings) == 1
    assert findings[0].lineno == 0
    assert findings[0].severity == "WARNING"
    assert "toc.not_included" in findings[0].text


@pytest.mark.unit
def test_findings_from_sphinx_output_strips_ansi_color_codes(
    check_rst: types.ModuleType,
) -> None:
    """The actual root cause, pinned directly: Sphinx's in-process build
    colorizes its console stream even into an io.StringIO() with no real
    isatty() — confirmed live — and the leading '\\x1b[31m' broke
    _WARNING_RE's '^' anchor, silently dropping every match."""
    raw = "\x1b[31m/some/repo/index.rst:16: ERROR: Inconsistent title style: skip from level 2 to 4.\x1b[39;49;00m\n"
    findings = check_rst._findings_from_sphinx_output(raw, [Path("/some/repo/index.rst")])
    assert len(findings) == 1
    assert findings[0].severity == "ERROR"
    assert "Inconsistent title style" in findings[0].text
    assert "\x1b" not in findings[0].text


@pytest.mark.unit
def test_run_sphinx_nonzero_with_only_warning_adds_failure_error(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A matching warning must not mask sphinx-build's failed exit status."""
    document = tmp_path / "index.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    warning = f"{document}:4: WARNING: warning emitted before fatal failure\n"

    command: list[str] = []

    def failed_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        command.extend(args)
        return subprocess.CompletedProcess(args=["sphinx-build"], returncode=2, stdout=warning, stderr="fatal\n")

    monkeypatch.setattr(check_rst.subprocess, "run", failed_run)
    findings = check_rst.run_sphinx([document], tmp_path / "_build", tmp_path, tmp_path)

    assert any(f.severity == "WARNING" for f in findings)
    assert any(f.severity == "ERROR" and "exited 2" in f.text for f in findings)
    assert command[:3] == [sys.executable, "-m", "sphinx"]


@pytest.mark.unit
def test_runtime_metadata_names_behavior_affecting_dependencies(
    check_rst: types.ModuleType,
) -> None:
    runtime = check_rst._runtime_metadata(verified=True, word_samples=True)

    assert runtime["check_rst"]["version"] == "0.1.0"
    assert runtime["python"]["version"]
    assert runtime["python"]["executable"] == sys.executable
    assert runtime["docutils"]["version"]
    assert runtime["sphinx"]["version"]
    assert runtime["snowballstemmer"]["version"]


@pytest.mark.integration
def test_cli_version_reports_release_identity(
    check_rst: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["check_rst", "--version"])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    assert capsys.readouterr().out == "check_rst 0.1.0\n"


@pytest.mark.integration
def test_build_sphinx_env_returns_its_own_warning_text(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """_build_sphinx_env must return its captured warning stream, not
    just the env — the whole point of the fix: the caller MUST see it."""
    (tmp_path / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    (tmp_path / "index.rst").write_text(_INCONSISTENT_TITLE_STYLE_RST, encoding="utf-8")
    _env, warning_text = check_rst._build_sphinx_env(tmp_path, tmp_path / "_build")
    assert "Inconsistent title style" in warning_text


@pytest.mark.integration
def test_build_sphinx_env_reemits_persistent_warning_with_cached_build_dir(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    """Re-read checked documents without discarding the incremental cache.

    The documented edit/fix/recheck loop deliberately reuses its Sphinx
    build directory for speed.  A checked document must reproduce its
    persistent diagnostic, while an unrelated unchanged document must stay
    cached and avoid a second ``source-read`` event.
    """
    read_log = tmp_path / "source-read.log"
    (tmp_path / "conf.py").write_text(
        textwrap.dedent(f"""\
            from pathlib import Path

            project = "t"
            extensions = []

            def record_source_read(app, docname, source):
                with Path({str(read_log)!r}).open("a", encoding="utf-8") as fh:
                    fh.write(docname + "\\n")

            def setup(app):
                app.connect("source-read", record_source_read)
            """),
        encoding="utf-8",
    )
    checked = tmp_path / "index.rst"
    checked.write_text(_INCONSISTENT_TITLE_STYLE_RST, encoding="utf-8")
    (tmp_path / "other.rst").write_text(_GOOD_BLOCK, encoding="utf-8")
    build_dir = tmp_path / "_build"

    _env, first_warning_text = check_rst._build_sphinx_env(tmp_path, build_dir)
    read_log.write_text("", encoding="utf-8")
    _env, second_warning_text = check_rst._build_sphinx_env(tmp_path, build_dir, files=[checked])

    assert "Inconsistent title style" in first_warning_text
    assert "Inconsistent title style" in second_warning_text
    assert read_log.read_text(encoding="utf-8").splitlines() == ["index"]


@pytest.mark.integration
def test_cli_materializes_required_docutils_model_before_sphinx(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No lazy bare-Docutils parse may first occur after extension loading.

    ``--no-directives`` normally avoids Phase 1's doctree consumer, while
    prose-word sampling still needs that doctree later.  Materialize it
    before constructing Sphinx so extension side effects cannot influence
    the bare parser.
    """
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    events: list[str] = []
    original_parse = check_rst._parse_rst

    def recording_parse(*args: object, **kwargs: object) -> object:
        events.append("docutils")
        return original_parse(*args, **kwargs)

    env = types.SimpleNamespace(
        found_docs={"test"},
        domaindata={},
        path2doc=lambda _path: "test",
    )

    def recording_sphinx_build(*_args: object, **_kwargs: object) -> tuple[object, str]:
        events.append("sphinx")
        return env, ""

    monkeypatch.setattr(check_rst, "_parse_rst", recording_parse)
    monkeypatch.setattr(check_rst, "_build_sphinx_env", recording_sphinx_build)
    monkeypatch.setattr(check_rst, "run_sphinx", lambda *_args: [])
    monkeypatch.setattr(check_rst, "_top_prose_words", lambda *_args: ([], 0))
    monkeypatch.setattr(check_rst, "_rare_prose_words", lambda *_args: ([], 0))
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "check", "--no-directives", "--word-samples", "1", str(p)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    capsys.readouterr()
    assert exc.value.code == 0
    assert events == ["docutils", "sphinx"]


@pytest.mark.integration
def test_cli_verified_mode_surfaces_phase2_inconsistent_title_style(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """End to end, the real regression: a fresh --build-dir, verified
    mode, --outline (so Phase 2 actually resolves structure) — the
    ERROR must reach the user, not vanish between Phase 2 and Phase 3."""
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    p = rst_repo / "index.rst"
    p.write_text(_INCONSISTENT_TITLE_STYLE_RST, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "--build-dir",
            str(rst_repo / "_build"),
            "outline",
            "--with-findings",
            str(p),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    out = capsys.readouterr().out
    assert "Inconsistent title style" in out
    assert exc.value.code == 1


@pytest.mark.integration
def test_cli_verified_mode_deduplicates_same_phase2_and_phase3_finding(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One Sphinx diagnostic emitted by both builds is one user finding."""
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    raw_warning = f"{p}:5: WARNING: repeated Sphinx diagnostic [review.test]\n"
    env = types.SimpleNamespace(
        found_docs={"test"},
        domaindata={},
        path2doc=lambda _path: "test",
    )
    duplicate = check_rst.Finding(
        lineno=5,
        severity="WARNING",
        text="test.rst: repeated Sphinx diagnostic [review.test]",
    )
    monkeypatch.setattr(
        check_rst,
        "_build_sphinx_env",
        lambda *_args, **_kwargs: (env, raw_warning),
    )
    monkeypatch.setattr(check_rst, "run_sphinx", lambda *_args: [duplicate])
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--sphinx-src", str(rst_repo), "check", str(p)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    out = capsys.readouterr().out
    assert exc.value.code == 0
    assert out.count("repeated Sphinx diagnostic") == 1
    assert "0 error(s), 1 warning(s)" in out


# ---------------------------------------------------------------------------
# "Did you mean" suggestions on broken :doc:/:ref: findings (2026-07-22) —
# the first stage of "Reference intelligence" (Max's priority list, item 2).
# Derived from the SAME live Sphinx environment Phase 2 already builds
# (env.found_docs, env.domaindata['std']['anonlabels']) — never objects.inv,
# which needs a completed HTML build and holds less than the env already in
# hand.  Kills the guess-and-wait loop the contract otherwise leaves to a
# human/AI on a broken cross-reference.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_did_you_mean_finds_close_match(check_rst: types.ModuleType) -> None:
    result = check_rst._did_you_mean("idnex", ["index", "other"])
    assert result is not None
    assert "index" in result


@pytest.mark.unit
def test_did_you_mean_returns_none_when_nothing_close(check_rst: types.ModuleType) -> None:
    assert check_rst._did_you_mean("totally-unrelated-xyz", ["index"]) is None


@pytest.mark.integration
def test_attach_did_you_mean_unknown_document_suggests_close_docname(
    check_rst: types.ModuleType,
    build_sphinx_env: Callable[[str], tuple[object, str]],
) -> None:
    env, _docname = build_sphinx_env("Title\n=====\n")
    finding = check_rst.Finding(4, "WARNING", "unknown document: 'idnex' [ref.doc]")
    result = check_rst._attach_did_you_mean(finding, env)
    assert "did you mean" in result.text
    assert "'index'" in result.text


@pytest.mark.integration
def test_attach_did_you_mean_toctree_nonexisting_document(
    check_rst: types.ModuleType,
    build_sphinx_env: Callable[[str], tuple[object, str]],
) -> None:
    """'toctree contains reference to nonexisting document' has no colon
    before the quoted target — a different shape than 'unknown document:'."""
    env, _docname = build_sphinx_env("Title\n=====\n")
    finding = check_rst.Finding(
        4,
        "WARNING",
        "toctree contains reference to nonexisting document 'idnex' [toc.not_readable]",
    )
    result = check_rst._attach_did_you_mean(finding, env)
    assert "did you mean" in result.text
    assert "'index'" in result.text


@pytest.mark.integration
def test_attach_did_you_mean_undefined_label_suggests_close_label(
    check_rst: types.ModuleType,
    build_sphinx_env: Callable[[str], tuple[object, str]],
) -> None:
    env, _docname = build_sphinx_env("Title\n=====\n\n.. _real-label:\n\nSection\n-------\n")
    finding = check_rst.Finding(4, "WARNING", "undefined label: 'real-labl' [ref.ref]")
    result = check_rst._attach_did_you_mean(finding, env)
    assert "did you mean" in result.text
    assert "'real-label'" in result.text


@pytest.mark.integration
def test_attach_did_you_mean_no_suggestion_when_nothing_close(
    check_rst: types.ModuleType,
    build_sphinx_env: Callable[[str], tuple[object, str]],
) -> None:
    env, _docname = build_sphinx_env("Title\n=====\n")
    finding = check_rst.Finding(4, "WARNING", "unknown document: 'zzz-nothing-alike-qqq' [ref.doc]")
    result = check_rst._attach_did_you_mean(finding, env)
    assert result.text == finding.text


@pytest.mark.integration
def test_attach_did_you_mean_leaves_unrelated_findings_unchanged(
    check_rst: types.ModuleType,
    build_sphinx_env: Callable[[str], tuple[object, str]],
) -> None:
    env, _docname = build_sphinx_env("Title\n=====\n")
    finding = check_rst.Finding(4, "WARNING", "Inconsistent title style: skip from level 2 to 4.")
    result = check_rst._attach_did_you_mean(finding, env)
    assert result.text == finding.text


@pytest.mark.integration
def test_cli_did_you_mean_suggested_for_broken_doc_reference(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """End to end, real sphinx-build subprocess (Phase 3): a typo'd :doc:
    target gets a suggestion naming the real docname, right in the same
    WARNING line."""
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "other-page.rst").write_text("Other Page\n==========\n", encoding="utf-8")
    p = rst_repo / "index.rst"
    p.write_text("Title\n=====\n\n:doc:`other-pge`\n", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "--sphinx-src", str(rst_repo), "check", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "unknown document" in out
    assert "did you mean" in out
    assert "other-page" in out


# ---------------------------------------------------------------------------
# Per-file incoming/outgoing reference reports (2026-07-22) — the third and
# final part of "Reference intelligence" (Max's priority list, item 2).
# find_references reads the raw, still-unresolved pending_xref nodes
# env.get_doctree() carries (resolution happens later, during a builder's
# write phase, and is never written back to the pickled doctree — confirmed
# by direct probe).  find_incoming_references is its inverse, built by
# scanning every document once (confirmed by direct probe: ~2.6s across this
# repo's full 1444 documents).  Both reuse the SAME resolution Sphinx itself
# performs (docname_join for :doc:, domaindata['std']['anonlabels'] for
# :ref:/:term:), so a reference this reports as resolved is exactly one
# Phase 3 would accept.
# ---------------------------------------------------------------------------


def _build_multi_file_env(check_rst: types.ModuleType, tmp_path: Path, files: dict[str, str]) -> object:
    """Write conf.py + *files* (docname -> rst text) under tmp_path and
    return a real, in-process Sphinx env over them.

    root_doc is pinned to the first key — Sphinx requires ITS OWN master
    document to exist and defaults to "index", which these fixtures don't
    always define."""
    root_doc = next(iter(files))
    (tmp_path / "conf.py").write_text(f'project = "test"\nextensions = []\nroot_doc = "{root_doc}"\n', encoding="utf-8")
    for docname, text in files.items():
        path = tmp_path / f"{docname}.rst"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")
    env, _warning_text = check_rst._build_sphinx_env(tmp_path, tmp_path / "_build")
    return env


@pytest.mark.integration
def test_resolve_xref_target_doc_resolves_relative_target(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "index": "Title\n=====\n",
            "sub/page": "Sub Page\n========\n",
        },
    )
    assert check_rst._resolve_xref_target(env, "sub/page", "doc", "../index") == "index"


@pytest.mark.integration
def test_resolve_xref_target_doc_unresolvable_returns_none(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(check_rst, tmp_path, {"index": "Title\n=====\n"})
    assert check_rst._resolve_xref_target(env, "index", "doc", "no-such-page") is None


@pytest.mark.integration
def test_resolve_xref_target_ref_resolves_label(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "index": "Title\n=====\n\n.. _my-label:\n\nSection\n-------\n",
        },
    )
    assert check_rst._resolve_xref_target(env, "index", "ref", "my-label") == "index"


@pytest.mark.integration
def test_resolve_xref_target_unknown_reftype_returns_none(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(check_rst, tmp_path, {"index": "Title\n=====\n"})
    assert check_rst._resolve_xref_target(env, "index", "obj", "whatever") is None


@pytest.mark.integration
def test_find_references_outgoing_doc_and_ref_in_document_order(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "index": """\
            Title
            =====

            :doc:`other`

            See :ref:`other-label`.
            """,
            "other": "Other\n=====\n\n.. _other-label:\n\nSection\n-------\n",
        },
    )
    entries = check_rst.find_references(env, "index")
    assert [e.reftype for e in entries] == ["doc", "ref"]
    assert entries[0].target == "other"
    assert entries[0].resolved == "other"
    assert entries[1].target == "other-label"
    assert entries[1].resolved == "other"
    assert entries[0].lineno < entries[1].lineno


@pytest.mark.integration
def test_find_references_broken_target_resolved_is_none(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "index": "Title\n=====\n\n:doc:`nonexistent`\n",
        },
    )
    entries = check_rst.find_references(env, "index")
    assert len(entries) == 1
    assert entries[0].resolved is None


@pytest.mark.integration
def test_find_incoming_references_finds_pointing_docs(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "a": "A\n=\n\n:doc:`b`\n",
            "b": "B\n=\n\n.. _shared-label:\n\nSection\n-------\n",
            "c": "C\n=\n\nSee :ref:`shared-label`.\n",
        },
    )
    incoming = check_rst.find_incoming_references(env, "b")
    assert {e.docname for e in incoming} == {"a", "c"}


@pytest.mark.integration
def test_find_incoming_references_empty_when_nothing_points_at_it(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "index": "Title\n=====\n",
            "lonely": "Lonely\n======\n",
        },
    )
    assert check_rst.find_incoming_references(env, "lonely") == []


@pytest.mark.integration
def test_cli_refs_shows_outgoing_and_incoming(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\nroot_doc = "a"\n', encoding="utf-8")
    (rst_repo / "a.rst").write_text("A\n=\n\n:doc:`b`\n", encoding="utf-8")
    b = rst_repo / "b.rst"
    b.write_text("B\n=\n\n:doc:`a`\n", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "--sphinx-src", str(rst_repo), "refs", str(b)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "outgoing" in out
    assert "-> a" in out
    assert "incoming" in out
    assert "a:" in out


@pytest.mark.integration
def test_cli_refs_includes_parent_and_globbed_child_toctree_edges(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Toctrees are document references too, including glob-expanded entries."""
    (rst_repo / "conf.py").write_text(
        'project = "test"\nextensions = []\nroot_doc = "index"\n',
        encoding="utf-8",
    )
    (rst_repo / "index.rst").write_text(
        "Root\n====\n\n.. toctree::\n\n   organs/index\n",
        encoding="utf-8",
    )
    organs = rst_repo / "organs"
    (organs / "alpha").mkdir(parents=True)
    (organs / "beta").mkdir()
    target = organs / "index.rst"
    target.write_text(
        "Organizations\n=============\n\n.. toctree::\n   :glob:\n\n   */index\n",
        encoding="utf-8",
    )
    (organs / "alpha" / "index.rst").write_text("Alpha\n=====\n", encoding="utf-8")
    (organs / "beta" / "index.rst").write_text("Beta\n====\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "refs", str(target)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "toctree -> organs/alpha/index (organs/alpha/index)" in out
    assert "toctree -> organs/beta/index (organs/beta/index)" in out
    assert "index:4: toctree -> organs/index" in out


@pytest.mark.integration
def test_cli_refs_requires_sphinx_src(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "index.rst"
    p.write_text("Title\n=====\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "refs", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--sphinx-src DIR" in out
    assert "--config FILE" in out


@pytest.mark.integration
def test_cli_refs_file_not_part_of_project(
    check_rst: types.ModuleType,
    rst_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text("Title\n=====\n", encoding="utf-8")
    # rst_repo IS tmp_path (tmp_git_repo returns it directly) — a genuinely
    # unreachable file must live outside it, same precedent as
    # test_docname_for_unreachable_file_returns_none.
    outside = tmp_path.parent / "not_in_this_project.rst"
    outside.write_text("Title\n=====\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--sphinx-src", str(rst_repo), "refs", str(outside)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    assert "not part of" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_refs_missing_file_errors_cleanly(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    missing = rst_repo / "missing.rst"
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--sphinx-src", str(rst_repo), "refs", str(missing)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    assert "missing.rst" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# check_bare_filenames — a bare '<name>.rst' filename mentioned as plain
# prose text where a real :doc:/:ref: cross-reference belongs (Max,
# 2026-07-23, real downstream-project evidence: several 'coding-standards.rst' prose
# mentions in that project's own docs are plain text, not links) — the
# mirror image of "did you mean": here a reference is MISSING where one
# should exist, not broken.  Matched by basename (prose almost never spells
# out the full project-relative path).  Needs the live Sphinx env
# (env.found_docs), so verified mode only, same family as --refs.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_bare_filenames_flags_mention_matching_known_docname(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "a": "A\n=\n\nSee guide.rst for details.\n",
            "guide": "Guide\n=====\n",
        },
    )
    doc = check_rst.Document(tmp_path / "a.rst")
    violations = check_rst.check_bare_filenames(env, "a", doc)
    assert len(violations) == 1
    assert violations[0].severity == "WARNING"
    assert "guide" in violations[0].text


@pytest.mark.integration
def test_bare_filenames_ignores_self_mention(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "a": "A\n=\n\nThis file, a.rst, describes itself.\n",
        },
    )
    doc = check_rst.Document(tmp_path / "a.rst")
    assert check_rst.check_bare_filenames(env, "a", doc) == []


@pytest.mark.integration
def test_bare_filenames_ignores_unknown_filename(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "a": "A\n=\n\nSee nonexistent.rst for details.\n",
        },
    )
    doc = check_rst.Document(tmp_path / "a.rst")
    assert check_rst.check_bare_filenames(env, "a", doc) == []


@pytest.mark.integration
def test_bare_filenames_lists_multiple_candidates_when_ambiguous(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "a": "A\n=\n\nSee guide.rst for details.\n",
            "sub1/guide": "Guide One\n=========\n",
            "sub2/guide": "Guide Two\n=========\n",
        },
    )
    doc = check_rst.Document(tmp_path / "a.rst")
    violations = check_rst.check_bare_filenames(env, "a", doc)
    assert len(violations) == 1
    assert "sub1/guide" in violations[0].text
    assert "sub2/guide" in violations[0].text


@pytest.mark.integration
def test_bare_filenames_skips_when_too_many_candidates_share_basename(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    """Real evidence: this Journal's own corpus has 1072 files named
    'Notes.rst' — a bare mention of that basename is not a specific,
    actionable reference candidate, so it must stay silent rather than
    dump an unusable wall of candidates."""
    files = {"a": "A\n=\n\nSee notes.rst for details.\n"}
    for i in range(10):
        files[f"day{i}/notes"] = f"Day {i}\n=====\n"
    env = _build_multi_file_env(check_rst, tmp_path, files)
    doc = check_rst.Document(tmp_path / "a.rst")
    assert check_rst.check_bare_filenames(env, "a", doc) == []


@pytest.mark.integration
def test_bare_filenames_skips_literal_block_content(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "a": "A\n=\n\n::\n\n    See guide.rst for details.\n",
            "guide": "Guide\n=====\n",
        },
    )
    doc = check_rst.Document(tmp_path / "a.rst")
    assert check_rst.check_bare_filenames(env, "a", doc) == []


@pytest.mark.integration
def test_bare_filenames_flags_mention_inside_inline_literal(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """The real downstream-project evidence's own shape: a filename wrapped in double
    backticks as the author's own emphasis, not code output."""
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "a": "A\n=\n\nDocumented in ``guide.rst`` under Section One.\n",
            "guide": "Guide\n=====\n",
        },
    )
    doc = check_rst.Document(tmp_path / "a.rst")
    assert len(check_rst.check_bare_filenames(env, "a", doc)) == 1


@pytest.mark.integration
@pytest.mark.parametrize(
    "reference",
    [
        ":doc:`guide.rst <guide>`",
        "`guide.rst <https://example.com/guide.rst>`_",
    ],
)
def test_bare_filenames_ignores_already_linked_filename_labels(
    check_rst: types.ModuleType, tmp_path: Path, reference: str
) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "a": f"A\n=\n\nSee {reference} for details.\n",
            "guide": "Guide\n=====\n",
        },
    )
    doc = check_rst.Document(tmp_path / "a.rst")

    assert check_rst.check_bare_filenames(env, "a", doc) == []


@pytest.mark.integration
def test_cli_bare_filenames_warning_shown(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\nroot_doc = "a"\n', encoding="utf-8")
    (rst_repo / "a.rst").write_text("A\n=\n\nSee guide.rst for details.\n", encoding="utf-8")
    (rst_repo / "guide.rst").write_text("Guide\n=====\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--sphinx-src", str(rst_repo), "check", str(rst_repo / "a.rst")])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "WARNING:" in out
    assert "guide" in out


@pytest.mark.integration
def test_cli_json_bare_filenames_included(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\nroot_doc = "a"\n', encoding="utf-8")
    (rst_repo / "a.rst").write_text("A\n=\n\nSee guide.rst for details.\n", encoding="utf-8")
    (rst_repo / "guide.rst").write_text("Guide\n=====\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "check", "--format=json", str(rst_repo / "a.rst")],
    )
    with pytest.raises(SystemExit):
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    findings = data["files"][0]["findings"]
    assert any(f["severity"] == "WARNING" and "guide" in f["text"] for f in findings)


# ---------------------------------------------------------------------------
# The trust invariant: --fix touches ONLY adornment geometry and byte
# hygiene, never prose content (2026-07-21) — the exact question an
# independent Claude Code session hand-rolled a grep filter to answer
# before recommending a real project normalize six adopted, external
# documents in full.  Individual regression tests already pinned this for
# specific scenarios (a '..' comment block staying byte-identical, etc.);
# this test pins it as a general, whole-document property, across every
# fixer path at once (underline-only synthesis, wrong-length correction,
# hierarchy remap, BOM/line-ending normalization) — so the guarantee
# documented in guide.rst's trust section can say "provably" and mean
# it, not just "true by inspection of the two fixers that exist".
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_fix_never_changes_prose_content_lines(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
        return [line for line in text.splitlines() if line.strip() and not check_rst._is_adornment(line.rstrip())]

    before = prose_lines(original_text)

    check_rst.fix_hygiene(p)
    check_rst.fix_structure(p, True)

    after = prose_lines(p.read_text(encoding="utf-8"))
    assert after == before
    assert before  # sanity: the fixture actually has prose to compare


@pytest.mark.integration
def test_code_blocks_language_and_no_language(
    check_rst: types.ModuleType, build_sphinx_env: Callable[[str], tuple[object, str]]
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
    entries = check_rst.find_code_blocks(env, docname)
    assert [e.language for e in entries] == ["default", "bash"]


@pytest.mark.integration
def test_code_blocks_plain_literal_and_parsed_literal_excluded(
    check_rst: types.ModuleType, build_sphinx_env: Callable[[str], tuple[object, str]]
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
    assert check_rst.find_code_blocks(env, docname) == []


@pytest.mark.integration
def test_code_blocks_depth_matches_enclosing_section(
    check_rst: types.ModuleType, build_sphinx_env: Callable[[str], tuple[object, str]]
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
    entries = check_rst.find_code_blocks(env, docname)
    assert len(entries) == 1
    assert entries[0].depth == 3  # Chapter One=1, Sub A=2, code-block=3


@pytest.mark.integration
def test_code_blocks_nested_fake_marker_not_double_counted(
    check_rst: types.ModuleType, build_sphinx_env: Callable[[str], tuple[object, str]]
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
    entries = check_rst.find_code_blocks(env, docname)
    assert len(entries) == 1
    assert entries[0].language == "rst"


@pytest.mark.integration
def test_code_blocks_with_linenos_option_still_found(
    check_rst: types.ModuleType, build_sphinx_env: Callable[[str], tuple[object, str]]
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
    entries = check_rst.find_code_blocks(env, docname)
    assert len(entries) == 1
    assert entries[0].language == "python"


@pytest.mark.integration
def test_code_blocks_lineno_is_directive_marker_line(
    check_rst: types.ModuleType, build_sphinx_env: Callable[[str], tuple[object, str]]
) -> None:
    """lineno points at the directive's own marker line, stable regardless
    of trailing EOF (unlike bare docutils' .line for the same node kind,
    which is off by one depending on whether anything trails the block)."""
    env, docname = build_sphinx_env(
        """\
        Title
        =====

        .. code-block:: bash

           echo hi
        """
    )
    entries = check_rst.find_code_blocks(env, docname)
    assert entries[0].lineno == 4


@pytest.mark.integration
def test_code_blocks_str_format(
    check_rst: types.ModuleType, build_sphinx_env: Callable[[str], tuple[object, str]]
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
    entries = check_rst.find_code_blocks(env, docname)
    assert str(entries[0]) == "    4: code-block (bash): echo hi"


@pytest.mark.integration
def test_code_blocks_preview_whitespace_collapsed(
    check_rst: types.ModuleType, build_sphinx_env: Callable[[str], tuple[object, str]]
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
    entries = check_rst.find_code_blocks(env, docname)
    assert entries[0].preview == "x = 1 y = 2"


# ---------------------------------------------------------------------------
# find_code_blocks_heuristic — Phase 2 fallback with no --sphinx-src → Zone 2
#
# Pure text search, no docutils/Sphinx parsing at all — restores full recall
# for Sphinx-only options (:caption:/:linenos:) that break bare docutils
# parsing entirely, at the cost of a known, accepted, tested limitation: a
# ".. code-block::" merely quoted as example text inside another real
# code-block IS double-counted (there is no AST to guard against it, unlike
# the real find_code_blocks). depth is derived from build_outline's already-
# reliable section headings, not from any code-block-specific parsing.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_heuristic_code_blocks_short_alias_code_detected(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].language == "bash"


@pytest.mark.integration
def test_heuristic_code_blocks_sourcecode_alias_detected(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].language == "python"


@pytest.mark.integration
def test_heuristic_code_blocks_language_and_bare(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_code_blocks_heuristic(p)
    assert [e.language for e in entries] == ["bash", None]


@pytest.mark.integration
def test_heuristic_code_blocks_with_caption_no_language_still_found(
    check_rst: types.ModuleType, tmp_path: Path
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
    entries = check_rst.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].language is None


@pytest.mark.integration
def test_heuristic_code_blocks_with_linenos_option_still_found(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].language == "python"


@pytest.mark.integration
def test_heuristic_code_blocks_plain_literal_and_parsed_literal_excluded(
    check_rst: types.ModuleType, tmp_path: Path
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
    assert check_rst.find_code_blocks_heuristic(p) == []


@pytest.mark.integration
def test_heuristic_code_blocks_depth_from_build_outline(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].depth == 3  # Chapter One=1, Sub A=2, code-block=3


@pytest.mark.integration
def test_heuristic_code_blocks_no_preceding_heading_is_depth_1(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A code-block with no heading above it at all is depth 1 (top-level)."""
    p = _rst(
        tmp_path,
        """\
        .. code-block:: bash

           echo hi
        """,
    )
    entries = check_rst.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].depth == 1


@pytest.mark.integration
def test_heuristic_code_blocks_nested_fake_marker_is_double_counted(
    check_rst: types.ModuleType, tmp_path: Path
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
    entries = check_rst.find_code_blocks_heuristic(p)
    assert len(entries) == 2
    assert [e.language for e in entries] == ["rst", "python"]


@pytest.mark.integration
def test_heuristic_code_blocks_str_format(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_code_blocks_heuristic(p)
    assert str(entries[0]) == "    4-6: code-block (bash): echo hi"


@pytest.mark.integration
def test_heuristic_code_block_preview_skips_options_and_blank_separator(
    check_rst: types.ModuleType, tmp_path: Path
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
    entries = check_rst.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].preview == "echo hi"
    assert "Example" not in entries[0].preview


@pytest.mark.integration
def test_heuristic_code_block_preview_whitespace_collapsed(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Leading/trailing indentation and internal multi-space/multi-line gaps
    all collapse to single spaces — cut unnecessary spaces before output
    (Max, 2026-07-20)."""
    p = _rst(
        tmp_path,
        "Title\n=====\n\n.. code-block:: python\n\n    x = 1\n\n    y   =    2\n",
    )
    entries = check_rst.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].preview == "x = 1 y = 2"


@pytest.mark.integration
def test_heuristic_code_block_preview_truncated(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """The preview is bounded at 74 chars, truncated with '...' — a quick
    identity, not the block's full content."""
    long_line = "x = 1  # " + "word " * 20
    p = _rst(tmp_path, f"Title\n=====\n\n.. code-block:: python\n\n    {long_line}\n")
    entries = check_rst.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].preview.endswith("...")
    assert len(entries[0].preview) <= 77


@pytest.mark.integration
def test_heuristic_literalinclude_with_language_option_detected(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].language == "none"


@pytest.mark.integration
def test_heuristic_literalinclude_without_language_or_diff_excluded(
    check_rst: types.ModuleType, tmp_path: Path
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
    assert check_rst.find_code_blocks_heuristic(p) == []


@pytest.mark.integration
def test_heuristic_literalinclude_diff_option_is_udiff(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].language == "udiff"


@pytest.mark.integration
def test_heuristic_literalinclude_depth_matches_enclosing_section(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert entries[0].depth == 2


# ---------------------------------------------------------------------------
# fix_structure / diff_structure, adornment focus — auto-correction → Zone 2
# (fix_adornments/diff_adornments were folded into the composed pass —
# these tests keep pinning the adornment-fix behaviors through it)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_fix_wrong_length(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    changed = check_rst.fix_structure(p, True)
    assert changed
    assert "#######\nTitle\n#######" in p.read_text(encoding="utf-8")
    assert check_rst.check_adornments(p, True) == []


@pytest.mark.integration
def test_fix_mismatched_chars(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    check_rst.fix_structure(p, True)
    assert "#######\nTitle\n#######" in p.read_text(encoding="utf-8")
    assert check_rst.check_adornments(p, True) == []


@pytest.mark.integration
def test_fix_missing_blank_before_overline(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    check_rst.fix_structure(p, True)
    assert check_rst.check_adornments(p, True) == []


@pytest.mark.integration
def test_fix_missing_blank_after_underline(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    check_rst.fix_structure(p, True)
    assert check_rst.check_adornments(p, True) == []


@pytest.mark.integration
def test_fix_title_spaces(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    check_rst.fix_structure(p, True)
    content = p.read_text(encoding="utf-8")
    assert " Title" not in content
    assert check_rst.check_adornments(p, True) == []


@pytest.mark.integration
def test_fix_combined_errors(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    check_rst.fix_structure(p, True)
    assert check_rst.check_adornments(p, True) == []


@pytest.mark.integration
def test_fix_correct_file_unchanged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    changed = check_rst.fix_structure(p, True)
    assert not changed
    assert p.read_text(encoding="utf-8") == original


@pytest.mark.integration
def test_fix_underline_only(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    check_rst.fix_structure(p, True)
    assert check_rst.check_adornments(p, True) == []
    content = p.read_text(encoding="utf-8")
    # The lone '-' is this document's level 1, so the same pass remaps it
    # to '#' (this was always the CLI's end state — fix_hierarchy used to
    # do it right after fix_adornments; the composition makes the single
    # pass produce it directly).
    assert "#######\nTitle\n#######" in content


@pytest.mark.integration
def test_fix_underline_shorter_than_title(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    check_rst.fix_structure(p, True)
    assert check_rst.check_adornments(p, True) == []
    content = p.read_text(encoding="utf-8")
    assert "\nbla-bla\n" in content
    # 'bla-bla' is 7 chars -> expected adornment length 9.
    lines = content.splitlines()
    idx = lines.index("bla-bla")
    assert len(lines[idx - 1]) == len(lines[idx + 1]) == 9


@pytest.mark.integration
def test_fix_multiple_blocks(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    check_rst.fix_structure(p, True)
    assert check_rst.check_adornments(p, True) == []


@pytest.mark.integration
def test_diff_structure_returns_diff(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    diff = check_rst.diff_structure(p, True)
    assert diff
    assert "---" in diff
    assert "Title" in diff
    assert "######\nTitle\n######" in p.read_text(encoding="utf-8")


@pytest.mark.integration
def test_diff_structure_clean_file_empty(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    assert check_rst.diff_structure(p, True) == ""


# ---------------------------------------------------------------------------
# fix_structure / diff_structure, hierarchy focus — char remapping → Zone 2
# (a firing remap implies canonical geometry for every block it rewrites,
# so expectations here include the +2 widths, not remap-only results)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_fix_hierarchy_skipped_level(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    check_rst.fix_structure(p, True)
    assert check_rst.check_hierarchy(p) == []
    content = p.read_text(encoding="utf-8")
    assert "=====" not in content
    assert "*****\nSub\n*****" in content


@pytest.mark.integration
def test_fix_hierarchy_wrong_order(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    check_rst.fix_structure(p, True)
    assert check_rst.check_hierarchy(p) == []
    content = p.read_text(encoding="utf-8")
    assert "#######\nFirst\n#######" in content
    assert "********\nSecond\n********" in content


@pytest.mark.integration
def test_fix_hierarchy_correct_unchanged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    changed = check_rst.fix_structure(p, True)
    assert not changed
    assert p.read_text(encoding="utf-8") == original


@pytest.mark.integration
def test_fix_hierarchy_single_level_unchanged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A file with only one level (no hierarchy violations possible) is not modified."""
    original = textwrap.dedent("""\
        #######
        Title
        #######
        """)
    p = tmp_path / "test.rst"
    p.write_text(original, encoding="utf-8")
    assert not check_rst.fix_structure(p, True)


@pytest.mark.integration
def test_fix_hierarchy_remaps_lone_non_preferred_char_to_preferred(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    assert check_rst.fix_structure(p, True)
    fixed = p.read_text(encoding="utf-8")
    assert "#######\nTitle\n#######" in fixed


@pytest.mark.integration
def test_fix_hierarchy_remaps_non_preferred_char_mixed_with_preferred(
    check_rst: types.ModuleType, tmp_path: Path
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
    assert check_rst.fix_structure(p, True)
    fixed = p.read_text(encoding="utf-8")
    # '*' (1st seen) -> '#' (1st correct), at canonical width (3+2)
    assert "#####\nMid\n#####" in fixed
    # '~' (2nd seen) -> '*' (2nd correct), at canonical width (5+2)
    assert "*******\nAside\n*******" in fixed
    # '#' (3rd seen) -> '=' (3rd correct), at canonical width (3+2)
    assert "=====\nTop\n=====" in fixed


# ---------------------------------------------------------------------------
# _first_appearance_adornments blind to SHORT underline-only titles (Max,
# 2026-07-21) — found live, writing check_rst.rst itself: a document with
# two genuine but short titles ("Doc"/"###", "Sub"/"***" — 3-char
# underlines, below iter_underline_only's OWN MIN_UNDERLINE_ONLY_LEN=4
# floor, never yet promoted to full blocks) was entirely invisible to the
# old title-blocks-only scan.  The scan thought the FIRST character it had
# ever seen was a LATER, longer-titled heading's char, and the remap
# "corrected" it into the rank-1 slot already occupied by the earlier,
# invisible heading — producing a genuinely inconsistent document (the
# same char at two different depths) that no later --fix run could ever
# converge out of, since the scanner's blind spot never changes.  Real
# docutils' own minimum for a title-underline attempt to register at all
# is 2 chars (confirmed by direct probe), well below check_rst's own,
# stricter, promotion-safety floor of 4 — a fundamentally different
# question ("is this a real title" vs "is it safe to auto-promote this").
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_first_appearance_adornments_sees_short_underline_only_titles(
    check_rst: types.ModuleType,
) -> None:
    """The exact repro: two short (3-char), never-promoted underline-only
    titles must be visible to first-appearance detection, in document
    order, ahead of a later, longer, already-promotable title."""
    lines = ["Doc", "###", "", "Sub", "***", "", "Deep", "===="]
    seen = check_rst._first_appearance_adornments(lines)
    assert seen == [("#", 1), ("*", 4), ("=", 7)]


@pytest.mark.unit
def test_compute_structure_fixes_does_not_collide_short_titles(
    check_rst: types.ModuleType,
) -> None:
    """The full regression: composing the fix must not remap a later,
    correctly-ranked character into collision with an earlier, short,
    not-yet-promoted title using a DIFFERENT character at a DIFFERENT
    rank.  '=' (rank 3, correct for "Deep") must stay '=', never get
    "corrected" to '#' (already used, invisibly, by "Doc")."""
    lines = ["Doc", "###", "", "Sub", "***", "", "Deep", "===="]
    fixed = "\n".join(check_rst._compute_structure_fixes(lines, None))
    assert "######\nDoc\n######" not in fixed  # never remap Doc away from '#'
    assert "\n======\nDeep\n======" in fixed  # Deep stays '=', at canonical width


@pytest.mark.integration
def test_cli_fix_short_titles_converge_with_no_inconsistent_style(
    check_rst: types.ModuleType,
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
        ["check_rst.py", "--sphinx-src", str(rst_repo), "--build-dir", str(rst_repo / "_build"), "fix", str(p)],
    )
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    capsys.readouterr()

    result = subprocess.run(
        ["sphinx-build", "--builder", "html", str(rst_repo), str(rst_repo / "_verify")],
        capture_output=True,
        text=True,
    )
    assert "Inconsistent title style" not in result.stdout + result.stderr


# Must match check_rst.PREFERRED_HIERARCHY ('#*=-^"'); hardcoded here
# because parametrize runs at collection time, before the check_rst fixture
# exists. HIERARCHY itself is now 32 chars (PREFERRED_HIERARCHY plus every
# other valid RST adornment character appended after) — PREFERRED_HIERARCHY
# is exactly HIERARCHY's first 6, so this exhaustive test still holds.
_HIERARCHY_CHARS = '#*=-^"'


@pytest.mark.integration
@pytest.mark.parametrize("perm", list(itertools.permutations(_HIERARCHY_CHARS)))
def test_fix_hierarchy_any_permutation_converges_to_standard_order(
    check_rst: types.ModuleType, tmp_path: Path, perm: tuple[str, ...]
) -> None:
    """Exhaustive: for every one of the 6! = 720 orderings of the 6 project
    adornment characters, fix_structure converges to the exact same single
    canonical result (#*=-^" in document order) — a mechanical remap keyed
    only on first-appearance order, independent of which characters the
    document originally happened to use for each level.
    """
    assert check_rst.PREFERRED_HIERARCHY == _HIERARCHY_CHARS
    assert check_rst.HIERARCHY[: len(_HIERARCHY_CHARS)] == _HIERARCHY_CHARS

    titles = [f"Level {i}" for i in range(1, len(_HIERARCHY_CHARS) + 1)]

    def block(ch: str, title: str) -> str:
        adorn = ch * (len(title) + 2)
        return f"{adorn}\n{title}\n{adorn}"

    original = "\n\n".join(block(ch, t) for ch, t in zip(perm, titles, strict=True)) + "\n"
    expected = "\n\n".join(block(ch, t) for ch, t in zip(_HIERARCHY_CHARS, titles, strict=True)) + "\n"

    p = tmp_path / "test.rst"
    p.write_text(original, encoding="utf-8")

    check_rst.fix_structure(p, True)

    assert p.read_text(encoding="utf-8") == expected
    assert check_rst.check_hierarchy(p) == []


@pytest.mark.integration
def test_diff_structure_hierarchy_returns_diff(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    diff = check_rst.diff_structure(p, True)
    assert diff
    assert "---" in diff
    assert "-=====" in diff  # original underline in diff
    assert "+*****" in diff  # replacement in diff
    assert "=====\nSub\n=====" in p.read_text(encoding="utf-8")  # file not modified


@pytest.mark.integration
def test_diff_structure_hierarchy_clean_empty(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    assert check_rst.diff_structure(p, True) == ""


# ---------------------------------------------------------------------------
# Literal-block context tests — verify docutils NodeVisitor implementation
#
# These tests were initially written as xfail (RED phase) to document the
# false-positive behaviour of the raw-line regex implementation.  They
# became GREEN when check_directives was rewritten with a docutils visitor:
# SkipNode in visit_literal_block prevents visiting any children of
# literal-block nodes, eliminating all code-example false positives.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_directives_rubric_in_code_block_not_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """.. rubric:: inside a .. code-block:: rst example must NOT be flagged.

    docutils skips children of literal_block nodes via SkipNode, so the
    rubric directive written as a code example is never visited.
    """
    p = _rst(
        tmp_path,
        """\
        Use ``.. rubric::`` sparingly.  Example of the directive syntax:

        .. code-block:: rst

           .. rubric:: My Heading

           Some rubric body text.

        Prefer a proper section title instead.
        """,
    )
    assert check_rst.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_rubric_in_literal_block_not_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """.. rubric:: inside a :: literal block must NOT be flagged.

    A paragraph ending with ``::`` creates a literal_block node in docutils;
    its children are never visited.
    """
    p = _rst(
        tmp_path,
        """\
        The following is literal text, not a directive::

            .. rubric:: Example Heading

        Back to normal text.
        """,
    )
    assert check_rst.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_rubric_in_nested_literal_block_not_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """.. rubric:: in a code-block nested inside .. note:: must NOT be flagged.

    SkipNode applies regardless of nesting depth — the visitor never
    descends into any literal_block subtree.
    """
    p = _rst(
        tmp_path,
        """\
        .. note::

           Usage example::

              .. rubric:: Demo

        Normal text.
        """,
    )
    assert check_rst.check_directives(p, True) == []


# ---------------------------------------------------------------------------
# whole_file scoping against real git state
#   (committed, staged, unstaged, untracked) → Zone 2
#
# check_adornments(path, whole_file) restricts findings to lines changed
# since HEAD unless whole_file=True.  The CLI (main()) sets whole_file from
# whether files were named explicitly (bool(args.files)) — naming a file is
# a deliberate "check this" instruction, so it's always checked in full;
# auto-detected files (no args, git status) stay diff-scoped.  These tests
# exercise that scoping against an actual git repository in each relevant
# state, plus one CLI-level test tying it to explicit-vs-auto file selection.
# ---------------------------------------------------------------------------

# "Title" = 5 chars → expected adornment length 7; "######" is 6 → ERROR.
_BAD_BLOCK = textwrap.dedent("""\
    Some text.

    ######
    Title
    ######

    More text.
    """)

# Same block, correctly formed — no violations.
_GOOD_BLOCK = textwrap.dedent("""\
    Some text.

    #######
    Title
    #######

    More text.
    """)

# Appended to a committed-clean file as an unstaged/staged edit: an
# underline-only title with no matching overline.
_APPENDED_UNDERLINE_ONLY = textwrap.dedent("""

    New Title
    ---------
    """)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def rst_repo(check_rst: types.ModuleType, tmp_git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point check_rst's PROJECT_ROOT at the temp git repo for git-scoped checks."""
    monkeypatch.setattr(check_rst, "PROJECT_ROOT", tmp_git_repo)
    return tmp_git_repo


@pytest.mark.integration
def test_changed_rst_files_decodes_git_quoted_non_ascii_path(check_rst: types.ModuleType, rst_repo: Path) -> None:
    """Bare discovery must return the real path, not Git's octal escapes."""
    _git(rst_repo, "config", "core.quotePath", "true")
    p = rst_repo / "документ.rst"
    p.write_text("", encoding="utf-8")

    assert check_rst._changed_rst_files() == [p]


@pytest.mark.integration
def test_changed_rst_files_skips_deleted_paths(check_rst: types.ModuleType, rst_repo: Path) -> None:
    """A deleted document has no working-tree file left for check_rst to read."""
    p = rst_repo / "deleted.rst"
    p.write_text("", encoding="utf-8")
    _git(rst_repo, "add", "deleted.rst")
    _git(rst_repo, "commit", "-m", "add document")
    p.unlink()

    assert check_rst._changed_rst_files() == []


@pytest.mark.integration
def test_changed_rst_files_from_nested_directory_uses_worktree_root(
    check_rst: types.ModuleType,
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
    monkeypatch.setattr(check_rst, "PROJECT_ROOT", nested)

    assert check_rst._changed_rst_files() == [p]


@pytest.mark.integration
def test_changed_rst_files_supports_non_utf8_git_filename(check_rst: types.ModuleType, rst_repo: Path) -> None:
    """Git filenames are byte strings; porcelain -z must use surrogateescape."""
    raw_path = os.fsencode(rst_repo) + b"/non_utf8_\xff.rst"
    fd = os.open(raw_path, os.O_WRONLY | os.O_CREAT, 0o600)
    os.close(fd)

    assert check_rst._changed_rst_files() == [Path(os.fsdecode(raw_path))]


@pytest.mark.integration
def test_changed_rst_files_preserves_non_repository_git_failure(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A corrupt index is not falsely diagnosed as 'not a git repository'."""
    responses = iter(
        [
            subprocess.CompletedProcess(["git"], 0, stdout=f"{tmp_path}\n", stderr=""),
            subprocess.CompletedProcess(["git"], 128, stdout="", stderr="fatal: index file corrupt"),
        ]
    )
    monkeypatch.setattr(check_rst, "_git", lambda *_args: next(responses))

    with pytest.raises(SystemExit) as exc:
        check_rst._changed_rst_files()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "git status failed" in out
    assert "index file corrupt" in out
    assert "not a git repository" not in out


@pytest.mark.integration
def test_whole_file_catches_preexisting_error_in_committed_file(check_rst: types.ModuleType, rst_repo: Path) -> None:
    """A fully committed file with no pending changes: diff-scoped (default
    for auto-detected files) finds nothing, whole_file=True (what the CLI
    uses for explicitly-named files) finds the pre-existing adornment error."""
    p = rst_repo / "test.rst"
    p.write_text(_BAD_BLOCK, encoding="utf-8")
    _git(rst_repo, "add", "test.rst")
    _git(rst_repo, "commit", "-m", "add file with a pre-existing error")

    assert check_rst.check_adornments(p, whole_file=False) == []

    violations = check_rst.check_adornments(p, whole_file=True)
    assert violations
    assert any("must be 7 chars" in v for v in violations)


@pytest.mark.integration
def test_default_ignores_committed_error_but_catches_unstaged_addition(
    check_rst: types.ModuleType, rst_repo: Path
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

    default_violations = check_rst.check_adornments(p, whole_file=False)
    assert any("underline-only" in v for v in default_violations)
    assert not any("must be 7 chars" in v for v in default_violations)

    all_violations = check_rst.check_adornments(p, whole_file=True)
    assert any("underline-only" in v for v in all_violations)
    assert any("must be 7 chars" in v for v in all_violations)


@pytest.mark.integration
def test_default_catches_error_in_staged_change(check_rst: types.ModuleType, rst_repo: Path) -> None:
    """A staged (git add, not committed) change is diffed against HEAD, so
    diff-scoped (whole_file=False) still catches its errors."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    _git(rst_repo, "add", "test.rst")
    _git(rst_repo, "commit", "-m", "add clean file")

    p.write_text(_GOOD_BLOCK + _APPENDED_UNDERLINE_ONLY, encoding="utf-8")
    _git(rst_repo, "add", "test.rst")  # staged, not committed

    assert check_rst.check_adornments(p, whole_file=False) != []


@pytest.mark.integration
def test_default_catches_error_in_unstaged_change(check_rst: types.ModuleType, rst_repo: Path) -> None:
    """A tracked file edited but not staged is still diffed against HEAD, so
    diff-scoped (whole_file=False) catches errors in the unstaged edit."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    _git(rst_repo, "add", "test.rst")
    _git(rst_repo, "commit", "-m", "add clean file")

    p.write_text(_GOOD_BLOCK + _APPENDED_UNDERLINE_ONLY, encoding="utf-8")  # unstaged

    assert check_rst.check_adornments(p, whole_file=False) != []


@pytest.mark.integration
def test_default_catches_error_in_untracked_new_file(check_rst: types.ModuleType, rst_repo: Path) -> None:
    """An untracked (never git-added) file is always checked in full, even
    with whole_file=False — there is no HEAD state to diff against."""
    p = rst_repo / "new.rst"
    p.write_text(_BAD_BLOCK, encoding="utf-8")  # not added to git at all

    violations = check_rst.check_adornments(p, whole_file=False)
    assert any("must be 7 chars" in v for v in violations)


@pytest.mark.integration
def test_cli_explicit_file_is_whole_file_auto_detect_is_diff_scoped(
    check_rst: types.ModuleType,
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
        check_rst.main()
    assert auto_exit.value.code == 1
    auto_out = capsys.readouterr().out
    assert "underline-only" in auto_out
    assert "must be 7 chars" not in auto_out

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as explicit_exit:
        check_rst.main()
    assert explicit_exit.value.code == 1
    explicit_out = capsys.readouterr().out
    assert "underline-only" in explicit_out
    assert "must be 7 chars" in explicit_out


@pytest.mark.integration
def test_cli_deduplicates_repeated_explicit_file_arguments(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "doc.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(document), str(document.resolve())])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    assert "1 file(s) checked" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_git_scope_fix_changes_only_selected_changed_file(
    check_rst: types.ModuleType,
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
        check_rst.main()

    assert exc.value.code == 0
    assert selected.read_text(encoding="utf-8") == _GOOD_BLOCK
    assert unrelated.read_bytes() == unrelated_before
    assert str(unrelated) not in capsys.readouterr().out


@pytest.mark.integration
def test_cli_git_scope_preserves_diff_scope_for_selected_file(
    check_rst: types.ModuleType,
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
        check_rst.main()

    assert exc.value.code == 0
    assert "must be 7 chars" not in capsys.readouterr().out


@pytest.mark.integration
@pytest.mark.parametrize("selection", ["bare", "git-scope"])
@pytest.mark.parametrize("verb_tail", [["fix"], ["fix", "--fast"]], ids=["fix", "fix-fast"])
def test_git_scoped_fix_reflows_adornments_when_only_title_text_changed(
    check_rst: types.ModuleType,
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
        check_rst.main()

    assert exc.value.code == 0
    expected = "#" * (len("Longer Title") + 2)
    assert document.read_text(encoding="utf-8") == (f"{expected}\nLonger Title\n{expected}\n")


@pytest.mark.integration
def test_cli_git_scope_unchanged_file_is_not_selected(
    check_rst: types.ModuleType,
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
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "no selected changed .rst files" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_cli_git_scope_rejects_file_outside_selected_worktree_before_fix(
    check_rst: types.ModuleType,
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
        check_rst.main()

    assert exc.value.code == 1
    assert selected.read_text(encoding="utf-8") == selected_original
    out = capsys.readouterr().out
    assert "outside the selected Git worktree" in out
    assert "Phase 1" not in out


# ---------------------------------------------------------------------------
# fix_structure / diff_structure — remap and widths compose in ONE pass
# → Zones 1-2
#
# Found in a downstream project's coding-standards.rst (2026-07-20): a git-changed file
# whose hierarchy remap fired needed TWO bare --fix runs to converge.
# Pass 1 remapped adornment chars document-wide but preserved their (wrong)
# widths — those blocks sat outside the diff scope; only after that write
# did the remapped lines enter the diff scope, so pass 2 fixed the widths.
# The composition rule: every line the remap rewrites joins the fix scope
# in the same pass — git would report it as changed after the write anyway.
# ---------------------------------------------------------------------------

# Committed base, matching the downstream project's coding-standards shape:
# '*'-rooted hierarchy (the
# remap fires for every level) with non-canonical widths everywhere.
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

# Unstaged working-tree addition: a third level, itself non-canonical.
_APPENDED_THIRD_LEVEL = textwrap.dedent("""
    ----------------------
    Added
    ----------------------

    New text.
    """)


@pytest.mark.unit
def test_compute_structure_fixes_remapped_lines_join_scope(
    check_rst: types.ModuleType,
) -> None:
    """When the remap fires, the blocks it rewrites get canonical geometry
    in the SAME pass, even though they sit outside the changed ranges."""
    lines = (_WIDE_STARRED_DOC + _APPENDED_THIRD_LEVEL).splitlines()
    appended_start = len(_WIDE_STARRED_DOC.splitlines()) + 1
    ranges = [(appended_start, appended_start + 6)]

    fixed = "\n".join(check_rst._compute_structure_fixes(lines, ranges))

    assert "#######\nTitle\n#######" in fixed
    assert "*********\nSection\n*********" in fixed
    assert "=======\nAdded\n=======" in fixed
    assert "*" * 22 not in fixed
    assert "=" * 22 not in fixed


@pytest.mark.unit
def test_compute_structure_fixes_no_remap_keeps_diff_scope(
    check_rst: types.ModuleType,
) -> None:
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

    fixed = "\n".join(check_rst._compute_structure_fixes(lines, ranges))

    assert "##########\nTitle\n##########" in fixed  # out of scope: kept
    assert "*****\nSub\n*****" in fixed  # in scope: width fixed


@pytest.mark.integration
def test_cli_bare_fix_converges_in_one_pass_when_remap_fires(
    check_rst: types.ModuleType,
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
        check_rst.main()
    assert fix_exit.value.code == 0
    capsys.readouterr()

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check"])
    with pytest.raises(SystemExit) as check_exit:
        check_rst.main()
    out = capsys.readouterr().out
    assert "ERROR" not in out
    assert check_exit.value.code == 0


@pytest.mark.integration
def test_cli_bare_diff_previews_composed_result(
    check_rst: types.ModuleType,
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
        check_rst.main()
    out = capsys.readouterr().out

    assert "+#######\n" in out  # Title block, remapped AND resized
    assert "+" + "#" * 22 not in out  # the intermediate must not appear


# ---------------------------------------------------------------------------
# --sphinx-src — Phase 2/3 opt-in, no implicit default → Zone 2
#
# There is no --no-sphinx: omitting --sphinx-src skips both Phase 2 (Python
# Sphinx rules) and Phase 3 (sphinx-build integrity) entirely, and an
# explicitly-given directory without conf.py is a hard error rather than a
# silent skip (a typo'd path is a mistake worth failing loudly on).
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_sphinx_src_omitted_runs_heuristic_phase2_skips_phase3(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No --sphinx-src at all: Phase 2 still runs, but in labeled heuristic
    mode (no real Sphinx env is built) — only Phase 3 (which has no
    heuristic equivalent) is actually skipped."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Phase 2: Python Sphinx rules (heuristic — no --sphinx-src given" in out
    assert "Phase 3: Sphinx build — skipped (no --sphinx-src given)" in out


@pytest.mark.integration
def test_sphinx_src_missing_conf_py_errors_before_phase1(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--sphinx-src DIR with no conf.py in DIR is a hard error, not a skip —
    and it happens before Phase 1 even starts."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    empty_dir = rst_repo / "not_sphinx"
    empty_dir.mkdir()

    monkeypatch.setattr("sys.argv", ["check_rst.py", "--sphinx-src", str(empty_dir), "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "no conf.py found" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_sphinx_src_valid_dir_runs_phase2_and_phase3(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--sphinx-src DIR with a real conf.py in DIR runs both Phase 2 and
    Phase 3, in that order."""
    p = rst_repo / "index.rst"
    p.write_text(_GOOD_BLOCK + "\n.. toctree::\n", encoding="utf-8")
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "--sphinx-src", str(rst_repo), "check", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "Phase 2: Python Sphinx rules" in out
    assert "Phase 3: Sphinx build integrity" in out
    assert "runtime: check_rst 0.1.0, Python " in out
    assert "Sphinx " in out
    assert "docutils " in out
    assert out.index("Phase 2: Python Sphinx rules") < out.index("Phase 3: Sphinx build integrity")


@pytest.mark.integration
def test_cli_invalid_sphinx_configuration_is_clean_error_not_traceback(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text("this is not valid Python(\n", encoding="utf-8")
    document = rst_repo / "index.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "check", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Sphinx environment build failed" in out
    assert "ConfigError" in out
    assert "syntax error" in out
    assert "Traceback" not in out


@pytest.mark.integration
def test_outline_without_sphinx_src_shows_heuristic_headings_and_code_blocks(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--outline with no --sphinx-src: the merged structure now prints
    during Phase 2 (heuristic mode), never Phase 1 — one place for
    --outline's output regardless of whether --sphinx-src is given."""
    p = rst_repo / "test.rst"
    p.write_text(
        "Chapter One\n===========\n\n.. code-block:: bash\n\n   echo hi\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out

    phase1_block = out[out.index("Phase 1: RST rules") : out.index("Phase 2: Python Sphinx rules")]
    assert "Outline:" not in phase1_block

    phase2_block = out[out.index("Phase 2: Python Sphinx rules") : out.index("Phase 3:")]
    assert "Outline:" in phase2_block
    assert "levels: 1 '='" in phase2_block
    assert "1-6:= Chapter One" in phase2_block
    assert "code-block" in phase2_block


@pytest.mark.integration
def test_outline_with_sphinx_src_merges_headings_and_code_blocks(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--outline with --sphinx-src: headings and code-blocks appear together,
    sorted by line, in ONE block under Phase 2 — not split across phases."""
    p = rst_repo / "index.rst"
    p.write_text(
        "Chapter One\n===========\n\n.. code-block:: bash\n\n   echo hi\n",
        encoding="utf-8",
    )
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv", ["check_rst.py", "--sphinx-src", str(rst_repo), "outline", "--with-findings", str(p)]
    )
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out

    # Phase 1 must not print its own separate outline when --sphinx-src is given.
    phase1_block = out[out.index("Phase 1: RST rules") : out.index("Phase 2: Python Sphinx rules")]
    assert "Outline:" not in phase1_block

    phase2_block = out[out.index("Phase 2: Python Sphinx rules") : out.index("Phase 3:")]
    assert "Outline:" in phase2_block
    heading_idx = phase2_block.index("1-6:= Chapter One")
    code_idx = phase2_block.index("code-block")
    assert heading_idx < code_idx  # heading (line 1) before code-block (line 4)


@pytest.mark.integration
def test_outline_with_sphinx_src_uses_sphinx_doctree_for_headings(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verified mode must derive sections, not only code blocks, from Sphinx.

    Bare docutils cannot parse ``only`` and drops its nested content.  The
    dummy Sphinx builder does parse ``.. only:: dummy`` and its nested
    section is therefore part of the verified structure promised by
    ``--outline``.
    """
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    p = rst_repo / "index.rst"
    p.write_text(
        textwrap.dedent("""\
            #######
            Title
            #######

            .. only:: dummy

               ********
               Nested
               ********

               Body.
            """),
        encoding="utf-8",
    )
    monkeypatch.setattr(check_rst, "run_sphinx", lambda *_args: [])
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "outline", "--no-adornments", "--no-directives", str(p)],
    )

    with pytest.raises(SystemExit):
        check_rst.main()

    out = capsys.readouterr().out
    assert "Title" in out
    assert "Nested" in out


# ---------------------------------------------------------------------------
# find_toctrees / --outline across .. toctree:: boundaries (2026-07-26)
#
# Extends --outline to recurse into every document a toctree directive
# reaches, in turn — cross-file headings reuse OutlineEntry (docname set)
# so --sections-only's isinstance filter naturally keeps them; the
# container itself is a distinct ToctreeEntry, naturally hidden by that
# same filter.  Verified mode only (--sphinx-src) — toctree is invisible
# to bare docutils entirely.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_multiple_toctree_check_flags_same_child_twice_in_one_parent(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "index": "Index\n=====\n\n.. toctree::\n\n   child\n   child\n",
            "child": "Child\n=====\n",
        },
    )

    findings = check_rst.check_multiple_toctree_parents(env, [tmp_path / "index.rst"])

    assert len(findings) == 1
    assert findings[0].severity == "WARNING"
    assert findings[0].lineno == 4
    assert "child" in findings[0].text
    assert "index" in findings[0].text


@pytest.mark.integration
def test_multiple_toctree_check_flags_child_under_distinct_parents(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "index": "Index\n=====\n",
            "parent-a": "Parent A\n========\n\n.. toctree::\n\n   child\n",
            "parent-b": "Parent B\n========\n\n.. toctree::\n\n   child\n",
            "child": "Child\n=====\n",
        },
    )

    findings = check_rst.check_multiple_toctree_parents(env, [tmp_path / "parent-a.rst", tmp_path / "child.rst"])

    assert len(findings) == 2
    assert {f.severity for f in findings} == {"WARNING"}
    assert all("parent-a" in f.text and "parent-b" in f.text for f in findings)


@pytest.mark.integration
def test_multiple_toctree_check_single_reference_is_clean(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "index": "Index\n=====\n\n.. toctree::\n\n   child\n",
            "child": "Child\n=====\n",
        },
    )

    assert check_rst.check_multiple_toctree_parents(env, [tmp_path / "index.rst", tmp_path / "child.rst"]) == []


@pytest.mark.integration
def test_cli_selected_toctree_parent_surfaces_child_anchored_anomaly(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The selected parent must surface a concern Sphinx anchors to its child."""
    (tmp_path / "conf.py").write_text(
        'project = "test"\nextensions = []\nroot_doc = "index"\n',
        encoding="utf-8",
    )
    parent = tmp_path / "index.rst"
    parent.write_text(
        "#######\nIndex\n#######\n\n.. toctree::\n\n   child\n   child\n",
        encoding="utf-8",
    )
    (tmp_path / "child.rst").write_text("#######\nChild\n#######\n", encoding="utf-8")
    monkeypatch.setattr(check_rst, "run_sphinx", lambda *_args: [])
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(tmp_path), "check", "--quiet", str(parent)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert f"{parent}:5: WARNING:" in out
    assert "child" in out


@pytest.mark.integration
def test_multiple_toctree_check_survives_persistent_cache_rerun(check_rst: types.ModuleType, tmp_path: Path) -> None:
    (tmp_path / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    parent = tmp_path / "index.rst"
    parent.write_text("Index\n=====\n\n.. toctree::\n\n   child\n   child\n", encoding="utf-8")
    (tmp_path / "child.rst").write_text("Child\n=====\n", encoding="utf-8")
    build_dir = tmp_path / "_build"

    check_rst._build_sphinx_env(tmp_path, build_dir, files=[parent])
    env, _warnings = check_rst._build_sphinx_env(tmp_path, build_dir, files=[parent])

    findings = check_rst.check_multiple_toctree_parents(env, [parent])
    assert len(findings) == 1


@pytest.mark.integration
def test_toctree_recurses_into_included_documents(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A single-level toctree pulls in each target's own headings, depth
    offset by the toctree container's own depth (Index=1, Section A=2,
    so sub1's own top heading — locally depth 1 — lands at 2+1=3)."""
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text(
        textwrap.dedent("""\
            Index
            =====

            Section A
            ---------

            .. toctree::
               :maxdepth: 2

               sub1
               sub2
            """),
        encoding="utf-8",
    )
    (rst_repo / "sub1.rst").write_text("Sub One\n=======\n\nSub One Child\n-------------\n", encoding="utf-8")
    (rst_repo / "sub2.rst").write_text("Sub Two\n=======\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "outline", str(rst_repo / "index.rst")],
    )
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out

    assert "toctree (2 entries, maxdepth=2)" in out
    assert "sub1:1-5:= Sub One" in out
    assert "sub1:4-5:- Sub One Child" in out
    assert "sub2:1-2:= Sub Two" in out
    # Depth math: sub1's own local depth-1 title lands one level deeper
    # than the toctree container that pulled it in (10-space indent),
    # its own local depth-2 child one level deeper still.
    assert "          7-11: toctree (2 entries, maxdepth=2)" in out
    assert "              sub1:1-5:= Sub One" in out
    assert "                  sub1:4-5:- Sub One Child" in out


@pytest.mark.integration
def test_toctree_recurses_across_multiple_levels(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A nested toctree (sub1 -> subsub1) is followed recursively, not
    only one level deep — --outline-depth is the only bound, never a
    per-toctree :maxdepth:."""
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text("Index\n=====\n\n.. toctree::\n\n   sub1\n", encoding="utf-8")
    (rst_repo / "sub1.rst").write_text("Sub One\n=======\n\n.. toctree::\n\n   subsub1\n", encoding="utf-8")
    (rst_repo / "subsub1.rst").write_text("Sub Sub One\n===========\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "outline", str(rst_repo / "index.rst")],
    )
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out

    assert "sub1:1-6:= Sub One" in out
    assert "subsub1:1-2:= Sub Sub One" in out
    # Provenance belongs only to entries pulled from another document:
    # the root container is local to index.rst and stays bare, while the
    # nested container must be self-identifying when read as one line.
    assert "index:4-6: toctree" not in out
    assert "sub1:4-6: toctree (1 entry, maxdepth=unlimited)" in out
    # subsub1 must appear strictly after sub1's own toctree line, nested
    # one level deeper than sub1's own heading.
    assert out.index("sub1:1-6:= Sub One") < out.index("subsub1:1-2:= Sub Sub One")


@pytest.mark.integration
def test_toctree_cycle_is_reported_and_does_not_hang(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """index -> a -> b -> index: the revisit of 'index' stops that branch
    with a visible marker instead of recursing forever."""
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text("Index\n=====\n\n.. toctree::\n\n   a\n", encoding="utf-8")
    (rst_repo / "a.rst").write_text("Doc A\n=====\n\n.. toctree::\n\n   b\n", encoding="utf-8")
    (rst_repo / "b.rst").write_text("Doc B\n=====\n\n.. toctree::\n\n   index\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "outline", str(rst_repo / "index.rst")],
    )
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out

    assert "a:1-6:= Doc A" in out
    assert "b:1-6:= Doc B" in out
    assert "toctree cycle" in out
    assert "b:4: toctree cycle" in out
    assert "'index' is already an ancestor" in out


@pytest.mark.integration
def test_toctree_diamond_shows_heading_again_without_reexpanding(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A document reachable via two different toctrees (a->b and index->b,
    non-cyclic) gets its heading twice, but its own nested toctree is only
    walked once — the second occurrence shows no nested toctree line."""
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text("Index\n=====\n\n.. toctree::\n\n   a\n   b\n", encoding="utf-8")
    (rst_repo / "a.rst").write_text("Doc A\n=====\n\n.. toctree::\n\n   b\n", encoding="utf-8")
    (rst_repo / "b.rst").write_text("Doc B\n=====\n\nBody of B.\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "outline", str(rst_repo / "index.rst")],
    )
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out

    assert out.count("b:1-4:= Doc B") == 2


@pytest.mark.integration
def test_toctree_sections_only_hides_container_keeps_cross_file_headings(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--sections-only hides the toctree CONTAINER marker (a leaf) but
    keeps the cross-file headings it pulled in (real sections)."""
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text("Index\n=====\n\n.. toctree::\n\n   sub1\n", encoding="utf-8")
    (rst_repo / "sub1.rst").write_text("Sub One\n=======\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "outline", "--sections-only", str(rst_repo / "index.rst")],
    )
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out

    assert "toctree (" not in out
    assert "sub1:1-2:= Sub One" in out


@pytest.mark.integration
def test_toctree_outline_depth_bounds_across_file_boundary(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--outline-depth applies uniformly to depth, including nested
    documents pulled in via toctree — not just this file's own headings."""
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text("Index\n=====\n\n.. toctree::\n\n   sub1\n", encoding="utf-8")
    (rst_repo / "sub1.rst").write_text("Sub One\n=======\n\nSub One Child\n-------------\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "outline", "--outline-depth", "2", str(rst_repo / "index.rst")],
    )
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out

    # The toctree container itself is shallow enough to stay visible, but
    # sub1's own title AND its own child heading both land deeper than
    # --outline-depth 2 once offset by the container's depth — hidden on
    # both sides of the file boundary, uniformly, not just locally.
    assert "toctree (1 entry, maxdepth=unlimited)" in out
    assert "Sub One" not in out
    assert "2 deeper entries hidden — --outline-depth 2" in out


@pytest.mark.integration
def test_no_toctree_flag_suppresses_recursion(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--no-toctree opts out of toctree recursion entirely."""
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text("Index\n=====\n\n.. toctree::\n\n   sub1\n", encoding="utf-8")
    (rst_repo / "sub1.rst").write_text("Sub One\n=======\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "outline", "--no-toctree", str(rst_repo / "index.rst")],
    )
    with pytest.raises(SystemExit):
        check_rst.main()
    # Search only the Outline: section's own body, not the whole capture —
    # pytest's own tmp_path for THIS test's name literally contains
    # "no_toctree", which would false-positive a bare substring check
    # against the full output (which echoes the checked file's path).
    out = capsys.readouterr().out
    outline_body = out[out.index("levels:") :]

    assert "toctree" not in outline_body
    assert "Sub One" not in outline_body


@pytest.mark.integration
def test_toctree_json_shape_includes_toctrees_and_cross_file_ids(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--json reports local and foreign toctree-container provenance and
    merges cross-file headings into "outline" with their OWN document's
    id — never the requesting file's id."""
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text("Index\n=====\n\n.. toctree::\n\n   sub1\n", encoding="utf-8")
    (rst_repo / "sub1.rst").write_text("Sub One\n=======\n\n.. toctree::\n\n   subsub1\n", encoding="utf-8")
    (rst_repo / "subsub1.rst").write_text("Sub Sub One\n===========\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "check", "--format=json", str(rst_repo / "index.rst")],
    )
    with pytest.raises(SystemExit):
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    file_record = data["files"][0]

    assert len(file_record["toctrees"]) == 2
    assert file_record["toctrees"][0]["item_count"] == 1
    assert [entry["docname"] for entry in file_record["toctrees"]] == [None, "sub1"]
    ids = {e["id"] for e in file_record["outline"]}
    assert "sub1:Sub One" in ids
    assert "subsub1:Sub Sub One" in ids
    assert "index:Index" in ids


@pytest.mark.integration
def test_toctree_invisible_without_sphinx_src(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Heuristic mode (no --sphinx-src) never recurses: toctree is not
    even a recognized directive to bare docutils."""
    (rst_repo / "sub1.rst").write_text("Sub One\n=======\n", encoding="utf-8")
    p = rst_repo / "index.rst"
    p.write_text("Index\n=====\n\n.. toctree::\n\n   sub1\n", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out

    assert "sub1:" not in out
    assert "Sub One" not in out


# ---------------------------------------------------------------------------
# --skip-fixable — suppress auto-fixable errors → Zone 2 (CLI)
#
# All ERROR-level findings from check_adornments and check_hierarchy are
# guaranteed to be resolved by --fix.  --skip-fixable silences them on the
# pre-fix validation pass so only WARNINGs (bold headings, rubric — requiring
# human judgment) remain visible.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_skip_fixable_suppresses_width_error(
    check_rst: types.ModuleType,
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
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "must be 7 chars" not in out
    assert "adornments + hierarchy OK" not in out
    assert "1 auto-fixable finding(s) suppressed" in out


@pytest.mark.integration
def test_skip_fixable_suppresses_underline_only(
    check_rst: types.ModuleType,
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
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "underline-only" not in out


@pytest.mark.integration
def test_skip_fixable_suppresses_hierarchy_error(
    check_rst: types.ModuleType,
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
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--fix remaps" not in out


@pytest.mark.integration
def test_skip_fixable_preserves_directive_warnings(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Directive WARNINGs (bold headings, rubric) are still shown with --skip-fixable."""
    p = _rst(tmp_path, "**Bold Heading**\n\nSome text.\n")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--skip-fixable", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "WARNING:" in out


@pytest.mark.integration
def test_skip_fixable_preserves_single_top_level_warnings(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A second top-level title is not --fix-fixable (which section should
    demote is a content decision), so --skip-fixable must not swallow it —
    same precedent as directive WARNINGs."""
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
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "top-level" in out
    assert "WARNING:" in out


@pytest.mark.integration
def test_cli_json_single_top_level_warning_included(
    check_rst: types.ModuleType,
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
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    findings = data["files"][0]["findings"]
    assert any(f["severity"] == "WARNING" and "top-level" in f["text"] for f in findings)


@pytest.mark.integration
def test_skip_fixable_mixed_shows_only_warnings(
    check_rst: types.ModuleType,
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
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "must be 7 chars" not in out
    assert "WARNING:" in out


@pytest.mark.integration
def test_skip_fixable_suppresses_sphinx_structural_duplicate_only(
    check_rst: types.ModuleType,
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
        check_rst,
        "run_sphinx",
        lambda *_args: [
            check_rst.Finding(1, "WARNING", "index.rst: Title overline too short."),
            check_rst.Finding(
                5,
                "WARNING",
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
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Title overline too short" not in out
    assert "Title underline too short" not in out
    assert "nonexisting document" in out
    assert "1 warning(s)" in out


@pytest.mark.integration
def test_without_skip_fixable_width_error_exits_1(
    check_rst: types.ModuleType,
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
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "must be 7 chars" in out


# ---------------------------------------------------------------------------
# --recursive / --exclude — native directory-scope discovery → Zone 2
#
# Replaces the hand-rolled `find ... -print0 | mapfile -d ''` idiom that
# recurred across /rst-formatting invocations (see calendar/2026/07/2026-
# 07-16 analysis): a scope (a calendar month, a docs/ tree) resolved into a
# file list by shell, repeated identically per invocation, that once caused
# a real word-splitting bug on filenames containing spaces. pathlib.rglob
# has no shell word-splitting at all, so that bug class is structurally
# closed here, not just patched at one call site.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_recursive_discovers_nested_rst_files(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--recursive DIR discovers *.rst files at any depth under DIR."""
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b").mkdir()
    top = tmp_path / "top.rst"
    nested = tmp_path / "a" / "mid.rst"
    deep = tmp_path / "a" / "b" / "deep.rst"
    for p in (top, nested, deep):
        p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--recursive", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert str(top) in out
    assert str(nested) in out
    assert str(deep) in out


@pytest.mark.integration
def test_recursive_multiple_directories_merged_no_duplicates(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Overlapping --recursive directories don't check the same file twice.

    tmp_path and tmp_path/sub both reach sub/a.rst via rglob, so passing
    both must still process it exactly once — not once per directory that
    happens to reach it.
    """
    (tmp_path / "sub").mkdir()
    f = tmp_path / "sub" / "a.rst"
    f.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "check", "--recursive", str(tmp_path), str(tmp_path / "sub")],
    )
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    # Each file gets exactly 2 status lines (adornments+hierarchy, directives)
    # when processed once — 4 would mean it was checked twice.
    assert out.count(str(f)) == 2


@pytest.mark.integration
def test_recursive_exclude_pattern_skips_file(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--exclude PATTERN skips a matching discovered file entirely — its
    errors never appear, even though it has a real adornment violation."""
    keep = tmp_path / "keep.rst"
    skip = tmp_path / "skip.rst"
    keep.write_text(_GOOD_BLOCK, encoding="utf-8")
    skip.write_text(_BAD_BLOCK, encoding="utf-8")  # would flag "must be 7 chars"

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "check", "--recursive", "--exclude", "skip.rst", str(tmp_path)],
    )
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert str(keep) in out
    assert str(skip) not in out
    assert "must be 7 chars" not in out


@pytest.mark.integration
def test_recursive_multiple_exclude_patterns(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--exclude is repeatable: each pattern excludes its own file."""
    keep = tmp_path / "keep.rst"
    skip1 = tmp_path / "skip1.rst"
    skip2 = tmp_path / "skip2.rst"
    for p in (keep, skip1, skip2):
        p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "check", "--recursive", "--exclude", "skip1.rst", "--exclude", "skip2.rst", str(tmp_path)],
    )
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert str(keep) in out
    assert str(skip1) not in out
    assert str(skip2) not in out


@pytest.mark.integration
def test_cli_missing_explicit_file_stops_before_all_check_phases(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An explicit missing file is invalid input, so no check/build phase runs."""
    (tmp_path / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    missing = tmp_path / "does_not_exist.rst"

    def unexpected_sphinx(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Sphinx must not run when no input files exist")

    monkeypatch.setattr(check_rst, "_build_sphinx_env", unexpected_sphinx)
    monkeypatch.setattr(check_rst, "run_sphinx", unexpected_sphinx)
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(tmp_path), "check", str(missing)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert f"{missing}: file not found" in out
    assert "Phase 1" not in out
    assert "Phase 2" not in out
    assert "Phase 3" not in out


@pytest.mark.integration
@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["outline", "--outline-depth", "0"], "--outline-depth must be >= 1"),
        (["outline", "--outline-depth", "-1"], "--outline-depth must be >= 1"),
        (["check", "--exclude", "skip.rst"], "--exclude requires --recursive"),
        (["check", "--git-scope"], "--git-scope requires at least one file"),
        (
            ["check", "--git-scope", "--recursive", "docs"],
            "--git-scope is incompatible with --recursive",
        ),
    ],
)
def test_cli_rejects_semantically_incompatible_arguments_before_actions(
    check_rst: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    message: str,
) -> None:
    """The remaining value-level/peer-flag rules that still need a runtime
    check under the subcommand redesign (docs/roadmap.rst, "Subcommands:
    flag-soup incompatibilities become verbs") — every combination this
    parametrize used to cover that the redesign made structurally
    impossible (e.g. --outline-only + --fix, --refs + --json, --diff-json +
    --config) was removed rather than converted: those now fail as an
    ordinary argparse "unrecognized argument" (exit 2, message on stderr),
    which is argparse's own behavior, not this project's logic to pin down
    with a regression test. --outline-depth requiring --outline is likewise
    gone: the flag only exists on outline's own parser now."""
    monkeypatch.setattr("sys.argv", ["check_rst.py", *argv])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert message in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_cli_help_uses_launcher_name(
    check_rst: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--help"])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    first_line = out.splitlines()[0]
    assert first_line.startswith("usage: check_rst ")
    assert "check_rst.py" not in first_line


@pytest.mark.integration
def test_cli_help_covers_examples_and_self_contained_modes(
    check_rst: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Top-level help (the module docstring) is sufficient to discover the
    self-contained report verbs and see worked examples of each, without
    treating examples as exhaustive."""
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--help"])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Common examples:" in out
    assert "check_rst refs doc.rst" in out
    assert "check_rst diff-json before.json after.json" in out
    assert "check_rst fix --fast" in out
    assert "check_rst check --max-output-lines 40" in out


@pytest.mark.integration
@pytest.mark.parametrize(
    ("verb", "needle"),
    [
        ("fix", "unresolved merge entry"),
        ("fix", "configured Sphinx settings are reported inactive"),
        ("check", "authoritative final status"),
        ("check", "Phase 0 byte hygiene remains enabled"),
    ],
)
def test_cli_verb_help_covers_write_safety_claims(
    check_rst: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    verb: str,
    needle: str,
) -> None:
    """Under the subcommand redesign, each flag's safety-relevant detail
    lives on its own verb's --help page rather than one combined top-level
    page — progressive disclosure, not information loss (see
    test_cli_help_covers_examples_and_self_contained_modes for the
    top-level page's own remaining content)."""
    monkeypatch.setattr("sys.argv", ["check_rst.py", verb, "--help"])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = " ".join(capsys.readouterr().out.split())
    assert needle in out
    assert "once-per-run rationale" in out


@pytest.mark.integration
def test_cli_file_valued_build_dir_stops_before_fix_or_phases(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Invalid output scope is input validation, not a post-Phase-1 traceback."""
    (tmp_path / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    p = tmp_path / "index.rst"
    original = "\ufeffTitle\n=====\n"
    p.write_text(original, encoding="utf-8")
    build_file = tmp_path / "not-a-directory"
    build_file.write_text("occupied", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(tmp_path), "--build-dir", str(build_file), "fix", str(p)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    assert p.read_text(encoding="utf-8") == original
    out = capsys.readouterr().out
    assert "not a directory" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_cli_explicit_build_dir_requires_resolved_sphinx_source(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "doc.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--build-dir", str(tmp_path / "_build"), "check", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--build-dir requires verified Sphinx mode" in out
    assert "--sphinx-src DIR" in out
    assert "--config FILE" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_cli_no_toctree_requires_resolved_sphinx_source(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "doc.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", "--no-toctree", str(document)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--no-toctree requires verified Sphinx mode" in out
    assert "--config FILE" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_cli_no_toctree_requires_format_json(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Under the subcommand redesign, --no-toctree's "requires one of
    --outline/--outline-only/--json/--context" half narrows to "requires
    --format=json" on check's own parser — outline and context each
    guarantee the condition structurally now (see _validate_check_args)."""
    (tmp_path / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    document = tmp_path / "doc.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(tmp_path), "check", "--no-toctree", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--no-toctree requires --format=json" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_cli_foreign_sphinx_file_stops_before_fix_or_phases(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verified mode must never mutate a file outside its Sphinx source tree."""
    sphinx_src = tmp_path / "docs"
    sphinx_src.mkdir()
    (sphinx_src / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    (sphinx_src / "index.rst").write_text("Index\n=====\n", encoding="utf-8")
    foreign = tmp_path / "foreign.rst"
    original = "\ufeffForeign\n=======\n"
    foreign.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(sphinx_src), "fix", str(foreign)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    assert foreign.read_text(encoding="utf-8") == original
    out = capsys.readouterr().out
    assert "not part of --sphinx-src" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_cli_unmerged_file_stops_before_fix_and_preserves_markers(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Git's unmerged index is authoritative; --fix must be atomic and inert."""
    p = rst_repo / "conflict.rst"
    p.write_text("Base\n####\n", encoding="utf-8")
    _git(rst_repo, "add", "conflict.rst")
    _git(rst_repo, "commit", "-m", "base")
    _git(rst_repo, "checkout", "-b", "other")
    p.write_text("Theirs\n######\n", encoding="utf-8")
    _git(rst_repo, "add", "conflict.rst")
    _git(rst_repo, "commit", "-m", "theirs")
    _git(rst_repo, "checkout", "master")
    p.write_text("Ours\n####\n", encoding="utf-8")
    _git(rst_repo, "add", "conflict.rst")
    _git(rst_repo, "commit", "-m", "ours")
    merge = subprocess.run(
        ["git", "-C", str(rst_repo), "merge", "other"],
        capture_output=True,
        check=False,
    )
    assert merge.returncode != 0
    original = p.read_bytes()
    assert b"<<<<<<<" in original
    invocation_dir = rst_repo.parent / "outside-invocation"
    invocation_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(check_rst, "PROJECT_ROOT", invocation_dir)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", str(p)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    assert p.read_bytes() == original
    out = capsys.readouterr().out
    assert "unresolved Git merge conflict" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_recursive_nonexistent_directory_errors(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A --recursive argument that doesn't exist is a hard error, not a
    silent empty result — same fail-loud precedent as --sphinx-src."""
    missing = tmp_path / "does_not_exist"
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--recursive", str(missing)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "not a directory" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_recursive_file_argument_errors(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A --recursive argument that is a file, not a directory, is a hard error."""
    p = tmp_path / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--recursive", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "not a directory" in out


@pytest.mark.integration
def test_recursive_no_directories_given_errors(
    check_rst: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--recursive with no positional directories is a clear error, not a
    silent no-op or an implicit fallback to some other scope."""
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--recursive"])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--recursive" in out


@pytest.mark.integration
def test_recursive_no_rst_files_found_exits_zero(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A --recursive directory with no *.rst files anywhere under it is not
    an error — same "nothing to do" convention as the no-files-changed case."""
    (tmp_path / "empty").mkdir()
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--recursive", str(tmp_path / "empty")])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0


@pytest.mark.integration
def test_recursive_filename_with_spaces(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Regression guard for the exact historical bug: a filename containing
    spaces (e.g. a saved AI chat transcript) must be discovered and checked
    correctly, not word-split into bogus fragments. pathlib.rglob has no
    shell involved at all, so this is structural, not a patched special case.
    """
    spaced = tmp_path / "saved chat transcript.rst"
    spaced.write_text(_BAD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--recursive", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert str(spaced) in out
    assert "must be 7 chars" in out
    assert "file not found" not in out


@pytest.mark.integration
def test_recursive_implies_whole_file_scoping(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--recursive is a deliberate scope selection, same as naming files
    explicitly: it must check discovered files in full, not diff-scoped —
    there is no git relationship implied by a directory sweep at all."""
    p = tmp_path / "test.rst"
    p.write_text(_BAD_BLOCK, encoding="utf-8")  # pre-existing-style violation, no git involved

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--recursive", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "must be 7 chars" in out
    assert "must be 7 chars" in out


# ---------------------------------------------------------------------------
# Phase 0 — byte-level hygiene (check_hygiene / fix_hygiene) → Zone 2
#
# Project policy: Unix LF line endings only, no BOM.  Every hygiene finding
# is ERROR-level and --fix-able; none may silently alter content semantics.
# Each test here reproduces a defect found by direct probing of the real
# functions (2026-07-18) before Phase 0 existed.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_hygiene_clean_file_no_findings_unchanged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    assert check_rst.check_hygiene(p) == []
    assert check_rst.fix_hygiene(p) is False
    assert p.read_bytes() == before


@pytest.mark.integration
def test_hygiene_crlf_flagged_and_fixed(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """CRLF line endings are an ERROR (policy: Unix LF) and --fix normalizes
    every line ending, preserving content."""
    p = tmp_path / "crlf.rst"
    p.write_bytes(b"#######\r\nTitle\r\n#######\r\n\r\nText.\r\n")

    findings = check_rst.check_hygiene(p)
    assert any("CRLF" in f for f in findings)
    # One coalesced finding per defect kind: the total count is in the
    # message, the anchor line is labeled as the first of them.
    assert any("on 5 line(s), first here" in f for f in findings)
    assert all(f.severity == "ERROR" for f in findings)

    assert check_rst.fix_hygiene(p) is True
    raw = p.read_bytes()
    assert b"\r" not in raw
    assert raw == b"#######\nTitle\n#######\n\nText.\n"
    assert check_rst.check_hygiene(p) == []


@pytest.mark.integration
def test_hygiene_lone_cr_flagged_and_fixed(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A lone CR is a line break to Python/docutils but not to git — line
    numbering silently desynchronizes.  ERROR, fixed to LF."""
    p = tmp_path / "cr.rst"
    p.write_bytes(b"line one\rline two\n")

    findings = check_rst.check_hygiene(p)
    assert any("lone CR" in f for f in findings)

    assert check_rst.fix_hygiene(p) is True
    assert p.read_bytes() == b"line one\nline two\n"


@pytest.mark.integration
def test_hygiene_bom_flagged_and_fixed(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A UTF-8 BOM is an ERROR (policy: no BOM) and --fix strips it."""
    p = tmp_path / "bom.rst"
    p.write_bytes(b"\xef\xbb\xbf#######\nTitle\n#######\n\nText.\n")

    findings = check_rst.check_hygiene(p)
    assert any("BOM" in f for f in findings)

    assert check_rst.fix_hygiene(p) is True
    raw = p.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw == b"#######\nTitle\n#######\n\nText.\n"


@pytest.mark.integration
def test_hygiene_exotic_separators_flagged_and_fixed(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Exotic separators split lines for Python/docutils but not for git.
    U+2028/U+0085-class separators become LF; VT/FF become a space (docutils'
    own convert_whitespace semantics)."""
    p = tmp_path / "exotic.rst"
    p.write_bytes("line one\u2028line two\nalpha\x0cbeta\n".encode())

    findings = check_rst.check_hygiene(p)
    assert any("U+2028" in f for f in findings)
    assert any("U+000C" in f for f in findings)
    assert all("1 occurrence(s), first here" in f for f in findings)

    assert check_rst.fix_hygiene(p) is True
    assert p.read_bytes() == b"line one\nline two\nalpha beta\n"


@pytest.mark.integration
def test_hygiene_trailing_whitespace_on_adornment_flagged_and_fixed(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    """Trailing whitespace on an adornment line hides it from every structure
    check (docutils itself strips it, so stripping is semantically free)."""
    p = tmp_path / "trailws.rst"
    p.write_bytes(b"####### \nTitle\n#######\n\nText.\n")

    findings = check_rst.check_hygiene(p)
    assert any("trailing whitespace" in f for f in findings)

    assert check_rst.fix_hygiene(p) is True
    assert p.read_bytes() == b"#######\nTitle\n#######\n\nText.\n"


@pytest.mark.integration
def test_hygiene_trailing_whitespace_on_text_line_flagged_and_fixed(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    """Docutils right-strips every input line before parsing, so retaining
    spaces or tabs at the end of an ordinary text line has no RST meaning."""
    p = tmp_path / "textws.rst"
    p.write_bytes(b"#######\nTitle\n#######\n\nSome text. \t\n")

    findings = check_rst.check_hygiene(p)
    assert len(findings) == 1
    assert findings[0].lineno == 5
    assert "trailing whitespace" in findings[0]

    assert check_rst.fix_hygiene(p) is True
    assert p.read_bytes().endswith(b"Some text.\n")
    assert check_rst.check_hygiene(p) == []


@pytest.mark.integration
def test_hygiene_trailing_whitespace_on_section_title_and_body_is_parser_invisible(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    """string2lines right-strips before the title/paragraph states run, so
    section text and simple body text have the same before/after doctree."""
    before = "#######\nTitle  \n#######\n\nSimple text block. \t\n"
    after = "#######\nTitle\n#######\n\nSimple text block.\n"
    p = tmp_path / "title-and-body.rst"
    p.write_text(before, encoding="utf-8")
    before_tree = check_rst._parse_rst(p, text=before).pformat()

    assert len(check_rst.check_hygiene(p)) == 2
    assert check_rst.fix_hygiene(p) is True

    assert p.read_text(encoding="utf-8") == after
    assert check_rst._parse_rst(p, text=after).pformat() == before_tree


@pytest.mark.integration
def test_hygiene_trailing_whitespace_safe_in_whitespace_preserving_blocks(
    check_rst: types.ModuleType, tmp_path: Path
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
    before_tree = check_rst._parse_rst(p, text=before).pformat()

    findings = check_rst.check_hygiene(p)
    assert len(findings) == 6
    assert check_rst.fix_hygiene(p) is True

    assert p.read_text(encoding="utf-8") == after
    assert check_rst._parse_rst(p, text=after).pformat() == before_tree


@pytest.mark.integration
def test_hygiene_trailing_whitespace_preserves_missing_final_newline(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    """Right-stripping the final line must not invent a final newline."""
    p = tmp_path / "no-final-newline.rst"
    p.write_bytes(b"Text without final newline \t")

    assert len(check_rst.check_hygiene(p)) == 1
    assert check_rst.fix_hygiene(p) is True
    assert p.read_bytes() == b"Text without final newline"


@pytest.mark.unit
def test_hygiene_trailing_whitespace_structured_count(check_rst: types.ModuleType) -> None:
    """Fix-only output needs one stable count of affected source lines."""
    normalized, findings, counts = check_rst._normalize_source_detailed("one  \n \t\nthree\t\n")

    assert normalized == "one\n\nthree\n"
    assert len(findings) == 3
    assert counts.trailing_whitespace == 3
    assert counts.describe() == "trailing whitespace lines 3"


# ---------------------------------------------------------------------------
# Opt-in blank-line normalization.  Unlike trailing whitespace, redundant
# empty source lines are not globally parser-invisible: literal-like blocks
# can retain them as content.  Every accepted run therefore has to preserve
# the complete doctree; the option is deliberately separate from --fix.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_normalize_blank_lines_collapses_parser_equivalent_block_separators(
    check_rst: types.ModuleType, tmp_path: Path
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

    normalized, removed = check_rst._normalize_blank_lines(path, before)

    assert normalized == after
    assert removed == 8
    assert check_rst._parse_rst(path, text=normalized).pformat() == check_rst._parse_rst(path, text=before).pformat()
    assert check_rst._normalize_blank_lines(path, normalized) == (normalized, 0)


@pytest.mark.unit
def test_normalize_blank_lines_preserves_content_in_literal_like_blocks(
    check_rst: types.ModuleType, tmp_path: Path
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

    normalized, removed = check_rst._normalize_blank_lines(path, before)

    assert normalized == expected
    assert removed == 4
    assert "literal one\n\n\n   literal two" in normalized
    assert "parsed one\n\n\n   parsed two" in normalized
    assert "raw one</p>\n\n\n   <p>raw two" in normalized


@pytest.mark.unit
def test_normalize_blank_lines_is_conservative_for_unknown_project_directive(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    """Bare docutils represents an unknown Sphinx/project directive as a
    diagnostic plus literal source.  Its indented body must remain intact;
    uncertainty is a reason to retain source, never to guess."""
    before = ".. project-specific::\n\n   first\n\n\n   second\n"

    normalized, removed = check_rst._normalize_blank_lines(tmp_path / "foreign.rst", before)

    assert normalized == before
    assert removed == 0


@pytest.mark.unit
def test_normalize_blank_lines_normalizes_document_edges_and_final_newline_state(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    before = "\n\nAlpha.\n\n\nBeta.\n\n"

    normalized, removed = check_rst._normalize_blank_lines(tmp_path / "edges.rst", before)

    assert normalized == "Alpha.\n\nBeta.\n"
    assert removed == 4
    assert normalized.endswith("Beta.\n")

    without_final_newline, removed = check_rst._normalize_blank_lines(
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
    check_rst: types.ModuleType,
    tmp_path: Path,
    before: str,
    after: str,
    removed: int,
) -> None:
    path = tmp_path / "leading.rst"
    before_tree = check_rst._parse_rst(path, text=before).pformat()

    normalized, actual_removed = check_rst._normalize_blank_lines(path, before)

    assert normalized == after
    assert actual_removed == removed
    assert check_rst._parse_rst(path, text=normalized).pformat() == before_tree


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
    check_rst: types.ModuleType,
    tmp_path: Path,
    before: str,
    after: str,
    removed: int,
) -> None:
    path = tmp_path / "eof.rst"
    before_tree = check_rst._parse_rst(path, text=before).pformat()

    normalized, actual_removed = check_rst._normalize_blank_lines(path, before)

    assert normalized == after
    assert actual_removed == removed
    assert check_rst._parse_rst(path, text=normalized).pformat() == before_tree


@pytest.mark.integration
def test_cli_normalize_blank_lines_is_opt_in_and_composes_with_fix(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    original = "\n\n##########\nDocument\n##########\n\n\nBody.\n\n\n"
    document.write_text(original, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", str(document)])
    with pytest.raises(SystemExit):
        check_rst.main()
    assert document.read_text(encoding="utf-8") == original

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "fix", "--normalize-blank-lines", str(document)],
    )
    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    assert document.read_text(encoding="utf-8") == "##########\nDocument\n##########\n\nBody.\n"
    assert "5 redundant blank lines removed" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_normalize_blank_lines_diff_previews_without_writing(
    check_rst: types.ModuleType,
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
        check_rst.main()

    assert exc.value.code == 0
    assert document.read_text(encoding="utf-8") == original
    output = capsys.readouterr().out
    assert f"--- {document}" in output
    assert "1 file(s) would change" in output


@pytest.mark.integration
def test_cli_normalize_blank_lines_absent_from_check_verb(
    check_rst: types.ModuleType,
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
        check_rst.main()

    assert exc.value.code == 2


@pytest.mark.integration
@pytest.mark.parametrize("verb", ["fix", "diff"])
def test_cli_normalize_blank_lines_rejected_under_fast(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    verb: str,
) -> None:
    document = tmp_path / "test.rst"
    document.write_text("Alpha.\n\n\nBeta.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", verb, "--fast", "--normalize-blank-lines", str(document)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    assert f"{verb} --fast is self-contained" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Opt-in editorial spacing.  Unlike blank-line normalization, these changes
# deliberately alter visible Text nodes.  The acceptance predicate permits
# exactly the requested title/prose space-run delta while requiring every
# structural node, attribute, target, and generated id to remain unchanged.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_collapse_title_spaces_changes_only_visible_title_text(check_rst: types.ModuleType, tmp_path: Path) -> None:
    before = (
        "###############################\n"
        "Title  outside ``two  spaces``\n"
        "###############################\n\n"
        "Paragraph  remains.\n"
    )
    expected = before.replace("Title  outside", "Title outside")
    path = tmp_path / "title.rst"
    before_doc = check_rst._parse_rst(path, text=before)

    normalized, counts = check_rst._normalize_text_spaces(
        path,
        before,
        collapse_titles=True,
        single_space_prose=False,
    )

    after_doc = check_rst._parse_rst(path, text=normalized)
    assert normalized == expected
    assert counts.title_runs == 1
    assert counts.prose_runs == 0
    assert "``two  spaces``" in normalized
    assert "Paragraph  remains." in normalized
    assert [section["ids"] for section in before_doc.findall(check_rst.docutils.nodes.section)] == [
        section["ids"] for section in after_doc.findall(check_rst.docutils.nodes.section)
    ]


@pytest.mark.unit
def test_collapse_title_spaces_is_a_fixed_point_and_leaves_prose_only_document(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    source = "Alpha.  Beta.\n"
    path = tmp_path / "prose-only.rst"

    normalized, counts = check_rst._normalize_text_spaces(
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
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    original = "#############\nTitle  text\n#############\n\nBody.\n"
    document.write_text(original, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", str(document)])
    with pytest.raises(SystemExit):
        check_rst.main()
    assert document.read_text(encoding="utf-8") == original

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "fix", "--collapse-title-spaces", str(document)],
    )
    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    assert document.read_text(encoding="utf-8") == "############\nTitle text\n############\n\nBody.\n"
    assert "1 title space run collapsed" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_collapse_title_spaces_absent_from_check_verb(
    check_rst: types.ModuleType,
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
        check_rst.main()

    assert exc.value.code == 2


@pytest.mark.integration
@pytest.mark.parametrize("verb", ["fix", "diff"])
def test_cli_collapse_title_spaces_rejected_under_fast(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    verb: str,
) -> None:
    document = tmp_path / "test.rst"
    document.write_text("Title  text\n===========\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", verb, "--fast", "--collapse-title-spaces", str(document)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    assert f"{verb} --fast is self-contained" in capsys.readouterr().out


@pytest.mark.unit
def test_single_space_prose_accepts_only_accounted_visible_text_deltas(
    check_rst: types.ModuleType, tmp_path: Path
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

    normalized, counts = check_rst._normalize_text_spaces(
        path,
        before,
        collapse_titles=False,
        single_space_prose=True,
    )

    assert normalized == expected
    assert counts.title_runs == 0
    assert counts.prose_runs == 5
    assert check_rst._normalize_text_spaces(
        path,
        normalized,
        collapse_titles=False,
        single_space_prose=True,
    ) == (normalized, check_rst.TextSpaceCounts())


@pytest.mark.unit
def test_single_space_prose_preserves_tabs_unicode_spaces_and_title_scope(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    source = (
        "#############\nTitle  text\n#############\n\n"
        "Tab\tseparated; non-breaking\u00a0\u00a0spaces; ordinary  prose.\n"
    )

    normalized, counts = check_rst._normalize_text_spaces(
        tmp_path / "characters.rst",
        source,
        collapse_titles=False,
        single_space_prose=True,
    )

    assert normalized == source.replace("ordinary  prose", "ordinary prose")
    assert counts == check_rst.TextSpaceCounts(prose_runs=1)


@pytest.mark.unit
def test_title_and_prose_space_options_compose_with_separate_counts(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    source = "#############\nTitle  text\n#############\n\nAlpha.  Beta.\n"

    normalized, counts = check_rst._normalize_text_spaces(
        tmp_path / "combined.rst",
        source,
        collapse_titles=True,
        single_space_prose=True,
    )

    assert normalized == source.replace("Title  text", "Title text").replace("Alpha.  Beta", "Alpha. Beta")
    assert counts == check_rst.TextSpaceCounts(title_runs=1, prose_runs=1)


@pytest.mark.integration
def test_cli_single_space_prose_is_opt_in_and_preserves_literal_payload(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    original = "##########\nDocument\n##########\n\nAlpha.  Beta with ``fixed  text``.\n"
    document.write_text(original, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", str(document)])
    with pytest.raises(SystemExit):
        check_rst.main()
    assert document.read_text(encoding="utf-8") == original

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "fix", "--single-space-prose", str(document)],
    )
    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    assert document.read_text(encoding="utf-8") == original.replace("Alpha.  Beta", "Alpha. Beta")
    assert "1 prose space run collapsed" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_editorial_space_options_compose_in_diff_without_writing(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    original = "#############\nTitle  text\n#############\n\nAlpha.  Beta.\n"
    document.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "diff", "--collapse-title-spaces", "--single-space-prose", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    assert document.read_text(encoding="utf-8") == original
    output = capsys.readouterr().out
    assert "-Title  text" in output
    assert "+Title text" in output
    assert "-Alpha.  Beta." in output
    assert "+Alpha. Beta." in output


@pytest.mark.integration
def test_cli_single_space_prose_absent_from_check_verb(
    check_rst: types.ModuleType,
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
        check_rst.main()

    assert exc.value.code == 2


@pytest.mark.integration
@pytest.mark.parametrize("verb", ["fix", "diff"])
def test_cli_single_space_prose_rejected_under_fast(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    verb: str,
) -> None:
    document = tmp_path / "test.rst"
    document.write_text("Alpha.  Beta.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", verb, "--fast", "--single-space-prose", str(document)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    assert f"{verb} --fast is self-contained" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Cascade-corruption regressions: hygiene defects must not cause Phase 1 to
# misdiagnose valid titles — previously --fix CORRUPTED these files → Zone 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_adornments_bom_file_no_false_underline_only(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Regression: a BOM glued to a valid overline made the overline invisible,
    the title was misdiagnosed as underline-only, and --fix inserted a
    duplicate overline.  Adornment checks now see BOM-stripped text."""
    p = tmp_path / "bom.rst"
    p.write_bytes(b"\xef\xbb\xbf#######\nTitle\n#######\n\nText.\n")

    assert check_rst.check_adornments(p, whole_file=True) == []
    assert check_rst.diff_structure(p, True) == ""


@pytest.mark.integration
def test_adornments_trailing_ws_overline_no_false_underline_only(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Regression: '####### ' (trailing space) was not recognized as an
    overline — docutils strips it and accepts the title, but check_rst
    misdiagnosed underline-only and --fix inserted a duplicate overline."""
    p = tmp_path / "trailws.rst"
    p.write_bytes(b"####### \nTitle\n#######\n\nText.\n")

    violations = check_rst.check_adornments(p, whole_file=True)
    assert not any("underline-only" in v for v in violations)
    assert violations == []


@pytest.mark.integration
def test_fix_bom_and_hygiene_then_adornments_no_duplicate_overline(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """End-to-end fix order: hygiene first, then adornments — the result is a
    single valid block, not the historical corrupted double-overline."""
    p = tmp_path / "bom_fix.rst"
    p.write_bytes(b"\xef\xbb\xbf#########\n Title A \n#########\n\nText.\n")

    check_rst.fix_hygiene(p)
    check_rst.fix_structure(p, True)

    assert p.read_bytes() == b"#########\nTitle A\n#########\n\nText.\n"
    assert check_rst.check_hygiene(p) == []
    assert check_rst.check_adornments(p, whole_file=True) == []


# ---------------------------------------------------------------------------
# '..' comment marker vs '.' adornment — docutils gives explicit markup
# precedence, so '..' is never an over/underline → Zone 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_adornments_dot_comment_pair_not_title(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_adornments(p, whole_file=True)
    assert not any("internal note" in v for v in violations)

    # The title block above the comment is deliberately broken, so a diff
    # exists — but the comment itself must only ever appear as unchanged
    # context, never on a +/- line, and no dotted adornment may be added.
    diff = check_rst.diff_structure(p, True)
    changed = [
        line for line in diff.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    assert not any("internal note" in line for line in changed)
    assert not any(set(line[1:]) == {"."} for line in changed)


@pytest.mark.integration
def test_fix_dot_comment_pair_unchanged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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

    assert check_rst.fix_structure(p, True) is False
    assert p.read_text(encoding="utf-8") == content


# ---------------------------------------------------------------------------
# Display width vs code-point length — the +2 rule must measure what docutils
# measures (docutils.utils.column_width), or --fix output fails Phase 3 → Zone 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_adornments_cjk_title_uses_column_width(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Regression: '日本語入門' is 5 code points but 10 columns; len()+2 = 7
    passed check_rst while docutils itself warned 'Title overline too short'.
    The +2 rule must use column width: expected adornment is 12."""
    bad = tmp_path / "cjk_bad.rst"
    bad.write_text("#######\n日本語入門\n#######\n\nText.\n", encoding="utf-8")
    violations = check_rst.check_adornments(bad, whole_file=True)
    assert any("must be 12 chars" in v for v in violations)

    good = tmp_path / "cjk_good.rst"
    good.write_text("############\n日本語入門\n############\n\nText.\n", encoding="utf-8")
    assert check_rst.check_adornments(good, whole_file=True) == []


@pytest.mark.integration
def test_fix_cjk_title_adornment_width(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """--fix on a CJK placeholder title produces column-width+2 adornments —
    output that docutils/Phase 3 accepts, so the fix loop converges."""
    p = tmp_path / "cjk_fix.rst"
    p.write_text("日本語入門\n---------\n\nText.\n", encoding="utf-8")

    assert check_rst.fix_structure(p, True) is True
    lines = p.read_text(encoding="utf-8").splitlines()
    # The lone '-' is the document's level 1, remapped to '#' in the same
    # pass — what the CLI always produced; the width is the point here.
    assert lines[0] == "#" * 12
    assert lines[1] == "日本語入門"
    assert lines[2] == "#" * 12


@pytest.mark.integration
def test_adornments_combining_accents_use_column_width(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    assert check_rst.check_adornments(p, whole_file=True) == []


# ---------------------------------------------------------------------------
# Phase 0 at CLI level — reported loudly, --skip-fixable suppresses,
# --fix resolves → Zone 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_hygiene_error_reported_and_exit_1(
    check_rst: types.ModuleType,
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
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "CRLF" in out

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--skip-fixable", str(p)])
    with pytest.raises(SystemExit) as exc2:
        check_rst.main()
    assert exc2.value.code == 0
    out2 = capsys.readouterr().out
    assert "CRLF" not in out2


@pytest.mark.integration
def test_cli_fix_resolves_hygiene_and_recheck_is_clean(
    check_rst: types.ModuleType,
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
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "hygiene fix applied" in out

    raw = p.read_bytes()
    assert b"\r" not in raw
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw == b"#########\nTitle A\n#########\n\nText.\n"

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as exc2:
        check_rst.main()
    assert exc2.value.code == 0


@pytest.mark.integration
def test_cli_diff_previews_hygiene_changes(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--diff must show Phase 0 edits, not merely count the affected file."""
    p = rst_repo / "test.rst"
    p.write_bytes(b"####### \nTitle\n#######\n\nText.\n")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "diff", str(p)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    out = capsys.readouterr().out
    assert exc.value.code == 1
    assert f"--- {p}" in out
    assert f"+++ {p}" in out
    assert "-####### \n" in out
    assert "+#######\n" in out


# ---------------------------------------------------------------------------
# Check/fix rule unification — the checker consumes the same computation the
# fixer applies (hierarchy: _compute_hierarchy_remap; blocks: analyze_block),
# so the two can no longer disagree.  Each test below pins a divergence found
# by direct probing (2026-07-18): files the check passed but --fix rewrote,
# and check messages reporting targets the fixer never produced → Zone 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_hierarchy_star_only_document_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    violations = check_rst.check_hierarchy(p)
    errors = [v for v in violations if v.severity == "ERROR"]
    assert len(errors) == 1
    assert any("hierarchy level 1 is '#'" in v for v in errors)
    assert check_rst.diff_structure(p, True) != ""


@pytest.mark.integration
def test_hierarchy_offset_consecutive_sequence_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    errors = [v for v in check_rst.check_hierarchy(p) if v.severity == "ERROR"]
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
def test_hierarchy_check_and_fix_agree(check_rst: types.ModuleType, tmp_path: Path, content: str) -> None:
    """The unification invariant: check_hierarchy reports an ERROR if and
    only if the composed fixer would modify the file (the fixtures here are
    geometrically canonical, so any diff is the remap's) — and after fixing,
    the check is clean.  Both sides consume _compute_hierarchy_remap, so
    this holds by construction; the test pins it against regression."""
    p = tmp_path / "test.rst"
    p.write_text(content, encoding="utf-8")

    errors = [v for v in check_rst.check_hierarchy(p) if v.severity == "ERROR"]
    diff = check_rst.diff_structure(p, True)
    assert bool(errors) == bool(diff)

    check_rst.fix_structure(p, True)
    assert [v for v in check_rst.check_hierarchy(p) if v.severity == "ERROR"] == []


@pytest.mark.integration
def test_adornments_spaced_title_expected_width_is_stripped(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Regression: for ' Title A ' with 9-char adornments the checker
    demanded 'must be 11 chars' (unstripped width) while --fix stripped the
    title and kept 9 — a target the fixer never produces.  The canonical
    rule measures the stripped title: 9 is already correct, so only the
    title-spaces error remains."""
    p = tmp_path / "spaced.rst"
    p.write_text("#########\n Title A \n#########\n\nText.\n", encoding="utf-8")

    violations = check_rst.check_adornments(p, whole_file=True)
    assert any("leading or trailing spaces" in v for v in violations)
    assert not any("must be" in v for v in violations)


@pytest.mark.integration
def test_adornments_spaced_title_wrong_length_reports_stripped_target(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    """When a spaced title's adornments match its UNSTRIPPED width (11),
    the reported target must be the canonical one --fix produces (9),
    not the unstripped measurement."""
    p = tmp_path / "spaced.rst"
    p.write_text("###########\n Title A \n###########\n\nText.\n", encoding="utf-8")

    violations = check_rst.check_adornments(p, whole_file=True)
    assert any("must be 9 chars" in v for v in violations)
    assert any("leading or trailing spaces" in v for v in violations)


@pytest.mark.integration
def test_adornments_check_and_fix_agree_on_spaced_title(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """After fix_structure, the checker must be fully satisfied — the
    canonical values it validated are the ones the fixer applied."""
    p = tmp_path / "spaced.rst"
    p.write_text("###########\n Title A \n###########\n\nText.\n", encoding="utf-8")

    assert check_rst.fix_structure(p, True) is True
    assert check_rst.check_adornments(p, whole_file=True) == []
    assert p.read_text(encoding="utf-8") == "#########\nTitle A\n#########\n\nText.\n"


# ---------------------------------------------------------------------------
# Git invocation — bare auto-detection outside a git repository → Zone 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_bare_invocation_outside_git_repo_clean_error(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Bare check_rst (git auto-detection) outside any git repository must
    fail with a one-line diagnostic, not a CalledProcessError traceback —
    the same loud-and-clean precedent as a missing conf.py in --sphinx-src
    or a nonexistent --recursive directory.  Found by direct probing
    (2026-07-18): the 'project-agnostic, call from any project' tool
    crashed with a raw traceback when that project wasn't a git repo."""
    monkeypatch.setattr(check_rst, "PROJECT_ROOT", tmp_path)  # no .git here
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check"])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "not a git repository" in out


@pytest.mark.integration
def test_directives_mistyped_directive_single_colon_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """'.. code: bash' (single colon) is a legal RST comment — the content
    silently disappears from the build and no other phase flags it (found
    via a real typo in a calendar note, 2026-07-18).  Warn."""
    p = _rst(tmp_path, "Text.\n\n.. code: bash\n\n    pandoc --from gfm\n")
    violations = check_rst.check_directives(p, True)
    assert len(violations) == 1
    assert "mistyped directive" in violations[0]
    assert "code" in violations[0]
    assert violations[0].severity == "WARNING"


@pytest.mark.integration
def test_directives_mistyped_directive_docutils_name_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Any docutils directive name qualifies, not just 'code'."""
    p = _rst(tmp_path, ".. note: remember to flush the cache\n")
    violations = check_rst.check_directives(p, True)
    assert any("mistyped directive" in v for v in violations)


@pytest.mark.integration
def test_directives_mistyped_directive_sphinx_name_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Common Sphinx directive names are covered too (toctree, etc.)."""
    p = _rst(tmp_path, ".. toctree: pages/index\n")
    violations = check_rst.check_directives(p, True)
    assert any("mistyped directive" in v for v in violations)


@pytest.mark.integration
def test_directives_mistyped_directive_case_insensitive(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Directive names are case-insensitive in docutils; so is the lint."""
    p = _rst(tmp_path, ".. Note: remember\n")
    violations = check_rst.check_directives(p, True)
    assert any("mistyped directive" in v for v in violations)


@pytest.mark.integration
def test_directives_todo_comment_not_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """'.. TODO: …' is an extremely common genuine-comment idiom and 'todo'
    is not a docutils directive (nor in the Sphinx supplement, deliberately)
    — never flagged."""
    p = _rst(tmp_path, ".. TODO: fix this paragraph later\n")
    assert check_rst.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_plain_comment_not_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """An ordinary comment stays invisible to the lint."""
    p = _rst(tmp_path, ".. this file is maintained by hand\n")
    assert check_rst.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_unknown_name_comment_not_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A name-colon shape with an unknown name is a legit comment tag."""
    p = _rst(tmp_path, ".. myproject-tag: value\n")
    assert check_rst.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_real_directive_not_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A correctly written directive produces no comment node at all."""
    p = _rst(tmp_path, ".. code:: bash\n\n    echo ok\n")
    assert check_rst.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_mistyped_directive_in_literal_block_not_flagged(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    """The typo QUOTED AS AN EXAMPLE inside a real code-block is literal
    text, never parsed as a comment — no warning."""
    p = _rst(tmp_path, ".. code:: rst\n\n    .. code: bash\n\n        oops\n")
    assert check_rst.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_mistyped_directive_in_block_quote_not_flagged(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Inside a blockquote it is quoted material — exempt, same as bold and
    rubric (the whole quoted subtree is skipped)."""
    p = _rst(tmp_path, "He sent:\n\n    .. code: bash\n\n        quoted\n")
    assert check_rst.check_directives(p, True) == []


# ---------------------------------------------------------------------------
# Summary line + --quiet — born from session-transcript evidence (2026-07-18):
# five AI sessions independently piped check_rst output through grep '^⚠' /
# grep -c / exit-code probes to recover findings and counts from around the
# per-file OK lines and phase banners → Zone 2
#
# The '^⚠' anchor itself is gone (2026-07-20: findings dropped their leading
# glyph for de-facto compiler output — see guide.rst, "De-facto compiler
# output" — 'grep WARNING:'/'grep ERROR:' does the same job now, and --quiet
# already made the original grep workaround mostly moot anyway).  The
# findings-survive-quiet CONTRACT this section pins is unchanged.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_summary_line_always_printed(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every run ends with one machine-parseable summary line — no flag
    needed; kills the grep -c / exit-code-probe post-processing class."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "check_rst: 1 file(s) checked, 0 error(s), 0 warning(s)" in out


@pytest.mark.integration
def test_cli_summary_counts_errors_and_warnings(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(_BAD_BLOCK + "\n**Bold Heading**\n\nText after.\n", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "check_rst: 1 file(s) checked, 1 error(s), 1 warning(s)" in out


@pytest.mark.integration
def test_cli_summary_fix_mode_reports_fixed_files(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(_BAD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "1 file(s) fixed" in out


@pytest.mark.integration
def test_cli_summary_diff_mode_reports_would_change(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--diff counts files that would change — the observed workaround was
    counting '^---' diff headers."""
    p = rst_repo / "test.rst"
    p.write_text(_BAD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "diff", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "1 file(s) would change" in out


@pytest.mark.integration
def test_cli_diff_only_prints_preview_without_checks_or_writes(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    original = document.read_bytes()

    def unexpected_check(*_args: object, **_kwargs: object) -> None:
        pytest.fail("--diff-only must not run Sphinx")

    monkeypatch.setattr(check_rst, "_build_sphinx_env", unexpected_check)
    monkeypatch.setattr(check_rst, "run_sphinx", unexpected_check)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "diff", "--fast", str(document)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    assert document.read_bytes() == original
    out = capsys.readouterr().out
    assert f"--- {document}" in out
    assert "1 file(s) would change" in out
    assert "Phase 1" not in out
    assert "Phase 2" not in out
    assert "Phase 3" not in out


@pytest.mark.integration
def test_cli_diff_only_clean_file_exits_zero(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "diff", "--fast", str(document)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    assert "0 file(s) would change" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_fix_only_composes_hygiene_and_structure_with_structured_output(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The fast mode applies both mutators in their required order and
    reports what changed without continuing into validation phases."""
    document = rst_repo / "test.rst"
    document.write_bytes(b"\xef\xbb\xbf#########\r\n Title A \r\n#####\r\n\r\nText.\r\n")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", "--fast", str(document)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    assert document.read_bytes() == b"#########\nTitle A\n#########\n\nText.\n"
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == ("check_rst: fast scope — explicit/whole-file; hygiene and hierarchy are whole-file")
    assert lines[1] == (
        f"{document}: fixed — BOM 1, CRLF line endings 5, trailing whitespace lines 1, structural lines 2"
    )
    assert lines[-1] == ("check_rst: 1 file(s) processed, 0 error(s), 1 file(s) fixed [fast]")
    assert "Phase 1" not in "\n".join(lines)
    assert "Phase 2" not in "\n".join(lines)
    assert "Phase 3" not in "\n".join(lines)


@pytest.mark.integration
def test_cli_fix_only_plans_all_inputs_before_writing_invalid_utf8(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One undecodable sibling aborts the operation before a valid plan writes."""
    fixable = rst_repo / "fixable.rst"
    invalid = rst_repo / "invalid.rst"
    original = b"######\nTitle\n######\n"
    fixable.write_bytes(original)
    invalid.write_bytes(b"Title\n\xff\n")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "fix", "--fast", str(fixable), str(invalid)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    assert fixable.read_bytes() == original
    lines = capsys.readouterr().out.splitlines()
    assert any(f"{invalid}:2: ERROR: not valid UTF-8" in line for line in lines)
    assert not any(": fixed —" in line for line in lines)
    assert lines[-1] == ("check_rst: 2 file(s) processed, 1 error(s), 0 file(s) fixed [fast]")


@pytest.mark.integration
def test_cli_fix_only_missing_sibling_aborts_before_writing(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Path preflight has the same whole-operation atomicity as decode planning."""
    fixable = rst_repo / "fixable.rst"
    missing = rst_repo / "missing.rst"
    original = b"######\nTitle\n######\n"
    fixable.write_bytes(original)
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "fix", "--fast", str(fixable), str(missing)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    assert fixable.read_bytes() == original
    lines = capsys.readouterr().out.splitlines()
    assert f"check_rst: {missing}: file not found" in lines
    assert lines[-1] == ("check_rst: 2 file(s) processed, 1 error(s), 0 file(s) fixed [fast]")


@pytest.mark.integration
def test_cli_fix_only_ignores_configured_sphinx_and_never_parses(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Config still roots selection, but its Sphinx settings are inactive."""
    document = tmp_path / "test.rst"
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    config = tmp_path / "check-rst.toml"
    config.write_text(
        'sphinx-src = "missing-docs"\nbuild-dir = "missing-build"\n',
        encoding="utf-8",
    )

    def unexpected_phase(*_args: object, **_kwargs: object) -> None:
        pytest.fail("--fix-only must not parse RST or construct/run Sphinx")

    monkeypatch.setattr(check_rst, "_parse_rst", unexpected_phase)
    monkeypatch.setattr(check_rst, "_build_sphinx_env", unexpected_phase)
    monkeypatch.setattr(check_rst, "run_sphinx", unexpected_phase)
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--config", str(config), "fix", "--fast", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "sphinx-src=missing-docs inactive (--fast)" in out
    assert "build-dir=missing-build inactive (--fast)" in out
    assert check_rst.CALL_COUNTS["_parse_rst"] == 0
    assert check_rst.CALL_COUNTS["_build_sphinx_env"] == 0
    assert check_rst.CALL_COUNTS["run_sphinx"] == 0


@pytest.mark.integration
def test_cli_diff_fast_ignores_configured_sphinx_and_never_parses(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """diff --fast's sibling of the fix --fast case above — found live: the
    config-inactive branch checked only args.fix_only, so diff --fast
    silently applied a configured sphinx-src/build-dir instead of reporting
    them inactive (confirmed by direct reproduction before the fix: fix
    --fast printed 'inactive (--fast)' on this exact config, diff --fast
    printed the values as if active, with no inactive marker at all)."""
    document = tmp_path / "test.rst"
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    config = tmp_path / "check-rst.toml"
    config.write_text(
        'sphinx-src = "missing-docs"\nbuild-dir = "missing-build"\n',
        encoding="utf-8",
    )

    def unexpected_phase(*_args: object, **_kwargs: object) -> None:
        pytest.fail("diff --fast must not parse RST or construct/run Sphinx")

    monkeypatch.setattr(check_rst, "_parse_rst", unexpected_phase)
    monkeypatch.setattr(check_rst, "_build_sphinx_env", unexpected_phase)
    monkeypatch.setattr(check_rst, "run_sphinx", unexpected_phase)
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--config", str(config), "diff", "--fast", str(document)],
    )

    with pytest.raises(SystemExit):
        check_rst.main()

    out = capsys.readouterr().out
    assert "sphinx-src=missing-docs inactive (--fast)" in out
    assert "build-dir=missing-build inactive (--fast)" in out
    assert check_rst.CALL_COUNTS["_parse_rst"] == 0
    assert check_rst.CALL_COUNTS["_build_sphinx_env"] == 0
    assert check_rst.CALL_COUNTS["run_sphinx"] == 0


@pytest.mark.integration
@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--sphinx-src", "docs"], "fix --fast is self-contained"),
        (["--build-dir", "build"], "fix --fast is self-contained"),
        (["--skip-fixable"], "fix --fast is self-contained"),
    ],
)
def test_cli_fix_only_rejects_meaningless_options_before_actions(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra: list[str],
    message: str,
) -> None:
    document = tmp_path / "test.rst"
    original = _BAD_BLOCK
    document.write_text(original, encoding="utf-8")
    # --sphinx-src/--build-dir are global now (before the verb); --skip-fixable
    # stays on fix's own parser (after the verb) — each extra goes wherever its
    # own flag actually parses, exercising the same _validate_fast_allowlist
    # rejection either way.
    global_flags = {"--sphinx-src", "--build-dir"}
    if extra and extra[0] in global_flags:
        argv = ["check_rst.py", *extra, "fix", "--fast", str(document)]
    else:
        argv = ["check_rst.py", "fix", "--fast", *extra, str(document)]
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    assert document.read_text(encoding="utf-8") == original
    assert message in capsys.readouterr().out


@pytest.mark.integration
def test_cli_fix_only_no_adornments_is_hygiene_only(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    document.write_bytes(_BAD_BLOCK.replace("\n", "\r\n").encode())
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "fix", "--fast", "--no-adornments", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    assert document.read_text(encoding="utf-8") == _BAD_BLOCK
    out = capsys.readouterr().out
    assert "CRLF line endings 7" in out
    assert "structural lines" not in out


@pytest.mark.integration
def test_cli_fix_only_quiet_emits_only_the_status_footer(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", "--fast", "--quiet", str(document)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    assert capsys.readouterr().out.splitlines() == [
        "check_rst: 1 file(s) processed, 0 error(s), 1 file(s) fixed [fast]"
    ]


@pytest.mark.integration
def test_cli_fix_only_write_failure_is_nonzero_and_keeps_final_status(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    original = _BAD_BLOCK
    document.write_text(original, encoding="utf-8")

    def fail_write(_plan: object) -> None:
        raise OSError("read-only filesystem")

    monkeypatch.setattr(check_rst, "_apply_fix_plan", fail_write)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", "--fast", str(document)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    assert document.read_text(encoding="utf-8") == original
    lines = capsys.readouterr().out.splitlines()
    assert any("ERROR: cannot write fix: read-only filesystem" in line for line in lines)
    assert lines[-1] == ("check_rst: 1 file(s) processed, 1 error(s), 0 file(s) fixed [fast]")


@pytest.mark.integration
def test_cli_fix_only_is_convergent_and_verbose_names_clean_files(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", "--fast", str(document)])
    with pytest.raises(SystemExit) as first:
        check_rst.main()
    assert first.value.code == 0
    capsys.readouterr()

    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", "--fast", "--verbose", str(document)])
    with pytest.raises(SystemExit) as second:
        check_rst.main()

    assert second.value.code == 0
    lines = capsys.readouterr().out.splitlines()
    assert f"{document}: no fixable changes" in lines
    assert lines[-1] == ("check_rst: 1 file(s) processed, 0 error(s), 0 file(s) fixed [fast]")


# ---------------------------------------------------------------------------
# Whole-report output budget — semantic checks still run to completion while
# the report sink reserves its statistics line and authoritative final status.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--max-output-lines", "10"], 10),
        (["--max-output-lines=7"], 7),
        (["--max-output-lines", "10", "--max-output-lines=2"], 2),
        (["--", "--max-output-lines", "10"], None),
        (["--max-output-lines", "1"], None),
        (["--help", "--max-output-lines", "10"], None),
    ],
)
def test_requested_output_limit_matches_cli_bootstrap_rules(
    check_rst: types.ModuleType, argv: list[str], expected: int | None
) -> None:
    assert check_rst._requested_output_limit(argv) == expected


@pytest.mark.integration
def test_cli_max_output_lines_rejects_values_below_two(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "test.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "check", "--max-output-lines", "1", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    assert "--max-output-lines must be >= 2" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_max_output_lines_two_reserves_statistics_and_failed_footer(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "test.rst"
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "check", "--quiet", "--max-output-lines", "2", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert lines[0] == (
        "check_rst: output limited — 0 of 1 detail line(s) shown, 1 skipped (1 ERROR); full output requires 3 lines"
    )
    assert lines[1].startswith("check_rst: 1 file(s) checked, 1 error(s)")


@pytest.mark.integration
def test_cli_max_output_lines_reports_zero_suppression_without_padding(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "test.rst"
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "check", "--quiet", "--max-output-lines", "10", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    assert lines[0].startswith(f"{document}:")
    assert lines[1] == (
        "check_rst: output limited — 1 of 1 detail line(s) shown, 0 skipped; full output requires 3 lines"
    )
    assert lines[2].startswith("check_rst: 1 file(s) checked, 1 error(s)")


@pytest.mark.integration
def test_cli_max_output_lines_classifies_suppressed_warnings(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "test.rst"
    document.write_text(
        _GOOD_BLOCK + "\n**Bold opener** starts a paragraph.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "check", "--quiet", "--max-output-lines", "2", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert "1 WARNING" in lines[0]
    assert lines[1].startswith("check_rst: 1 file(s) checked, 0 error(s), 1 warning(s)")


@pytest.mark.integration
def test_cli_max_output_lines_applies_after_outline_filters_and_classifies(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "test.rst"
    document.write_text(
        "#######\nTitle\n#######\n\n*******\nChild\n*******\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "outline", "--sections-only", "--max-output-lines", "3", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    assert lines[0] == f"Outline: {document}"
    assert "skipped" in lines[1]
    assert "outline" in lines[1]
    assert lines[2].startswith("check_rst: 1 file(s) checked, 0 error(s)")


@pytest.mark.integration
def test_cli_max_output_lines_early_failure_has_hint_and_status_footer(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing.rst"
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "check", "--max-output-lines", "2", str(missing)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert "rerun without --max-output-lines for complete diagnostics" in lines[0]
    assert lines[1] == ("check_rst: command failed before producing a run summary, exit status 1")


@pytest.mark.integration
def test_cli_max_output_lines_keeps_footer_last_after_verbose_statistics(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "test.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "check", "--verbose", "--max-output-lines", "5", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 5
    assert lines[-2].startswith("check_rst: output limited")
    assert lines[-1].startswith("check_rst: 1 file(s) checked, 0 error(s)")


@pytest.mark.integration
def test_cli_max_output_lines_supports_fix_only_without_masking_mutation(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "test.rst"
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "fix", "--fast", "--max-output-lines", "2", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    assert document.read_text(encoding="utf-8") == _GOOD_BLOCK
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert "0 of 2 detail line(s) shown, 2 skipped" in lines[0]
    assert lines[1] == ("check_rst: 1 file(s) processed, 0 error(s), 1 file(s) fixed [fast]")


@pytest.mark.integration
def test_cli_max_output_lines_rejects_format_json(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Of the old incompatible_budget_mode rule's six modes, --format=json
    is the only one that survives as a value-level check under the
    subcommand redesign — see _validate_check_args. The other five
    (diff/diff --fast/refs/context/diff-json, tested below) never define
    --max-output-lines on their own parser at all now."""
    document = tmp_path / "test.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "check", "--format=json", "--max-output-lines", "10", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    lines = capsys.readouterr().out.splitlines()
    assert any("--max-output-lines" in line and "incompatible" in line for line in lines)
    assert lines[-1] == ("check_rst: command failed before producing a run summary, exit status 1")


@pytest.mark.integration
@pytest.mark.parametrize(
    "argv_tail",
    [
        ["diff", "--max-output-lines", "10", "FILE"],
        ["diff", "--fast", "--max-output-lines", "10", "FILE"],
        ["refs", "--max-output-lines", "10", "FILE"],
        ["context", "Title", "--max-output-lines", "10", "FILE"],
        ["diff-json", "--max-output-lines", "10", "old.json", "new.json"],
    ],
)
def test_cli_max_output_lines_absent_from_structured_or_copyable_verbs(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv_tail: list[str],
) -> None:
    """--max-output-lines is now an ordinary argparse "unrecognized
    arguments" error on every verb that used to need a custom
    incompatible_budget_mode rejection for it — none of diff/refs/context/
    diff-json define the flag on their own parser. Still exit 2, but on
    stdout, not stderr: --max-output-lines being present anywhere in raw
    argv activates main()'s OutputBudgetSink (_requested_output_limit's own
    pre-argparse raw scan) before argparse ever runs, which merges
    stdout/stderr into one captured stream — same architecture the passing
    test_cli_max_output_lines_rejects_format_json above already relies on."""
    document = tmp_path / "test.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    argv = ["check_rst.py", *[str(document) if a == "FILE" else a for a in argv_tail]]
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_quiet_suppresses_progress_keeps_summary(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--quiet drops phase banners and per-file OK lines; the summary line
    stays — a clean run prints essentially one line."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Phase 1" not in out
    assert "✓" not in out
    assert "check_rst: 1 file(s) checked" in out


@pytest.mark.integration
def test_cli_findings_match_de_facto_compiler_output_shape(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every finding line is bare 'path:line: LEVEL: message' — no leading
    glyph, nothing before the path (Max, 2026-07-20: "we break de-facto
    compiler alike output... will it be better to delete them?" — added
    to the contract, see projects/journal/check_rst.rst, "De-facto
    compiler output").  This is the shape generic tooling (IDE problem
    matchers, editor jump-to-error) already knows how to parse."""
    p = rst_repo / "test.rst"
    p.write_text(_BAD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    finding_lines = [ln for ln in out.splitlines() if ": ERROR: " in ln or ": WARNING: " in ln]
    assert finding_lines
    for ln in finding_lines:
        assert re.match(r"^\S.*:\d+: (ERROR|WARNING): .+$", ln), ln
        assert not ln.startswith(("✗", "⚠", " "))


@pytest.mark.integration
def test_cli_quiet_keeps_findings(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--quiet never hides findings — exactly the WARNING:/ERROR: lines the
    old grep '^⚠' workaround was extracting (glyph-less since 2026-07-20,
    same findings-survive-quiet contract)."""
    p = rst_repo / "test.rst"
    p.write_text(_BAD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "must be 7 chars" in out
    assert "ERROR:" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_cli_quiet_keeps_requested_outline(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--quiet suppresses noise, not requested reports: --outline output
    still prints."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", "--quiet", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "Outline:" in out
    assert "Title" in out
    assert "Phase 2" not in out


# ---------------------------------------------------------------------------
# Verbosity-level inventory (Max, 2026-07-20) — three levels: --quiet,
# default, --verbose.  The 'levels:' legend stays unconditional whenever
# --outline runs (unchanged); 'blocks:' and the footer's 'lines:'/'words:'
# are promoted to --verbose-only; top/rare prose words move to
# --verbose-only too, but independently promotable at any level (--quiet
# included) via the new --word-samples N, which also unifies the
# footer's old N=13 and the JSON model's old N=10 into one shared,
# flag-controlled default of 10.  Computation, not just display, is
# skipped when the result would not be shown — "we shouldn't pay for
# what we don't use" (Max): no stopword/stemmer cost for output nobody
# asked to see.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_outline_blocks_summary_hidden_by_default(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """'blocks:' requires --verbose; 'levels:' does not — the one line
    demoted out of the two the a6ea216-era design originally paired."""
    p = rst_repo / "test.rst"
    p.write_text(
        "Root\n####\n\n.. code-block:: bash\n\n   echo one\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", "--quiet", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "levels:" in out
    assert "blocks:" not in out


@pytest.mark.integration
def test_outline_blocks_summary_shown_with_verbose(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "Root\n####\n\n.. code-block:: bash\n\n   echo one\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "blocks: 1 code block" in out


@pytest.mark.integration
def test_footer_lines_words_hidden_by_default(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "check_rst: 1 file(s) checked" in out  # Line 1 always prints
    assert "lines:" not in out
    assert "words:" not in out


@pytest.mark.integration
def test_footer_lines_words_shown_with_verbose(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "lines:" in out
    assert "words:" in out


@pytest.mark.integration
def test_default_run_never_computes_word_frequency(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The default level (no --verbose, no --word-samples) must not even
    CALL the stopword/stemmer machinery — display suppression alone would
    still pay the computation cost for output nobody sees."""

    def _must_not_run(*_a: object, **_k: object) -> None:
        raise AssertionError("word-frequency computation must be skipped")

    monkeypatch.setattr(check_rst, "_top_prose_words", _must_not_run)
    monkeypatch.setattr(check_rst, "_rare_prose_words", _must_not_run)
    p = rst_repo / "test.rst"
    p.write_text("#######\nTitle\n#######\n\nSome real prose content here.\n", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0


@pytest.mark.integration
def test_word_samples_zero_disables_even_under_verbose(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--word-samples 0 overrides --verbose's own default of 10 — an
    explicit request always wins, in either direction."""

    def _must_not_run(*_a: object, **_k: object) -> None:
        raise AssertionError("word-frequency computation must be skipped")

    monkeypatch.setattr(check_rst, "_top_prose_words", _must_not_run)
    monkeypatch.setattr(check_rst, "_rare_prose_words", _must_not_run)
    p = rst_repo / "test.rst"
    p.write_text("#######\nTitle\n#######\n\nSome real prose content here.\n", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", "--word-samples", "0", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "top prose words:" not in out
    assert "rare prose words:" not in out


@pytest.mark.integration
def test_word_samples_promotes_top_rare_words_under_quiet(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--word-samples N promotes the prose-word lines at ANY level,
    --quiet included — the one line-4 exception to the verbosity
    ladder (Max: 'promote in any level to output them')."""
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\nproduct server product server product.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--word-samples", "5", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "top prose words: product (3 @" in out
    # lines:/words: stay hidden — --word-samples promotes only line 4.
    # (Line-start check: "words:" alone is a substring of "rare prose
    # words:", which IS expected to be present here.)
    assert not any(ln.startswith("lines:") or ln.startswith("words:") for ln in out.splitlines())


@pytest.mark.integration
def test_json_word_samples_disabled_by_default(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--json without --verbose/--word-samples: top_words/rare_words are
    null, not the old always-populated N=10 — same skip-entirely contract
    as the text footer, unifying the two previously-independent defaults
    (footer 13, JSON 10) into one shared, flag-controlled value."""
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\nproduct server product server.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    stats = data["files"][0]["stats"]
    assert stats["top_words"] is None
    assert stats["rare_words"] is None
    assert stats["word_stats_error"] is None  # null ≠ error: simply not requested


@pytest.mark.integration
def test_word_samples_rejects_negative(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--word-samples", "-1", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--word-samples must be >= 0" in out


# ---------------------------------------------------------------------------
# Outline enrichment: per-title subsection counts + --outline-depth (Max,
# 2026-07-18) — each outline line becomes self-contained data, and deep
# structure can be trimmed without silent truncation → Zone 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_outline_children_counts(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.build_outline(p)
    assert [(e.title, e.children) for e in entries] == [
        ("Root", 2),
        ("Sub A", 1),
        ("Leaf A1", 0),
        ("Sub B", 0),
    ]


@pytest.mark.integration
def test_outline_str_shows_subsection_count(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.build_outline(p)
    assert str(entries[0]) == "1-8:# Root [2 subsections]"
    assert str(entries[1]) == "    4-5:* Sub A"  # trailing blank trimmed


@pytest.mark.integration
def test_cli_outline_depth_limits_levels(
    check_rst: types.ModuleType,
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
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", "--outline-depth", "2", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
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
    check_rst: types.ModuleType,
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
        ["check_rst.py", "outline", "--with-findings", "--quiet", "--outline-depth", "2", str(p)],
    )
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "Sub" in out
    assert "code-block" not in out
    assert "1 deeper entry hidden" in out


@pytest.mark.integration
def test_cli_summary_reports_line_statistics(
    check_rst: types.ModuleType,
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
        check_rst.main()
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
    check_rst: types.ModuleType,
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
        check_rst.main()
    out = capsys.readouterr().out
    # Two identical files: same repertoire, nothing occurs once anymore.
    assert "92 char(s) (= bytes, 15 distinct, 0 once), 4 space(s) (4%)" in out
    assert "lines: 14 total (4 empty, 29%), length min/avg/max 5/8/10 chars (= bytes)" in out
    assert "words: 14 total, 5 distinct (0 once), length min/avg/max 4/5/7" in out


@pytest.mark.integration
def test_cli_non_utf8_file_clean_error_not_traceback(
    check_rst: types.ModuleType,
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
        check_rst.main()
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
    check_rst: types.ModuleType,
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
        check_rst.main()
    out = capsys.readouterr().out
    assert "char(s) (" in out  # distinct/once detail binds to chars
    assert "byte(s)" in out
    assert "= bytes" not in out  # differ form: bytes shown, no collapse note
    # Line-length spread differs too (Cyrillic-free but non-ASCII lines):
    # both triples shown, no collapse.  lines:/words: are --verbose-only
    # (Max, 2026-07-20: verbosity-level inventory).
    assert " chars / " in out


@pytest.mark.integration
def test_cli_outline_legend_line_replaces_per_entry_level_info(
    check_rst: types.ModuleType,
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
        check_rst.main()
    out = capsys.readouterr().out
    assert "levels: 1 '#' (1), 2 '*' (2), 3 '=' (1)" in out
    assert "Level" not in out.replace("levels:", "")
    assert "  1-11:# Root [2 subsections]" in out
    assert "      4-8:* Sub A [1 subsection]" in out
    assert "          7-8:= Deep" in out


@pytest.mark.integration
def test_cli_outline_legend_shows_total_sections(
    check_rst: types.ModuleType,
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
        check_rst.main()
    out = capsys.readouterr().out
    assert "levels: 1 '#' (1), 2 '*' (2), 3 '=' (1), 4 sections total" in out


@pytest.mark.integration
def test_cli_outline_blocks_summary_line(
    check_rst: types.ModuleType,
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
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "blocks: 2 code blocks, 1 blockquote" in out


@pytest.mark.integration
def test_cli_outline_blocks_summary_absent_without_blocks(
    check_rst: types.ModuleType,
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
        check_rst.main()
    out = capsys.readouterr().out
    assert "blocks:" not in out


@pytest.mark.integration
def test_cli_outline_section_bracket_shows_cumulative_code_and_quote_counts(
    check_rst: types.ModuleType,
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
        check_rst.main()
    out = capsys.readouterr().out
    root_line = next(ln for ln in out.splitlines() if "Root" in ln)
    sub_line = next(ln for ln in out.splitlines() if "Sub" in ln and "Root" not in ln)
    assert "[1 subsection, 1 code block, 1 blockquote]" in root_line
    assert "[1 code block, 1 blockquote]" in sub_line


# ---------------------------------------------------------------------------
# Blockquote entries in --outline (Max, 2026-07-18) — quote zones are
# semantically significant since the blockquote exemption: they explain
# absent warnings and show composition.  Each entry carries a limited
# preview of the quote's beginning for quick identification → Zone 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_block_quotes_found_with_preview_and_depth(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_block_quotes(p)
    assert [(e.lineno, e.depth) for e in entries] == [(6, 2), (13, 3)]
    assert entries[0].preview.startswith("The Parsing Bug")
    assert entries[1].preview == "Short quote."


@pytest.mark.integration
def test_block_quotes_no_preceding_heading_is_depth_1(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A blockquote with no enclosing section at all is depth 1 (top-level),
    same convention as test_heuristic_code_blocks_no_preceding_heading_is_depth_1."""
    p = _rst(
        tmp_path,
        """\
        Intro paragraph, no title above it at all.

            A quote with no enclosing section.
        """,
    )
    entries = check_rst.find_block_quotes(p)
    assert len(entries) == 1
    assert entries[0].depth == 1


@pytest.mark.integration
def test_block_quote_preview_truncated(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """The preview is a LIMITED beginning — one collapsed line, truncated
    with '...' — a quick identity, not the quote's content."""
    long_text = "word " * 40
    p = _rst(tmp_path, f"Intro.\n\n    {long_text}\n")
    entries = check_rst.find_block_quotes(p)
    assert len(entries) == 1
    assert entries[0].preview.endswith("...")
    assert len(entries[0].preview) <= 77


@pytest.mark.integration
def test_block_quote_str_format(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(tmp_path, "Intro.\n\n    Quoted line.\n")
    entries = check_rst.find_block_quotes(p)
    assert str(entries[0]) == '3: blockquote "Quoted line."'


@pytest.mark.integration
def test_block_quote_nested_quote_single_entry(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A quote within a quote reports once — the outer entry's preview
    already covers the subtree; a second entry would double-count."""
    p = _rst(tmp_path, "Intro.\n\n    Outer quote.\n\n        Inner quote.\n")
    entries = check_rst.find_block_quotes(p)
    assert len(entries) == 1
    assert entries[0].preview.startswith("Outer quote.")


@pytest.mark.integration
def test_block_quote_in_literal_block_not_reported(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Indented text inside a real code-block is literal content, never
    parsed as a blockquote — automatic, pinned."""
    p = _rst(tmp_path, ".. code:: text\n\n    looks like\n\n        a quote\n")
    assert check_rst.find_block_quotes(p) == []


@pytest.mark.integration
def test_cli_outline_includes_blockquotes_in_order(
    check_rst: types.ModuleType,
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
        check_rst.main()
    out = capsys.readouterr().out
    assert 'blockquote "Quoted answer text."' in out
    assert out.index("2-9:# Title") < out.index('blockquote "Quoted answer text."')


@pytest.mark.integration
def test_cli_outline_depth_trims_blockquotes_too(
    check_rst: types.ModuleType,
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
        ["check_rst.py", "outline", "--with-findings", "--quiet", "--outline-depth", "2", str(p)],
    )
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    # The aggregate legend and the parent section's cumulative bracket both
    # legitimately still mention "blockquote" (Max: totals are never hidden
    # by --outline-depth) — what must actually be absent is the entry
    # ITSELF, i.e. its quoted content.
    assert "Deep quote" not in out
    assert "1 deeper entry hidden" in out


# ---------------------------------------------------------------------------
# --outline-only: the structure-only view (roadmap item 7, from the downstream-project
# assessment) — one flag replacing the four-flag stack
# --quiet --skip-fixable --no-warnings --outline, without touching the
# "never suppress warnings in the validation loop" rule → Zone 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_outline_only_pure_structure_with_honest_footer(
    check_rst: types.ModuleType,
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
        check_rst.main()
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
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No need to also pass --outline or --quiet — one flag is the point."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Outline:" in out
    assert "4-7:# Title" in out  # heading entry with extent (_GOOD_BLOCK)
    assert "Phase 2" not in out


@pytest.mark.integration
def test_cli_outline_only_composes_with_outline_depth(
    check_rst: types.ModuleType,
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
        check_rst.main()
    out = capsys.readouterr().out
    assert "levels: 1 '#' (1), 2 '*' (1), 3 '=' (1)" in out
    assert "Deep" not in out
    assert "1 deeper entry hidden" in out


# ---------------------------------------------------------------------------
# Per-repo configuration file (roadmap item 5) — .check_rst.toml or
# pyproject.toml [tool.check_rst] at the working directory declares the
# project facts (sphinx-src, build-dir) so invocations stop carrying the
# long options.  NOT auto-detection: a checked-in config is an explicit,
# versioned declaration.  Honesty conditions: cwd-only discovery, applied
# values echoed, CLI flags always override, unknown keys fail loudly → Zone 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_config_dedicated_file_applies_and_is_echoed(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    (rst_repo / ".check_rst.toml").write_text(
        f'sphinx-src = "{rst_repo}"\nbuild-dir = "{rst_repo}/_build"\n',
        encoding="utf-8",
    )
    p = rst_repo / "index.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "config: .check_rst.toml" in out  # applied values are echoed
    assert "sphinx-src" in out
    assert "Phase 3: Sphinx build integrity" in out  # verified mode ON via config


@pytest.mark.integration
def test_config_pyproject_table_applies(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "pyproject.toml").write_text(
        f'[tool.check_rst]\nsphinx-src = "{rst_repo}"\nbuild-dir = "{rst_repo}/_build"\n',
        encoding="utf-8",
    )
    p = rst_repo / "index.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "config: pyproject.toml" in out
    assert "Phase 3: Sphinx build integrity" in out


@pytest.mark.integration
def test_config_build_dir_without_sphinx_source_is_reported_inactive(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = rst_repo / ".check_rst.toml"
    config.write_text('build-dir = "_build"\n', encoding="utf-8")
    document = rst_repo / "doc.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(document)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "config: .check_rst.toml" in out
    assert "build-dir=_build inactive (no sphinx-src)" in out
    assert "Phase 3: Sphinx build — skipped" in out
    assert not (rst_repo / "_build").exists()


@pytest.mark.integration
def test_config_cli_flags_override(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI always wins: a config pointing at a conf.py-less directory must
    not be path-validated when the CLI supplies its own --sphinx-src."""
    bad = rst_repo / "not_sphinx"
    bad.mkdir()
    (rst_repo / ".check_rst.toml").write_text(f'sphinx-src = "{bad}"\n', encoding="utf-8")
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    p = rst_repo / "index.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "--build-dir", str(rst_repo / "_build"), "check", str(p)],
    )
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0  # config's bad path never used
    out = capsys.readouterr().out
    assert "no conf.py" not in out


@pytest.mark.integration
def test_config_unknown_key_fails_loudly(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A typo'd key is a mistake worth failing on immediately — same
    precedent as a --sphinx-src without conf.py."""
    (rst_repo / ".check_rst.toml").write_text('sphix-src = "."\n', encoding="utf-8")
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "sphix-src" in out
    assert "unknown key" in out


@pytest.mark.integration
def test_no_config_skips_auto_discovery(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--no-config runs as if the working directory declared no project
    facts at all — a valid, discoverable .check_rst.toml is never applied
    (no "config: ..." echo, no verified Sphinx mode from its sphinx-src)."""
    (rst_repo / ".check_rst.toml").write_text('sphinx-src = "."\n', encoding="utf-8")
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "--no-config", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "config:" not in out
    assert "Sphinx" not in out.split("\n")[0]  # runtime line carries no Sphinx version


@pytest.mark.integration
def test_no_config_skips_even_a_malformed_config(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The strongest evidence discovery is truly skipped, not just
    deprioritized: a committed .check_rst.toml with an unknown key would
    normally fail loudly on discovery alone (test_config_unknown_key_fails_
    loudly above) — --no-config must never even read it, let alone validate
    it, so the same file causes no error at all here."""
    (rst_repo / ".check_rst.toml").write_text('sphix-src = "."\n', encoding="utf-8")
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "--no-config", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "unknown key" not in out


@pytest.mark.integration
def test_no_config_rejects_explicit_config(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--no-config and --config are a direct contradiction — one says skip
    config loading, the other explicitly requests it; neither can silently
    win over the other."""
    config = rst_repo / "check-rst.toml"
    config.write_text('sphinx-src = "."\n', encoding="utf-8")
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--no-config", "--config", str(config), "check", str(p)],
    )
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--no-config is incompatible with --config" in out


@pytest.mark.integration
def test_config_dedicated_file_wins_over_pyproject(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    (rst_repo / ".check_rst.toml").write_text(
        f'sphinx-src = "{rst_repo}"\nbuild-dir = "{rst_repo}/_build"\n',
        encoding="utf-8",
    )
    (rst_repo / "pyproject.toml").write_text('[tool.check_rst]\nsphinx-src = "/nonexistent"\n', encoding="utf-8")
    p = rst_repo / "index.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "config: .check_rst.toml" in out


@pytest.mark.integration
def test_config_echo_suppressed_when_quiet(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    (rst_repo / ".check_rst.toml").write_text(
        f'sphinx-src = "{rst_repo}"\nbuild-dir = "{rst_repo}/_build"\n',
        encoding="utf-8",
    )
    p = rst_repo / "index.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "config:" not in out


@pytest.mark.integration
def test_explicit_config_from_foreign_cwd_resolves_relative_values_from_config(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--config names the project explicitly: its paths are config-relative,
    while the process may run from an entirely unrelated directory."""
    project = tmp_path / "project"
    docs = project / "docs"
    docs.mkdir(parents=True)
    (docs / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    document = docs / "index.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    config = project / ".check_rst.toml"
    config.write_text(
        'sphinx-src = "docs"\nbuild-dir = "_build"\n',
        encoding="utf-8",
    )
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    monkeypatch.setattr(check_rst, "PROJECT_ROOT", foreign)
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--config", str(config.relative_to(foreign, walk_up=True)), "check", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert f"config: {config.resolve()}" in out
    assert f"Phase 2: Python Sphinx rules ({project / '_build'})" in out
    assert f"Phase 3: Sphinx build integrity ({project / '_build'})" in out


@pytest.mark.integration
def test_explicit_config_bare_run_discovers_git_changes_from_config_root(
    check_rst: types.ModuleType,
    tmp_git_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With no positional files, --config also defines where bare Git
    discovery and diff scoping run; invocation cwd must be irrelevant."""
    document = tmp_git_repo / "changed.rst"
    # The committed error must stay out of scope when only the appended line
    # changes; this proves diff queries use the config-selected repository.
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    config = tmp_git_repo / ".check_rst.toml"
    config.write_text('build-dir = "_build"\n', encoding="utf-8")
    _git(tmp_git_repo, "add", "changed.rst", ".check_rst.toml")
    _git(tmp_git_repo, "commit", "-m", "base")
    document.write_text(_BAD_BLOCK + "\nChanged.\n", encoding="utf-8")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    monkeypatch.setattr(check_rst, "PROJECT_ROOT", foreign)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--config", str(config), "check"])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "1 file(s) checked" in out
    assert "no changed .rst files" not in out


@pytest.mark.integration
def test_explicit_config_suppresses_cwd_config_discovery(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = project / ".check_rst.toml"
    config.write_text('build-dir = "_build"\n', encoding="utf-8")
    document = project / "index.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / ".check_rst.toml").write_text('sphix-src = "typo must not be loaded"\n', encoding="utf-8")
    monkeypatch.chdir(foreign)
    monkeypatch.setattr(check_rst, "PROJECT_ROOT", foreign)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--config", str(config), "check", str(document)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert f"config: {config.resolve()}" in out
    assert "unknown key" not in out


@pytest.mark.integration
def test_explicit_pyproject_config_uses_tool_table(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = project / "pyproject.toml"
    config.write_text('[tool.check_rst]\nbuild-dir = "_build"\n', encoding="utf-8")
    document = project / "index.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    monkeypatch.setattr(check_rst, "PROJECT_ROOT", foreign)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--config", str(config), "check", str(document)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    assert f"config: {config.resolve()}" in capsys.readouterr().out


@pytest.mark.integration
def test_explicit_config_json_uses_config_root_for_document_ids(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    docs = project / "docs"
    docs.mkdir(parents=True)
    config = project / ".check_rst.toml"
    config.write_text('build-dir = "_build"\n', encoding="utf-8")
    document = docs / "index.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    monkeypatch.setattr(check_rst, "PROJECT_ROOT", foreign)
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--config", str(config), "check", "--format=json", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["config"]["source"] == str(config.resolve())
    assert data["files"][0]["outline"][0]["id"] == "docs/index:Title"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("problem", "message"),
    [
        ("missing", "file not found"),
        ("directory", "not a regular file"),
        ("malformed", "invalid TOML"),
        ("empty", "does not declare check_rst settings"),
    ],
)
def test_explicit_config_errors_cleanly_before_actions(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    problem: str,
    message: str,
) -> None:
    config = tmp_path / "selected.toml"
    if problem == "directory":
        config.mkdir()
    elif problem == "malformed":
        config.write_text('sphinx-src = ["unterminated"\n', encoding="utf-8")
    elif problem == "empty":
        config.write_text("", encoding="utf-8")

    def unexpected_action(*_args: object, **_kwargs: object) -> None:
        pytest.fail("invalid explicit config must stop before Git or Sphinx")

    monkeypatch.setattr(check_rst, "_changed_rst_files", unexpected_action)
    monkeypatch.setattr(check_rst, "_build_sphinx_env", unexpected_action)
    monkeypatch.setattr(check_rst, "run_sphinx", unexpected_action)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--config", str(config), "check"])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--config" in out
    assert message in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_explicit_config_values_are_overridden_by_cli_paths(
    check_rst: types.ModuleType,
    rst_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_dir = tmp_path / "config-project"
    config_dir.mkdir()
    config = config_dir / ".check_rst.toml"
    config.write_text(
        'sphinx-src = "missing"\nbuild-dir = "occupied"\n',
        encoding="utf-8",
    )
    (rst_repo / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    document = rst_repo / "index.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    build_dir = rst_repo / "_build"
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--config",
            str(config),
            "--sphinx-src",
            str(rst_repo),
            "--build-dir",
            str(build_dir),
            "check",
            str(document),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "no conf.py" not in out
    assert "not a directory" not in out


@pytest.mark.integration
def test_refs_accepts_explicit_config(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    document = tmp_path / "index.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    config = tmp_path / ".check_rst.toml"
    config.write_text('sphinx-src = "."\nbuild-dir = "_build"\n', encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--config", str(config), "refs", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    assert f"References: {document}" in capsys.readouterr().out


@pytest.fixture(autouse=True)
def _isolated_project_root(check_rst: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every test from the real repository's .check_rst.toml.

    PROJECT_ROOT is captured at import time — under pytest that is the
    Journal itself, which now carries a real config declaring sphinx-src.
    Without this guard, every CLI test that doesn't patch PROJECT_ROOT
    silently picks up that config and runs a FULL Journal Sphinx build.
    Found via the CALL_COUNTS instrumentation (Max's counters idea): a
    "heuristic-mode" test showed _build_sphinx_env=1, run_sphinx=1 —
    deterministic proof, where wall-clock only raised suspicion.  Autouse
    fixtures run before explicitly requested ones, so rst_repo's own
    PROJECT_ROOT patch still wins for tests that use it.
    """
    monkeypatch.setattr(check_rst, "PROJECT_ROOT", tmp_path)
    check_rst.CALL_COUNTS.clear()  # each test starts from zero — counts are assertable


@pytest.mark.integration
def test_call_counts_heuristic_run_never_builds_sphinx(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CALL_COUNTS pin the execution stack (Max, 2026-07-19): a bare
    heuristic-mode run must never build a Sphinx environment nor run
    sphinx-build.  This is exactly the regression the counters caught the
    day they were added — a config leak made "heuristic" CLI tests silently
    run full Journal builds; wall-clock raised suspicion, the counters
    proved it deterministically, and this assertion now FAILS instead of
    merely running slowly."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    check_rst.CALL_COUNTS.clear()
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()

    assert check_rst.CALL_COUNTS["_build_sphinx_env"] == 0
    assert check_rst.CALL_COUNTS["run_sphinx"] == 0
    assert check_rst.CALL_COUNTS["_load_config"] == 1
    assert check_rst.CALL_COUNTS["_parse_rst"] >= 1


@pytest.mark.integration
def test_call_counts_verified_run_builds_exactly_once(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verified mode: one env build and one sphinx-build PER RUN, never per
    file — the counters make the O(1)-vs-O(files) distinction a test fact
    instead of a performance impression."""
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    a = rst_repo / "index.rst"
    a.write_text(_GOOD_BLOCK, encoding="utf-8")
    b = rst_repo / "other.rst"
    b.write_text(_GOOD_BLOCK, encoding="utf-8")

    check_rst.CALL_COUNTS.clear()
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "--build-dir",
            str(rst_repo / "_build"),
            "check",
            str(a),
            str(b),
        ],
    )
    with pytest.raises(SystemExit):
        check_rst.main()

    assert check_rst.CALL_COUNTS["_build_sphinx_env"] == 1
    assert check_rst.CALL_COUNTS["run_sphinx"] == 1


@pytest.mark.integration
def test_call_counts_toctree_anomalies_computed_once_per_run(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Found by code review: check_multiple_toctree_parents rebuilt the
    whole project-wide parents_by_child/anomalies graph from
    env.toctree_includes from scratch on every call, but Phase 2's own
    loop called it once PER FILE with the same, unchanged env — O(files)
    redundant rebuilds of one project-wide graph. _toctree_anomalies
    (the split-out, cacheable half) must run exactly once per run, no
    matter how many files are selected, the same one-computation
    contract test_call_counts_verified_run_builds_exactly_once already
    pins for _build_sphinx_env/run_sphinx."""
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    a = rst_repo / "index.rst"
    a.write_text(_GOOD_BLOCK, encoding="utf-8")
    b = rst_repo / "other.rst"
    b.write_text(_GOOD_BLOCK, encoding="utf-8")

    check_rst.CALL_COUNTS.clear()
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "--build-dir",
            str(rst_repo / "_build"),
            "check",
            str(a),
            str(b),
        ],
    )
    with pytest.raises(SystemExit):
        check_rst.main()

    assert check_rst.CALL_COUNTS["_toctree_anomalies"] == 1


# ---------------------------------------------------------------------------
# Stage 1 of the Document facade (roadmap item 1) — one read-only object per
# file: normalized text, lines, hygiene, doctree, outline, quotes — computed
# once, shared by every checker.  Fixers deliberately keep the mutating
# buffer; after a fixer writes, a NEW Document is constructed (invalidation
# is explicit in the object lifetime — no cache staleness possible).
# The dedup is pinned with CALL_COUNTS, not wall-clock → Zone 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_document_reads_and_parses_once(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Accessing every facade property costs exactly one read and one
    docutils parse."""
    p = _rst(tmp_path, "Title\n=====\n\nText.\n\n    Quoted.\n")
    check_rst.CALL_COUNTS.clear()
    doc = check_rst.Document(p)
    _ = doc.text, doc.lines, doc.hygiene, doc.outline, doc.block_quotes
    _ = doc.doctree
    assert check_rst.CALL_COUNTS["_read_source"] == 1
    assert check_rst.CALL_COUNTS["_parse_rst"] == 1


@pytest.mark.integration
def test_cli_check_run_reads_each_file_once(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The whole check pipeline (hygiene + adornments + hierarchy +
    directives + footer stats) shares one Document: one read, one parse
    per file.  Before the facade: five reads per file."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    check_rst.CALL_COUNTS.clear()
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    assert check_rst.CALL_COUNTS["_read_source"] == 1
    assert check_rst.CALL_COUNTS["_parse_rst"] == 1


@pytest.mark.integration
def test_cli_outline_run_still_one_read_one_parse(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--outline reuses the Phase 1 Document across phases — the Phase 2
    outline loop must not re-read or re-parse."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    check_rst.CALL_COUNTS.clear()
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    assert check_rst.CALL_COUNTS["_read_source"] == 1
    assert check_rst.CALL_COUNTS["_parse_rst"] == 1


# ---------------------------------------------------------------------------
# --json: the document model as machine-readable output (stage 1's API) —
# one JSON document on stdout, nothing else; findings inside; exit code
# semantics unchanged → Zone 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_json_valid_and_complete(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "Title\n=====\n\n**Bold Heading**\n\nHe wrote:\n\n    Quoted text.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1  # underline-only ERROR — exit semantics unchanged
    out = capsys.readouterr().out
    data = json.loads(out)  # pure JSON — nothing else on stdout
    assert data["schema_version"] == 1
    assert data["mode"] == "heuristic"
    assert data["runtime"]["python"]["executable"] == sys.executable
    assert data["runtime"]["docutils"]["version"]
    assert data["runtime"]["sphinx"] is None
    assert data["runtime"]["snowballstemmer"] is None
    assert data["config"] is None  # no per-repo config in this sandbox
    (f,) = data["files"]
    assert f["path"].endswith("test.rst")
    assert any(x["severity"] == "ERROR" for x in f["findings"])
    assert any(x["severity"] == "WARNING" for x in f["findings"])
    assert f["outline"][0]["title"] == "Title"
    assert f["block_quotes"][0]["preview"] == "Quoted text."
    assert f["stats"]["lines"] == 8
    assert data["summary"]["errors"] >= 1


@pytest.mark.integration
def test_cli_json_no_warnings_filters_records_and_summary(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    document.write_text("#######\nTitle\n#######\n\n**Heading-like text**\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", "--no-warnings", str(document)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["warnings"] == 0
    assert all(finding["severity"] != "WARNING" for finding in data["files"][0]["findings"])


@pytest.mark.integration
def test_cli_json_no_warnings_filters_sphinx_findings(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    document = rst_repo / "index.rst"
    document.write_text("#######\nTitle\n#######\n\nSee :doc:`missing`.\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "check", "--format=json", "--no-warnings", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["warnings"] == 0
    assert data.get("sphinx_findings", []) == []


@pytest.mark.integration
def test_cli_json_stable_section_ids(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Outline entries carry a stable id in the autosectionlabel convention
    (docname:title) — an AI can say 'insert after <id>' without line
    numbers."""
    sub = rst_repo / "docs"
    sub.mkdir()
    p = sub / "guide.rst"
    p.write_text("#######\nTitle\n#######\n\nText.\n", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    assert data["files"][0]["outline"][0]["id"] == "docs/guide:Title"


@pytest.mark.integration
def test_cli_json_section_ids_are_unique_for_duplicate_titles(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "doc.rst"
    document.write_text(
        textwrap.dedent("""\
            #######
            Title
            #######

            **********
            Repeated
            **********

            Text.

            **********
            Repeated
            **********
            """),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(document)])

    with pytest.raises(SystemExit):
        check_rst.main()

    data = json.loads(capsys.readouterr().out)
    ids = [entry["id"] for entry in data["files"][0]["outline"]]
    assert ids == ["doc:Title", "doc:Repeated", "doc:Repeated#2"]


# ---------------------------------------------------------------------------
# Ranges instead of start lines (Max, 2026-07-19): "where check_rst informs
# about the line number, it must inform the range instead, where applicable."
# Outline entries carry their extent — the exact numbers a follow-up
# sed/Read needs, previously re-derived by hand from the NEXT entry's line.
# Findings deliberately keep single-line anchors (they point AT a defect).
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_outline_section_extents(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A section's extent runs from its title line to the last content line
    before the next same-or-shallower section's block (overline included),
    trailing blank separator lines trimmed; the last section runs to EOF."""
    p = _rst(
        tmp_path,
        """\
        Root
        ####

        Intro.

        Sub A
        =====

        Body A.

        Sub B
        =====

        Body B.
        """,
    )
    entries = check_rst.build_outline(p)
    assert [(e.title, e.lineno, e.end) for e in entries] == [
        ("Root", 1, 14),
        ("Sub A", 6, 9),  # blank line 10 before Sub B trimmed
        ("Sub B", 11, 14),
    ]


@pytest.mark.integration
def test_block_quote_multiline_extent(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A multi-paragraph quote reports its full range; a single-line quote
    keeps the single-number format."""
    p = _rst(
        tmp_path,
        "Intro:\n\n    First quoted line.\n\n    Second quoted paragraph.\n\nAfter.\n",
    )
    entries = check_rst.find_block_quotes(p)
    assert len(entries) == 1
    assert (entries[0].lineno, entries[0].end) == (3, 5)
    assert str(entries[0]).startswith('3-5: blockquote "')

    single = _rst(tmp_path / "sub" if False else tmp_path, "Intro:\n\n    One line.\n")
    entries = check_rst.find_block_quotes(single)
    assert str(entries[0]) == '3: blockquote "One line."'


@pytest.mark.integration
def test_heuristic_code_block_extent(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A code-block's extent covers the directive line through the last
    indented content line."""
    p = _rst(
        tmp_path,
        "Title\n=====\n\n.. code-block:: python\n\n    x = 1\n    y = 2\n\nAfter.\n",
    )
    entries = check_rst.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert (entries[0].lineno, entries[0].end) == (4, 7)
    assert str(entries[0]) == "    4-7: code-block (python): x = 1 y = 2"


@pytest.mark.integration
def test_cli_json_outline_carries_extent(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    entry = data["files"][0]["outline"][0]
    assert entry["lineno"] == 4
    assert entry["end"] == 7


# ---------------------------------------------------------------------------
# Top prose words (Max, 2026-07-19) — the meaningful-frequency statistic the
# raw layer couldn't provide, built ONLY from existing dependencies: the
# bare-docutils doctree for prose extraction (no Sphinx build/config
# needed), sphinx.search stopword lists (en+ru+fr union, package import
# only), snowballstemmer for GROUPING (display = most frequent real
# surface form, never a stem) → Zone 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_document_prose_text_skips_code_comments_topics(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Prose is what the author wrote as text: titles and paragraphs —
    not code content, not comments, not generated topics (.. contents::)."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. contents:: Contents

        Real prose here.

        .. code:: python

            SECRETTOKEN = 1

        .. a comment HIDDENWORD

        Final paragraph.
        """,
    )
    doc = check_rst.Document(p)
    assert "Real prose here." in doc.prose_text
    assert "Title" in doc.prose_text
    assert "Final paragraph." in doc.prose_text
    assert "SECRETTOKEN" not in doc.prose_text
    assert "HIDDENWORD" not in doc.prose_text
    assert "Contents" not in doc.prose_text


@pytest.mark.integration
def test_cli_footer_top_prose_words(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Footer line 4: stopwords filtered (en/ru/fr), counts case-insensitive,
    ordered by frequency."""
    p = rst_repo / "test.rst"
    p.write_text(
        "#########\nproduct\n#########\n\n"
        "The product and the server de la maison \u0438 \u0441\u0435\u0440\u0432\u0435\u0440.\n\n"
        "product server again.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "top prose words: product (3 @2), server (2 @5)" in out
    assert "the (" not in out  # stopwords never appear


# ---------------------------------------------------------------------------
# Per-language stopword exclusion — dedicated coverage for each of the three
# languages this journal filters (2026-07-20).  The existing tests above
# pin exactly one English word ("the") and never assert Russian/French
# exclusion at all — a gap concrete enough that a documentation example
# invented three fake prose words ("when", "about", "itself") that are
# real English stopwords, and nothing caught it (docs aren't test-covered,
# but the gap this section closes is the code-level equivalent: pin
# several stopwords BY NAME per language, not just one for English and
# none for the other two).  Fixtures and expected output were captured
# against the real tool, per project doctrine — never invented.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_stopword_sets_pins_known_words_all_three_languages(
    check_rst: types.ModuleType,
) -> None:
    """Regression guard, strengthened: the single existing membership check
    ("the" in English) said nothing about Russian or French ever
    resolving to real content — pin several common words per language."""
    sets = check_rst._stopword_sets()
    assert {"the", "and", "a", "over", "again"} <= sets["en"]
    assert {"и", "в", "на"} <= sets["ru"]
    assert {"le", "la", "de", "et"} <= sets["fr"]


@pytest.mark.integration
def test_cli_footer_top_prose_words_excludes_english_stopwords(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dedicated English fixture, several distinct stopwords at once —
    the existing test above only ever excludes "the"."""
    p = rst_repo / "test.rst"
    p.write_text(
        "#########\nproduct\n#########\n\n"
        "The product and the server over the network. product server "
        "communicate again. product server run again.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "product (4 @2), server (3 @5)" in out
    # Word-boundary match: a naive substring check falsely matches inside
    # a longer word ending in the same letters — confirmed live on the
    # Russian fixture below, where a bare-substring check on the "and"
    # stopword matched inside the unrelated "data" content word.
    for stopword in ("the", "and", "over", "again"):
        assert not re.search(rf"\b{stopword} \(", out), stopword


@pytest.mark.integration
def test_cli_footer_top_prose_words_excludes_russian_stopwords(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dedicated Russian fixture — no prior test asserted a Russian
    stopword's absence by name at all.  Cyrillic via \\uXXXX escapes
    (ruff RUF001/RUF003): "sensor"/"server" are the content words
    under test; "and"/"in"/"on" are the stopwords under test."""
    title = "\u0414\u0430\u0442\u0447\u0438\u043a"  # Sensor (capitalized, as title)
    sensor = "\u0434\u0430\u0442\u0447\u0438\u043a"  # sensor
    server = "\u0441\u0435\u0440\u0432\u0435\u0440"  # server
    room = "\u043a\u043e\u043c\u043d\u0430\u0442\u0435"  # room
    works = "\u0440\u0430\u0431\u043e\u0442\u0430\u0435\u0442"  # works
    exchange = "\u043e\u0431\u043c\u0435\u043d\u0438\u0432\u0430\u044e\u0442\u0441\u044f"  # exchange
    data = "\u0434\u0430\u043d\u043d\u044b\u043c\u0438"  # data
    network = "\u0441\u0435\u0442\u0438"  # network
    and_ = "\u0438"  # and
    in_ = "\u0432"  # in
    on_ = "\u043d\u0430"  # on
    p = rst_repo / "test.rst"
    p.write_text(
        f"########\n{title}\n########\n\n"
        f"{sensor} {and_} {server} "
        f"{in_} {room}. {sensor} "
        f"{works} {on_} {server}. "
        f"{sensor} {and_} {server} "
        f"{exchange} "
        f"{data} {in_} {network}.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    # Sensor/server: content words, high frequency.
    assert f"{sensor} (4 @2), {server} (3 @5)" in out
    # Word-boundary match: a naive substring check on the "and" stopword
    # falsely matches inside the "data" content word above (which ends
    # in the same letter) — confirmed live, this is exactly why the
    # check needs a boundary, not just the other two languages' luck at
    # avoiding it.
    for stopword in (and_, in_, on_):
        assert not re.search(rf"\b{stopword} \(", out), stopword


@pytest.mark.integration
def test_cli_footer_top_prose_words_excludes_french_stopwords(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dedicated French fixture — no prior test asserted a French
    stopword's absence by name at all."""
    p = rst_repo / "test.rst"
    p.write_text(
        "#########\nCapteur\n#########\n\n"
        "Le capteur et le serveur. Le capteur fonctionne sur le serveur. "
        "Le capteur et le serveur échangent des données.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "capteur (4 @2), serveur (3 @5)" in out
    for stopword in ("le", "et", "de", "sur"):
        assert not re.search(rf"\b{stopword} \(", out), stopword


@pytest.mark.integration
def test_cli_footer_top_words_stem_grouping_shows_surface_form(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Inflections group via stemming, but the displayed word is the most
    frequent REAL surface form — never a stem."""
    p = rst_repo / "test.rst"
    # Cyrillic via escapes (ruff RUF001): Заголовок / Проблемы и проблемы
    # дают проблема.
    p.write_text(
        "#########\n\u0417\u0430\u0433\u043e\u043b\u043e\u0432\u043e\u043a\n#########\n\n"
        "\u041f\u0440\u043e\u0431\u043b\u0435\u043c\u044b \u0438 \u043f\u0440\u043e\u0431\u043b\u0435\u043c\u044b \u0434\u0430\u044e\u0442 \u043f\u0440\u043e\u0431\u043b\u0435\u043c\u0430.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "\u043f\u0440\u043e\u0431\u043b\u0435\u043c\u044b (3 @5)" in out
    assert "\u043f\u0440\u043e\u0431\u043b\u0435\u043c (" not in out.replace(
        "\u043f\u0440\u043e\u0431\u043b\u0435\u043c\u044b (", ""
    )  # no bare stems


@pytest.mark.integration
def test_cli_json_top_words(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "#########\nproduct\n#########\n\nproduct server and server product.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", "--word-samples", "10", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    top, suppressed = data["files"][0]["stats"]["top_words"]
    assert top[0] == ["product", 3]
    assert top[1] == ["server", 2]
    assert suppressed == 0


@pytest.mark.integration
def test_cli_footer_top_words_bounded_with_suppression_note(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Top-10 shown (--word-samples default), the rest counted — bounded
    output, never silent truncation (Max: 'word 1, word 2, ... (yet N
    suppressed)')."""
    p = rst_repo / "test.rst"
    nato = [
        "bravo",
        "charlie",
        "delta",
        "echo",
        "foxtrot",
        "golf",
        "hotel",
        "india",
        "juliett",
        "kilo",
        "lima",
        "mike",
        "november",
        "oscar",
        "papa",
    ]
    words = " ".join(["alpha"] * 3 + nato)
    p.write_text(f"#######\nTitle\n#######\n\n{words}.\n", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--word-samples", "10", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "top prose words: alpha (3 @" in out
    # 17 groups total (15 nato words + alpha + title), 10 shown, 7 suppressed
    assert "(yet 7 suppressed)" in out


# ---------------------------------------------------------------------------
# Rare prose words (Max, 2026-07-19) — the other extreme, in its honest
# form: the tool states deterministic facts (once-only + closest frequent
# sibling by edit similarity), the human judges typo vs morphology vs legit.
# Probed on the real downstream-project document: naive "misspelling" labeling would be
# ~80% French-morphology false positives, so the annotation is neutral.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_footer_rare_words_with_sibling_annotation(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A once-word with a frequent close sibling is annotated with the
    fact — '(~sibling Nx)' — and sorts first; plain once-words follow;
    identifier debris (mixed alphanumerics) is excluded."""
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\n"
        "The server processes data; processes run; processes wait.\n\n"
        "One procesess appears here; zebra abc123def.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "rare prose words: procesess @7 (~processes 3x)" in out
    assert "zebra" in out
    assert "abc123def" not in out  # debris filter


@pytest.mark.integration
def test_cli_footer_rare_words_bounded(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    nato = [
        "bravo",
        "charlie",
        "delta",
        "echo",
        "foxtrot",
        "golf",
        "hotel",
        "india",
        "juliett",
        "kilo",
        "lima",
        "mike",
        "november",
        "oscar",
        "papa",
        "quebec",
    ]
    p = rst_repo / "test.rst"
    p.write_text("#######\nTitle\n#######\n\n" + " ".join(nato) + ".\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--word-samples", "10", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    # 17 once-groups (16 nato + title), 10 shown, 7 suppressed
    assert "rare prose words: " in out
    line = next(ln for ln in out.splitlines() if ln.startswith("rare prose words"))
    assert "(yet 7 suppressed)" in line


@pytest.mark.integration
def test_cli_json_rare_words(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\n"
        "The server processes data; processes run; processes wait.\n\n"
        "One procesess appears.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", "--word-samples", "10", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    rare, suppressed = data["files"][0]["stats"]["rare_words"]
    assert ["procesess", "processes", 3] in rare
    assert isinstance(suppressed, int)


@pytest.mark.integration
def test_prose_grouping_detects_french_documents(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The en/fr stopword lists double as a language detector: a French
    document routes Latin tokens to the FRENCH stemmer, so inflections
    (vérifie / vérifier / vérifiée — 1sg, infinitive, participle) form ONE
    group instead of three rare words with misleading annotations (Max, on
    a downstream project's page: 'wrong language taken as a base for another
    language').  Snowball reality check: the French stemmer unifies the
    infinitive and the participle (vérifier/vérifiée -> vérifi) but stems
    the 1sg differently (vérifie -> vérif) — so the grouping proof is
    'vérifier (2)', and vérifie appears rare WITH the one-edit
    annotation (~vérifier): the edit-distance fact catches exactly the
    inflection pair the stemmer misses, and the human (who named the
    pair: 1sg and infinitive) judges it instantly."""
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitre\n#######\n\nLe serveur vérifie la connexion; il faut vérifier; elle est vérifiée.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "vérifier (2 @" in out  # infinitive+participle: ONE group of two
    rare = next(ln for ln in out.splitlines() if ln.startswith("rare prose words"))
    assert "vérifie @5 (~vérifier 2x)" in rare  # the one-edit fact fills the stemmer's gap


@pytest.mark.integration
def test_cli_rare_words_catches_the_confessed_mistake(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The journal-attested case this feature exists for: Max's habitual
    Russian mistake (one substitution) against the frequent correct form
    — missed by the 0.87 similarity cutoff (0.857), caught by the
    one-edit-apart criterion.  Cyrillic via escapes (ruff RUF001):
    померил x3, померял x1."""
    ok = "померил"  # померил
    bad = "померял"  # померял
    dav = "давление"  # давление
    p = rst_repo / "test.rst"
    p.write_text(
        f"#########\nTitle\n#########\n\n{ok} {dav}. {ok} {dav}. {ok} {dav}. {bad} {dav}.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert f"rare prose words: {bad} @5 (~{ok} 3x)" in out


@pytest.mark.integration
def test_cli_rare_words_annotates_once_vs_once_pair(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A small page's typo signature is TWO once-words one edit apart —
    fameworks/frameworks on a real 2025 note (the typo even lives in the
    linked filename).  No frequency threshold on the sibling — and the
    symmetric fact is reported ONCE, as 'a ↔ b', never as two reciprocal
    annotations (the "loop" display Max flagged)."""
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\nDetect the JS frameworks today.\n\nSee the fameworks page again.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    rare = next(ln for ln in out.splitlines() if ln.startswith("rare prose words"))
    assert "fameworks @7 \u2194 frameworks @5" in rare  # one symmetric fact, with jump targets
    assert "(~fameworks" not in rare  # no reciprocal annotation
    assert "(~frameworks" not in rare


@pytest.mark.integration
def test_prose_statistics_on_realistic_journal_note(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Modeled on calendar/2025/06/2025-06-25/Notes.rst — the reference
    note for this feature (Max: the AI reads the content and sees the
    repetitions; the tool counts).  The fixture reproduces the note's
    phenomena: trilingual prose, a :doc: role bare docutils can't
    resolve, a Sphinx code-block with :caption: and French tool output
    inside, the auto-generated toctree apparatus, and the typo pair.

    Semantic expectations (the AI's half):
    - top words are the AUTHOR's repetitions — never docutils' own
      error vocabulary ('unknown directive type', 'no role entry')
      leaking through system_message nodes: the bug this test caught
      on the real note, where top-3 was doc/directive/role;
    - code-block content (including its French wget chatter) and the
      toctree entries are not prose;
    - the typo pair surfaces as one symmetric fact."""
    ok = "кондей"  # kondej — the repeated theme word
    got_up = "встал"  # vstal
    became = "стал"  # stal
    became2 = "стало"  # stalo — same lexeme as стал, stems together
    p = rst_repo / "test.rst"
    p.write_text(
        "#########\nWednesday\n#########\n\n"
        f"{ok} работает. {ok} гудит. Чинил {ok} снова.\n\n"
        f"{got_up} рано. {became} запускать сервер. Потом {became2} тихо.\n\n"
        "Detect the JS frameworks:\n"
        ":doc:`./16-15 HTML and JS fameworks of restserver`\n\n"
        ".. code-block:: shell\n"
        "   :caption: Скачка\n\n"
        "   wget https://cdn.example.net/van.js\n"
        "   Résolution de cdn.example.net... connecté.\n\n"
        ".. toctree::\n"
        "   :maxdepth: 1\n\n"
        "   16-15 HTML and JS fameworks of restserver\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    top = next(ln for ln in out.splitlines() if ln.startswith("top prose"))
    rare = next(ln for ln in out.splitlines() if ln.startswith("rare prose"))

    # The author's repetition leads — not the parser's error vocabulary.
    assert f"top prose words: {ok} (3 @5)" in top
    for parser_noise in ("directive", "unknown", "role", "caption", "canonical"):
        assert parser_noise not in top
        assert parser_noise not in rare
    # Code-block content is not prose (its French chatter neither).
    assert "wget" not in top + rare
    assert "résolution" not in (top + rare).lower()
    # The same-lexeme pair groups (стал+стало), and the annotation shows
    # the legit-pair fact for встал.
    assert f"{got_up} @7 (~{became} 2x)" in rare
    # The typo pair: one symmetric fact (role text vs title; toctree
    # apparatus does not inflate the counts).
    assert "fameworks @10 ↔ frameworks @9" in rare


# ---------------------------------------------------------------------------
# StopwordsUnavailable (Max, 2026-07-20) — sphinx renamed the stopword
# constant's casing between the two dev hosts this project runs on
# (lowercase english_stopwords on one, uppercase ENGLISH_STOPWORDS
# re-exported from sphinx.search._stopwords on the other); _find_stopwords
# must accept either, and when NEITHER matches (sphinx moves it again),
# the failure must be explicit and counted — never a silently vanished
# footer line, which is the exact bug reported: "I don't see word
# frequency at the end of the output. Why?"
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_find_stopwords_accepts_either_known_casing(check_rst: types.ModuleType) -> None:
    uppercase_mod = types.SimpleNamespace(ENGLISH_STOPWORDS={"the", "a"})  # sphinx 9.1.0 (gl63)
    lowercase_mod = types.SimpleNamespace(english_stopwords={"the", "a"})  # sphinx 8.2.3 (this host)

    names = ("ENGLISH_STOPWORDS", "english_stopwords")
    assert check_rst._find_stopwords(uppercase_mod, names) == frozenset({"the", "a"})
    assert check_rst._find_stopwords(lowercase_mod, names) == frozenset({"the", "a"})


@pytest.mark.unit
def test_find_stopwords_raises_when_neither_name_present(
    check_rst: types.ModuleType,
) -> None:
    """A third casing (sphinx renamed it again) must raise — never
    silently return an empty set mistaken for 'no stopwords'."""
    renamed_again_mod = types.SimpleNamespace(SOME_OTHER_NAME={"the", "a"})
    renamed_again_mod.__name__ = "renamed_again_mod"

    with pytest.raises(check_rst.StopwordsUnavailable, match="renamed_again_mod"):
        check_rst._find_stopwords(renamed_again_mod, ("ENGLISH_STOPWORDS", "english_stopwords"))


@pytest.mark.unit
def test_stopword_sets_returns_nonempty_sets_for_all_three_languages(
    check_rst: types.ModuleType,
) -> None:
    """Regression guard for the reported bug: against the REAL installed
    sphinx (whichever casing it uses), _stopword_sets() must resolve —
    not silently return None."""
    sets = check_rst._stopword_sets()
    assert set(sets) == {"en", "ru", "fr"}
    assert all(sets[lang] for lang in sets)
    assert "the" in sets["en"]


@pytest.mark.unit
def test_stopword_sets_raises_when_sphinx_search_not_importable(
    check_rst: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sphinx.search unimportable must raise, not silently return None."""
    check_rst._stopword_sets.cache_clear()
    monkeypatch.setitem(sys.modules, "sphinx.search.en", None)
    try:
        with pytest.raises(check_rst.StopwordsUnavailable):
            check_rst._stopword_sets()
    finally:
        check_rst._stopword_sets.cache_clear()


@pytest.mark.unit
def test_prose_stemmers_raise_instead_of_silently_degrading(
    check_rst: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_rst._prose_stemmers.cache_clear()
    monkeypatch.setitem(sys.modules, "snowballstemmer", None)
    try:
        with pytest.raises(check_rst.WordStatsUnavailable, match="snowballstemmer"):
            check_rst._prose_stemmers()
    finally:
        check_rst._prose_stemmers.cache_clear()


@pytest.mark.integration
def test_cli_footer_explicit_warning_when_stopwords_unavailable(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The footer must say so explicitly and count it as a warning — never
    silently omit the top/rare prose words lines with zero trace.  The
    warning must also land in Line 1's own count (computed ahead of that
    print), not just appear after it already printed 0."""
    p = rst_repo / "test.rst"
    p.write_text("#######\nTitle\n#######\n\nSome prose words here.\n", encoding="utf-8")

    def _boom() -> dict[str, set[str]]:
        raise check_rst.StopwordsUnavailable("sphinx.search.en has neither X nor Y")

    monkeypatch.setattr(check_rst, "_stopword_sets", _boom)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit) as exc_info:
        check_rst.main()
    assert exc_info.value.code == 0  # a broken cosmetic stat must not fail the run
    out = capsys.readouterr().out
    assert "WARNING: top/rare prose words unavailable — sphinx.search.en has neither X nor Y" in out
    assert "top prose words:" not in out
    assert "rare prose words:" not in out
    summary = next(ln for ln in out.splitlines() if ln.startswith("check_rst:"))
    assert "1 warning(s)" in summary


@pytest.mark.integration
def test_cli_json_word_stats_error_when_stopwords_unavailable(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--json gets the same explicit, counted failure: null stats plus a
    named reason, never a bare null with no way to tell why."""
    p = rst_repo / "test.rst"
    p.write_text("#######\nTitle\n#######\n\nSome prose words here.\n", encoding="utf-8")

    def _boom() -> dict[str, set[str]]:
        raise check_rst.StopwordsUnavailable("sphinx.search.en has neither X nor Y")

    monkeypatch.setattr(check_rst, "_stopword_sets", _boom)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", "--word-samples", "10", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    stats = data["files"][0]["stats"]
    assert stats["top_words"] is None
    assert stats["rare_words"] is None
    assert "sphinx.search.en has neither X nor Y" in stats["word_stats_error"]


@pytest.mark.integration
def test_cli_no_warnings_suppresses_word_stats_failure_warning(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    document.write_text(_GOOD_BLOCK + "\nSome prose words here.\n", encoding="utf-8")

    def _boom() -> dict[str, set[str]]:
        raise check_rst.StopwordsUnavailable("unavailable for test")

    monkeypatch.setattr(check_rst, "_stopword_sets", _boom)
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "check", "--quiet", "--no-warnings", "--word-samples", "10", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "top/rare prose words unavailable" not in out
    assert "0 warning(s)" in out


# ---------------------------------------------------------------------------
# Semantic diffs between two --json dumps (2026-07-22) — logged
# 2026-07-18, independently re-confirmed 2026-07-21 by a real downstream-project
# session: "several times this session I rewrote a whole file... and had
# to manually eyeball 'same warning count, same categories as before'
# rather than get a machine answer."  Matches files by path, outline
# entries by their stable docname:title id (built for exactly this),
# findings by (severity, text) — never by line number, which drifts with
# any unrelated edit.
# ---------------------------------------------------------------------------


def _json_dump(
    path: str = "doc.rst",
    outline: list[dict[str, Any]] | None = None,
    findings: list[dict[str, Any]] | None = None,
    files_checked: int = 1,
    errors: int = 0,
    warnings: int = 0,
    sphinx_findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a minimal --json-shaped dict for _diff_json_dumps tests —
    only the fields the diff actually reads."""
    data = {
        "files": [{"path": path, "outline": outline or [], "findings": findings or []}],
        "summary": {"files_checked": files_checked, "errors": errors, "warnings": warnings},
    }
    if sphinx_findings is not None:
        data["sphinx_findings"] = sphinx_findings
    return data


@pytest.mark.unit
def test_diff_json_dumps_summary_deltas(check_rst: types.ModuleType) -> None:
    old = _json_dump(warnings=74)
    new = _json_dump(warnings=95)
    diff = check_rst._diff_json_dumps(old, new)
    assert diff["summary"]["warnings"] == {"old": 74, "new": 95, "delta": 21}
    assert diff["summary"]["errors"] == {"old": 0, "new": 0, "delta": 0}


@pytest.mark.unit
def test_diff_json_dumps_outline_added_section_hierarchy_unchanged(
    check_rst: types.ModuleType,
) -> None:
    """The doc's own worked example: 'added subsection, hierarchy
    unchanged' — a new section id appears, but every surviving section
    keeps its (depth, char)."""
    old = _json_dump(
        outline=[
            {"id": "doc:Title", "depth": 1, "char": "#", "title": "Title"},
            {"id": "doc:Sub", "depth": 2, "char": "*", "title": "Sub"},
        ]
    )
    new = _json_dump(
        outline=[
            {"id": "doc:Title", "depth": 1, "char": "#", "title": "Title"},
            {"id": "doc:Sub", "depth": 2, "char": "*", "title": "Sub"},
            {"id": "doc:New", "depth": 2, "char": "*", "title": "New"},
        ]
    )
    diff = check_rst._diff_json_dumps(old, new)
    file_diff = diff["files"]["doc.rst"]
    assert file_diff["outline"]["added"] == ["doc:New"]
    assert file_diff["outline"]["removed"] == []
    assert file_diff["outline"]["hierarchy_changed"] == []
    assert file_diff["status"] == "changed"


@pytest.mark.unit
def test_diff_json_dumps_hierarchy_changed_flags_the_id(
    check_rst: types.ModuleType,
) -> None:
    """A surviving section that changed depth or char is named, not just
    flagged true/false — the reader needs to know WHICH one."""
    old = _json_dump(outline=[{"id": "doc:Sub", "depth": 2, "char": "*", "title": "Sub"}])
    new = _json_dump(outline=[{"id": "doc:Sub", "depth": 3, "char": "=", "title": "Sub"}])
    diff = check_rst._diff_json_dumps(old, new)
    assert diff["files"]["doc.rst"]["outline"]["hierarchy_changed"] == ["doc:Sub"]


@pytest.mark.unit
def test_diff_json_dumps_findings_added_and_resolved_matched_by_severity_and_text(
    check_rst: types.ModuleType,
) -> None:
    """Findings match on (severity, text), NOT line number — a finding
    that merely shifted lines because of an unrelated earlier edit must
    not appear as both resolved and added."""
    old = _json_dump(
        findings=[
            {"lineno": 10, "severity": "WARNING", "text": "bold paragraph opener 'Foo'"},
            {"lineno": 20, "severity": "WARNING", "text": "bold paragraph opener 'Gone'"},
        ]
    )
    new = _json_dump(
        findings=[
            {"lineno": 15, "severity": "WARNING", "text": "bold paragraph opener 'Foo'"},  # shifted, not new
            {"lineno": 30, "severity": "WARNING", "text": "bold paragraph opener 'New'"},
        ]
    )
    diff = check_rst._diff_json_dumps(old, new)
    findings = diff["files"]["doc.rst"]["findings"]
    assert findings["added"] == [{"severity": "WARNING", "text": "bold paragraph opener 'New'"}]
    assert findings["resolved"] == [{"severity": "WARNING", "text": "bold paragraph opener 'Gone'"}]


@pytest.mark.unit
def test_diff_json_dumps_compares_sphinx_findings_even_when_counts_cancel(
    check_rst: types.ModuleType,
) -> None:
    """One resolved and one added Sphinx warning must not look unchanged."""
    old = _json_dump(
        warnings=1,
        sphinx_findings=[{"lineno": 4, "severity": "WARNING", "text": "doc.rst: old warning"}],
    )
    new = _json_dump(
        warnings=1,
        sphinx_findings=[{"lineno": 8, "severity": "WARNING", "text": "doc.rst: new warning"}],
    )

    diff = check_rst._diff_json_dumps(old, new)

    assert diff["sphinx_findings"]["added"] == [{"severity": "WARNING", "text": "doc.rst: new warning"}]
    assert diff["sphinx_findings"]["resolved"] == [{"severity": "WARNING", "text": "doc.rst: old warning"}]
    assert "new warning" in check_rst._format_json_diff(diff)


@pytest.mark.unit
def test_diff_json_dumps_reports_runtime_provenance_change(
    check_rst: types.ModuleType,
) -> None:
    old = _json_dump()
    old.update(
        {
            "schema_version": 1,
            "mode": "verified",
            "runtime": {"sphinx": {"version": "8.2.3"}},
        }
    )
    new = _json_dump()
    new.update(
        {
            "schema_version": 1,
            "mode": "verified",
            "runtime": {"sphinx": {"version": "9.1.0"}},
        }
    )

    diff = check_rst._diff_json_dumps(old, new)

    assert "runtime" in diff["provenance"]["changed"]
    assert "provenance differs" in check_rst._format_json_diff(diff)


@pytest.mark.unit
def test_diff_json_dumps_unchanged_file_reports_unchanged_status(
    check_rst: types.ModuleType,
) -> None:
    same = _json_dump(outline=[{"id": "doc:T", "depth": 1, "char": "#", "title": "T"}])
    diff = check_rst._diff_json_dumps(same, same)
    assert diff["files"]["doc.rst"]["status"] == "unchanged"


@pytest.mark.unit
def test_diff_json_dumps_added_and_removed_files(check_rst: types.ModuleType) -> None:
    old = _json_dump(path="a.rst")
    new = _json_dump(path="b.rst")
    diff = check_rst._diff_json_dumps(old, new)
    assert diff["files"]["a.rst"] == {"status": "removed"}
    assert diff["files"]["b.rst"] == {"status": "added"}


@pytest.mark.integration
def test_cli_diff_json_end_to_end(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """End to end: two real --json dumps, one edit apart, compared via
    --diff-json — the report names the added finding and the summary
    delta, no manual eyeballing of two large JSON blobs required."""
    p = rst_repo / "test.rst"
    p.write_text("#######\nTitle\n#######\n\n**A point.**  Detail.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    old_json = capsys.readouterr().out
    (rst_repo / "old.json").write_text(old_json, encoding="utf-8")

    p.write_text(
        "#######\nTitle\n#######\n\n**A point.**  Detail.\n\n**Another point.**  More.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    new_json = capsys.readouterr().out
    (rst_repo / "new.json").write_text(new_json, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "diff-json", str(rst_repo / "old.json"), str(rst_repo / "new.json")],
    )
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "warnings" in out
    assert "1" in out
    assert "2" in out
    assert "Another point" in out


@pytest.mark.integration
def test_cli_diff_json_missing_file_errors_cleanly(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "diff-json", str(tmp_path / "missing1.json"), str(tmp_path / "missing2.json")],
    )
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "missing1.json" in out


@pytest.mark.integration
@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("not JSON", "invalid JSON"),
        ("[]", "top level must be an object"),
        ("{}", "missing required key"),
        ('{"files": [], "summary": {}}', "summary missing"),
    ],
)
def test_cli_diff_json_rejects_malformed_or_wrong_schema_cleanly(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    content: str,
    message: str,
) -> None:
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text(content, encoding="utf-8")
    new.write_text(json.dumps(_json_dump()), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "diff-json", str(old), str(new)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert message in out
    assert "Traceback" not in out


# ---------------------------------------------------------------------------
# Admonition entries in --outline (2026-07-22) — found live: a ".. important::"
# tl;dr this project itself wrote for check_rst.rst was completely invisible
# to --outline, even though docutils parses it perfectly fine (confirmed by
# direct probe: docutils.nodes.important at the exact line, just no
# corresponding outline entry kind).  docutils.nodes.Admonition covers all 10
# kinds uniformly (attention/caution/danger/error/important/note/tip/hint/
# warning/admonition) — bare docutils only, no verified/heuristic split, same
# as blockquotes and tables.  Only the generic ".. admonition:: Title" form
# carries an explicit title (a caption, same role as a table's); the other
# nine have none.  Counted in the blocks: legend and every section's
# cumulative bracket count, same as code-blocks/blockquotes/tables (Max:
# "we need to include them in the statistics: total, by section").
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_admonitions_named_kind_no_title(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. important::

           If you read nothing else: check the outline first.
        """,
    )
    entries = check_rst.find_admonitions(p)
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == "important"
    assert e.title is None
    assert e.preview == "If you read nothing else: check the outline first."
    assert e.lineno == 4  # the directive's own line


@pytest.mark.integration
def test_admonitions_generic_form_carries_a_title(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. admonition:: Custom Title

           Body text, custom kind.
        """,
    )
    entries = check_rst.find_admonitions(p)
    assert len(entries) == 1
    assert entries[0].kind == "admonition"
    assert entries[0].title == "Custom Title"
    assert entries[0].preview == "Body text, custom kind."


@pytest.mark.integration
def test_admonitions_all_ten_kinds_recognized(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_admonitions(p)
    assert [e.kind for e in entries] == kinds


@pytest.mark.integration
def test_admonitions_preview_collapsed_and_truncated(check_rst: types.ModuleType, tmp_path: Path) -> None:
    long_body = " ".join(f"word{i}" for i in range(30))
    p = _rst(
        tmp_path,
        f"Title\n=====\n\n.. note::\n\n   {long_body}\n",
    )
    preview = check_rst.find_admonitions(p)[0].preview
    assert preview.endswith("...")
    assert len(preview) <= check_rst._OUTLINE_PREVIEW_LEN + 3


@pytest.mark.integration
def test_admonitions_depth_counts_enclosing_sections(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    e = check_rst.find_admonitions(p)[0]
    assert e.depth == 3  # Root=1, Sub=2, admonition=3 — same convention as tables


@pytest.mark.integration
def test_cli_outline_admonitions_counted_in_blocks_legend_and_section_brackets(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "Title\n#####\n\n.. important::\n\n   Read this.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "blocks: 1 admonition" in out
    assert "[1 admonition]" in out  # the enclosing Title section's own bracket count
    assert "admonition (important): Read this." in out


@pytest.mark.integration
def test_cli_json_admonitions(
    check_rst: types.ModuleType,
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
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    admonitions = data["files"][0]["admonitions"]
    assert len(admonitions) == 1
    assert admonitions[0]["kind"] == "admonition"
    assert admonitions[0]["title"] == "Custom"
    assert admonitions[0]["preview"] == "Body."


# ---------------------------------------------------------------------------
# Comment entries in --outline (2026-07-22) — the mistyped-directive WARNING
# (a comment whose first line matches a KNOWN directive name + single colon)
# can only ever catch what it recognizes: a typo of an unlisted name, or one
# buried past the first line, stays invisible to that heuristic (Max: "we
# cannot cover all cases... they could be more complex cases").  Making every
# comment visible in --outline, same as blockquotes/admonitions/tables, closes
# that blind spot generically instead of chasing more regex cases — the
# WARNING itself is unchanged, but now sits next to the comment's own text
# instead of being the only signal.  suspicious reuses that exact same
# heuristic so the two views agree.  Bare docutils only, no verified/
# heuristic split, same as blockquotes/admonitions/tables.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_comments_found_with_preview_and_depth(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. An ordinary comment, not a directive typo.
        """,
    )
    entries = check_rst.find_comments(p)
    assert len(entries) == 1
    e = entries[0]
    assert e.preview == "An ordinary comment, not a directive typo."
    assert e.lineno == 4  # the comment's own line
    assert e.depth == 2  # Title=1, comment=2
    assert e.suspicious is False


@pytest.mark.integration
def test_comments_no_preceding_heading_is_depth_1(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Same top-level convention as
    test_heuristic_code_blocks_no_preceding_heading_is_depth_1 and
    test_block_quotes_no_preceding_heading_is_depth_1."""
    p = _rst(tmp_path, ".. A comment with no enclosing section at all.\n")
    entries = check_rst.find_comments(p)
    assert len(entries) == 1
    assert entries[0].depth == 1


@pytest.mark.integration
def test_comments_preview_collapsed_and_truncated(check_rst: types.ModuleType, tmp_path: Path) -> None:
    long_body = " ".join(f"word{i}" for i in range(30))
    p = _rst(tmp_path, f"Title\n=====\n\n.. {long_body}\n")
    preview = check_rst.find_comments(p)[0].preview
    assert preview.endswith("...")
    assert len(preview) <= check_rst._OUTLINE_PREVIEW_LEN + 3


@pytest.mark.integration
def test_comments_suspicious_flag_true_for_known_directive_typo(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Same heuristic as the Phase 1 WARNING (_MISTYPED_DIRECTIVE_RE +
    _KNOWN_DIRECTIVE_NAMES) — a single-colon '.. code: bash' is flagged
    suspicious right where its text is shown."""
    p = _rst(tmp_path, "Text.\n\n.. code: bash\n\n    pandoc --from gfm\n")
    e = check_rst.find_comments(p)[0]
    assert e.suspicious is True
    assert "suspicious" in str(e)


@pytest.mark.integration
def test_comments_suspicious_flag_false_for_todo_comment(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """'todo' is deliberately excluded from the heuristic (too common a
    genuine idiom) — the comment is still visible, just not tagged."""
    p = _rst(tmp_path, ".. TODO: fix this later\n")
    e = check_rst.find_comments(p)[0]
    assert e.suspicious is False
    assert "suspicious" not in str(e)


@pytest.mark.integration
def test_cli_outline_comments_counted_in_blocks_legend_and_section_brackets(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "Title\n#####\n\n.. code: bash\n\n    echo hi\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "blocks: 1 comment" in out
    assert "[1 comment]" in out  # the enclosing Title section's own bracket count
    assert "suspicious" in out


@pytest.mark.integration
def test_cli_json_comments(
    check_rst: types.ModuleType,
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
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    comments = data["files"][0]["comments"]
    assert len(comments) == 1
    assert comments[0]["preview"] == "An ordinary comment."
    assert comments[0]["suspicious"] is False


# ---------------------------------------------------------------------------
# ListEntry — bullet/enumerated/definition lists in --outline (Max,
# 2026-07-26).  Two-level for bullet/enumerated: a CONTAINER entry for the
# whole list (item_count set) and one entry per ITEM nested one level
# deeper, so --outline-depth can hide a long list's items while keeping the
# list's own existence and count visible.  Definition lists are flatter (Max:
# "one entry per item") — each definition_list_item stands alone, marker is
# its own term text, no container.  Bare docutils, no verified/heuristic
# split, same as blockquotes/admonitions/tables/comments.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_lists_bullet_container_and_items(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_lists(p)
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
def test_lists_bullet_marker_reflects_actual_bullet_char(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n=====\n\n- One.\n- Two.\n")
    entries = check_rst.find_lists(p)
    assert all(e.marker == "-" for e in entries)


@pytest.mark.integration
def test_lists_enumerated_arabic_markers(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n=====\n\n1. One.\n2. Two.\n3. Three.\n")
    entries = check_rst.find_lists(p)
    container, *items = entries
    assert container.kind == "enumerated"
    assert container.marker == "1."
    assert container.item_count == 3
    assert [i.marker for i in items] == ["1.", "2.", "3."]


@pytest.mark.integration
def test_lists_enumerated_auto_number(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """'#.' auto-numbering renders as plain arabic digits — docutils never
    stores '#' as the item's own marker, only enumtype='arabic'."""
    p = _rst(tmp_path, "Title\n=====\n\n#. One.\n#. Two.\n")
    entries = check_rst.find_lists(p)
    _container, *items = entries
    assert [i.marker for i in items] == ["1.", "2."]


@pytest.mark.integration
def test_lists_enumerated_alpha_markers(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n=====\n\na) First.\nb) Second.\n")
    entries = check_rst.find_lists(p)
    _container, *items = entries
    assert [i.marker for i in items] == ["a)", "b)"]


@pytest.mark.integration
def test_lists_definition_items_standalone_no_container(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_lists(p)
    assert len(entries) == 2  # no container entry, unlike bullet/enumerated
    assert [e.kind for e in entries] == ["definition", "definition"]
    assert [e.marker for e in entries] == ["Term One", "Term Two"]
    assert [e.preview for e in entries] == [
        "Definition of term one.",
        "Definition of term two.",
    ]
    assert all(e.item_count is None for e in entries)


@pytest.mark.integration
def test_lists_nested_bullet_list_depth_increments(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_lists(p)
    by_lineno = {e.lineno: e for e in entries if e.item_count is not None}
    outer_container = by_lineno[4]
    inner_container = by_lineno[6]
    assert outer_container.depth == 2
    assert inner_container.depth == 4  # outer item (3) + 1, not outer container (2) + 1


@pytest.mark.integration
def test_lists_item_extent_includes_continuation_paragraph(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_lists(p)
    items = {e.lineno: e for e in entries if e.item_count is None}
    assert items[5].end == 7  # "Second item." through its continuation paragraph
    assert items[4].end == 4  # single-line item, no continuation


@pytest.mark.integration
def test_lists_preview_collapsed_and_truncated(check_rst: types.ModuleType, tmp_path: Path) -> None:
    long_text = " ".join(f"word{i}" for i in range(30))
    p = _rst(tmp_path, f"Title\n=====\n\n* {long_text}\n")
    _container, item = check_rst.find_lists(p)
    assert item.preview.endswith("...")
    assert len(item.preview) <= check_rst._OUTLINE_PREVIEW_LEN + 3


@pytest.mark.integration
def test_cli_outline_lists_counted_in_blocks_legend_and_section_brackets(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text("Title\n#####\n\n* One.\n* Two.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "blocks: 1 list" in out
    assert "[1 list]" in out  # the enclosing Title section's own bracket count
    assert "bullet list ('*', 2 items)" in out


@pytest.mark.integration
def test_cli_outline_depth_hides_list_items_keeps_container(
    check_rst: types.ModuleType,
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
        ["check_rst.py", "outline", "--with-findings", "--quiet", "--outline-depth", "2", str(p)],
    )
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "bullet list" in out
    assert "One." not in out
    assert "deeper entr" in out  # hidden-entries note, never silent truncation


# ---------------------------------------------------------------------------
# --sections-only (Max, 2026-07-22 idea, implemented 2026-07-26) — filters by
# KIND, not depth: every leaf entry kind is suppressed regardless of how
# shallow it sits, unlike --outline-depth which bounds by depth regardless of
# kind.  A display filter: the levels:/blocks: legend and every heading's own
# bracketed counts still reflect the whole document either way.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_sections_only_hides_leaf_entries_keeps_headings(
    check_rst: types.ModuleType,
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
        "sys.argv", ["check_rst.py", "outline", "--with-findings", "--quiet", "--sections-only", str(p)]
    )
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "Title" in out
    assert "bullet list" not in out
    assert "One." not in out
    assert "code-block" not in out


@pytest.mark.integration
def test_cli_sections_only_keeps_bracket_counts_and_legend(
    check_rst: types.ModuleType,
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
        ["check_rst.py", "outline", "--with-findings", "--quiet", "--verbose", "--sections-only", str(p)],
    )
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "[1 list]" in out
    assert "blocks: 1 list" in out


@pytest.mark.integration
def test_cli_sections_only_hidden_note_wording(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A kind-filtered entry isn't necessarily 'deeper', so the note drops
    that word specifically when --sections-only is involved."""
    p = rst_repo / "test.rst"
    p.write_text("Title\n#####\n\n* One.\n* Two.\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv", ["check_rst.py", "outline", "--with-findings", "--quiet", "--sections-only", str(p)]
    )
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "entries hidden — --sections-only" in out
    assert "deeper entr" not in out


@pytest.mark.integration
def test_cli_sections_only_composes_with_outline_depth(
    check_rst: types.ModuleType,
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
        ["check_rst.py", "outline", "--with-findings", "--quiet", "--sections-only", "--outline-depth", "1", str(p)],
    )
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "Title" in out
    assert "Sub" not in out  # depth 2, cut by --outline-depth 1
    assert "bullet list" not in out  # cut by --sections-only
    assert "--outline-depth 1" in out
    assert "--sections-only" in out


@pytest.mark.integration
def test_cli_sections_only_works_with_outline_only(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text("Title\n#####\n\n* One.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--sections-only", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "Title" in out
    assert "bullet list" not in out


@pytest.mark.integration
def test_cli_json_lists(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text("Title\n#####\n\n* One.\n* Two.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    lists = data["files"][0]["lists"]
    assert len(lists) == 3  # 1 container + 2 items
    assert lists[0]["kind"] == "bullet"
    assert lists[0]["item_count"] == 2


# ---------------------------------------------------------------------------
# Block depth must account for enclosing LIST nesting, not just sections
# (Max, 2026-07-26, real output evaluation) — found live: a list-table added
# inside a bullet item (this very page's own "Nested inline markup
# detection" example) printed at the SAME depth as the bullet list
# container itself, sandwiched between two sibling items, because
# find_tables' depth walk only ever counted enclosing `section` ancestors —
# a fact that was harmless before ListEntry existed (nothing else tracked
# "inside a list item" as its own depth level) but became visibly
# inconsistent once ListEntry's own _block_depth started counting
# bullet_list/enumerated_list/definition_list/list_item too.  Fixed by
# routing every depth-computing finder through the SAME _block_depth
# ListEntry already uses — identical to the old section-only walk whenever
# there is no enclosing list (every existing depth test above stays
# unchanged), only correcting the case that was actually wrong.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_admonitions_depth_accounts_for_enclosing_list_item(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    e = check_rst.find_admonitions(p)[0]
    assert e.depth == 4  # Title=1, bullet list=2, item=3, admonition=4


@pytest.mark.integration
def test_block_quotes_depth_accounts_for_enclosing_list_item(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    e = check_rst.find_block_quotes(p)[0]
    assert e.depth == 4  # Title=1, bullet list=2, item=3, blockquote=4


@pytest.mark.integration
def test_comments_depth_accounts_for_enclosing_list_item(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        * Item one.

          .. A nested comment inside a list item.
        """,
    )
    e = check_rst.find_comments(p)[0]
    assert e.depth == 4  # Title=1, bullet list=2, item=3, comment=4


@pytest.mark.integration
def test_tables_depth_accounts_for_enclosing_list_item(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    e = check_rst.find_tables(p)[0]
    assert e.depth == 4  # Title=1, bullet list=2, item=3, table=4


@pytest.mark.integration
def test_heuristic_code_blocks_depth_ignores_enclosing_list_item(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    e = check_rst.find_code_blocks_heuristic(p)[0]
    assert e.depth == 2


@pytest.mark.integration
def test_code_blocks_depth_accounts_for_enclosing_list_item(
    check_rst: types.ModuleType, build_sphinx_env: Callable[[str], tuple[object, str]]
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
    entries = check_rst.find_code_blocks(env, docname)
    assert len(entries) == 1
    assert entries[0].depth == 4  # Title=1, bullet list=2, item=3, code-block=4


# ---------------------------------------------------------------------------
# Table entries in --outline (Max, 2026-07-20) — a real Sphinx build adds NO
# table-type information (confirmed directly: grid, simple, and the table/
# list-table/csv-table directives all produce an identical <table><tgroup>
# doctree shape), so find_tables is bare-docutils only, no verified/
# heuristic split — kind is recovered by scanning the raw source, the one
# place that fact still exists.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_tables_list_table_with_caption_and_header(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. list-table:: Quarterly Numbers
           :header-rows: 1

           * - Quarter
             - Revenue
           * - Q1
             - 100
        """,
    )
    entries = check_rst.find_tables(p)
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == "list"
    assert e.caption == "Quarterly Numbers"
    assert e.dims == (2, 2)
    assert e.preview == "Quarter Revenue Q1 100"  # both rows chained, header first
    assert e.lineno == 4  # the directive's own line


@pytest.mark.integration
def test_tables_grid_table_no_caption(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A bare grid table has no directive at all — kind and the true start
    (the TOP border, not the header content row the AST itself locates)
    both come from scanning the raw source."""
    p = _rst(
        tmp_path,
        "Title\n=====\n\n+-----+-----+\n| G1  | G2  |\n+=====+=====+\n| x   | y   |\n+-----+-----+\n",
    )
    entries = check_rst.find_tables(p)
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == "grid"
    assert e.caption is None
    assert e.dims == (2, 2)
    assert e.preview == "G1 G2 x y"  # both rows chained, header first
    assert (e.lineno, e.end) == (4, 8)


@pytest.mark.integration
def test_tables_simple_table_no_caption(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        "Title\n=====\n\n=====  =====\nA      B\n=====  =====\n1      2\n=====  =====\n",
    )
    entries = check_rst.find_tables(p)
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == "simple"
    assert e.caption is None
    assert e.dims == (2, 2)
    assert e.preview == "A B 1 2"  # both rows chained, header first
    assert (e.lineno, e.end) == (4, 8)


@pytest.mark.integration
def test_tables_table_directive_wraps_simple_table(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """'.. table:: Caption' is docutils' own directive for a captioned
    grid/simple table — distinct from Sphinx's list-table/csv-table."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. table:: Simple Wrapped

           =====  =====
           Col1   Col2
           =====  =====
           v1     v2
           =====  =====
        """,
    )
    entries = check_rst.find_tables(p)
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == "table"
    assert e.caption == "Simple Wrapped"
    assert e.dims == (2, 2)
    assert e.lineno == 4


@pytest.mark.integration
def test_tables_csv_table_detected(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_tables(p)
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == "csv"
    assert e.caption == "CSV Caption"
    assert e.dims == (2, 2)
    assert e.preview == "H1 H2 a b"  # both rows chained, header first


@pytest.mark.integration
def test_tables_headerless_chains_all_rows(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_tables(p)
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == "list"  # recovered via the indentation scan, no caption needed
    assert e.caption is None
    assert e.preview == "a b c d"


@pytest.mark.integration
def test_tables_end_extends_through_multiline_final_row(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_tables(p)
    assert len(entries) == 1
    assert (entries[0].lineno, entries[0].end) == (4, 11)


@pytest.mark.unit
def test_table_end_stops_at_closing_border_not_past_it(check_rst: types.ModuleType) -> None:
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
    assert check_rst._table_end(lines, last_content_line=4) == 5


@pytest.mark.integration
def test_tables_depth_matches_enclosing_section(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_tables(p)
    assert len(entries) == 1
    assert entries[0].depth == 3  # Chapter One=1, Sub A=2, table=3


@pytest.mark.integration
def test_tables_str_format_with_caption(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    entries = check_rst.find_tables(p)
    assert str(entries[0]) == '    4-10: Table (list, 2x2), "My Caption": A B x y'


@pytest.mark.integration
def test_tables_str_format_no_caption(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Without a caption, the '"caption"' clause is omitted entirely —
    same optional-clause contract as code-block's preview."""
    p = _rst(tmp_path, "Title\n=====\n\n=====  =====\nA      B\n=====  =====\n")
    entries = check_rst.find_tables(p)
    assert str(entries[0]) == "    4-6: Table (simple, 1x2): A B"


@pytest.mark.integration
def test_tables_preview_whitespace_collapsed_and_truncated(check_rst: types.ModuleType, tmp_path: Path) -> None:
    long_header = " ".join(f"Column{i}   with   extra   spaces" for i in range(6))
    p = _rst(
        tmp_path,
        f"Title\n=====\n\n.. list-table::\n   :header-rows: 1\n\n   * - {long_header}\n   * - x\n",
    )
    entries = check_rst.find_tables(p)
    assert len(entries) == 1
    preview = entries[0].preview
    assert "  " not in preview  # no doubled internal spaces
    assert not preview.startswith(" ")
    assert preview.endswith("...")
    assert len(preview) <= 77


@pytest.mark.integration
def test_tables_preview_chains_many_short_rows_then_truncates(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Many rows of short cells chain into ONE line ('A1 A2 A3 B1 B2 B3
    C1 C2 C3 ...', Max, 2026-07-20) before the 74-char/'...' bound ever
    kicks in — confirms truncation is a property of the WHOLE chained
    preview, not of any single row."""
    rows = "".join(f"   * - {r}1\n     - {r}2\n     - {r}3\n" for r in "ABCDEFGHIJ")
    p = _rst(tmp_path, f"Title\n=====\n\n.. list-table::\n   :header-rows: 0\n\n{rows}")
    entries = check_rst.find_tables(p)
    assert len(entries) == 1
    preview = entries[0].preview
    assert preview.startswith("A1 A2 A3 B1 B2 B3 C1 C2 C3")
    assert preview.endswith("...")
    assert len(preview) <= 77


@pytest.mark.integration
def test_cli_outline_blocks_summary_includes_tables(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "Root\n####\n\n=====  =====\nA      B\n=====  =====\n1      2\n=====  =====\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "blocks: 1 table" in out


@pytest.mark.integration
def test_cli_outline_section_bracket_cumulative_tables(
    check_rst: types.ModuleType,
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
        check_rst.main()
    out = capsys.readouterr().out
    root_line = next(ln for ln in out.splitlines() if "Root" in ln)
    assert "[1 subsection, 1 table]" in root_line


@pytest.mark.integration
def test_cli_json_tables(
    check_rst: types.ModuleType,
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
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    tables = data["files"][0]["tables"]
    assert len(tables) == 1
    assert tables[0]["kind"] == "simple"
    assert tables[0]["dims"] == [2, 2]
    assert tables[0]["preview"] == "A B 1 2"


# ---------------------------------------------------------------------------
# --context ENTRY — a targeted pre-edit briefing for every outline entry kind.
# Semantic exact matches are convenient; a generated selector makes even an
# otherwise anonymous entry addressable.  Resolution must consume the same
# heterogeneous stream as --outline without a closed entry-kind whitelist.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_context_resolver_accepts_future_entry_kind_without_registration(
    check_rst: types.ModuleType,
) -> None:
    @dataclass(frozen=True)
    class FutureWidgetEntry:
        lineno: int
        depth: int
        label: str
        end: int

    entry = FutureWidgetEntry(12, 2, "Opaque widget", 15)

    matches = check_rst._resolve_context_matches([entry], "Opaque widget", "guide")

    assert len(matches) == 1
    assert matches[0].entry is entry
    assert matches[0].kind == "future widget"
    assert matches[0].selector == "guide:future-widget@12"


@pytest.mark.integration
def test_cli_context_list_item_reports_parent_path_and_adjacent_siblings(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\n* First item.\n* Target item.\n* Third item.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "context", "Target item.", str(p)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "kind: bullet item" in out
    assert "selector: test:bullet-item@6" in out
    assert "range: 6" in out
    assert "path:" in out
    assert 'section "Title"' in out
    assert "bullet list" in out
    assert "parent: test:bullet-list@5" in out
    assert "previous: test:bullet-item@5" in out
    assert "next: test:bullet-item@7" in out
    assert "children:\n  (none)" in out
    assert "references:\n  unavailable — verified Sphinx mode required" in out


@pytest.mark.integration
def test_cli_context_section_stable_id_and_applicable_finding(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\n********\nTarget\n********\n\n**Decision**\n\nDetails.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "context", "test:Target", str(p)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "kind: section" in out
    assert "selector: test:Target" in out
    assert "range: 6-11" in out
    assert "findings:" in out
    assert "standalone bold line 'Decision'" in out


@pytest.mark.integration
def test_cli_context_ambiguous_exact_match_lists_candidates_without_guessing(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\n* Repeat.\n* Repeat.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "context", "Repeat.", str(p)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "ambiguous: 2 exact matches" in out
    assert "candidates:" in out
    assert "test:bullet-item@5" in out
    assert "test:bullet-item@6" in out
    assert "Context:" not in out


@pytest.mark.integration
def test_cli_context_ambiguous_candidates_are_bounded_without_silent_truncation(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    items = "".join("* Repeat.\n" for _ in range(25))
    p.write_text(f"#######\nTitle\n#######\n\n{items}", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "context", "Repeat.", str(p)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "ambiguous: 25 exact matches" in out
    assert out.count(" — path:") == 20
    assert "(5 more candidates suppressed)" in out


@pytest.mark.integration
def test_cli_context_universal_selector_addresses_anonymous_container(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\n* First.\n* Second.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "context", "test:bullet-list@5", str(p)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "kind: bullet list" in out
    assert "selector: test:bullet-list@5" in out
    assert "children:" in out
    assert "test:bullet-item@5" in out
    assert "test:bullet-item@6" in out


@pytest.mark.integration
def test_cli_context_requires_exactly_one_positional_file(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Under the subcommand redesign, context's parser defines exactly two
    positionals (ENTRY, FILE) — a third one is now an ordinary argparse
    "unrecognized arguments" (exit 2, message on stderr), not this
    project's own logic to pin down (that logic still checks the one
    surviving value rule — the file must end in .rst — see
    test_context_verb_rejects_empty_entry's sibling assertions in
    tests/test_cli_subcommands.py)."""
    one = rst_repo / "one.rst"
    two = rst_repo / "two.rst"
    one.write_text("Title\n=====\n", encoding="utf-8")
    two.write_text("Title\n=====\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "context", "Title", str(one), str(two)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


@pytest.mark.integration
def test_cli_context_verified_references_are_scoped_to_selected_entry(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    index = tmp_path / "index.rst"
    index.write_text(
        "Index\n=====\n\nSee :doc:`target`.\n",
        encoding="utf-8",
    )
    target = tmp_path / "target.rst"
    target.write_text(
        "Target\n======\n\nOutside\n-------\n\nSee :doc:`outside`.\n\nDetails\n-------\n\nSee :doc:`index`.\n",
        encoding="utf-8",
    )
    (tmp_path / "outside.rst").write_text("Outside\n=======\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(tmp_path), "context", "target:Details", str(target)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "outgoing (selected range):" in out
    assert "doc -> index (index)" in out
    assert "doc -> outside" not in out
    assert "incoming (document-level):" in out
    assert "index:" in out
    assert "doc -> target" in out


@pytest.mark.integration
def test_cli_context_resolves_nested_cross_file_toctree_in_its_source_document(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    index = tmp_path / "index.rst"
    child = tmp_path / "child.rst"
    grandchild = tmp_path / "grandchild.rst"
    index.write_text(
        "Index\n=====\n\n.. toctree::\n\n   child\n",
        encoding="utf-8",
    )
    child.write_text(
        "Child\n=====\n\n.. toctree::\n\n   grandchild\n",
        encoding="utf-8",
    )
    grandchild.write_text("Grandchild\n==========\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(tmp_path), "context", "child:toctree@4", str(index)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert f"Context: {child}" in out
    assert "selector: child:toctree@4" in out
    assert "index:toctree@4" in out
    assert 'child:Child — section "Child"' in out
    assert "parent: child:Child" in out


# ---------------------------------------------------------------------------
# list-table verb (docs/roadmap.rst, "Targeted aligned-table to list-table
# transformation") — full CLI-level integration. The conversion algorithm
# itself (docutils table-parser wrapping, rendering, semantic validation)
# is covered exhaustively in tests/test_list_table.py; these tests confirm
# the CLI wiring: exit codes, diff/write output, --quiet, --only/--skip
# end to end through check_rst.main().
# ---------------------------------------------------------------------------

_LIST_TABLE_GRID = "+-----+-------+\n| A   | B     |\n+=====+=======+\n| 1   | two   |\n+-----+-------+\n"


@pytest.mark.integration
def test_cli_list_table_dry_run_prints_diff_and_exits_1(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "doc.rst"
    p.write_text("Title\n#####\n\n" + _LIST_TABLE_GRID, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "-+-----+-------+" in out
    assert "+.. list-table::" in out
    assert p.read_text(encoding="utf-8") == "Title\n#####\n\n" + _LIST_TABLE_GRID  # untouched
    assert "1 file(s) would change" in out


@pytest.mark.integration
def test_cli_list_table_apply_writes_file_and_exits_0(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "doc.rst"
    original = "Title\n#####\n\n" + _LIST_TABLE_GRID
    p.write_text(original, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", "--apply", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    written = p.read_text(encoding="utf-8")
    assert ".. list-table::" in written
    assert written != original
    out = capsys.readouterr().out
    assert "converted table(s) 1" in out
    assert "1 file(s) converted" in out


@pytest.mark.integration
def test_cli_list_table_no_eligible_tables_is_clean_exit_0(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "doc.rst"
    p.write_text("Title\n#####\n\nJust prose.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    assert "no eligible tables to convert" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_list_table_unknown_ordinal_is_fatal(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "doc.rst"
    p.write_text("Title\n#####\n\n" + _LIST_TABLE_GRID, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", "--only", "5", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "unknown table ordinal(s): 5" in out
    assert p.read_text(encoding="utf-8") == "Title\n#####\n\n" + _LIST_TABLE_GRID  # untouched


@pytest.mark.integration
def test_cli_list_table_skip_excludes_table_from_conversion(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "doc.rst"
    p.write_text("Title\n#####\n\n" + _LIST_TABLE_GRID, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", "--skip", "1", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    assert "no eligible tables to convert" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_list_table_quiet_suppresses_status_and_skip_notice(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "doc.rst"
    p.write_text("Title\n#####\n\nJust prose.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", "--quiet", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    assert capsys.readouterr().out == ""


@pytest.mark.integration
def test_cli_list_table_rejects_sphinx_src(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "doc.rst"
    p.write_text("Title\n#####\n\n" + _LIST_TABLE_GRID, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--sphinx-src", str(tmp_path), "list-table", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    assert "does not use Sphinx" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_list_table_ignores_configured_sphinx_for_foreign_files(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Found by code review: the config-fill block's inactive-vs-applied
    branch only recognized --fast (fix_only/diff_only), so a configured
    sphinx-src/build-dir was silently APPLIED for list-table too — even
    though _validate_list_table_args already rejects those as *explicit*
    flags for this verb, since list-table never consults Sphinx. The live
    symptom: a file outside the configured sphinx-src tree failed with
    'not part of --sphinx-src ...', a check that exists only to protect
    Sphinx mode; --config itself must stay active (its docstring: it
    still roots project/Git-scope discovery for this verb), so only the
    Sphinx-specific settings should go inactive, the same as --fast."""
    docs = tmp_path / "docs"
    docs.mkdir()
    p = tmp_path / "doc.rst"
    p.write_text("Title\n#####\n\n" + _LIST_TABLE_GRID, encoding="utf-8")
    config = tmp_path / "check-rst.toml"
    config.write_text('sphinx-src = "docs"\nbuild-dir = "build"\n', encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--config", str(config), "list-table", str(p)],
    )
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "not part of --sphinx-src" not in out
    assert "sphinx-src=docs inactive (list-table)" in out
    assert "build-dir=build inactive (list-table)" in out
    assert "+.. list-table::" in out
