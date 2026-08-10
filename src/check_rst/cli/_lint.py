# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Semantic warning checks for author-facing RST prose — check_rst project

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

import docutils.nodes
import docutils.parsers.rst
import docutils.parsers.rst.languages
import docutils.parsers.rst.languages.en
import docutils.parsers.rst.states
import docutils.parsers.rst.tableparser
import docutils.statemachine
import docutils.utils

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Iterator


from ._document import (
    _KNOWN_DIRECTIVE_NAMES,
    _MISTYPED_DIRECTIVE_RE,
    Document,
    _inline_kind,
    _resolve_document,
)
from ._helpers import (
    _enclosing_section_title,
    _findall_node_types,
    _has_non_prose_ancestor,
    _in_scope,
    _inline_node_line,
    _node_line,
)
from ._types import (
    _INLINE_CONTAINER_TYPES,
    Finding,
    Severity,
)

_BOLD_PREVIEW_LEN = 60


# Hand-curated, explicit — "declaration, not auto-detection," the same
# precedent as PREFERRED_HIERARCHY/_KNOWN_DIRECTIVE_NAMES.  No installed
# library provides this on this system (confirmed by direct probe,
# 2026-07-26: confusable_homoglyphs, fontTools, regex, unicodedata2 are all
# absent, and stdlib unicodedata itself has no confusables data at all —
# checked decomposition() for every pair below, none decompose to anything,
# since the visual-twin relationship is encoded ONLY in Unicode's separate
# security-mechanisms data (UTS #39), which nothing installed here exposes).
# Scoped to Cyrillic<->Latin specifically — the only two scripts this
# corpus's Russian/French/English mixing ever produces.  Each pair is a
# genuine glyph-identical or near-identical twin, not a judgment call.
# Every key intentionally triggers the rule this table helps diagnose; keep
# per-line suppressions so RUF001 remains active everywhere else in this file.
_CYRILLIC_LATIN_CONFUSABLES: dict[str, str] = {
    "а": "a",  # noqa: RUF001
    "е": "e",  # noqa: RUF001
    "о": "o",  # noqa: RUF001
    "р": "p",  # noqa: RUF001
    "с": "c",  # noqa: RUF001
    "у": "y",  # noqa: RUF001
    "х": "x",  # noqa: RUF001
    "А": "A",  # noqa: RUF001
    "В": "B",  # noqa: RUF001
    "Е": "E",  # noqa: RUF001
    "К": "K",  # noqa: RUF001
    "М": "M",  # noqa: RUF001
    "Н": "H",  # noqa: RUF001
    "О": "O",  # noqa: RUF001
    "Р": "P",  # noqa: RUF001
    "С": "C",  # noqa: RUF001
    "Т": "T",  # noqa: RUF001
    "Х": "X",  # noqa: RUF001
}


_CONFUSABLE_CHARS = frozenset(_CYRILLIC_LATIN_CONFUSABLES) | frozenset(_CYRILLIC_LATIN_CONFUSABLES.values())


_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _char_script(ch: str) -> str | None:
    """Return 'CYRILLIC'/'LATIN' for a letter in either script, else None
    (digits, punctuation, other scripts) — a name-substring proxy, since
    stdlib unicodedata exposes no direct Script property."""
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return None
    if "CYRILLIC" in name:
        return "CYRILLIC"
    if "LATIN" in name:
        return "LATIN"
    return None


def _homoglyph_words_in(text: str) -> Iterator[tuple[int, int, str]]:
    """Yield (start, end, word) for each word in *text* mixing Cyrillic and
    Latin letters where EVERY minority-script letter is a known visual twin
    of a majority-script one (Max, 2026-07-24: "when letters look similar,
    but only one letter is from another alphabet").

    Never flagged merely for mixing scripts — confirmed by real corpus
    evidence (2026-07-26) that mixing alone is too common to be a signal
    (this Journal is deliberately trilingual) and that the "every minority
    letter must be confusable" condition is exactly what separates real
    typos ('Аuthor', 'Сalibration') from legitimate constructions ('VPNом',
    a Latin acronym plus a Cyrillic case ending — 'м' has no Latin twin;
    'jьmati', Proto-Slavic notation — 'ь' has no Latin twin either).  A
    tied majority/minority split is skipped as genuinely ambiguous, not
    guessed at.
    """  # noqa: RUF002
    for m in _WORD_RE.finditer(text):
        word = m.group(0)
        by_script: dict[str, list[str]] = {}
        for ch in word:
            script = _char_script(ch)
            if script is not None:
                by_script.setdefault(script, []).append(ch)
        if len(by_script) != 2:
            continue
        chars_by_size = sorted(by_script.values(), key=len)
        minority_chars, majority_chars = chars_by_size[0], chars_by_size[1]
        if len(minority_chars) == len(majority_chars):
            continue
        if all(ch in _CONFUSABLE_CHARS for ch in minority_chars):
            yield m.start(), m.end(), word


