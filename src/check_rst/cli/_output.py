# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Console output plumbing (budget sink, findings printer) — check_rst project

from __future__ import annotations

import collections
import contextlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import TextIO


from ._types import (
    AdmonitionEntry,
    BlockQuoteEntry,
    CodeBlockEntry,
    CommentEntry,
    ConditionalEntry,
    Finding,
    IncludeEntry,
    ListEntry,
    MergedEntry,
    OutlineEntry,
    Severity,
    TableEntry,
    ToctreeEntry,
    _plural,
)


class OutputBudgetSink:
    """A line-oriented report sink that retains only a bounded prefix.

    The checker still emits and computes its complete report.  This sink keeps
    the first ``limit - 2`` detail lines, counts all later records by their
    semantic kind, and reserves the final two lines for honest suppression
    statistics and the authoritative status supplied through
    :func:`_emit_final_status`.
    """

    def __init__(self, limit: int, target: TextIO) -> None:
        self.limit = limit
        self.target = target
        self.prefix: list[str] = []
        self.total = 0
        self.skipped_by_kind: collections.Counter[str] = collections.Counter()
        self.final_status: str | None = None
        self._pending = ""
        self._pending_kind = "detail"

    @property
    def encoding(self) -> str | None:
        return self.target.encoding

    def isatty(self) -> bool:
        return self.target.isatty()

    def fileno(self) -> int:
        return self.target.fileno()

    def write(self, text: str) -> int:
        if not self._pending:
            self._pending_kind = _OUTPUT_KIND
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._record(line, self._pending_kind)
            self._pending_kind = _OUTPUT_KIND
        return len(text)

    def flush(self) -> None:
        """Satisfy the text-stream protocol; finalization owns emission."""

    def set_final_status(self, text: str) -> None:
        self.final_status = text

    def _record(self, line: str, kind: str) -> None:
        self.total += 1
        if len(self.prefix) < self.limit - 2:
            self.prefix.append(line)
        else:
            self.skipped_by_kind[kind] += 1

    def finish(self, exit_code: int) -> None:
        if self._pending:
            self._record(self._pending, self._pending_kind)
            self._pending = ""

        shown = len(self.prefix)
        skipped = self.total - shown
        for line in self.prefix:
            self.target.write(f"{line}\n")

        classification = [
            f"{count} {kind}" for kind in ("ERROR", "WARNING", "outline") if (count := self.skipped_by_kind[kind])
        ]
        skipped_detail = f" ({', '.join(classification)})" if classification else ""
        statistics = (
            f"check_rst: output limited — {shown} of {self.total} detail line(s) "
            f"shown, {skipped} skipped{skipped_detail}; full output requires "
            f"{self.total + 2} lines"
        )
        if self.final_status is None:
            statistics += (
                "; run ended before normal summary — rerun without --max-output-lines for complete diagnostics"
            )
            outcome = "failed" if exit_code else "completed"
            self.final_status = f"check_rst: command {outcome} before producing a run summary, exit status {exit_code}"
        self.target.write(f"{statistics}\n{self.final_status}\n")
        self.target.flush()


_ACTIVE_OUTPUT_BUDGET: OutputBudgetSink | None = None


_OUTPUT_KIND = "detail"


@contextlib.contextmanager
def _report_kind(kind: str) -> Iterator[None]:
    """Tag lines emitted in this one-threaded process for sink statistics."""
    global _OUTPUT_KIND
    previous = _OUTPUT_KIND
    _OUTPUT_KIND = kind
    try:
        yield
    finally:
        _OUTPUT_KIND = previous


def _emit_final_status(text: str) -> None:
    """Emit normally, or reserve *text* as a bounded report's last line."""
    if _ACTIVE_OUTPUT_BUDGET is None:
        print(text)
    else:
        _ACTIVE_OUTPUT_BUDGET.set_final_status(text)


def _emit_report_line(text: str, kind: str = "detail") -> None:
    """Print one line with a semantic kind understood by the report sink."""
    with _report_kind(kind):
        print(text)


