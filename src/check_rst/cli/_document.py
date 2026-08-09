# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# The Document read-only facade and its domain mixins — check_rst project

from __future__ import annotations

import functools
import re
from typing import TYPE_CHECKING, cast

import docutils.nodes
import docutils.parsers.rst.languages
import docutils.parsers.rst.languages.en
import docutils.parsers.rst.states
import docutils.utils

from . import _helpers
from ._helpers import (
    CALL_COUNTS,
    _block_depth,
    _changed_line_ranges,
    _enum_marker,
    _findall_node_types,
    _indented_extent,
    _inline_node_line,
    _is_adornment,
    _node_line,
    _normalize_source,
    _read_source,
)
from ._types import (
    _INLINE_CONTAINER_TYPES,
    _NON_PROSE_NODE_TYPES,
    AdmonitionEntry,
    BlockQuoteEntry,
    CodeBlockEntry,
    CommentEntry,
    Finding,
    ListEntry,
    OutlineEntry,
    TableEntry,
)

if TYPE_CHECKING:
    import pathlib


class _DocumentCore:
    """The read/parse foundation every Document domain builds on: the
    Phase 0-normalized text, its lines, the git diff ranges, and the
    docutils doctree. Split out of Document (found by code review:
    Document was one ~15-property god object — splitting an
    outline-domain module from a prose/wordstats module still forced
    both to import the whole class, since neither sub-domain had its
    own smaller facade) so each domain mixin below depends on only
    this small core, not on its sibling domains' properties.

    Lazy (cached_property), so a consumer pays only for what it
    touches; CALL_COUNTS assertions pin the one-read/one-parse
    contract in the tests. Deliberately read-only: fixers keep working
    on their own mutating line buffer and write to disk; after a fixer
    writes, construct a NEW Document. Invalidation is explicit in the
    object lifetime — which is exactly what makes the caching safe (a
    path-keyed cache would serve stale text after --fix writes).
    """

    def __init__(
        self,
        path: pathlib.Path,
        project_root: pathlib.Path | None = None,
        *,
        source_text: str | None = None,
    ) -> None:
        self.path = path
        self.project_root = _helpers.PROJECT_ROOT if project_root is None else project_root
        self._source_text = source_text

    @functools.cached_property
    def source(self) -> str:
        if self._source_text is not None:
            return self._source_text
        return _read_source(self.path)

    @functools.cached_property
    def _normalized(self) -> tuple[str, list[Finding]]:
        return _normalize_source(self.source)

    @property
    def text(self) -> str:
        return self._normalized[0]

    @property
    def hygiene(self) -> list[Finding]:
        return self._normalized[1]

    @functools.cached_property
    def lines(self) -> list[str]:
        return self.text.splitlines()

    @functools.cached_property
    def ranges(self) -> list[tuple[int, int]] | None:
        return _changed_line_ranges(self.path, self.project_root)

    @functools.cached_property
    def doctree(self) -> docutils.nodes.document:
        return _helpers._parse_rst(self.path, text=self.text)


class _DocumentInlineMixin(_DocumentCore):
    """Inline-markup domain: consumed by check_nested_inline_markup's own
    warning and check_directives' misdiagnosis guard — nothing else in
    Document needs this, so it depends on _DocumentCore alone."""

    @functools.cached_property
    def nested_inline_by_node(self) -> dict[int, tuple[docutils.nodes.Node, ...]]:
        """Successful explicit inline constructs found inside each outer span.

        Both the dedicated warning and check_directives' misdiagnosis guard
        consume this map in one CLI run.  Cache the expensive grammar probes on
        the same read-only Document lifetime so each outer node is re-parsed
        exactly once, not once per consumer.
        """
        result: dict[int, tuple[docutils.nodes.Node, ...]] = {}
        for outer in _findall_node_types(self.doctree, _INLINE_CONTAINER_TYPES):
            nested = _nested_inline_nodes(outer, self.doctree)
            if nested:
                result[id(outer)] = nested
        return result


class _DocumentProseMixin(_DocumentCore):
    """Prose domain: word-stats and check_homoglyphs' shared skip-list
    consumer — depends on _DocumentCore's doctree alone, not on the
    outline domain's entry-finder properties below."""

    @functools.cached_property
    def prose_text(self) -> str:
        """The document's prose: text the author wrote as text.

        Doctree Text nodes, skipping literal blocks (code is not prose),
        comments, raw passthrough, and generated topics (a
        ``.. contents::`` directive's title is apparatus, not content —
        it was rank 2 in the first raw-frequency probe).  Bare docutils:
        no Sphinx build or configuration involved.

        The parser's own voice is not the author's prose either: under
        bare docutils every :doc: role and Sphinx-only directive produces
        a system_message whose text ("unknown directive type", "no role
        entry") leaked into the word statistics — on the reference note
        (2025-06-25) the "top prose words" were doc/directive/role/
        unknown: docutils' error vocabulary, not Max's.  Found by the
        semantic-vs-deterministic comparison the test method prescribes:
        the AI reads the repetitions, the tool counts, disagreement is a
        bug on one side or the other.  _NON_PROSE_NODE_TYPES (shared with
        check_homoglyphs) is exactly this skip-list.
        """
        parts: list[str] = []
        for text_node in self.doctree.findall(docutils.nodes.Text):
            node: docutils.nodes.Node | None = text_node.parent
            skipped = False
            while node is not None:
                if isinstance(node, _NON_PROSE_NODE_TYPES):
                    skipped = True
                    break
                node = node.parent
            if not skipped:
                parts.append(str(text_node))
        return "\n".join(parts)


