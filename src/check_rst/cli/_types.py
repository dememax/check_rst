# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Pure data types shared across check_rst.cli — check_rst project

from __future__ import annotations

import dataclasses
import enum
from typing import TYPE_CHECKING

import docutils.nodes
import docutils.statemachine

if TYPE_CHECKING:
    import pathlib


class Severity(enum.StrEnum):
    """Finding.severity's two levels. A StrEnum (not a plain Enum): members
    compare equal to and format identically to the plain "ERROR"/"WARNING"
    strings the CLI output, JSON schema, and _WARNING_RE regex group all
    already commit to — found by code review: a bare str field compared
    via ~8 scattered string literals had no type-checker signal to catch
    a mistyped literal like "Warning" (silently failing every downstream
    == comparison). str(Severity.ERROR) == "ERROR", not "Severity.ERROR"
    (confirmed by direct probe) — dataclasses.asdict()+json.dumps() and
    every f"{finding.severity}" call site keep their exact prior output."""

    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclasses.dataclass(frozen=True, slots=True)
class Finding:
    """A lint finding with a severity level (ERROR or WARNING)."""

    lineno: int
    severity: Severity
    text: str

    def __str__(self) -> str:
        return f"{self.lineno}: {self.severity}: {self.text}"

    def __contains__(self, item: object) -> bool:
        """Support ``"substring" in finding`` for test assertions."""
        if not isinstance(item, str):
            return False
        return item in str(self)


@dataclasses.dataclass(frozen=True, slots=True)
class FixCounts:
    """Structured counts for the deterministic mutation stages."""

    bom: int = 0
    crlf: int = 0
    lone_cr: int = 0
    line_separators: int = 0
    control_whitespace: int = 0
    trailing_whitespace: int = 0
    structural_lines: int = 0

    def with_structural_lines(self, count: int) -> FixCounts:
        """Return these hygiene counts plus the Phase 1 line-change count."""
        return dataclasses.replace(self, structural_lines=count)

    def describe(self) -> str:
        """Return stable, human-readable non-zero categories."""
        categories = (
            ("BOM", self.bom),
            ("CRLF line endings", self.crlf),
            ("lone CR line endings", self.lone_cr),
            ("exotic line separators", self.line_separators),
            ("control whitespace", self.control_whitespace),
            ("trailing whitespace lines", self.trailing_whitespace),
            ("structural lines", self.structural_lines),
        )
        return ", ".join(f"{label} {count}" for label, count in categories if count)


@dataclasses.dataclass(frozen=True, slots=True)
class FixPlan:
    """A fully computed, converged file mutation that has not been written."""

    path: pathlib.Path
    original: str
    fixed: str
    counts: FixCounts

    @property
    def changed(self) -> bool:
        return self.original != self.fixed


@dataclasses.dataclass(frozen=True, slots=True)
class FixResult:
    """The structured outcome of applying one :class:`FixPlan`."""

    path: pathlib.Path
    changed: bool
    counts: FixCounts


@dataclasses.dataclass(frozen=True, slots=True)
class TitleBlock:
    """A complete overline+title+underline block, found by raw-line scan."""

    index: int  # 0-based index of the title line in the lines list
    over: str
    title: str
    under: str

    @property
    def lineno(self) -> int:
        """1-based line number of the title text."""
        return self.index + 1


@dataclasses.dataclass(frozen=True, slots=True)
class UnderlineOnlyCandidate:
    """An adornment line glued directly under text — an underline-only title."""

    index: int  # 0-based index of the adornment (underline) line
    title: str  # the text line directly above (unstripped)
    under: str


@dataclasses.dataclass(frozen=True, slots=True)
class BlockCorrection:
    """A TitleBlock's canonical form, plus which rules it currently violates.

    Produced by analyze_block.  Blank-line requirements are deliberately
    NOT here: the checker evaluates them against the original lines and
    the fixer against the buffer it is mutating — surrounding context,
    not block-local rules.
    """

    char: str  # canonical adornment character (the overline's)
    title: str  # canonical title (stripped)
    expected: int  # canonical adornment length (display width + 2)
    char_mismatch: bool
    wrong_length: bool
    title_spaces: bool