def _print_outline_entries(
    entries: list[MergedEntry],
    depth_limit: int | None,
    verbose: bool,
    sections_only: bool = False,
) -> None:
    """Print outline entries, honoring --outline-depth and --sections-only.

    Bounded output is never silent truncation (house rule): when a depth
    limit and/or --sections-only hides entries, a trailing note says how
    many and why.

    sections_only (2026-07-26) filters by KIND, not depth: every leaf
    entry (code-block/blockquote/table/admonition/comment/list) is
    suppressed regardless of how shallow it sits, unlike --outline-depth
    which bounds by depth regardless of kind — the two compose rather
    than overlap.  The levels:/blocks: legend and every heading's own
    bracketed counts are computed against the FULL entries list either
    way, never `shown` — a display filter trims display, never
    information, the same contract --outline-depth already established.

    verbose gates only the 'blocks:' whole-document summary line (Max,
    2026-07-20: verbosity-level inventory — the 'levels:' legend stays
    unconditional whenever --outline runs at all, matching its existing,
    unchanged behavior; 'blocks:' is the one promoted to --verbose-only).
    """
    shown = [
        e
        for e in entries
        if (depth_limit is None or e.depth <= depth_limit) and (not sections_only or isinstance(e, OutlineEntry))
    ]

    # Legend: the depth→char mapping with per-level section counts, plus the
    # document's total section/code-block/blockquote counts (Max,
    # 2026-07-20) — stated once and always for the WHOLE document, under a
    # depth limit it reveals what exists below the cut (the limit trims
    # entries, never information; two legend lines are not heavy).  In a
    # valid document each depth has one char; a malformed one lists all
    # observed chars for the depth, '/'-joined.
    level_chars: dict[int, list[str]] = {}
    level_counts: dict[int, int] = {}
    n_code = 0
    n_quotes = 0
    n_tables = 0
    n_admonitions = 0
    n_comments = 0
    n_lists = 0
    n_toctrees = 0
    n_cycles = 0
    n_includes = 0
    n_include_cycles = 0
    n_conditionals = 0
    for entry in entries:
        if isinstance(entry, OutlineEntry):
            # Cross-file headings (entry.docname set) are excluded from
            # THIS file's own levels: legend — they carry another
            # document's own adornment convention, which would pollute
            # what this legend promises: what chars/depths this file
            # itself uses (Max, 2026-07-26, implicit in the toctree
            # design: the legend answers "what do I pick for a new
            # sibling heading HERE", a question cross-file entries can't
            # answer for this file).
            if entry.docname is None:
                chars = level_chars.setdefault(entry.depth, [])
                if entry.char not in chars:
                    chars.append(entry.char)
                level_counts[entry.depth] = level_counts.get(entry.depth, 0) + 1
        elif isinstance(entry, ToctreeEntry):
            if entry.cycle is not None:
                n_cycles += 1
            else:
                n_toctrees += 1
        elif isinstance(entry, IncludeEntry):
            if entry.cycle is not None:
                n_include_cycles += 1
            else:
                n_includes += 1
        elif isinstance(entry, ConditionalEntry):
            n_conditionals += 1
        elif isinstance(entry, CodeBlockEntry):
            n_code += 1
        elif isinstance(entry, BlockQuoteEntry):
            n_quotes += 1
        elif isinstance(entry, TableEntry):
            n_tables += 1
        elif isinstance(entry, AdmonitionEntry):
            n_admonitions += 1
        elif isinstance(entry, CommentEntry):
            n_comments += 1
        elif isinstance(entry, ListEntry) and (entry.item_count is not None or entry.kind == "definition"):
            # Count the list as one unit (container, or a standalone
            # definition item) — never its individual bullet/enumerated
            # items, the same convention as a table counting once, not
            # once per row.
            n_lists += 1
    if level_chars:
        total_sections = sum(level_counts.values())
        legend = ", ".join(
            f"{depth} " + "/".join(repr(c) for c in chars) + f" ({level_counts[depth]})"
            for depth, chars in sorted(level_chars.items())
        )
        print(f"  levels: {legend}, {total_sections} {_plural(total_sections, 'section')} total")
    if verbose and (
        n_code
        or n_quotes
        or n_tables
        or n_admonitions
        or n_comments
        or n_lists
        or n_toctrees
        or n_cycles
        or n_includes
        or n_include_cycles
        or n_conditionals
    ):
        block_parts = []
        if n_code:
            block_parts.append(f"{n_code} {_plural(n_code, 'code block')}")
        if n_quotes:
            block_parts.append(f"{n_quotes} {_plural(n_quotes, 'blockquote')}")
        if n_tables:
            block_parts.append(f"{n_tables} {_plural(n_tables, 'table')}")
        if n_admonitions:
            block_parts.append(f"{n_admonitions} {_plural(n_admonitions, 'admonition')}")
        if n_comments:
            block_parts.append(f"{n_comments} {_plural(n_comments, 'comment')}")
        if n_lists:
            block_parts.append(f"{n_lists} {_plural(n_lists, 'list')}")
        if n_toctrees:
            block_parts.append(f"{n_toctrees} {_plural(n_toctrees, 'toctree')}")
        if n_cycles:
            block_parts.append(f"{n_cycles} {_plural(n_cycles, 'toctree cycle')}")
        if n_includes:
            block_parts.append(f"{n_includes} {_plural(n_includes, 'include')}")
        if n_include_cycles:
            block_parts.append(f"{n_include_cycles} {_plural(n_include_cycles, 'include cycle')}")
        if n_conditionals:
            block_parts.append(f"{n_conditionals} {_plural(n_conditionals, 'conditional')}")
        print(f"  blocks: {', '.join(block_parts)}")

    for entry in shown:
        if isinstance(entry, OutlineEntry):
            # Cumulative — everything anywhere in this section's line range,
            # including its subsections' own content (Max, 2026-07-20: asked
            # for whole-subtree totals, not direct-children-only, since
            # that's the simpler and more useful "how much is under this
            # heading" answer).  Computed against the FULL entries list,
            # never `shown` — a depth limit trims display, not information.
            #
            # entry.docname is not None (2026-07-26): a cross-file heading
            # pulled in via toctree recursion.  Its .lineno/.end live in
            # ANOTHER file's coordinate space — comparing them against
            # `entries`, which is this file's own local code/table/etc.
            # entries, would be a meaningless numeric coincidence, not a
            # real containment check (this listing never pulls a child
            # document's own code-blocks/tables/etc. in, only its headings
            # and toctrees), so nested counts are skipped entirely rather
            # than computed wrong.
            extra: list[str] = []
            if entry.docname is None:
                section_end = max(entry.end, entry.lineno)
                nested_code = sum(
                    1
                    for e in entries
                    if isinstance(e, CodeBlockEntry)
                    and e.provenance == entry.provenance
                    and entry.lineno <= e.lineno <= section_end
                )
                nested_quotes = sum(
                    1
                    for e in entries
                    if isinstance(e, BlockQuoteEntry)
                    and e.provenance == entry.provenance
                    and entry.lineno <= e.lineno <= section_end
                )
                nested_tables = sum(
                    1
                    for e in entries
                    if isinstance(e, TableEntry)
                    and e.provenance == entry.provenance
                    and entry.lineno <= e.lineno <= section_end
                )
                nested_admonitions = sum(
                    1
                    for e in entries
                    if isinstance(e, AdmonitionEntry)
                    and e.provenance == entry.provenance
                    and entry.lineno <= e.lineno <= section_end
                )
                nested_comments = sum(
                    1
                    for e in entries
                    if isinstance(e, CommentEntry)
                    and e.provenance == entry.provenance
                    and entry.lineno <= e.lineno <= section_end
                )
                nested_lists = sum(
                    1
                    for e in entries
                    if isinstance(e, ListEntry)
                    and e.provenance == entry.provenance
                    and (e.item_count is not None or e.kind == "definition")
                    and entry.lineno <= e.lineno <= section_end
                )
                nested_toctrees = sum(
                    1
                    for e in entries
                    if isinstance(e, ToctreeEntry)
                    and e.provenance == entry.provenance
                    and entry.lineno <= e.lineno <= section_end
                )
            else:
                nested_code = nested_quotes = nested_tables = 0
                nested_admonitions = nested_comments = nested_lists = nested_toctrees = 0
            if nested_code:
                extra.append(f"{nested_code} {_plural(nested_code, 'code block')}")
            if nested_quotes:
                extra.append(f"{nested_quotes} {_plural(nested_quotes, 'blockquote')}")
            if nested_tables:
                extra.append(f"{nested_tables} {_plural(nested_tables, 'table')}")
            if nested_admonitions:
                extra.append(f"{nested_admonitions} {_plural(nested_admonitions, 'admonition')}")
            if nested_comments:
                extra.append(f"{nested_comments} {_plural(nested_comments, 'comment')}")
            if nested_toctrees:
                extra.append(f"{nested_toctrees} {_plural(nested_toctrees, 'toctree')}")
            if nested_lists:
                extra.append(f"{nested_lists} {_plural(nested_lists, 'list')}")
            print(f"  {entry.formatted(extra)}")
        else:
            print(f"  {entry}")
    hidden = len(entries) - len(shown)
    if hidden:
        reasons = []
        if depth_limit is not None:
            reasons.append(f"--outline-depth {depth_limit}")
        if sections_only:
            reasons.append("--sections-only")
        noun = _plural(hidden, "entry", "entries")
        # "deeper" is only accurate when depth is the sole possible cause
        # (sections_only unset) — preserves the exact pre-existing wording
        # for that case; a kind-filtered entry isn't necessarily deeper.
        label = noun if sections_only else f"deeper {noun}"
        print(f"  ({hidden} {label} hidden — {', '.join(reasons)})")
    if not entries:
        print("  (no sections)")