class _DocumentOutlineMixin(_DocumentCore):
    """Outline domain: every entry-finder consumed by --outline/--json and
    check_bare_filenames/toctree reporting — the largest single cluster,
    but still only dependent on _DocumentCore, not on the inline-markup
    or prose domains above.

    Each finder below takes ``doc: Document | None`` (the pre-split type,
    still correct: most of their other callers pass a real Document and
    some, like check_bare_filenames, use cross-domain attributes on it)
    — so passing `self` needs one cast per property here. Nobody ever
    instantiates this mixin on its own; it exists only as part of the
    composed Document below, so the cast states a fact, not a hope."""

    @functools.cached_property
    def outline(self) -> list[OutlineEntry]:
        return build_outline(self.path, doc=cast("Document", self))

    @functools.cached_property
    def block_quotes(self) -> list[BlockQuoteEntry]:
        return find_block_quotes(self.path, doc=cast("Document", self))

    @functools.cached_property
    def admonitions(self) -> list[AdmonitionEntry]:
        return find_admonitions(self.path, doc=cast("Document", self))

    @functools.cached_property
    def comments(self) -> list[CommentEntry]:
        return find_comments(self.path, doc=cast("Document", self))

    @functools.cached_property
    def lists(self) -> list[ListEntry]:
        return find_lists(self.path, doc=cast("Document", self))

    @functools.cached_property
    def code_blocks_heuristic(self) -> list[CodeBlockEntry]:
        return find_code_blocks_heuristic(self.path, doc=cast("Document", self))

    @functools.cached_property
    def tables(self) -> list[TableEntry]:
        return find_tables(self.path, doc=cast("Document", self))


class Document(_DocumentInlineMixin, _DocumentProseMixin, _DocumentOutlineMixin):
    """Read-only facade over one .rst file — stage 1 of the document
    model, composed from _DocumentCore plus its three domain mixins
    above. Every existing `document.outline`/`.tables`/`.text`/... call
    site keeps working unchanged: composition via inheritance preserves
    the exact same attribute surface (confirmed by direct probe: a
    diamond-shared _DocumentCore base plus functools.cached_property
    behaves identically whether attributes live on one class or are
    assembled from mixins, under both CPython and strict mypy).  What
    changes is where each domain's code CAN live once cli.py is
    eventually split into modules: each mixin above already depends on
    _DocumentCore alone, never on a sibling mixin, so a future outline
    module only needs to import _DocumentCore, not the prose or
    inline-markup domains bundled with it today.
    """


def _resolve_document(path: pathlib.Path, doc: Document | None) -> Document:
    """Return *doc* if the caller already has one, else construct a fresh
    Document for *path* — the one-liner every checker/reporter used to
    duplicate inline (14 call sites, found by code review): a caller
    chaining off another Document (e.g. via Document.tables/.outline)
    passes it through and never re-reads or re-parses the file; a caller
    with none still gets one lazily, on first touch."""
    return doc if doc is not None else Document(path)


# --outline's own preview length for code-block/blockquote entries (Max,
# 2026-07-20) — deliberately separate from _BOLD_PREVIEW_LEN above (the
# bold-related findings' own text preview, default and --verbose alike):
# different feature, different reader, no reason the two should move
# together.
_OUTLINE_PREVIEW_LEN = 74


def _outline_preview(text: str) -> str:
    """Whitespace-collapsed, length-bounded content preview for --outline's
    code-block/blockquote entries: no leading/trailing or doubled internal
    spaces (any whitespace run, including newlines, collapses to one
    space), truncated with '...' when it doesn't fit — a quick identity,
    not the content."""
    collapsed = " ".join(text.split())
    if len(collapsed) > _OUTLINE_PREVIEW_LEN:
        collapsed = collapsed[:_OUTLINE_PREVIEW_LEN] + "..."
    return collapsed