def check_homoglyphs(path: pathlib.Path, doc: Document | None = None) -> list[Finding]:
    """Flag a word mixing Cyrillic and Latin letters that are visual twins
    — a keyboard-layout slip, not intentional content (see
    _homoglyph_words_in for the precise rule).

    Scans the same author-facing prose Text nodes as Document.prose_text
    (_has_non_prose_ancestor) — code, comments, raw passthrough, and
    generated topics are apparatus, not something an author "wrote" as
    prose, so a confusable-looking identifier inside a code-block must
    never be flagged.  Unlike check_directives' bold/rubric exemption,
    block_quote content is NOT skipped: a garbled word is still garbled
    regardless of who originally typed it.

    lineno is the exact physical line, not merely the enclosing
    paragraph's first line: a docutils Text node spans its WHOLE
    paragraph, so the count of embedded newlines up to the match's own
    offset is added to _node_line's base — more precise than
    check_directives bothers to be, because a bold/rubric node is always
    short while a homoglyph can be anywhere in a long paragraph.
    """
    document = _resolve_document(path, doc)
    findings: list[Finding] = []
    for text_node in document.doctree.findall(docutils.nodes.Text):
        if _has_non_prose_ancestor(text_node):
            continue
        s = str(text_node)
        base_line = _node_line(text_node)
        for start, _end, word in _homoglyph_words_in(s):
            lineno = base_line + s[:start].count("\n")
            findings.append(
                Finding(
                    lineno,
                    Severity.WARNING,
                    f"{word!r} mixes Cyrillic and Latin letters that look "
                    "identical — probably a keyboard-layout slip, not "
                    "intentional",
                )
            )
    return findings


def check_nested_inline_markup(
    path: pathlib.Path,
    whole_file: bool,
    doc: Document | None = None,
) -> list[Finding]:
    """Warn when one RST inline role silently contains another.

    RST inline markup never nests: docutils keeps the inner delimiters as the
    outer node's text.  Re-parsing that residual text with Inliner detects the
    real grammar rather than approximating it, in either nesting direction and
    regardless of paragraph position.  Warnings are semantic: RST cannot
    preserve both roles, so choosing which one survives is not auto-fixable.
    """
    document = _resolve_document(path, doc)
    ranges: list[tuple[int, int]] | None = None if whole_file else document.ranges
    findings: list[Finding] = []
    for outer in _findall_node_types(document.doctree, _INLINE_CONTAINER_TYPES):
        nested = document.nested_inline_by_node.get(id(outer), ())
        if not nested:
            continue
        lineno = _inline_node_line(outer)
        if not _in_scope(ranges, lineno, lineno):
            continue
        source = " ".join(str(outer.rawsource).split())
        if len(source) > _BOLD_PREVIEW_LEN:
            source = source[:_BOLD_PREVIEW_LEN] + "…"
        inner_kinds = ", ".join(dict.fromkeys(_inline_kind(node) for node in nested))
        findings.append(
            Finding(
                lineno=lineno,
                severity=Severity.WARNING,
                text=(f"nested inline markup in {_inline_kind(outer)} span {source!r} (contains {inner_kinds})"),
            )
        )
    return findings