@dataclasses.dataclass(frozen=True, slots=True)
class TextSpaceCounts:
    """Accepted editorial space-run changes, separated by visible scope."""

    title_runs: int = 0
    prose_runs: int = 0

    def __add__(self, other: TextSpaceCounts) -> TextSpaceCounts:
        return TextSpaceCounts(
            title_runs=self.title_runs + other.title_runs,
            prose_runs=self.prose_runs + other.prose_runs,
        )

    @property
    def total(self) -> int:
        return self.title_runs + self.prose_runs

    def describe(self) -> str:
        """Return stable, grammatical non-zero editorial categories."""
        parts: list[str] = []
        if self.title_runs:
            noun = "run" if self.title_runs == 1 else "runs"
            parts.append(f"{self.title_runs} title space {noun} collapsed")
        if self.prose_runs:
            noun = "run" if self.prose_runs == 1 else "runs"
            parts.append(f"{self.prose_runs} prose space {noun} collapsed")
        return ", ".join(parts)


@dataclasses.dataclass(frozen=True, slots=True)
class _TextSpaceEdit:
    """One raw-source ASCII-space run and its intended visible-text owner."""

    start: int
    end: int
    scope: str  # ``title`` or ``prose``


@dataclasses.dataclass(frozen=True, slots=True)
class _TextSpaceEvidence:
    """Canonical tree plus eligible repeated-space counts by scope."""

    tree: object
    counts: TextSpaceCounts


# Shared by Document.prose_text and check_homoglyphs: what counts as
# author-facing prose rather than markup apparatus.  Code, comments, raw
# passthrough, and generated topics (a '.. contents::' directive's own
# title) are not something an author "wrote" as content — see
# Document.prose_text's docstring for the system_message/parser-vocabulary
# story that motivated the last entry.
_NON_PROSE_NODE_TYPES = (
    docutils.nodes.literal_block,
    docutils.nodes.comment,
    docutils.nodes.raw,
    docutils.nodes.topic,
    docutils.nodes.system_message,
)


_INLINE_CONTAINER_TYPES = (docutils.nodes.strong, docutils.nodes.emphasis, docutils.nodes.literal)