# Known directive names for the mistyped-directive comment lint: docutils'
# own English directive-name mapping (derived, not hardcoded — includes
# aliases like 'code'/'code-block' equivalents docutils knows), plus the
# Sphinx directives common in this ecosystem.  'todo' is deliberately NOT
# in the supplement: '.. TODO: …' is an extremely common genuine-comment
# idiom, and flagging it would drown the signal in noise.
_SPHINX_DIRECTIVE_NAMES = frozenset(
    {
        "toctree",
        "code-block",
        "sourcecode",
        "literalinclude",
        "seealso",
        "index",
        "glossary",
        "only",
        "highlight",
        "versionadded",
        "versionchanged",
        "deprecated",
        "centered",
        "hlist",
    }
)


_KNOWN_DIRECTIVE_NAMES = frozenset(docutils.parsers.rst.languages.en.directives) | _SPHINX_DIRECTIVE_NAMES


# First line of a comment that looks like a directive typed with ONE colon:
# 'code: bash', 'note:', 'toctree:pages'.  (?!:) exists only for symmetry —
# a valid 'name::' line would have parsed as a directive, not a comment.
_MISTYPED_DIRECTIVE_RE = re.compile(r"([\w-]+):(?!:)")


def build_outline(
    path: pathlib.Path,
    doc: Document | None = None,
    doctree: docutils.nodes.document | None = None,
) -> list[OutlineEntry]:
    """Return every section heading in *path*, in document order.

    depth is this document's own nesting depth (1 = top-level), as docutils
    itself resolved it from first-appearance order — independent of
    check_hierarchy's own HIERARCHY ranking, so the same character can
    legitimately report a different depth in a different file.
    char is the literal adornment character read back from the source at
    the title's underline. Always whole-document — outline context is never
    scoped to changed lines, unlike Finding-producing checks.
    """
    document = _resolve_document(path, doc)
    tree = doctree if doctree is not None else document.doctree
    lines = document.lines
    raw: list[tuple[int, int, str, str, int, int]] = []  # (+ block_start)
    for sec in tree.findall(docutils.nodes.section):
        title_node = sec.children[0]
        underline_row = title_node.line  # docutils reports the underline's 1-based line
        if not isinstance(underline_row, int):
            continue
        title_row = underline_row - 1
        underline_idx = underline_row - 1
        char = "?"
        if 0 <= underline_idx < len(lines):
            underline = lines[underline_idx].strip()
            if _is_adornment(underline):
                char = underline[0]
        depth = 1
        n: docutils.nodes.Node | None = sec.parent
        while n is not None:
            if isinstance(n, docutils.nodes.section):
                depth += 1
            n = n.parent
        children = 0
        for candidate in sec.findall(docutils.nodes.section):
            if candidate is sec:
                continue
            parent = candidate.parent
            while parent is not None and not isinstance(parent, docutils.nodes.section):
                parent = parent.parent
            if parent is sec:
                children += 1
        # The section's block starts at the overline when present — the
        # boundary the PREVIOUS section's extent must stop before.
        has_overline = title_row >= 2 and _is_adornment(lines[title_row - 2].strip())
        block_start = title_row - 1 if has_overline else title_row
        raw.append((title_row, depth, char, title_node.astext(), children, block_start))

    # Extents: a section runs to the line before the next same-or-shallower
    # section's block (findall order is document order), or to EOF; trailing
    # blank separator lines are trimmed.
    entries: list[OutlineEntry] = []
    for i, (title_row, depth, char, title, children, _bs) in enumerate(raw):
        nxt = next((r for r in raw[i + 1 :] if r[1] <= depth), None)
        end = (nxt[5] - 1) if nxt is not None else len(lines)
        while end > title_row and not lines[end - 1].strip():
            end -= 1
        entries.append(OutlineEntry(title_row, depth, char, title, children, end))
    return entries


def find_admonitions(path: pathlib.Path, doc: Document | None = None) -> list[AdmonitionEntry]:
    """Return every admonition in *path*, in document order.

    Bare docutils, like find_block_quotes/find_tables — a real Sphinx
    build adds no admonition-type information beyond what bare docutils
    already resolves (docutils.nodes.Admonition covers all 10 kinds
    uniformly), so there is no verified/heuristic split.  depth is
    _block_depth — enclosing sections AND enclosing list nesting, same
    as every other entry kind (2026-07-26).  Found live (2026-07-22):
    a ".. important::" tl;dr this project itself wrote for
    check_rst.rst was entirely invisible to --outline — docutils parses
    it fine, check_rst simply had no entry kind for it.
    """
    document = _resolve_document(path, doc)
    lines = document.lines
    entries: list[AdmonitionEntry] = []
    for node in document.doctree.findall(docutils.nodes.Admonition):
        depth = _block_depth(node)

        title: str | None = None
        body_children = node.children
        if body_children and isinstance(body_children[0], docutils.nodes.title):
            title = body_children[0].astext()
            body_children = body_children[1:]

        preview = _outline_preview(" ".join(c.astext() for c in body_children))
        start = _node_line(node)
        entries.append(
            AdmonitionEntry(
                start,
                depth,
                node.__class__.__name__,
                title,
                preview,
                _indented_extent(lines, start),
            )
        )
    return entries


