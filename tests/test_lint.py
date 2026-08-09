# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Semantic warning checker tests — check_rst project

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import docutils.nodes
import pytest
from _support import _git, _rst

from check_rst import cli
from check_rst.cli import _document, _formatting, _helpers, _lint, _sphinx

if TYPE_CHECKING:
    from pathlib import Path

    from _support import BuildSphinxEnv


@pytest.mark.unit
def test_homoglyph_words_flags_confusable_minority() -> None:
    # Cyrillic А (U+0410) + Latin "uthor" — the real corpus catch.  # noqa: RUF003
    matches = list(_lint._homoglyph_words_in("See Аuthor for details."))  # noqa: RUF001
    assert len(matches) == 1
    assert matches[0][2] == "Аuthor"  # noqa: RUF001


@pytest.mark.unit
def test_homoglyph_words_ignores_pure_single_script() -> None:
    assert list(_lint._homoglyph_words_in("Purely English text here.")) == []
    assert list(_lint._homoglyph_words_in("Совсем русский текст здесь.")) == []


@pytest.mark.unit
def test_homoglyph_words_ignores_non_confusable_minority_letter() -> None:
    """'VPNом' — Latin majority 'VPN' + Cyrillic minority 'ом'; 'о' is
    confusable but 'м' is not, so NOT every minority letter qualifies."""  # noqa: RUF002
    assert list(_lint._homoglyph_words_in("используя VPNом провод")) == []  # noqa: RUF001


@pytest.mark.unit
def test_homoglyph_words_ignores_tied_script_counts() -> None:
    # One Cyrillic confusable + one Latin letter: 1-vs-1 is ambiguous, skip.
    assert list(_lint._homoglyph_words_in("аb")) == []  # noqa: RUF001


@pytest.mark.unit
def test_homoglyph_words_ignores_legitimate_non_confusable_notation() -> None:
    # 'jьmati' — Proto-Slavic notation; Cyrillic ь has no Latin confusable.
    assert list(_lint._homoglyph_words_in("jьmati")) == []