@dataclasses.dataclass(frozen=True, slots=True)
class OutlineEntry:
    """A single section heading, as reported by --outline.

    children is the number of DIRECT subsections — shown only when
    non-zero, so each outline line is self-contained data (an AI or a
    grep consuming lines individually doesn't have to reconstruct the
    tree to know a section has children), while leaf entries keep the
    exact historical format.

    docname (2026-07-26): set only for a heading recursively pulled in
    from ANOTHER file via find_toctrees — the first entry kind whose
    items can point outside the file being outlined.  Empty/None for
    every local heading, matching every OutlineEntry ever constructed
    before this field existed.  A cross-file heading reuses this SAME
    class deliberately, not a separate one: --sections-only's own
    ``isinstance(e, OutlineEntry)`` filter must keep it (it is a real
    section, just from elsewhere), while the toctree CONTAINER marker
    (ToctreeEntry) is correctly treated as a leaf and hidden — caught
    before implementation began (Max: "--sections-only shouldn't stop
    treating toctree elements").
    """

    lineno: int
    depth: int
    char: str
    title: str
    children: int = 0
    end: int = 0  # last line of the section's content (its extent)
    docname: str | None = None

    def __str__(self) -> str:
        return self.formatted()

    def formatted(self, extra: list[str] | None = None) -> str:
        # Lean format: line RANGE, adornment CHAR, then title (Max,
        # 2026-07-19: "inform the range, not only the start" — the extent
        # is what a follow-up sed/Read needs, previously re-derived from
        # the NEXT entry).  Depth is the indentation (4 spaces per level —
        # recoverable from a lone grepped line).
        #
        # The char WAS omitted here (2026-07-18: "repeating it on every
        # entry was pure noise", relying on the per-document legend
        # instead) — reversed 2026-07-20 after repeated real mistakes
        # writing a NEW heading's placeholder: choosing the adornment
        # character correctly means knowing the established char at that
        # EXACT depth, and cross-referencing the legend against indentation
        # in a large, evolving document is exactly the kind of counting
        # task an LLM is unreliable at — the same class of problem the
        # tool exists to take off the AI's hands for adornment LENGTH.
        # Now every grepped line carries its own answer directly, no
        # legend cross-reference needed: pick the char shown on the line
        # you want to add a sibling under.
        #
        # extra: additional bracket items beyond the subsection count (Max,
        # 2026-07-20) — e.g. nested code-block/blockquote totals, which this
        # entry alone can't know (they come from OTHER entries' line ranges),
        # so _print_outline_entries computes and passes them in; plain str()
        # stays self-contained with subsections only.
        indent = "    " * (self.depth - 1)
        pos = f"{self.lineno}-{self.end}" if self.end > self.lineno else f"{self.lineno}"
        if self.docname:
            pos = f"{self.docname}:{pos}"
        base = f"{indent}{pos}:{self.char} {self.title}"
        parts = []
        if self.children:
            plural = "s" if self.children != 1 else ""
            parts.append(f"{self.children} subsection{plural}")
        if extra:
            parts.extend(extra)
        if parts:
            return f"{base} [{', '.join(parts)}]"
        return base

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return item in str(self)


@dataclasses.dataclass(frozen=True, slots=True)
class CodeBlockEntry:
    """A single real `.. code-block::` directive, as reported by --outline.

    preview is a limited beginning of the block's own content — one
    collapsed line, truncated — the same quick-identity contract as
    BlockQuoteEntry.preview (Max, 2026-07-20: "let's add the beginning of
    the block to the line about it")."""

    lineno: int
    depth: int
    language: str | None
    preview: str = ""
    end: int = 0  # last line of the directive's indented content

    def __str__(self) -> str:
        indent = "    " * (self.depth - 1)
        lang = self.language if self.language is not None else "no language"
        pos = f"{self.lineno}-{self.end}" if self.end > self.lineno else f"{self.lineno}"
        base = f"{indent}{pos}: code-block ({lang})"
        return f"{base}: {self.preview}" if self.preview else base

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return item in str(self)


@dataclasses.dataclass(frozen=True, slots=True)
class BlockQuoteEntry:
    """A single blockquote, as reported by --outline.

    Quote zones are semantically significant since the blockquote
    exemption (nothing inside them is ever a heading-substitute finding):
    seeing them in the outline explains absent warnings and shows
    composition — a note that is 80% quotation reads differently from one
    that is 80% original prose.  preview is a limited beginning of the
    quote's text — one collapsed line, ellipsis-truncated — a quick
    identity, not the content.
    """

    lineno: int
    depth: int
    preview: str
    end: int = 0  # last line of the quoted block

    def __str__(self) -> str:
        indent = "    " * (self.depth - 1)
        pos = f"{self.lineno}-{self.end}" if self.end > self.lineno else f"{self.lineno}"
        return f'{indent}{pos}: blockquote "{self.preview}"'

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return item in str(self)