def find_block_quotes(path: pathlib.Path, doc: Document | None = None) -> list[BlockQuoteEntry]:
    """Return every top-level blockquote in *path*, in document order.

    Bare docutils — blockquotes need no Sphinx environment, so unlike
    code-blocks there is no verified/heuristic split: the same function
    serves both --outline modes.  A quote nested inside another quote is
    not reported separately (the outer entry's preview covers the
    subtree).  depth is _block_depth — enclosing sections AND enclosing
    list nesting, same as every other entry kind (2026-07-26).
    """
    document = _resolve_document(path, doc)
    entries: list[BlockQuoteEntry] = []
    for bq in document.doctree.findall(docutils.nodes.block_quote):
        n: docutils.nodes.Node | None = bq.parent
        nested = False
        while n is not None:
            if isinstance(n, docutils.nodes.block_quote):
                nested = True
                break
            n = n.parent
        if nested:
            continue
        depth = _block_depth(bq)
        preview = _outline_preview(bq.astext())
        start = _node_line(bq)
        entries.append(BlockQuoteEntry(start, depth, preview, _indented_extent(document.lines, start)))
    return entries


def find_comments(path: pathlib.Path, doc: Document | None = None) -> list[CommentEntry]:
    """Return every comment in *path*, in document order.

    Bare docutils, same as blockquotes/admonitions/tables — no verified/
    heuristic split.
    """
    document = _resolve_document(path, doc)
    lines = document.lines
    entries: list[CommentEntry] = []
    for node in document.doctree.findall(docutils.nodes.comment):
        depth = _block_depth(node)

        text = node.astext()
        first = text.split("\n", 1)[0]
        m = _MISTYPED_DIRECTIVE_RE.match(first)
        suspicious = bool(m and m.group(1).lower() in _KNOWN_DIRECTIVE_NAMES)

        preview = _outline_preview(text)
        start = _node_line(node)
        entries.append(CommentEntry(start, depth, preview, suspicious, _indented_extent(lines, start)))
    return entries


def find_lists(path: pathlib.Path, doc: Document | None = None) -> list[ListEntry]:
    """Return every bullet/enumerated/definition list in *path*, in
    document order — bare docutils, no verified/heuristic split, same as
    blockquotes/admonitions/tables/comments."""
    document = _resolve_document(path, doc)
    lines = document.lines
    entries: list[ListEntry] = []

    for node in document.doctree.findall(docutils.nodes.bullet_list):
        container_depth = _block_depth(node)
        items = list(node.children)
        container_start = _node_line(node)
        container_end = _indented_extent(lines, _node_line(items[-1])) if items else container_start
        bullet = node.get("bullet", "*")
        entries.append(
            ListEntry(
                container_start,
                container_depth,
                "bullet",
                bullet,
                "",
                item_count=len(items),
                end=container_end,
            )
        )
        for item in items:
            start = _node_line(item)
            entries.append(
                ListEntry(
                    start,
                    container_depth + 1,
                    "bullet",
                    bullet,
                    _outline_preview(item.astext()),
                    end=_indented_extent(lines, start),
                )
            )

    for node in document.doctree.findall(docutils.nodes.enumerated_list):
        container_depth = _block_depth(node)
        items = list(node.children)
        container_start = _node_line(node)
        container_end = _indented_extent(lines, _node_line(items[-1])) if items else container_start
        first_marker = _enum_marker(node, 0)
        entries.append(
            ListEntry(
                container_start,
                container_depth,
                "enumerated",
                first_marker,
                "",
                item_count=len(items),
                end=container_end,
            )
        )
        for position, item in enumerate(items):
            start = _node_line(item)
            entries.append(
                ListEntry(
                    start,
                    container_depth + 1,
                    "enumerated",
                    _enum_marker(node, position),
                    _outline_preview(item.astext()),
                    end=_indented_extent(lines, start),
                )
            )

    for node in document.doctree.findall(docutils.nodes.definition_list_item):
        depth = _block_depth(node)
        term, definition = node.children[0], node.children[1]
        start = _node_line(node)
        entries.append(
            ListEntry(
                start,
                depth,
                "definition",
                term.astext(),
                _outline_preview(definition.astext()),
                end=_indented_extent(lines, start),
            )
        )

    return entries


# Directive-based tables carry their own syntax name in the source; bare
# grid/simple tables don't, so kind falls back to the border/rule shape.
_TABLE_DIRECTIVE_RE = re.compile(r"\.\.\s+(table|list-table|csv-table)::")


_TABLE_DIRECTIVE_KIND = {"table": "table", "list-table": "list", "csv-table": "csv"}


_GRID_TABLE_BORDER_RE = re.compile(r"^[ \t]*\+[-+]+\+[ \t]*$")


