# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Safe aligned-table to list-table conversion — check_rst project

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING, cast

import docutils.nodes
import docutils.parsers.rst.tableparser
import docutils.statemachine
from docutils import ApplicationError

if TYPE_CHECKING:
    import pathlib
    from typing import TypeGuard


from . import _helpers
from ._document import (
    _SIMPLE_TABLE_RULE_RE,
    _TABLE_DIRECTIVE_RE,
    Document,
    _simple_table_end,
    find_tables,
)
from ._helpers import (
    _read_source,
)
from ._types import (
    ListTableCandidate,
    ListTableFileResult,
    ListTableIssue,
    ParsedTable,
    TableEntry,
)

_TABLE_OPTION_VALUE_RE = re.compile(r"^[ \t]+:([\w-]+):[ \t]*(.*?)[ \t]*$")


@dataclasses.dataclass(frozen=True, slots=True)
class _AlignedTableSource:
    """The exact editable source block belonging to one aligned table.

    Offsets are zero-based, end-exclusive physical line indexes.  They
    deliberately do not trust ``TableEntry.end``: doctree line metadata
    identifies semantic nodes, not the final physical continuation or
    border line of a source table.
    """

    start: int
    end: int
    body_start: int
    body_end: int
    indent: str
    first_prefix: str
    caption: str | None
    options: tuple[tuple[str, str], ...]