@dataclasses.dataclass(frozen=True, slots=True)
class AdmonitionEntry:
    """A ``.. note::``/``.. warning::``/etc. admonition, as reported by
    --outline.

    kind is the directive name docutils resolved: one of the 9 named
    admonitions (attention, caution, danger, error, hint, important,
    note, tip, warning) or the generic ``admonition``.  title is the
    generic form's own ``.. admonition:: Title`` argument — the other
    nine never have one, matching a table's optional caption.  preview
    is the body's own content, collapsed and truncated exactly like
    blockquote/code-block/table's own preview — the whole body is the
    input, not just its first line."""

    lineno: int
    depth: int
    kind: str
    title: str | None
    preview: str
    end: int = 0

    def __str__(self) -> str:
        indent = "    " * (self.depth - 1)
        pos = f"{self.lineno}-{self.end}" if self.end > self.lineno else f"{self.lineno}"
        base = f"{indent}{pos}: admonition ({self.kind})"
        if self.title:
            base += f', "{self.title}"'
        return f"{base}: {self.preview}" if self.preview else base

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return item in str(self)


@dataclasses.dataclass(frozen=True, slots=True)
class CommentEntry:
    """A single comment (``.. text`` with no ``::``), as reported by
    --outline.

    The mistyped-directive WARNING (visit_comment, above) can only ever
    catch what it recognizes — a known directive name typo'd with a
    single colon on the comment's first line.  A typo of an unlisted
    name, or one buried past the first line, stays invisible to that
    heuristic (Max, 2026-07-22: "we cannot cover all cases... they could
    be more complex cases").  Showing every comment in --outline, same
    as blockquote/code-block/table/admonition, closes that blind spot
    generically instead of chasing more regex cases.  suspicious reuses
    the exact same heuristic as the WARNING, so the flagged case is
    visible right next to its own text instead of a separate,
    disconnected report.
    """

    lineno: int
    depth: int
    preview: str
    suspicious: bool
    end: int = 0

    def __str__(self) -> str:
        indent = "    " * (self.depth - 1)
        pos = f"{self.lineno}-{self.end}" if self.end > self.lineno else f"{self.lineno}"
        base = f'{indent}{pos}: comment "{self.preview}"'
        if self.suspicious:
            base += " [suspicious — looks like a mistyped directive]"
        return base

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return item in str(self)


@dataclasses.dataclass(frozen=True, slots=True)
class ListEntry:
    """A bullet list, enumerated list, or definition list, as reported by
    --outline (Max, 2026-07-26).

    Two-level for bullet/enumerated lists: a CONTAINER entry for the
    whole list (item_count set, marker is the bullet character or the
    first item's rendered numeral, depth = enclosing_section_depth+1)
    and one entry per ITEM nested one level deeper (item_count=None,
    marker/preview specific to that item) — so --outline-depth can hide
    a long list's individual items while keeping the list's own
    existence and count visible, the same "depth trims display, never
    information" contract sections already use.  Definition lists are
    flatter (Max: "one entry per item"): each definition_list_item
    stands alone with no container — marker is the item's own term
    text, the natural per-item unit since every item has a genuinely
    distinct term (unlike a bullet list's one shared bullet character),
    the same title+body shape as AdmonitionEntry (term=title,
    definition=body).
    """

    lineno: int
    depth: int
    kind: str  # "bullet", "enumerated", "definition"
    marker: str
    preview: str
    item_count: int | None = None  # set only on a bullet/enumerated container
    end: int = 0

    def __str__(self) -> str:
        indent = "    " * (self.depth - 1)
        pos = f"{self.lineno}-{self.end}" if self.end > self.lineno else f"{self.lineno}"
        if self.item_count is not None:
            plural = "s" if self.item_count != 1 else ""
            return f"{indent}{pos}: {self.kind} list ({self.marker!r}, {self.item_count} item{plural})"
        base = f'{indent}{pos}: "{self.marker}"' if self.kind == "definition" else f"{indent}{pos}: {self.marker}"
        return f"{base}: {self.preview}" if self.preview else base

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return item in str(self)