# 2+ '='-runs separated by whitespace — never a bare section underline
# (a single '=====' run), which is the one thing this must not match.
_SIMPLE_TABLE_RULE_RE = re.compile(r"^[ \t]*=+(?:[ \t]+=+)+[ \t]*$")


_TABLE_OPTION_RE = re.compile(r"^[ \t]+:([\w-]+):")


def _simple_table_end(lines: list[str], start: int) -> int | None:
    """Docutils' exact end-exclusive simple-table stopping predicate.

    ``start`` is the zero-based top rule.  ``None`` means no complete
    bottom was found; a mismatched rule is malformed rather than an end.
    Keeping this in the source-attribution module gives outline ranges and
    list-table replacement ranges one definition of the grammar boundary.
    """
    top_length = len(lines[start].strip())
    found = 0
    for cursor in range(start + 1, len(lines)):
        line = lines[cursor]
        if not _SIMPLE_TABLE_RULE_RE.match(line):
            continue
        if len(line.strip()) != top_length:
            raise ValueError("simple-table bottom/header rule does not match its top rule")
        found += 1
        if found == 2 or cursor + 1 == len(lines) or not lines[cursor + 1].strip():
            return cursor + 1
    return None


def _table_kind_and_start(lines: list[str], anchor: int) -> tuple[str, int]:
    """Best-effort kind + true start line (both 1-based) for the table
    whose earliest located AST line is *anchor* — either its <title>
    child's line (caption present) or the first content paragraph found
    inside it (no caption, so the anchor sits somewhere inside the table's
    own body).

    A directive's own line IS the anchor when there's a caption (docutils
    sets a '.. table:: Caption' title's .line to the directive's own
    line — confirmed directly).  Without a caption, the anchor is either
    still inside an indented directive body (scan upward past the
    indentation to the marker) or somewhere in a raw grid/simple table
    (scan upward, INCLUSIVE of the anchor itself, through consecutive
    border/rule lines to the topmost one) — inclusive because which line
    docutils locates here is version-dependent: confirmed directly that
    docutils 0.23 (gl63) sets the <table> node's OWN .line to the TOP
    border, while this host's docutils leaves it unset and the first
    locatable line is the header content row one line below the border;
    scanning inclusive of the anchor handles both without caring which
    one this docutils build gave us.  KNOWN, ACCEPTED limitation: a
    captionless, headerless directive table (no thead, no title) can't be
    told apart from this scan if its body's own indentation is ambiguous;
    falls back to kind='table' at the anchor itself.
    """
    anchor_idx = anchor - 1
    if not (0 <= anchor_idx < len(lines)):
        return "table", anchor
    anchor_line = lines[anchor_idx]
    m = _TABLE_DIRECTIVE_RE.match(anchor_line.strip())
    if m:
        return _TABLE_DIRECTIVE_KIND[m.group(1)], anchor
    # A directive can begin in the first content line of a list item —
    # notably inside a list-table cell (``* - .. table::``).  The table
    # title's line then points at the list marker, so a start-anchored
    # directive match misses the real nested directive and the upward
    # fallback incorrectly attributes it to the enclosing list-table.
    # Only accept a directive after a list marker here; ``| .. table::``
    # inside an aligned-table cell is virtual parsed content and is not
    # independently editable in the physical source.
    list_item_directive = re.match(
        r"^[ \t]*(?:(?:[*+-]|\d+[.)])[ \t]+)+(\.\.\s+(table|list-table|csv-table)::)",
        anchor_line,
    )
    if list_item_directive:
        return _TABLE_DIRECTIVE_KIND[list_item_directive.group(2)], anchor

    # Where to start looking for the run of border/rule lines: the anchor
    # itself if it's ALREADY one (docutils 0.23/gl63 — table.line is the
    # top border), otherwise one line above it (this host's docutils —
    # the anchor is the header content row sitting just below the border).
    if _GRID_TABLE_BORDER_RE.match(anchor_line) or _SIMPLE_TABLE_RULE_RE.match(anchor_line):
        i = anchor_idx
    else:
        i = anchor_idx - 1
    top: int | None = None
    while i >= 0 and (_GRID_TABLE_BORDER_RE.match(lines[i]) or _SIMPLE_TABLE_RULE_RE.match(lines[i])):
        top = i
        i -= 1
    if top is not None:
        kind = "grid" if lines[top].lstrip().startswith("+") else "simple"
        return kind, top + 1

    anchor_indent = len(anchor_line) - len(anchor_line.lstrip())
    i = anchor_idx - 1
    while i >= 0:
        line = lines[i]
        if not line.strip():
            i -= 1
            continue
        if len(line) - len(line.lstrip()) >= anchor_indent:
            i -= 1
            continue
        m = _TABLE_DIRECTIVE_RE.match(line.strip())
        return (_TABLE_DIRECTIVE_KIND[m.group(1)], i + 1) if m else ("table", anchor)
    return "table", anchor


