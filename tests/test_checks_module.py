# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Tests for check_rst.cli's _checks domain (Phase 0/1 checkers, fixers, list-table) — check_rst project

from __future__ import annotations

import itertools
import json
import os
import subprocess
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from _support import _BAD_BLOCK, _GOOD_BLOCK, _git, _rst

if TYPE_CHECKING:
    import types
    from collections.abc import Callable


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


# Appended to a committed-clean file as an unstaged/staged edit: an
# underline-only title with no matching overline.
_APPENDED_UNDERLINE_ONLY = textwrap.dedent("""

    New Title
    ---------
    """)


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
    monkeypatch.setattr(check_rst._helpers, "PROJECT_ROOT", nested)

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
    monkeypatch.setattr(check_rst._helpers, "_git", lambda *_args: next(responses))

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
        check_rst._sphinx,
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