@dataclasses.dataclass(frozen=True, slots=True)
class TableEntry:
    """A single table, as reported by --outline.

    kind is the RST/Sphinx syntax that produced it — 'grid', 'simple',
    'table', 'list', or 'csv' — recovered by scanning the raw source: the
    docutils/Sphinx doctree keeps NO trace of which syntax produced a
    table node (confirmed directly: a grid table, a simple table, and the
    table/list-table/csv-table directives all produce the identical
    <table><tgroup>... shape, even under a real Sphinx build), so this is
    the one fact that only the source text still carries.  dims is
    (rows, cols) — the rows-x-columns convention (matrix notation, NumPy/
    pandas .shape, spreadsheet "RxC"), not cols-x-rows.  caption is the
    table's own title, if any (the '.. table::'/'.. list-table::'/
    '.. csv-table::' directive argument, or docutils' own <title> child)
    — None when the table has none.  preview chains every row's cells in
    document order ("A1 A2 A3 B1 B2 B3 ...", header row first when one
    exists) into a single line, then collapses and truncates it exactly
    like code-block's own preview (Max, 2026-07-20: "the same principle
    as for snippets for code blocks") — the WHOLE table's content is the
    input, same as a code-block's whole body, not just its first row."""

    lineno: int
    depth: int
    kind: str
    dims: tuple[int, int]
    caption: str | None
    preview: str
    end: int = 0

    def __str__(self) -> str:
        indent = "    " * (self.depth - 1)
        pos = f"{self.lineno}-{self.end}" if self.end > self.lineno else f"{self.lineno}"
        rows, cols = self.dims
        base = f"{indent}{pos}: Table ({self.kind}, {rows}x{cols})"
        if self.caption:
            base += f', "{self.caption}"'
        return f"{base}: {self.preview}" if self.preview else base

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return item in str(self)


@dataclasses.dataclass(frozen=True, slots=True)
class ParsedTable:
    """A grid/simple table's parsed structure — docutils' own tableparser
    output, reshaped only enough to be self-describing. colspecs is
    character column widths; each row is a list of cells in
    ``(morerows, morecols, line_offset, StringList)`` shape, or ``None``
    at a position a spanning cell above/to the left already covers —
    docutils' own convention, kept verbatim rather than reinterpreted."""

    colspecs: list[int]
    header_rows: list[list[tuple[int, int, int, docutils.statemachine.StringList] | None]]
    body_rows: list[list[tuple[int, int, int, docutils.statemachine.StringList] | None]]


@dataclasses.dataclass(frozen=True, slots=True)
class ListTableCandidate:
    """One table judged ready for conversion, or refused with a reason —
    never a silent skip; the caller reports every refusal. parsed and
    caption are populated only when refusal is None."""

    entry: TableEntry
    parsed: ParsedTable | None
    caption: str | None
    refusal: str | None


@dataclasses.dataclass(frozen=True, slots=True)
class ListTableFileResult:
    """One file's complete list-table run: which ordinals converted,
    every in-scope refusal (with its reason — never silent), and whether
    an unresolvable --only/--skip ordinal or a failed whole-file
    semantic-validation safety net rejected the file outright."""

    path: pathlib.Path
    original: str
    candidate: str
    converted: list[int]
    refusals: list[tuple[int, str]]
    unknown_ordinals: list[int]
    fatal: str | None

    @property
    def changed(self) -> bool:
        return self.fatal is None and self.candidate != self.original


@dataclasses.dataclass(frozen=True, slots=True)
class ReferenceEntry:
    """One role or toctree document reference, as reported by --refs.

    docname is the entry's OWN document — the referring file for an
    OUTGOING entry (find_references), the file pointing IN for an
    INCOMING entry (find_incoming_references); the same shape serves both
    directions.  For roles, target is the raw text the author wrote (a
    relative path for :doc:, a label id for :ref:/:term:).  For toctrees,
    target is Sphinx's resolved docname — including each document produced
    by a glob.  resolved is the real docname it points at, or None when a
    role reference is broken (Phase 3 already reports why — this is not a
    substitute for that WARNING).
    """

    docname: str
    lineno: int
    reftype: str
    target: str
    resolved: str | None

    def __str__(self) -> str:
        return f"{self.docname}:{self.lineno}: {self.reftype} -> {self.target}"