def _leading_whitespace(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _table_directive_marker(line: str) -> tuple[re.Match[str], str, str] | None:
    """Return marker match, first-line prefix, continuation indentation.

    The ordinary form begins after leading whitespace.  The second form
    begins as a list item's first content (including a list-table cell),
    whose marker must remain on the replacement's first physical line.
    """
    leading = _leading_whitespace(line)
    direct = _TABLE_DIRECTIVE_RE.match(line[len(leading) :])
    if direct:
        return direct, leading, leading
    nested = re.match(
        r"^([ \t]*(?:(?:[*+-]|\d+[.)])[ \t]+)+)(\.\.\s+(table|list-table|csv-table)::)",
        line,
    )
    if nested is None:
        return None
    prefix = nested.group(1)
    marker = _TABLE_DIRECTIVE_RE.match(line[len(prefix) :])
    assert marker is not None
    # Docutils expands source tabs at the standard eight-column stops
    # before parsing.  Preserve the first line's bytes, but express later
    # directive lines at that same effective content column with spaces.
    return marker, prefix, " " * len(prefix.expandtabs())


def _aligned_table_end(lines: list[str], start: int) -> int:
    """Return the exact end-exclusive extent of a valid grid/simple table.

    The simple-table stopping predicate is docutils' own
    ``Body.isolate_simple_table`` rule: the second matching rule, or the
    first matching rule followed by a blank/end-of-input for a headerless
    table.  Keeping that predicate here fixes the information lost after
    parsing without inventing a different table grammar.
    """
    if lines[start].lstrip().startswith("+"):
        cursor = start
        while cursor < len(lines) and lines[cursor].lstrip().startswith(("+", "|")):
            cursor += 1
        return cursor

    end = _simple_table_end(lines, start)
    if end is not None:
        return end
    raise ValueError("simple table has no complete bottom rule")


def _is_simple_table_rule(line: str) -> bool:
    # Kept local so source capture and parser selection remain in this
    # module; this is the same narrow shape used by _document.
    return bool(_SIMPLE_TABLE_RULE_RE.match(line))


def _locate_aligned_table_source(lines: list[str], entry: TableEntry) -> _AlignedTableSource:
    """Recover the exact editable source block represented by *entry*.

    Directive ownership is established by its marker and indented body;
    bare tables are established by their top border/rule.  If neither is
    present at the reported source line, the table lives in a virtual
    nested parse (for example inside an outer aligned-table cell) and
    cannot safely be spliced until that ancestor is converted first.
    """
    start = entry.lineno - 1
    if not 0 <= start < len(lines):
        raise ValueError("reported table start is outside the source file")

    marker_info = _table_directive_marker(lines[start])
    if marker_info is not None and marker_info[0].group(1) == "table":
        marker, first_prefix, directive_indent = marker_info
        marker_text = lines[start][len(first_prefix) :]
        first_caption_line = marker_text[marker.end() :].strip()
        caption_lines = [first_caption_line] if first_caption_line else []
        body_start: int | None = None
        options: list[tuple[str, str]] = []
        argument_open = True
        options_started = False
        cursor = start + 1
        while cursor < len(lines):
            line = lines[cursor]
            if not line.strip():
                argument_open = False
                cursor += 1
                continue
            if len(_leading_whitespace(line)) <= len(directive_indent):
                break
            if line.lstrip().startswith("+") or _is_simple_table_rule(line):
                body_start = cursor
                break
            option_match = _TABLE_OPTION_VALUE_RE.match(line)
            if option_match:
                options_started = True
                options.append((option_match.group(1), option_match.group(2)))
                cursor += 1
                continue
            if argument_open and not options_started:
                caption_lines.append(line.strip())
                cursor += 1
                continue
            raise ValueError("table directive contains content before its aligned-table body")
        if body_start is None:
            raise ValueError("table directive has no aligned grid/simple body")
        caption = "\n".join(caption_lines) or None
        body_end = _aligned_table_end(lines, body_start)
        return _AlignedTableSource(
            start,
            body_end,
            body_start,
            body_end,
            directive_indent,
            first_prefix,
            caption,
            tuple(options),
        )

    if lines[start].lstrip().startswith("+") or _is_simple_table_rule(lines[start]):
        end = _aligned_table_end(lines, start)
        indent = _leading_whitespace(lines[start])
        return _AlignedTableSource(start, end, start, end, indent, indent, None, ())
    raise ValueError("table is nested inside source that cannot be edited independently")


def _resolve_list_table_selection(
    tables: list[TableEntry], only: list[int], skip: list[int]
) -> tuple[list[TableEntry], list[int]]:
    """Resolve --only/--skip ordinals (1-based, document order) against
    *tables* into the tables to convert.

    Returns (targets, unknown_ordinals). unknown_ordinals lists every
    --only/--skip value outside 1..len(tables) — including 0 and negative
    values, which are never valid — in the order given, duplicates
    included, so the caller can report exactly what was wrong; targets is
    always empty when unknown_ordinals is non-empty, a stale/invalid
    selector must never silently convert a different table than the one
    named. Otherwise: the eligible set starts as every table, narrows to
    exactly the --only ordinals if any were given, then --skip removes
    ordinals from whatever that is — a direct --only/--skip contradiction
    (the same ordinal in both) resolves to an empty target list here,
    which this pure function does not itself treat as an error; the
    caller distinguishes "resolved empty because of the selection" from
    "resolved empty because the file has no tables at all" by checking
    whether *tables* was empty to begin with.
    """
    n = len(tables)
    unknown = [ordinal for ordinal in (*only, *skip) if not (1 <= ordinal <= n)]
    if unknown:
        return [], unknown
    selected = set(range(1, n + 1))
    if only:
        selected &= set(only)
    selected -= set(skip)
    targets = [table for position, table in enumerate(tables, start=1) if position in selected]
    return targets, []


# Kinds this conversion accepts: bare/directive-wrapped grid and simple
# tables (a ``.. table::`` directive reports kind='table' regardless of
# which alignment grammar it wraps — TableEntry's own kind detection
# cannot tell the two apart, so the parser choice below inspects the
# actual first content line instead). Already 'list' needs no conversion;
# 'csv' is fundamentally different source (external/inline CSV data, not
# an aligned grid) and stays out of scope.
_LIST_TABLE_ELIGIBLE_KINDS = frozenset({"grid", "simple", "table"})


def _table_kind_eligible(kind: str) -> bool:
    return kind in _LIST_TABLE_ELIGIBLE_KINDS


# types-docutils' tableparser stub declares each parsed row's cells with a
# list[str] 4th element; at runtime it is a real StringList (confirmed) —
# ParsedTable's own field type (see _types.py) is the accurate one.
_ParsedTableRow = list[tuple[int, int, int, docutils.statemachine.StringList] | None]


def _parse_aligned_table(lines: list[str]) -> ParsedTable:
    """Parse a grid or simple table's raw source *lines* (border rows
    included, nothing else) via docutils' own GridTableParser/
    SimpleTableParser — never reimplementing the alignment grammar.
    Grid vs simple is chosen from the first line's own shape ('+' border
    vs '=' rule), not from TableEntry.kind, which collapses both under
    'table' for a directive-wrapped source (see _LIST_TABLE_ELIGIBLE_KINDS)."""
    is_grid = lines[0].lstrip().startswith("+")
    parser: docutils.parsers.rst.tableparser.TableParser = (
        docutils.parsers.rst.tableparser.GridTableParser()
        if is_grid
        else docutils.parsers.rst.tableparser.SimpleTableParser()
    )
    # docutils ships no stub body for TableParser.parse in this environment's
    # types-docutils snapshot, so mypy sees it as untyped — narrowest
    # possible ignore, not a broader override; cast() alone doesn't suppress
    # no-untyped-call, since the error fires on evaluating the call itself.
    colspecs, header_rows, body_rows = cast(
        "tuple[list[int], list[_ParsedTableRow], list[_ParsedTableRow]]",
        parser.parse(docutils.statemachine.StringList(lines)),  # type: ignore[no-untyped-call]
    )
    return ParsedTable(colspecs, header_rows, body_rows)


def _table_has_span(parsed: ParsedTable) -> bool:
    """True if any real cell (not a covered/None position) claims extra
    rows or columns.  list-table cannot express a merged cell, so this
    must be a hard, explanatory refusal — never a silent flatten,
    duplication, or guess at a spanned cell's content."""
    for row in (*parsed.header_rows, *parsed.body_rows):
        for cell in row:
            if cell is not None and (cell[0] or cell[1]):
                return True
    return False


def _evaluate_list_table_candidate(lines: list[str], entry: TableEntry) -> ListTableCandidate:
    """Judge one table ready for conversion, or refuse it with a reported
    reason and stable diagnostic code."""
    if entry.kind == "list":
        return ListTableCandidate(
            entry,
            None,
            None,
            "already a list-table — nothing to convert",
            refusal_code="list-table.already-list-table",
            refusal_category="unchanged",
        )
    if entry.kind == "csv":
        return ListTableCandidate(
            entry,
            None,
            None,
            "csv-table is out of scope for this conversion",
            refusal_code="list-table.csv-table",
            refusal_category="unsupported",
        )
    if not _table_kind_eligible(entry.kind):
        return ListTableCandidate(
            entry,
            None,
            None,
            f"kind {entry.kind!r} is not supported",
            refusal_code="list-table.unsupported-kind",
            refusal_category="unsupported",
        )

    try:
        source = _locate_aligned_table_source(lines, entry)
    except (IndexError, ValueError) as exc:
        nested = "nested inside source" in str(exc)
        return ListTableCandidate(
            entry,
            None,
            entry.caption,
            str(exc),
            refusal_code="list-table.nested-aligned-table" if nested else "list-table.source-model",
            refusal_category="incompatible" if nested else "source-model",
        )

    option_names = {name for name, _ in source.options}
    unsupported = option_names - {"class", "name", "align", "width", "widths"}
    if unsupported:
        name = sorted(unsupported)[0]
        return ListTableCandidate(
            entry,
            None,
            source.caption,
            f"the {name!r} table option has no proven list-table mapping",
            source_start=source.start,
            source_end=source.end,
            indent=source.indent,
            refusal_code="list-table.option-unsupported",
            refusal_category="unsupported",
        )
    body_indent = _leading_whitespace(lines[source.body_start])
    body_lines = lines[source.body_start : source.body_end]
    dedented = [line[len(body_indent) :] if line.startswith(body_indent) else line.lstrip() for line in body_lines]
    try:
        parsed = _parse_aligned_table(dedented)
    except (ApplicationError, IndexError, TypeError, ValueError) as exc:
        return ListTableCandidate(
            entry,
            None,
            source.caption,
            f"docutils could not parse the captured aligned table: {exc}",
            source_start=source.start,
            source_end=source.end,
            indent=source.indent,
            refusal_code="list-table.source-model",
            refusal_category="source-model",
        )
    if _table_has_span(parsed):
        return ListTableCandidate(
            entry,
            None,
            source.caption,
            "contains a merged row or column (span), which list-table cannot express",
            source_start=source.start,
            source_end=source.end,
            indent=source.indent,
            refusal_code="list-table.span",
            refusal_category="incompatible",
        )
    return ListTableCandidate(
        entry,
        parsed,
        source.caption,
        None,
        options=source.options,
        source_start=source.start,
        source_end=source.end,
        indent=source.indent,
        first_prefix=source.first_prefix,
    )


_LIST_TABLE_BODY_INDENT = 3


_LIST_TABLE_FIRST_MARKER = "* -"


_LIST_TABLE_OTHER_MARKER = "  -"


def _render_list_table_row(
    row: list[tuple[int, int, int, docutils.statemachine.StringList] | None],
) -> list[str]:
    """One row's worth of ``* -``/``  -`` lines. Every cell's own source
    lines are used verbatim — never re-serialized through a parsed tree
    — indented so continuation lines align under the first line's own
    content column, the same rule RST itself requires for list-item
    bodies. None cells never reach here — spans are rejected before
    rendering (_evaluate_list_table_candidate)."""
    out: list[str] = []
    content_column = _LIST_TABLE_BODY_INDENT + len(_LIST_TABLE_FIRST_MARKER) + 1
    for index, cell in enumerate(row):
        if cell is None:
            raise AssertionError("spanned cell reached the renderer — caller must reject spans first")
        _, _, _, block = cell
        # .data is StringList's own concrete list[str] backing store — more
        # version-robust than relying on __iter__'s overload matching, and
        # confirmed content-identical to list(block).
        cell_lines = list(block.data)
        # docutils pads every cell in a row to the row's tallest cell's
        # line count (confirmed by direct probe) — trailing empty entries
        # are that padding, not real trailing blank lines in the cell's
        # own content, so they're dropped; an INTERIOR empty line (a
        # genuine blank line separating two paragraphs in one cell) is
        # kept.
        while cell_lines and cell_lines[-1] == "":
            cell_lines.pop()
        marker = _LIST_TABLE_FIRST_MARKER if index == 0 else _LIST_TABLE_OTHER_MARKER
        prefix = " " * _LIST_TABLE_BODY_INDENT + marker
        if not cell_lines:
            out.append(prefix)
            continue
        out.append(f"{prefix} {cell_lines[0]}".rstrip())
        for extra in cell_lines[1:]:
            out.append(f"{' ' * content_column}{extra}".rstrip())
    return out


def _render_list_table(
    parsed: ParsedTable,
    caption: str | None,
    options: tuple[tuple[str, str], ...] = (),
    indent: str = "",
    first_prefix: str | None = None,
) -> str:
    """Emit RST text for a ``.. list-table::`` directive equivalent to
    *parsed*. Explicit :widths: values carry colspecs straight through.
    ``:widths: auto`` on an aligned ``table`` directive is represented by
    BOTH its parsed grid colspecs and Docutils' internal ``colwidths-auto``
    table class. A list-table's own ``auto`` value instead manufactures
    equal-width colspecs, so preserve the original model by emitting the
    parsed widths explicitly and adding that same internal class through
    ``:class:``. Docutils' writers consume the class as their automatic-
    layout switch, while the exact colspec model remains available to
    other consumers."""
    caption_lines = caption.splitlines() if caption else []
    lines = [f".. list-table:: {caption_lines[0]}" if caption_lines else ".. list-table::"]
    lines.extend(f"{' ' * _LIST_TABLE_BODY_INDENT}{line}" for line in caption_lines[1:])
    if parsed.header_rows:
        lines.append(f"{' ' * _LIST_TABLE_BODY_INDENT}:header-rows: {len(parsed.header_rows)}")
    source_widths = next((value for name, value in options if name == "widths"), None)
    auto_widths = source_widths == "auto"
    widths = (
        source_widths
        if source_widths not in (None, "grid", "auto")
        else " ".join(str(width) for width in parsed.colspecs)
    )
    lines.append(f"{' ' * _LIST_TABLE_BODY_INDENT}:widths: {widths}")
    class_emitted = False
    for name, value in options:
        if name != "widths":
            if name == "class" and auto_widths:
                value = f"{value} colwidths-auto".strip()
                class_emitted = True
            suffix = f" {value}" if value else ""
            lines.append(f"{' ' * _LIST_TABLE_BODY_INDENT}:{name}:{suffix}")
    if auto_widths and not class_emitted:
        lines.append(f"{' ' * _LIST_TABLE_BODY_INDENT}:class: colwidths-auto")
    lines.append("")
    for row in (*parsed.header_rows, *parsed.body_rows):
        lines.extend(_render_list_table_row(row))
    prefix = indent if first_prefix is None else first_prefix
    rendered = [f"{prefix}{lines[0]}"]
    rendered.extend(f"{indent}{line}" if line else "" for line in lines[1:])
    return "\n".join(rendered) + "\n"


def _canonical_doctree_model(node: docutils.nodes.Node) -> object:
    """A structural fingerprint of *node*: class identity, frozen
    attributes, and children, recursively — the same modeling technique
    as _text_space_evidence's permitted-delta model. Two permitted
    deltas, both confirmed by direct probe:

    - docutils marks a <table> node 'colwidths-given' whenever :widths:
      is given explicitly on list-table, and never otherwise — a grid/
      simple table never carries it regardless of its own widths, since
      there is no 'auto' alternative for that syntax to distinguish it
      from. _render_list_table always emits :widths: (to make colwidth
      match exactly), so this class is a one-directional, deterministic
      syntax-provenance marker, not semantic content — dropped from the
      comparison, on <table> nodes only.
    - a <system_message> node's own 'line' attribute records the exact
      physical source line docutils was parsing when it noticed
      something ambiguous (found live: a lone '#' table-header cell
      trips docutils' own title/transition heuristic — "Unexpected
      possible title overline or transition... too short" — even
      though it correctly resolves as ordinary text either way).
      list-table syntax lays the same cell out on a different physical
      line than a grid/simple table did, so this line number is
      EXPECTED to shift on an otherwise fully correct conversion —
      position bookkeeping, not semantic content, dropped from the
      comparison, on <system_message> nodes only."""
    if isinstance(node, docutils.nodes.Text):
        return ("Text", str(node))
    attributes: object = ()
    if isinstance(node, docutils.nodes.Element):
        attributes = dict(node.attributes)
        if isinstance(node, docutils.nodes.table) and "colwidths-given" in attributes.get("classes", ()):
            attributes["classes"] = [c for c in attributes["classes"] if c != "colwidths-given"]
        if isinstance(node, docutils.nodes.system_message):
            attributes.pop("line", None)
        attributes = _helpers._freeze_node_attribute(attributes)
    return (
        node.__class__.__module__,
        node.__class__.__qualname__,
        attributes,
        tuple(_canonical_doctree_model(child) for child in node.children),
    )


def _list_table_conversion_preserves_semantics(path: pathlib.Path, original_text: str, candidate_text: str) -> bool:
    """Parse both whole-file variants and require exact canonical-tree
    equality — the same all-or-nothing rule --fix already uses: a
    changed subtree means the conversion is rejected outright, never
    partially applied or guessed at."""
    original_model = _canonical_doctree_model(_helpers._parse_rst(path, text=original_text))
    candidate_model = _canonical_doctree_model(_helpers._parse_rst(path, text=candidate_text))
    return original_model == candidate_model


def _canonical_model_label(model: object) -> str:
    """Short, readable name for one _canonical_doctree_model() node —
    'Text' for a text node, its docutils tag name otherwise."""
    if isinstance(model, tuple) and len(model) == 2 and model[0] == "Text":
        return "Text"
    if isinstance(model, tuple) and len(model) == 4:
        return str(model[1])
    return "?"


def _is_text_model(model: object) -> TypeGuard[tuple[str, str]]:
    """True for a _canonical_doctree_model() Text-node tuple specifically
    — distinguished from an Element tuple by length alone (2 vs 4), the
    same shape _canonical_doctree_model itself constructs."""
    return isinstance(model, tuple) and len(model) == 2 and model[0] == "Text"


def _describe_doctree_divergence(original: object, candidate: object, path: tuple[str, ...] = ()) -> str:
    """Human-readable description of the FIRST structural difference
    between two _canonical_doctree_model() trees, walked in parallel,
    depth-first — found live: 'converted result failed semantic
    validation' named that the trees differed but never where or how,
    forcing a manual bisection of the whole file to isolate the actual
    cause. First divergence wins deliberately, not exhaustively: a
    dropped or retyped node cascades into every attribute/child-count/
    text comparison below it too, and those are consequences, not the
    cause — reporting all of them would bury the one fact that matters
    in noise the size of the whole subtree."""
    if original == candidate:
        return ""
    where = "/".join(path) if path else "document root"
    if _is_text_model(original) or _is_text_model(candidate):
        if _is_text_model(original) and _is_text_model(candidate):
            return f"{where}: text changed from {original[1]!r} to {candidate[1]!r}"
        return f"{where}: was {_canonical_model_label(original)!r}, became {_canonical_model_label(candidate)!r}"
    o_mod, o_name, o_attrs, o_children = cast("tuple[str, str, object, tuple[object, ...]]", original)
    c_mod, c_name, c_attrs, c_children = cast("tuple[str, str, object, tuple[object, ...]]", candidate)
    if (o_mod, o_name) != (c_mod, c_name):
        return f"{where}: node type changed from {o_name!r} to {c_name!r}"
    if o_attrs != c_attrs:
        return f"{where} <{o_name}>: attributes changed from {o_attrs!r} to {c_attrs!r}"
    if len(o_children) != len(c_children):
        return f"{where} <{o_name}>: child count changed from {len(o_children)} to {len(c_children)}"
    for index, (o_child, c_child) in enumerate(zip(o_children, c_children, strict=True)):
        sub = _describe_doctree_divergence(o_child, c_child, (*path, f"{o_name}[{index}]"))
        if sub:
            return sub
    return ""  # unreachable given the caller's own inequality check above


def _list_table_divergence_reason(path: pathlib.Path, original_text: str, candidate_text: str) -> str:
    """The diagnostic counterpart to _list_table_conversion_preserves_
    semantics' plain bool: re-parses both variants and names the first
    structural difference between them. Paid for only once validation
    has already failed — the common, passing-validation path never
    re-parses or walks the trees a second time for this."""
    original_model = _canonical_doctree_model(_helpers._parse_rst(path, text=original_text))
    candidate_model = _canonical_doctree_model(_helpers._parse_rst(path, text=candidate_text))
    return _describe_doctree_divergence(original_model, candidate_model)


def _replacement_text(original: str, start: int, end: int, rendered: str) -> str:
    """Replace one physical line range without touching any other bytes.

    Generated lines use the selected block's own newline convention and
    inherit whether its final physical line had a terminator.  This is a
    source-geometry guarantee beyond the semantic doctree proof.
    """
    lines = original.splitlines(keepends=True)
    removed = lines[start:end]
    if not removed:
        raise ValueError("replacement range is empty")
    first_ending = "\r\n" if removed[0].endswith("\r\n") else "\r" if removed[0].endswith("\r") else "\n"
    replacement = rendered.replace("\n", first_ending)
    final_had_ending = removed[-1].endswith(("\n", "\r"))
    if not final_had_ending:
        replacement = replacement.removesuffix(first_ending)
    return "".join((*lines[:start], replacement, *lines[end:]))


def _list_table_issue(
    ordinal: int | None,
    entry: TableEntry | None,
    code: str,
    category: str,
    reason: str,
    *,
    exact_selection: bool = False,
) -> ListTableIssue:
    table = f"table {ordinal}" if ordinal is not None else "selection"
    impact = f"{table} unchanged"
    if exact_selection:
        impact += "; file left untouched because --only named this table"
    elif ordinal is not None:
        impact += "; other selected tables may still convert"
    actions = {
        "list-table.span": "Keep the aligned table, remove the span, or exclude it with --skip.",
        "list-table.nested-aligned-table": "Convert its aligned-table ancestor first, then run list-table again.",
        "list-table.source-model": "Inspect the reported source range; the converter will not guess its boundaries.",
        "list-table.semantic-proof": "Keep the aligned table and inspect the reported doctree divergence.",
        "list-table.unknown-ordinal": "Run outline to obtain the current table ordinals, then retry.",
    }
    action = actions.get(code, "Keep this table unchanged or exclude it with --skip.")
    return ListTableIssue(ordinal, entry, code, category, reason, impact, action)


def _plan_list_table_text(
    path: pathlib.Path,
    original: str,
    only: list[int],
    skip: list[int],
    *,
    exact_selection: bool,
) -> ListTableFileResult:
    """Plan one conversion stage against supplied in-memory source.

    Resolve --only/--skip, evaluate
    and render every in-scope table, splice approved conversions into
    the whole-file text, then re-validate the whole result before it may
    ever be written. An --only ordinal that turns out refused is fatal
    (the user named that exact table); a refusal among the default,
    unnamed 'every eligible table' scope is reported but does not block
    converting the file's other eligible tables — the same
    review-don't-block spirit as --skip-fixable, not a hard-error either
    way rule."""
    plain_lines = original.splitlines()
    tables = find_tables(path, doc=Document(path, source_text=original))
    targets, unknown = _resolve_list_table_selection(tables, only, skip)
    if unknown:
        bad = ", ".join(str(n) for n in unknown)
        return ListTableFileResult(
            path,
            original,
            original,
            [],
            [],
            unknown,
            _list_table_issue(
                None,
                None,
                "list-table.unknown-ordinal",
                "selection",
                f"unknown table ordinal(s): {bad}",
            ),
        )

    ordinal_by_id = {id(table): ordinal for ordinal, table in enumerate(tables, start=1)}
    replacements: list[tuple[int, int, str]] = []
    converted: list[int] = []
    refusals: list[ListTableIssue] = []
    for table in targets:
        ordinal = ordinal_by_id[id(table)]
        candidate = _evaluate_list_table_candidate(plain_lines, table)
        if candidate.refusal is not None:
            issue = _list_table_issue(
                ordinal,
                table,
                candidate.refusal_code or "list-table.refused",
                candidate.refusal_category or "unsupported",
                candidate.refusal,
                exact_selection=exact_selection,
            )
            if exact_selection and issue.code != "list-table.nested-aligned-table":
                return ListTableFileResult(
                    path,
                    original,
                    original,
                    [],
                    [],
                    [],
                    issue,
                )
            refusals.append(issue)
            continue
        assert candidate.parsed is not None
        assert candidate.source_start is not None
        assert candidate.source_end is not None
        rendered = _render_list_table(
            candidate.parsed,
            candidate.caption,
            candidate.options,
            candidate.indent,
            candidate.first_prefix,
        )
        single_candidate = _replacement_text(original, candidate.source_start, candidate.source_end, rendered)
        if not _list_table_conversion_preserves_semantics(path, original, single_candidate):
            reason = _list_table_divergence_reason(path, original, single_candidate)
            detail = f"semantic proof failed: {reason}" if reason else "semantic proof failed"
            issue = _list_table_issue(
                ordinal,
                table,
                "list-table.semantic-proof",
                "semantic-proof",
                detail,
                exact_selection=exact_selection,
            )
            if exact_selection:
                return ListTableFileResult(path, original, original, [], [], [], issue)
            refusals.append(issue)
            continue
        replacements.append((candidate.source_start, candidate.source_end, rendered))
        converted.append(ordinal)

    candidate_text = original
    for start, end, rendered in sorted(replacements, key=lambda item: item[0], reverse=True):
        candidate_text = _replacement_text(candidate_text, start, end, rendered)

    if candidate_text != original and not _list_table_conversion_preserves_semantics(path, original, candidate_text):
        reason = _list_table_divergence_reason(path, original, candidate_text)
        detail = f" ({reason})" if reason else ""
        return ListTableFileResult(
            path,
            original,
            original,
            [],
            [],
            [],
            _list_table_issue(
                None,
                None,
                "list-table.semantic-proof",
                "semantic-proof",
                f"combined converted result failed semantic validation{detail}",
            ),
        )
    return ListTableFileResult(path, original, candidate_text, converted, refusals, [], None)


def _plan_list_table_file(path: pathlib.Path, only: list[int], skip: list[int]) -> ListTableFileResult:
    """Plan a file conversion, resolving nested tables ancestor-first.

    The first stage preserves the established bulk/explicit-selection
    semantics. In bulk mode, a nested aligned table initially has no
    independent source range, but a converted ancestor may expose one in
    the in-memory candidate. Retry only those nested ordinals until no
    further ancestor conversion makes progress. Every stage and the final
    aggregate remain protected by whole-document canonical-tree equality;
    the file is still read once and written only by the CLI after this
    complete plan succeeds.

    Explicit ``--only`` remains exact: an inner table cannot authorize
    converting an unselected ancestor merely to expose its source.
    """
    original = _read_source(path)
    result = _plan_list_table_text(path, original, only, skip, exact_selection=bool(only))
    if result.fatal is not None:
        return result

    nested_code = "list-table.nested-aligned-table"
    pending = {
        issue.ordinal: issue for issue in result.refusals if issue.code == nested_code and issue.ordinal is not None
    }
    if not pending:
        return result
    if not result.changed:
        if only:
            issue = pending[min(pending)]
            return ListTableFileResult(path, original, original, [], [], [], issue)
        return result

    candidate = result.candidate
    converted = set(result.converted)
    retained = [issue for issue in result.refusals if issue.code != nested_code]
    while pending:
        progressed = False
        for ordinal in sorted(pending):
            retry = _plan_list_table_text(
                path,
                candidate,
                [ordinal],
                [],
                exact_selection=False,
            )
            if retry.fatal is not None:
                return ListTableFileResult(path, original, original, [], [], [], retry.fatal)
            if ordinal in retry.converted:
                candidate = retry.candidate
                converted.add(ordinal)
                del pending[ordinal]
                progressed = True
                continue
            replacement_issue = next(
                (issue for issue in retry.refusals if issue.ordinal == ordinal),
                None,
            )
            if replacement_issue is not None:
                pending[ordinal] = replacement_issue
        if not progressed:
            break

    if pending and only:
        issue = pending[min(pending)]
        return ListTableFileResult(path, original, original, [], [], [], issue)

    if not _list_table_conversion_preserves_semantics(path, original, candidate):
        reason = _list_table_divergence_reason(path, original, candidate)
        detail = f" ({reason})" if reason else ""
        fatal = _list_table_issue(
            None,
            None,
            "list-table.semantic-proof",
            "semantic-proof",
            f"ancestor-first converted result failed semantic validation{detail}",
        )
        return ListTableFileResult(path, original, original, [], [], [], fatal)

    refusals = sorted((*retained, *pending.values()), key=lambda issue: issue.ordinal or 0)
    return ListTableFileResult(path, original, candidate, sorted(converted), refusals, [], None)