def _table_end(lines: list[str], last_content_line: int, start_line: int | None = None) -> int:
    """Extend *last_content_line* (1-based) through any trailing grid
    border / simple-table rule that belongs to it — the bottom border a
    grid or simple table always ends on, which carries no line info of
    its own in the doctree (only cell paragraphs do).

    When *start_line* identifies a simple-table top rule or a table
    directive containing one, recover its end with Docutils' own
    matching-rule predicate first.  Unlike grid rows, a simple table's
    multi-line continuation has no leading marker, so AST content lines
    plus a local continuation scan cannot locate it.

    First extends through a grid table's own bare ``|``-led continuation
    lines, when the table's last row spans multiple physical source
    lines: docutils' own .line tracking only reports a multi-line cell's
    FIRST physical line, so *last_content_line* can land there instead
    of on the row's real last line — found live building list-table's
    own real-world acceptance fixture, where a border-only extension
    silently truncated a table whose last row was multi-line, not just
    for that feature's own use of this function. Deliberately two
    SEPARATE, sequential passes rather than one merged loop: once a
    border is found, scanning must stop there, never resume matching
    '|'-led lines afterward — a border is only ever followed by more
    table content when another full row (which last_content_line, being
    the max already, would already have reached) is still to come, never
    by an unrelated construct. Found by code review: a merged loop
    covering both cases in either order would keep absorbing a
    '|'-led construct immediately after the closing border into the
    table's own reported end, on top of legitimately malformed input
    where RST's own required blank line after a table is missing."""
    if start_line is not None:
        start_index = start_line - 1
        simple_start: int | None = None
        if 0 <= start_index < len(lines) and _SIMPLE_TABLE_RULE_RE.match(lines[start_index]):
            simple_start = start_index
        elif 0 <= start_index < len(lines) and _TABLE_DIRECTIVE_RE.match(lines[start_index].strip()):
            directive_indent = len(lines[start_index]) - len(lines[start_index].lstrip())
            for cursor in range(start_index + 1, len(lines)):
                line = lines[cursor]
                if not line.strip():
                    continue
                if len(line) - len(line.lstrip()) <= directive_indent:
                    break
                if _SIMPLE_TABLE_RULE_RE.match(line):
                    simple_start = cursor
                    break
        if simple_start is not None:
            simple_end = _simple_table_end(lines, simple_start)
            if simple_end is not None:
                return simple_end

    end = last_content_line
    i = last_content_line  # 0-based index of the line right after
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        end = i + 1
        i += 1
    while i < len(lines) and (_GRID_TABLE_BORDER_RE.match(lines[i]) or _SIMPLE_TABLE_RULE_RE.match(lines[i])):
        end = i + 1
        i += 1
    return end


def find_tables(path: pathlib.Path, doc: Document | None = None) -> list[TableEntry]:
    """Return every table in *path*, in document order.

    Bare docutils, like find_block_quotes — a real Sphinx build adds no
    table-type information (confirmed directly), so there is no verified/
    heuristic split here; the same function serves both --outline modes.
    depth is _block_depth — enclosing sections AND enclosing list
    nesting, same as every other entry kind (2026-07-26; found live: a
    list-table added inside a bullet item printed at the same depth as
    the bullet list container itself before this fix).
    """
    document = _resolve_document(path, doc)
    lines = document.lines
    entries: list[TableEntry] = []
    for table in document.doctree.findall(docutils.nodes.table):
        depth = _block_depth(table)

        caption: str | None = None
        anchor: int | None = None
        if table.children and isinstance(table.children[0], docutils.nodes.title):
            title_node = table.children[0]
            caption = title_node.astext()
            if isinstance(title_node.line, int):
                anchor = title_node.line
        if anchor is None:
            anchor = next((n.line for n in table.findall() if isinstance(n.line, int)), None)
        if anchor is None:
            continue  # no locatable content at all — nothing to report

        kind, start = _table_kind_and_start(lines, anchor)

        tgroup = next(table.findall(docutils.nodes.tgroup), None)
        cols = tgroup.get("cols", 0) if tgroup is not None else 0
        table_rows = list(table.findall(docutils.nodes.row))
        rows = len(table_rows)

        # Chain every row's cells in document order (header row first when
        # one exists, via thead-before-tbody document order) into one
        # string, THEN collapse+truncate — the whole table is the input,
        # same as a code-block's whole body feeding its own preview.
        all_cells = [c.astext() for row in table_rows for c in row.children if isinstance(c, docutils.nodes.entry)]
        preview = _outline_preview(" ".join(all_cells))

        content_lines = [n.line for n in table.findall() if isinstance(n.line, int)]
        last_content_line = max(content_lines) if content_lines else start
        end = _table_end(lines, last_content_line, start)

        entries.append(TableEntry(start, depth, kind, (rows, cols), caption, preview, end))
    return entries