# Long, static rationale for a repeated finding pattern, printed once per
# run rather than on every matching line (Max, 2026-07-20: "it repeats...
# long. Can we inform this as a separate line only once?" — the same
# "state shared context once, not per entry" principle as the outline's
# levels: legend).  Keyed by the finding text's distinguishing prefix;
# _hints_shown tracks which have already printed and is reset at the top
# of main() — once per RUN, not once per file.
_FINDING_HINTS: tuple[tuple[str, str], ...] = (
    (
        "nested inline markup ",
        "reStructuredText renders only the outer inline role; choose which one should survive",
    ),
    (
        "bold paragraph opener ",
        "AI documents often use this pattern as an informal heading; consider a proper section title",
    ),
    ("standalone bold line ", "verify it is not substituting a section title (bold is for inline emphasis only)"),
    (
        "second effective top-level title ",
        "choose the page title, insert it before the existing sections with a nine-character underline "
        "using an adornment symbol unused in the effective document, then run check_rst fix",
    ),
)


_hints_shown: set[str] = set()


def _print_findings(
    findings: list[Finding],
    prefix: str,
    no_warnings: bool,
    suppress: bool = False,
) -> tuple[int, int]:
    """Print findings; return (error count, visible-warning count).

    Counts, not booleans, so main() can feed the final summary line —
    truthiness-compatible with the old (has_errors, has_warnings) shape.
    suppress=True counts without printing (--outline-only): a display
    filter under the "trims display, never information" contract — the
    footer and the exit code stay honest.
    """
    n_errors = 0
    n_warnings = 0
    for f in findings:
        finding_prefix = f.source or prefix
        visible = f.severity != Severity.WARNING or not no_warnings
        if not suppress and visible:
            for key, hint in _FINDING_HINTS:
                if f.text.startswith(key) and key not in _hints_shown:
                    _hints_shown.add(key)
                    print(f"  ({key.strip()}: {hint})")
        if f.severity == Severity.WARNING:
            if no_warnings:
                continue
            n_warnings += 1
            if not suppress:
                # No leading glyph (Max, 2026-07-20: "we break de-facto
                # compiler alike output... those prefixes are optional, we've
                # got the text warning or error" — added to the contract, see
                # docs/guide.rst, "De-facto compiler output").
                # Bare "{prefix}:{f}" already reads as "path:line: WARNING:
                # message" via Finding.__str__ — the shape generic tooling
                # (IDE problem matchers, editor jump-to-error) parses.
                with _report_kind("WARNING"):
                    print(f"{finding_prefix}:{f}")
        else:
            n_errors += 1
            if not suppress:
                with _report_kind("ERROR"):
                    print(f"{finding_prefix}:{f}")
    return n_errors, n_warnings


def _print_fix_only_status(processed: int, errors: int, fixed: int) -> None:
    """Print the mandatory final status line for ``fix --fast`` (was ``--fix-only``)."""
    _emit_final_status(f"check_rst: {processed} file(s) processed, {errors} error(s), {fixed} file(s) fixed [fast]")