def check_directives(
    path: pathlib.Path,
    whole_file: bool,
    verbose: bool = False,
    doc: Document | None = None,
) -> list[Finding]:
    """Detect heading-substitute patterns using the docutils AST.

    Content inside literal blocks (``.. code-block::``, ``::`` paragraphs,
    ``.. doctest::``, ``.. parsed-literal::``) is skipped entirely via
    SkipNode in visit_literal_block — no false positives from code examples.

    All findings have severity WARNING — they require human judgement and do
    not affect the exit code.  Use --no-warnings to suppress them.

    With verbose=True, findings additionally report the actual bold/rubric
    text, a preview of the paragraph text following a bold opener, and the
    title of the nearest enclosing section — none of that detail is computed
    or shown by default.
    """
    document = _resolve_document(path, doc)
    ranges: list[tuple[int, int]] | None = None if whole_file else document.ranges
    doc_tree = document.doctree
    findings: list[Finding] = []
    # A leading/standalone bold span with broken nested markup used to be
    # misdiagnosed as a heading substitute.  The more specific syntax warning
    # must own those nodes: promoting one to a section cannot restore the inner
    # styling that docutils discarded.
    nested_strong_ids = set(document.nested_inline_by_node)

    def warn(node: docutils.nodes.Node, text: str) -> None:
        lineno = _node_line(node)
        if _in_scope(ranges, lineno, lineno):
            findings.append(Finding(lineno=lineno, severity=Severity.WARNING, text=text))

    def section_clause(node: docutils.nodes.Node) -> str:
        title = _enclosing_section_title(node)
        return f"in section {title!r}" if title is not None else "(no enclosing section)"

    class _Visitor(docutils.nodes.NodeVisitor):  # type: ignore[misc]
        # docutils ships no stubs: NodeVisitor resolves as Any, so mypy
        # can't verify this subclass at all — narrowest possible ignore,
        # not a broader docutils.* override change (pyproject.toml already
        # has one, scoped to missing-import only, not to Any-flow errors
        # like this).
        def unknown_visit(self, node: docutils.nodes.Node) -> None:
            pass

        def unknown_departure(self, node: docutils.nodes.Node) -> None:
            pass

        def visit_literal_block(self, node: docutils.nodes.Node) -> None:
            # Skip the entire subtree — content is literal text, not RST structure.
            raise docutils.nodes.SkipNode

        def visit_block_quote(self, node: docutils.nodes.Node) -> None:
            # Skip the entire subtree — an indented blockquote is quoted
            # material (an AI's answer, an email body), not the author's own
            # prose, so nothing inside it (bold OR rubric) is a
            # heading-substitute candidate: promoting would de-indent the
            # quote, misrepresenting a quotation as original structure.
            # Found via a real corpus false positive: 2026-05-02/2026-05-12
            # Notes.rst flagged bold sub-headers inside a quoted
            # answer/email.  KNOWN, ACCEPTED limitation: RST turns any
            # accidentally indented paragraph into a blockquote, so a merely
            # mis-indented pseudo-heading is exempt too — quotation intent
            # is not detectable; in this corpus indented material is
            # overwhelmingly genuine quotation.
            raise docutils.nodes.SkipNode

        def visit_comment(self, node: docutils.nodes.Node) -> None:
            # A single-colon '.. name: …' is a perfectly legal comment, so a
            # mistyped directive silently HIDES its content instead of
            # rendering it — and no phase flags it otherwise: comments are
            # valid RST, so Sphinx and docutils are correctly silent (found
            # via a real '.. code: bash' typo in a calendar note,
            # 2026-07-18).  Warn when the comment's first line starts with a
            # known directive name followed by a single colon.
            first = node.astext().split("\n", 1)[0]
            m = _MISTYPED_DIRECTIVE_RE.match(first)
            if m and m.group(1).lower() in _KNOWN_DIRECTIVE_NAMES:
                name = m.group(1)
                warn(
                    node,
                    f"comment '.. {name}: …' looks like a mistyped directive — "
                    "a single colon makes it a comment that silently hides "
                    f"its content; did you mean '.. {name}::'?",
                )
            raise docutils.nodes.SkipNode

        def visit_rubric(self, node: docutils.nodes.Node) -> None:
            if verbose:
                warn(
                    node,
                    f"'.. rubric:: {node.astext()}' detected {section_clause(node)} — "
                    "verify it is not substituting a section title (rubric is "
                    "excluded from the ToC and cannot be :ref:-ed)",
                )
            else:
                warn(
                    node,
                    "'.. rubric::' detected — verify it is not substituting a section "
                    "title (rubric is excluded from the ToC and cannot be :ref:-ed)",
                )

        def visit_strong(self, node: docutils.nodes.Node) -> None:
            if id(node) in nested_strong_ids:
                return
            parent = node.parent
            if not isinstance(parent, docutils.nodes.paragraph):
                return  # bold inside a title, term, etc. — not a heading substitute
            # NOT exempt merely for being inside a list item (reversed Max,
            # 2026-07-20: "check_rst must warn about those bold texts... it's
            # up to the AI - accept or not").  A bold paragraph opener is the
            # same AI-writing habit whether wrapped in a list item or not —
            # confirmed the hard way: this project independently judged two
            # such lists worth converting to real subsections THIS SAME
            # SESSION, which the old blanket exemption would have silenced.
            # There is no tree-shape test that tells a short "term:" label
            # apart from a full bold-sentence-plus-prose opener — both are
            # "bold first child, more children follow" — so neither is
            # auto-exempt; the tool flags, the human/AI decides, uniformly.
            # The bold text itself, bounded — every finding must name what
            # it is actually flagging (Max, 2026-07-20: "without informing
            # the original text, it's hard to judge in one step" — a
            # multi-finding review pass needs to tell 19 identical-looking
            # findings apart without opening the file for each).  Every
            # OTHER directive finding already does this by default (rubric
            # shows its own text, the mistyped-directive warning shows the
            # actual name); bold was the inconsistent one, printing the
            # same placeholder for every occurrence.
            text = node.astext()
            if len(text) > _BOLD_PREVIEW_LEN:
                text = text[:_BOLD_PREVIEW_LEN] + "…"
            # The rationale ("AI documents often use...") is NOT repeated
            # per finding any more (Max, 2026-07-20: "it repeats... long.
            # Can we inform this as a separate line only once?" — the same
            # "state shared context once, not per entry" principle as the
            # outline's levels: legend).  _print_findings prints it once
            # per run, the first time each of these two prefixes appears —
            # see _FINDING_HINTS.
            if len(parent.children) == 1:
                if verbose:
                    warn(node, f"standalone bold line {text!r} {section_clause(node)}")
                else:
                    warn(node, f"standalone bold line {text!r}")
            elif parent.children[0] is node:
                if verbose:
                    rest = "".join(c.astext() for c in parent.children[1:]).strip()
                    if len(rest) > _BOLD_PREVIEW_LEN:
                        rest = rest[:_BOLD_PREVIEW_LEN] + "…"
                    warn(
                        node,
                        f"bold paragraph opener {text!r} followed by {rest!r} {section_clause(node)}",
                    )
                else:
                    warn(node, f"bold paragraph opener {text!r}")

    doc_tree.walkabout(_Visitor(doc_tree))
    return findings