# Sphinx treats "code-block", "code", and "sourcecode" as identical aliases
# for the same CodeBlock directive (confirmed by direct testing: all three
# produce the same "language" node attribute under a real Sphinx env) — a
# downstream project's docs use ".. code::" exclusively, never
# ".. code-block::", so matching only the long form missed 100% of its 75
# real code-blocks.
_CODE_BLOCK_MARKER_RE = re.compile(r"^[ \t]*\.\. (?:code-block|code|sourcecode)::[ \t]*(\S*)[ \t]*$")


# literalinclude's own argument is a file path, not a language — its
# language (if any) comes from a ":language: X" option line immediately
# following the directive, found separately via _find_directive_option.
_LITERALINCLUDE_MARKER_RE = re.compile(r"^[ \t]*\.\. literalinclude::")


_OPTION_LINE_RE = re.compile(r"^[ \t]+:([\w-]+):[ \t]*(.*?)[ \t]*$")


def _find_directive_option(lines: list[str], start: int, name: str) -> str | None:
    """Return the value of option *name* in the directive-option block
    starting at 0-based *start*, or None if absent.

    Directive options are consecutive indented ":name: value" lines
    immediately after the directive marker, ending at the first blank or
    non-option-shaped line.
    """
    for line in lines[start:]:
        if not line.strip():
            break
        m = _OPTION_LINE_RE.match(line)
        if not m:
            break
        if m.group(1) == name:
            return m.group(2) or None
    return None


def find_code_blocks_heuristic(path: pathlib.Path, doc: Document | None = None) -> list[CodeBlockEntry]:
    """Return every code-block-like marker line found by pure text search.

    Matches all three Sphinx code-block aliases ("code-block", "code",
    "sourcecode") plus ".. literalinclude::" — a real corpus differential
    test (calendar/2026/05/2026-05-04/Notes.rst) found the real Sphinx-based
    find_code_blocks also counts literalinclude, since it counts ANY
    literal_block with a "language" attribute regardless of which directive
    produced it.

    Used only when --sphinx-src is not given — the real find_code_blocks
    requires a Sphinx environment. No docutils/Sphinx parsing is involved at
    all, which is exactly what restores full recall for Sphinx-only options
    (:caption:/:linenos:/etc.) that break bare docutils parsing entirely
    (confirmed: those code-blocks silently vanish from the real Phase 1
    doctree, not just lose precise line info). For code-block/code/
    sourcecode, language is the explicit directive argument if given, else
    None (CodeBlock.run() always resolves SOME language, falling back to the
    project's highlight_language — unknown here, but the entry still exists).

    literalinclude is different: read directly from sphinx.directives.code.
    LiteralInclude.run(), it has NO such fallback — ':diff:' forces language
    'udiff', ':language:' sets it exactly, and otherwise the 'language'
    attribute is never set on the node at all. So a bare literalinclude (no
    :language:, no :diff:) is EXCLUDED here entirely, matching the real
    detector's "if lang is None: continue" for that same, genuinely
    unhighlighted node — found by a real corpus differential test
    (calendar/2026/05/2026-05-10/Notes.rst and others) that first showed the
    opposite mistake: including it with language=None produced 6 entries the
    real detector didn't have at all, not just a language mismatch.

    KNOWN, ACCEPTED limitation #1: unlike find_code_blocks, there is no AST
    here to guard against a marker merely quoted as example text inside
    another real code-block — it IS double-counted. This is the deliberate
    cost of dropping the AST cross-check to restore recall; see
    find_code_blocks for the version that avoids it (requires --sphinx-src).

    KNOWN, ACCEPTED limitation #2: "code", "code-block", and "sourcecode"
    are NOT fully equivalent aliases, confirmed by reading docutils'
    registry directly: "code" maps to sphinx.directives.patches.Code (option
    set: class/force/name/number-lines only — no caption, no linenos), while
    "code-block"/"sourcecode" map to the full sphinx.directives.code.
    CodeBlock (caption/linenos/emphasize-lines/dedent/etc.). This heuristic
    does not validate which options are legal for which alias — doing so
    would mean hardcoding a slice of Sphinx's own directive-class registry,
    the same cost/complexity already declined for :doc:/:ref:/toctree. A
    real corpus differential test (a "Sphinx essentials" cheatsheet, using
    ".. code:: rst" with ":caption:" — invalid for that alias, and a genuine
    pre-existing content bug independent of check_rst: Sphinx itself drops
    those blocks from the build) found 12 heuristic entries the real
    detector didn't have, all traceable to this cause.

    depth comes from build_outline's already-reliable section headings
    (unaffected by code-block option parsing issues): one level deeper than
    the nearest preceding heading, or 1 if none precede it at all.

    KNOWN, ACCEPTED limitation #3 (2026-07-26): unlike every OTHER block
    finder (find_admonitions/find_block_quotes/find_comments/find_tables/
    find_code_blocks), this one never touches the doctree at all, so it
    cannot use _block_depth — there is no node to walk ancestors of. A
    code-block nested inside a list item therefore gets the SAME depth
    it would have directly under the enclosing heading, one level
    shallower than the AST-aware finders would report for the identical
    shape. Consistent with limitations #1/#2 above: the deliberate cost
    of dropping the AST cross-check to restore recall when no
    --sphinx-src is given.
    """
    document = _resolve_document(path, doc)
    lines = document.lines
    headings = document.outline
    entries: list[CodeBlockEntry] = []
    for i, line in enumerate(lines):
        m = _CODE_BLOCK_MARKER_RE.match(line)
        if m:
            lang = m.group(1) or None
        elif _LITERALINCLUDE_MARKER_RE.match(line):
            # Unlike code-block, LiteralInclude.run() has no config/env
            # fallback: :diff: forces 'udiff', :language: sets it exactly,
            # and otherwise the attribute is never set at all — so a bare
            # literalinclude is excluded here too, matching the real
            # detector's "if lang is None: continue" for the same node.
            if _find_directive_option(lines, i + 1, "diff") is not None:
                lang = "udiff"
            else:
                lang = _find_directive_option(lines, i + 1, "language")
                if lang is None:
                    continue
        else:
            continue

        lineno = i + 1
        depth = 1
        for heading in headings:
            if heading.lineno <= lineno:
                depth = heading.depth + 1
            else:
                break
        end = _indented_extent(lines, lineno)
        # Preview skips the directive's own ':option:' lines and the blank
        # separator before the actual content starts — the same shape
        # _find_directive_option already scans, just walked to its end
        # instead of stopping at one named option.
        content_start = lineno  # 0-based index of the line right after the marker
        while content_start < end and _OPTION_LINE_RE.match(lines[content_start]):
            content_start += 1
        while content_start < end and not lines[content_start].strip():
            content_start += 1
        preview = _outline_preview("\n".join(lines[content_start:end]))
        entries.append(CodeBlockEntry(lineno, depth, lang, preview, end))
    return entries