@dataclasses.dataclass(frozen=True, slots=True)
class ToctreeEntry:
    """A single ``.. toctree::`` directive, as reported by --outline
    (2026-07-26) — the container marker; the documents it points at
    appear immediately after it as OutlineEntry instances (docname
    set), each recursively expanded through ITS OWN toctrees in turn,
    via find_toctrees.

    maxdepth is the directive's own configured value (-1 when
    unspecified — Sphinx's own "unlimited" convention), shown as
    information about what the author configured for human HTML
    browsing.  find_toctrees' own recursion deliberately does NOT stop
    there: confirmed by direct probe against a real 2-level nested
    toctree project that Sphinx's own maxdepth-limited resolver
    (sphinx.environment.adapters.toctree.TocTree.get_toctree_for) would
    hide a real, reachable document one hop beyond the configured
    maxdepth — fine for a human clicking through an HTML sidebar one
    page at a time, wrong for an AI that wants to know the whole
    reachable project graph from one command.

    cycle is set instead of item_count/maxdepth when this entry
    represents a DETECTED CYCLE rather than a real toctree directive —
    find_toctrees stops descending into an already-visited docname on
    the current traversal path and leaves this marker in its place,
    visibly, rather than looping forever or failing silently (the same
    "never silent truncation" house rule as everywhere else in this
    tool).

    docname is set only when this directive belongs to a document pulled in
    from another file, matching OutlineEntry's provenance contract.  None
    therefore means local to the file being outlined; a non-empty value is
    public, self-identifying provenance in text, JSON, and --context.
    """

    lineno: int
    depth: int
    item_count: int = 0
    maxdepth: int = -1
    end: int = 0
    cycle: str | None = None
    docname: str | None = None

    def __str__(self) -> str:
        indent = "    " * (self.depth - 1)
        pos = f"{self.lineno}-{self.end}" if self.end > self.lineno else f"{self.lineno}"
        if self.docname:
            # A lone foreign container line must identify its source exactly
            # like a foreign OutlineEntry; local containers remain lean.
            pos = f"{self.docname}:{pos}"
        if self.cycle is not None:
            return (
                f"{indent}{pos}: toctree cycle — '{self.cycle}' is already an "
                "ancestor on this branch, not descending further"
            )
        maxdepth_label = "unlimited" if self.maxdepth < 0 else str(self.maxdepth)
        noun = "entry" if self.item_count == 1 else "entries"
        return f"{indent}{pos}: toctree ({self.item_count} {noun}, maxdepth={maxdepth_label})"

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return item in str(self)


class WordStatsUnavailable(RuntimeError):
    """A required provider for meaningful prose-word statistics is absent."""


class StopwordsUnavailable(WordStatsUnavailable):
    """Raised when sphinx.search's per-language stopword data can't be
    located under any attribute name this project has ever seen it use.
    Callers surface this as an explicit, counted WARNING — never a
    silently omitted statistic (the exact bug this exception replaces:
    confirmed on two dev hosts running different Sphinx versions, each
    using a DIFFERENT attribute casing for the same data — 8.2.3 defines
    lowercase ``english_stopwords`` directly on the module, 9.1.0
    re-exports uppercase ``ENGLISH_STOPWORDS`` from a private
    ``sphinx.search._stopwords`` package — so this has already changed
    at least twice and will likely change again)."""


@dataclasses.dataclass(frozen=True, slots=True)
class ContextMatch:
    """One addressable member of the heterogeneous outline entry stream.

    ``selector`` is the preferred user-facing identity.  Sections retain
    their stable autosectionlabel-shaped id; every entry also has a generated
    ``kind@line`` alias, which makes anonymous and future entry kinds
    addressable without teaching the resolver about each class.
    """

    index: int
    entry: object
    selector: str
    universal_selector: str
    kind: str
    source_docname: str
    match_texts: tuple[str, ...]
