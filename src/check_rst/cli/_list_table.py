# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Safe aligned-table to list-table conversion — check_rst project

from __future__ import annotations

from typing import TYPE_CHECKING, cast

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
    from typing import TypeGuard


from . import _helpers
from ._document import (
    _TABLE_DIRECTIVE_RE,
    _TABLE_OPTION_RE,
    find_tables,
)
from ._helpers import (
    _read_source,
)
from ._types import (
    ListTableCandidate,
    ListTableFileResult,
    ParsedTable,
    TableEntry,
)


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
    colspecs, header_rows, body_rows = parser.parse(docutils.statemachine.StringList(lines))
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
    reason. Scope for this version: bare tables and directive-wrapped
    tables with an optional caption only — :name:/:class:/:align: (or any
    other ``.. table::`` option) is an explicit, reported refusal, not
    yet supported (docs/roadmap.rst, "Targeted aligned-table to
    list-table transformation"), never a silent mishandling."""
    if entry.kind == "list":
        return ListTableCandidate(entry, None, None, "already a list-table — nothing to convert")
    if entry.kind == "csv":
        return ListTableCandidate(entry, None, None, "csv-table is out of scope for this conversion")
    if not _table_kind_eligible(entry.kind):
        return ListTableCandidate(entry, None, None, f"kind {entry.kind!r} is not supported")

    directive_line = lines[entry.lineno - 1]
    match = _TABLE_DIRECTIVE_RE.match(directive_line.strip())
    caption: str | None = None
    body_start = entry.lineno - 1
    if match:
        caption = directive_line.strip()[match.end() :].strip() or None
        cursor = entry.lineno  # 0-based index of the line right after the directive
        option_names = []
        while cursor < entry.end:
            option_match = _TABLE_OPTION_RE.match(lines[cursor])
            if option_match is None:
                break
            option_names.append(option_match.group(1))
            cursor += 1
        if option_names:
            return ListTableCandidate(
                entry,
                None,
                caption,
                f"the {option_names[0]!r} option is not yet supported",
            )
        if cursor < entry.end and not lines[cursor].strip():
            cursor += 1  # the required blank line between options/caption and body
        body_start = cursor

    body_lines = lines[body_start : entry.end]
    indent = len(body_lines[0]) - len(body_lines[0].lstrip()) if body_lines else 0
    dedented = [line[indent:] if len(line) >= indent else line.lstrip() for line in body_lines]

    parsed = _parse_aligned_table(dedented)
    if _table_has_span(parsed):
        return ListTableCandidate(
            entry,
            None,
            caption,
            "contains a merged row or column (span), which list-table cannot express",
        )
    return ListTableCandidate(entry, parsed, caption, None)


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
        cell_lines = list(block)
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


def _render_list_table(parsed: ParsedTable, caption: str | None) -> str:
    """Emit RST text for a ``.. list-table::`` directive equivalent to
    *parsed*. :widths: carries colspecs straight through — confirmed by
    direct probe that docutils passes explicit :widths: values through to
    each colspec's own colwidth unchanged, making the resulting doctree's
    column-width representation match the original exactly, not merely
    proportionally."""
    lines = [f".. list-table:: {caption}" if caption else ".. list-table::"]
    if parsed.header_rows:
        lines.append(f"{' ' * _LIST_TABLE_BODY_INDENT}:header-rows: {len(parsed.header_rows)}")
    lines.append(f"{' ' * _LIST_TABLE_BODY_INDENT}:widths: {' '.join(str(width) for width in parsed.colspecs)}")
    lines.append("")
    for row in (*parsed.header_rows, *parsed.body_rows):
        lines.extend(_render_list_table_row(row))
    return "\n".join(lines) + "\n"


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


def _plan_list_table_file(path: pathlib.Path, only: list[int], skip: list[int]) -> ListTableFileResult:
    """Plan one file's conversion — read, resolve --only/--skip, evaluate
    and render every in-scope table, splice approved conversions into
    the whole-file text, then re-validate the whole result before it may
    ever be written. An --only ordinal that turns out refused is fatal
    (the user named that exact table); a refusal among the default,
    unnamed 'every eligible table' scope is reported but does not block
    converting the file's other eligible tables — the same
    review-don't-block spirit as --skip-fixable, not a hard-error either
    way rule."""
    original = _read_source(path)
    plain_lines = original.splitlines()
    tables = find_tables(path)
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
            f"unknown table ordinal(s): {bad}",
        )

    ordinal_by_id = {id(table): ordinal for ordinal, table in enumerate(tables, start=1)}
    replacements: list[tuple[int, int, str]] = []
    converted: list[int] = []
    refusals: list[tuple[int, str]] = []
    for table in targets:
        ordinal = ordinal_by_id[id(table)]
        candidate = _evaluate_list_table_candidate(plain_lines, table)
        if candidate.refusal is not None:
            if only:
                return ListTableFileResult(
                    path,
                    original,
                    original,
                    [],
                    [],
                    [],
                    f"table {ordinal}: {candidate.refusal}",
                )
            refusals.append((ordinal, candidate.refusal))
            continue
        assert candidate.parsed is not None
        rendered = _render_list_table(candidate.parsed, candidate.caption)
        replacements.append((table.lineno - 1, table.end, rendered.rstrip("\n")))
        converted.append(ordinal)

    new_lines = list(plain_lines)
    for start, end, text in sorted(replacements, key=lambda item: item[0], reverse=True):
        new_lines[start:end] = text.splitlines()
    candidate_text = "\n".join(new_lines)
    if original.endswith("\n"):
        candidate_text += "\n"

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
            f"converted result failed semantic validation — file left untouched{detail}",
        )
    return ListTableFileResult(path, original, candidate_text, converted, refusals, [], None)