def _inline_kind(node: docutils.nodes.Node) -> str:
    """Return an author-facing name for an inline node kind."""
    if isinstance(node, docutils.nodes.strong):
        return "bold"
    if isinstance(node, docutils.nodes.emphasis):
        return "emphasis"
    if isinstance(node, docutils.nodes.literal):
        return "inline literal"
    if isinstance(node, docutils.nodes.title_reference):
        return "interpreted text"
    return type(node).__name__.replace("_", " ")


def _is_implicit_reference(node: docutils.nodes.Node) -> bool:
    """True for URI/email recognition that used no inline-markup syntax.

    Inliner.parse deliberately performs implicit recognition after explicit
    markup.  A URL inside ``literal text`` therefore becomes a reference node
    when re-parsed, but no nested delimiters or role were present.  Its
    refuri plus rawsource==visible-text shape distinguishes it from explicit
    named, phrase, and embedded-link references.
    """
    return isinstance(node, docutils.nodes.reference) and "refuri" in node and str(node.rawsource) == str(node.astext())


def _nested_inline_nodes(
    outer: docutils.nodes.Node,
    document: docutils.nodes.document,
) -> tuple[docutils.nodes.Node, ...]:
    """Re-parse one outer inline span and return explicit inner constructs.

    This is intentionally docutils' Inliner, not a delimiter regex: its own
    whitespace, escape, role, and end-string predicates decide whether the
    leftover text is valid inline markup.  The probe uses a fresh document so
    references/targets discovered during re-parse cannot mutate the real
    doctree's registries or influence later checks.

    Problematic nodes represent invalid or unmatched syntax, not a complete
    nested construct.  Implicit URI/email links are excluded separately by
    _is_implicit_reference because recognition alone does not prove source
    markup was nested.
    """
    CALL_COUNTS["_nested_inline_reparse"] += 1
    probe = docutils.utils.new_document(f"{document.get('source', '<string>')}:inline-probe", document.settings)
    inliner = docutils.parsers.rst.states.Inliner()
    inliner.init_customizations(probe.settings)
    language = docutils.parsers.rst.languages.get_language(probe.settings.language_code, probe.reporter)
    memo = docutils.parsers.rst.states.Struct(
        document=probe,
        reporter=probe.reporter,
        language=language,
        title_styles=[],
        section_level=0,
        section_bubble_up_kludge=False,
        inliner=inliner,
    )
    reparsed, _messages = inliner.parse(str(outer.astext()), _inline_node_line(outer), memo, probe)
    return tuple(
        node
        for node in reparsed
        if not isinstance(node, (docutils.nodes.Text, docutils.nodes.problematic)) and not _is_implicit_reference(node)
    )