@pytest.mark.integration
def test_check_homoglyphs_flags_known_confusable_typo(tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n=====\n\nSee Аuthor for details.\n")  # noqa: RUF001
    violations = _lint.check_homoglyphs(p)
    assert len(violations) == 1
    assert violations[0].severity == "WARNING"
    assert "Аuthor" in violations[0].text  # noqa: RUF001


@pytest.mark.integration
def test_check_homoglyphs_ignores_clean_trilingual_prose(tmp_path: Path) -> None:
    """Cyrillic and Latin coexisting on the same line/paragraph — this
    corpus's normal case — must stay silent; only a single mixed-script
    WORD is ever suspicious."""
    p = _rst(
        tmp_path,
        "Title\n=====\n\nЗапустил check_rst и Sphinx, всё собралось чисто.\n",  # noqa: RUF001
    )
    assert _lint.check_homoglyphs(p) == []


@pytest.mark.integration
def test_check_homoglyphs_skips_literal_block_content(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        "Title\n=====\n\n::\n\n    Аuthor in a code block.\n",  # noqa: RUF001
    )
    assert _lint.check_homoglyphs(p) == []


@pytest.mark.integration
def test_check_homoglyphs_skips_comment_content(tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n=====\n\n.. Аuthor in a comment.\n")  # noqa: RUF001
    assert _lint.check_homoglyphs(p) == []


@pytest.mark.integration
def test_check_homoglyphs_does_not_skip_block_quote(tmp_path: Path) -> None:
    """Unlike check_directives' bold/rubric exemption, quoted material is
    still checked — a garbled word is still garbled regardless of who
    originally typed it."""
    p = _rst(
        tmp_path,
        "Title\n=====\n\nHe wrote:\n\n    See Аuthor for details.\n",  # noqa: RUF001
    )
    assert len(_lint.check_homoglyphs(p)) == 1


@pytest.mark.integration
def test_check_homoglyphs_lineno_precise_within_multiline_paragraph(
    tmp_path: Path,
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
    violations = _lint.check_homoglyphs(p)
    assert len(violations) == 1
    assert violations[0].lineno == 6


@pytest.mark.integration
def test_check_homoglyphs_multiple_occurrences_all_reported(tmp_path: Path) -> None:
    p = _rst(
        tmp_path,
        "Title\n=====\n\nАuthor wrote about Сalibration twice.\n",  # noqa: RUF001
    )
    assert len(_lint.check_homoglyphs(p)) == 2


@pytest.mark.integration
def test_cli_homoglyphs_warning_shown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = _rst(tmp_path, "Title\n=====\n\nSee Аuthor for details.\n")  # noqa: RUF001
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "WARNING:" in out
    assert "Аuthor" in out  # noqa: RUF001


@pytest.mark.integration
def test_cli_json_homoglyphs_included(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text("Title\n#####\n\nSee Аuthor for details.\n", encoding="utf-8")  # noqa: RUF001
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    data = json.loads(capsys.readouterr().out)
    findings = data["files"][0]["findings"]
    assert any(
        f["severity"] == "WARNING" and "Аuthor" in f["text"]  # noqa: RUF001
        for f in findings
    )


@pytest.mark.integration
def test_directives_rubric_flagged(tmp_path: Path) -> None:
    """A .. rubric:: directive must be flagged as a heading substitute."""
    p = _rst(tmp_path, ".. rubric:: My Heading\n\nSome text.\n")
    violations = _lint.check_directives(p, True)
    assert violations
    assert any("rubric" in v for v in violations)


@pytest.mark.integration
def test_directives_indented_rubric_flagged(tmp_path: Path) -> None:
    """.. rubric:: inside a directive body must also be flagged.

    The fixture is a real directive body (a note admonition).  The
    original fixture was a bare indented rubric at document start —
    which docutils parses as a *blockquote*, not a directive body, so
    the test passed on a false premise; the blockquote exemption
    (quoted material is never a heading substitute) exposed it."""
    p = _rst(tmp_path, ".. note::\n\n   .. rubric:: My Heading\n\nSome text.\n")
    violations = _lint.check_directives(p, True)
    assert violations
    assert any("rubric" in v for v in violations)


@pytest.mark.integration
def test_directives_bold_standalone_flagged(tmp_path: Path) -> None:
    """A line consisting entirely of bold text must be flagged, by the
    actual text it names (see test_directives_standalone_bold_default_
    shows_actual_text — no generic '**...**' placeholder any more)."""
    p = _rst(tmp_path, "**Section Heading**\n\nSome text.\n")
    violations = _lint.check_directives(p, True)
    assert violations
    assert any("Section Heading" in v for v in violations)


@pytest.mark.integration
def test_directives_bold_inline_ok(tmp_path: Path) -> None:
    """Bold text within a sentence must NOT be flagged."""
    p = _rst(tmp_path, "Use **bold** for inline emphasis only.\n")
    assert _lint.check_directives(p, True) == []


@pytest.mark.integration
def test_nested_inline_markup_mid_sentence_flagged(tmp_path: Path) -> None:
    """The dominant real corpus shape must not depend on paragraph position.

    Pandoc preserves Markdown's bold-around-code nesting even though RST does
    not render the inner role.  The old bold-opener check was silent when the
    malformed span occurred mid-sentence, which is where most corpus examples
    occur.
    """
    p = _rst(tmp_path, "Use **``XGrabServer()``** to lock the server.\n")

    findings = _lint.check_nested_inline_markup(p, True)

    assert len(findings) == 1
    assert findings[0].severity == "WARNING"
    assert "nested inline markup in bold span" in findings[0].text
    assert "contains inline literal" in findings[0].text
    assert "XGrabServer" in findings[0].text


@pytest.mark.integration
def test_nested_inline_markup_reports_its_physical_line(tmp_path: Path) -> None:
    """A multiline paragraph must not collapse every inline finding to line 1."""
    p = _rst(tmp_path, "The paragraph starts here\nand uses **``nested``** markup here.\n")

    findings = _lint.check_nested_inline_markup(p, True)

    assert len(findings) == 1
    assert findings[0].lineno == 2


@pytest.mark.integration
def test_nested_inline_markup_diff_scope_uses_physical_line(rst_repo: Path) -> None:
    """A new span on line 2 is in scope; an unchanged line-1 span is not."""
    p = rst_repo / "nested.rst"
    p.write_text("**``old``** starts this paragraph\nand continues plainly.\n", encoding="utf-8")
    _git(rst_repo, "add", "nested.rst")
    _git(rst_repo, "commit", "-m", "add nested fixture")
    p.write_text(
        "**``old``** starts this paragraph\nand adds **``new``** markup.\n",
        encoding="utf-8",
    )

    findings = _lint.check_nested_inline_markup(p, False)

    assert len(findings) == 1
    assert findings[0].lineno == 2
    assert "new" in findings[0].text


@pytest.mark.integration
def test_nested_inline_markup_supersedes_heading_diagnosis(tmp_path: Path) -> None:
    """A more specific syntax diagnosis must suppress misleading advice.

    Before this rule, a leading or standalone ``**``code``**`` span was
    reported as a heading substitute.  Promoting it to a section would not
    repair the lost inline styling, so check_directives must leave this node
    to the nested-markup finding.
    """
    p = _rst(tmp_path, "**``image->data``**\n")

    nested = _lint.check_nested_inline_markup(p, True)
    directives = _lint.check_directives(p, True)

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
    tmp_path: Path,
    source: str,
    outer: str,
    inner: str,
) -> None:
    """Delegate delimiter and role recognition to docutils' own grammar."""
    p = _rst(tmp_path, source)

    findings = _lint.check_nested_inline_markup(p, True)

    assert len(findings) == 1
    assert f"in {outer} span" in findings[0].text
    assert f"contains {inner}" in findings[0].text


@pytest.mark.unit
def test_findall_node_types_uses_callable_condition_for_docutils_022() -> None:
    """Docutils 0.22 rejects a tuple passed directly as Node.findall's
    condition; the compatibility adapter must use the callable form accepted
    by both 0.22 and 0.23."""
    strong = docutils.nodes.strong()
    emphasis = docutils.nodes.emphasis()
    paragraph = docutils.nodes.paragraph("", "plain")
    document = docutils.utils.new_document("test")
    document.extend([strong, emphasis, paragraph])

    found = list(
        _helpers._findall_node_types(
            document,
            (docutils.nodes.strong, docutils.nodes.emphasis),
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
def test_nested_inline_markup_ignores_non_markup_reparse_results(tmp_path: Path, source: str) -> None:
    """Only successful explicit inline constructs count as nested markup."""
    p = _rst(tmp_path, source)

    assert _lint.check_nested_inline_markup(p, True) == []


@pytest.mark.integration
def test_nested_inline_markup_inside_literal_block_is_not_source_markup(
    tmp_path: Path,
) -> None:
    """An RST example in a code block is captured text, not parsed structure."""
    p = _rst(tmp_path, ".. code-block:: rst\n\n   Use **``nested``** here.\n")

    assert _lint.check_nested_inline_markup(p, True) == []


@pytest.mark.integration
def test_nested_inline_markup_inside_block_quote_still_flagged(tmp_path: Path) -> None:
    """Quoted imports still render incorrectly even though they are not headings."""
    p = _rst(tmp_path, "An imported answer said:\n\n   Use **``nested``** here.\n")

    findings = _lint.check_nested_inline_markup(p, True)

    assert len(findings) == 1
    assert _lint.check_directives(p, True) == []


@pytest.mark.integration
def test_cli_nested_inline_markup_reports_each_span_and_one_shared_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI exposes every occurrence without repeating its rationale."""
    p = _rst(tmp_path, "Use **``one``** and **``two``** here.\n")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out.count("WARNING: nested inline markup in bold span") == 2
    assert out.count("reStructuredText renders only the outer inline role") == 1


@pytest.mark.integration
def test_cli_no_directives_does_not_disable_nested_inline_markup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--no-directives skips its named lint, not this independent rule."""
    p = _rst(tmp_path, "Use **``nested``** here.\n")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--no-directives", str(p)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert "WARNING: nested inline markup" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_json_includes_nested_inline_markup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Automation receives the same specific finding as text mode."""
    p = _rst(tmp_path, "Use **``nested``** here.\n")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    findings = json.loads(capsys.readouterr().out)["files"][0]["findings"]
    assert any(f["severity"] == "WARNING" and f["text"].startswith("nested inline markup ") for f in findings)


@pytest.mark.integration
def test_nested_inline_reparse_is_cached_across_warning_consumers(
    tmp_path: Path,
) -> None:
    """A Document probes each outer span once even when two checks need it."""
    p = _rst(tmp_path, "Use **``one``** and ``plain literal`` here.\n")
    document = _document.Document(p)
    _helpers.CALL_COUNTS.clear()

    assert len(_lint.check_nested_inline_markup(p, True, doc=document)) == 1
    assert _lint.check_directives(p, True, doc=document) == []

    assert _helpers.CALL_COUNTS["_nested_inline_reparse"] == 2


@pytest.mark.integration
def test_directives_bold_opener_in_list_item_flagged(tmp_path: Path) -> None:
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
    findings = _lint.check_directives(p, True)
    assert len(findings) == 1
    assert findings[0].severity == "WARNING"
    assert "bold paragraph opener" in findings[0].text


@pytest.mark.integration
def test_directives_bold_term_in_list_item_also_flagged(tmp_path: Path) -> None:
    """The short 'term:' idiom is structurally identical (bold first
    child, more children follow) to the opener-plus-prose shape above —
    there is no tree-shape test that tells them apart, and per the
    reversed design neither is auto-exempt any more: judgment stays
    with the AI/human, uniformly, list item or not."""
    p = _rst(tmp_path, "* **term**: definition of the term\n")
    findings = _lint.check_directives(p, True)
    assert len(findings) == 1
    assert findings[0].severity == "WARNING"
    assert "bold paragraph opener" in findings[0].text


@pytest.mark.integration
def test_directives_bold_standalone_in_block_quote_ok(tmp_path: Path) -> None:
    """A standalone bold line inside a blockquote is quoted material, not a heading substitute."""
    p = _rst(
        tmp_path,
        "Он ответил:\n\n    **The Parsing Bug**\n\n    Some quoted explanation.\n",
    )
    assert _lint.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_bold_opener_in_block_quote_ok(tmp_path: Path) -> None:
    """A bold paragraph opener inside a blockquote is quoted material, not a heading substitute."""
    p = _rst(
        tmp_path,
        "He wrote:\n\n    **Note:** this is quoted, not my own heading.\n",
    )
    assert _lint.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_rubric_in_block_quote_ok(tmp_path: Path) -> None:
    """A rubric inside a blockquote is quoted material too — the same
    rationale as quoted bold (promoting it would de-indent the quote,
    misrepresenting a quotation as the author's structure) applies to
    every heading-substitute pattern, so the whole blockquote subtree is
    exempt via SkipNode, the same idiom as literal blocks."""
    p = _rst(
        tmp_path,
        "He wrote:\n\n    .. rubric:: Quoted Heading\n\n    Quoted body.\n",
    )
    assert _lint.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_bold_in_accidental_indent_silent_known_limitation(
    tmp_path: Path,
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
    assert _lint.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_bold_not_first_child_ok(tmp_path: Path) -> None:
    """Bold text that is not the first element in a paragraph must NOT be flagged."""
    p = _rst(tmp_path, "See **bold term** for details.\n")
    assert _lint.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_bold_opener_period_flagged(tmp_path: Path) -> None:
    """A bold paragraph opener ending with a period must be flagged (AI heading pattern)."""
    p = _rst(tmp_path, "**Memory layout.** Zephyr stores the kernel state here.\n")
    violations = _lint.check_directives(p, True)
    assert violations
    assert any("bold paragraph opener" in v for v in violations)


@pytest.mark.integration
def test_directives_bold_opener_default_shows_actual_text(tmp_path: Path) -> None:
    """Max, 2026-07-20: 'without informing the original text, it's hard to
    judge in one step' — the DEFAULT (non-verbose) message must name the
    actual bold text, not a generic '**...** text' placeholder every
    finding shared, indistinguishable from every other one in a
    19-finding review pass.  Every OTHER directive finding already does
    this by default (rubric shows its own text, the mistyped-directive
    warning shows the actual name) — bold was the inconsistent one."""
    p = _rst(tmp_path, "**Memory layout.** Zephyr stores the kernel state here.\n")
    violations = _lint.check_directives(p, True)
    assert any("Memory layout" in v for v in violations)


@pytest.mark.integration
def test_directives_standalone_bold_default_shows_actual_text(tmp_path: Path) -> None:
    """Same fix, the other bold-as-heading shape (nothing else in the
    paragraph)."""
    p = _rst(tmp_path, "**Section Heading**\n\nSome text.\n")
    violations = _lint.check_directives(p, True)
    assert any("Section Heading" in v for v in violations)


@pytest.mark.integration
def test_directives_bold_opener_colon_flagged(tmp_path: Path) -> None:
    """A bold paragraph opener ending with a colon must be flagged (heading substitute pattern)."""
    p = _rst(
        tmp_path,
        "**Как сбросить:** Command Palette → ``Python: Clear Workspace Interpreter Setting``.\n",
    )
    violations = _lint.check_directives(p, True)
    assert violations
    assert any("bold paragraph opener" in v for v in violations)


@pytest.mark.integration
def test_directives_bold_note_colon_flagged(tmp_path: Path) -> None:
    """**Note:** opener is the same colon pattern and must also be flagged."""
    p = _rst(tmp_path, "**Note:** this is a warning paragraph.\n")
    violations = _lint.check_directives(p, True)
    assert violations
    assert any("bold paragraph opener" in v for v in violations)


@pytest.mark.integration
def test_directives_bold_opener_no_punctuation_flagged(tmp_path: Path) -> None:
    """A bold paragraph opener with no terminal punctuation must also be flagged."""
    p = _rst(tmp_path, "**Overview** This section explains the architecture.\n")
    violations = _lint.check_directives(p, True)
    assert violations
    assert any("bold paragraph opener" in v for v in violations)


@pytest.mark.integration
def test_directives_bold_opener_quoted_flagged(tmp_path: Path) -> None:
    """A bold paragraph opener ending with a closing quote must also be flagged."""
    p = _rst(tmp_path, '**"raw mode"** leaves the terminal in a broken state.\n')
    violations = _lint.check_directives(p, True)
    assert violations
    assert any("bold paragraph opener" in v for v in violations)


@pytest.mark.integration
def test_directives_clean_rst_ok(tmp_path: Path) -> None:
    """A file with no forbidden directives returns an empty violation list."""
    p = _rst(
        tmp_path,
        """\
        Some text with **inline bold** emphasis.

        - A bullet with **bold term**: inline only.
        - Another item.
        """,
    )
    assert _lint.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_default_verbose_false_unchanged(tmp_path: Path) -> None:
    """Omitting verbose must be identical to passing verbose=False explicitly."""
    p = _rst(tmp_path, "**Note:** this is a warning paragraph.\n")
    assert _lint.check_directives(p, True) == _lint.check_directives(p, True, False)


@pytest.mark.integration
def test_directives_rubric_verbose_shows_text_and_section(tmp_path: Path) -> None:
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
    violations = _lint.check_directives(p, True, True)
    assert violations
    assert any("See also" in v and "Chapter One" in v for v in violations)


@pytest.mark.integration
def test_directives_bold_standalone_verbose_shows_text(tmp_path: Path) -> None:
    """Verbose standalone-bold findings must include the actual bold text."""
    p = _rst(tmp_path, "**Section Heading**\n\nSome text.\n")
    violations = _lint.check_directives(p, True, True)
    assert violations
    assert any("Section Heading" in v for v in violations)


@pytest.mark.integration
def test_directives_bold_opener_verbose_shows_text_preview_and_section(
    tmp_path: Path,
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
    violations = _lint.check_directives(p, True, True)
    assert violations
    opener = next(v for v in violations if "bold paragraph opener" in v)
    assert "Overview" in opener
    assert "This section explains the architecture" in opener
    assert "Inner" in opener


@pytest.mark.integration
def test_directives_verbose_no_enclosing_section(tmp_path: Path) -> None:
    """Verbose findings with no enclosing section must say so rather than
    silently omitting the section clause."""
    p = _rst(tmp_path, "**Overview** This section explains the architecture.\n")
    violations = _lint.check_directives(p, True, True)
    assert violations
    assert any("no enclosing section" in v for v in violations)


@pytest.mark.integration
def test_directives_non_verbose_omits_extra_detail(tmp_path: Path) -> None:
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
    violations = _lint.check_directives(p, True, False)
    assert violations
    assert not any("Chapter One" in v for v in violations)
    assert not any("This section explains the architecture" in v for v in violations)


@pytest.mark.integration
def test_code_blocks_lineno_is_directive_marker_line(
    build_sphinx_env: BuildSphinxEnv,
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
    entries = _sphinx.find_code_blocks(env, docname)
    assert entries[0].lineno == 4


@pytest.mark.integration
def test_directives_rubric_in_code_block_not_flagged(tmp_path: Path) -> None:
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
    assert _lint.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_rubric_in_literal_block_not_flagged(tmp_path: Path) -> None:
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
    assert _lint.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_rubric_in_nested_literal_block_not_flagged(tmp_path: Path) -> None:
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
    assert _lint.check_directives(p, True) == []


@pytest.mark.integration
def test_skip_fixable_preserves_directive_warnings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Directive WARNINGs (bold headings, rubric) are still shown with --skip-fixable."""
    p = _rst(tmp_path, "**Bold Heading**\n\nSome text.\n")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--skip-fixable", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "WARNING:" in out


@pytest.mark.unit
def test_normalize_blank_lines_is_conservative_for_unknown_project_directive(
    tmp_path: Path,
) -> None:
    """Bare docutils represents an unknown Sphinx/project directive as a
    diagnostic plus literal source.  Its indented body must remain intact;
    uncertainty is a reason to retain source, never to guess."""
    before = ".. project-specific::\n\n   first\n\n\n   second\n"

    normalized, removed = _formatting._normalize_blank_lines(tmp_path / "foreign.rst", before)

    assert normalized == before
    assert removed == 0


@pytest.mark.integration
def test_comments_suspicious_flag_true_for_known_directive_typo(tmp_path: Path) -> None:
    """Same heuristic as the Phase 1 WARNING (_MISTYPED_DIRECTIVE_RE +
    _KNOWN_DIRECTIVE_NAMES) — a single-colon '.. code: bash' is flagged
    suspicious right where its text is shown."""
    p = _rst(tmp_path, "Text.\n\n.. code: bash\n\n    pandoc --from gfm\n")
    e = _document.find_comments(p)[0]
    assert e.suspicious is True
    assert "suspicious" in str(e)


@pytest.mark.integration
def test_tables_table_directive_wraps_simple_table(tmp_path: Path) -> None:
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
    entries = _document.find_tables(p)
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == "table"
    assert e.caption == "Simple Wrapped"
    assert e.dims == (2, 2)
    assert e.lineno == 4
