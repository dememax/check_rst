# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED/GREEN tests for the list-table conversion verb, built in isolated
# stages before CLI wiring — check_rst project
"""Tests for the ``list-table`` verb (docs/roadmap.rst, "Targeted
aligned-table to list-table transformation"), staged the same way the
subcommand redesign was: each piece built and tested standalone before
wiring into the CLI. See tests/test_cli_subcommands.py for that precedent.

Stage 1: the --only/--skip ordinal resolver — pure, no table-parsing or
conversion logic at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import docutils.parsers.rst.tableparser
import pytest

from check_rst import cli
from check_rst.cli import _document, _list_table, _types

if TYPE_CHECKING:
    from pathlib import Path


def _tables(n: int) -> list[_types.TableEntry]:
    """Return minimal entries; the resolver only counts and indexes them."""
    return [_types.TableEntry(index, 1, "grid", (1, 1), None, "", index) for index in range(1, n + 1)]


def _rst(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "doc.rst"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.mark.unit
def test_no_only_no_skip_selects_everything() -> None:
    tables = _tables(3)
    targets, unknown = _list_table._resolve_list_table_selection(tables, [], [])
    assert targets == tables
    assert unknown == []


@pytest.mark.unit
def test_only_narrows_to_exactly_those_ordinals() -> None:
    tables = _tables(3)
    targets, unknown = _list_table._resolve_list_table_selection(tables, [2], [])
    assert targets == [tables[1]]
    assert unknown == []


@pytest.mark.unit
def test_only_preserves_document_order_regardless_of_argument_order() -> None:
    tables = _tables(3)
    targets, unknown = _list_table._resolve_list_table_selection(tables, [3, 1], [])
    assert targets == [tables[0], tables[2]]
    assert unknown == []


@pytest.mark.unit
def test_skip_removes_exactly_those_ordinals() -> None:
    tables = _tables(3)
    targets, unknown = _list_table._resolve_list_table_selection(tables, [], [2])
    assert targets == [tables[0], tables[2]]
    assert unknown == []


@pytest.mark.unit
def test_only_and_skip_combine_only_then_skip() -> None:
    """The documented combination rule: the eligible set starts as
    everything, narrows to --only if given, then --skip removes from
    whatever that is — not the reverse order."""
    tables = _tables(5)
    targets, unknown = _list_table._resolve_list_table_selection(tables, [1, 2, 3], [2])
    assert targets == [tables[0], tables[2]]
    assert unknown == []


@pytest.mark.unit
def test_only_and_skip_the_same_ordinal_resolves_empty() -> None:
    """A direct contradiction — --only 2 --skip 2 — resolves to an empty
    target list, not an error by itself; the caller decides whether an
    empty result is fatal (it is, for the actual CLI, but this function
    stays pure)."""
    tables = _tables(3)
    targets, unknown = _list_table._resolve_list_table_selection(tables, [2], [2])
    assert targets == []
    assert unknown == []


@pytest.mark.unit
def test_out_of_range_only_ordinal_is_reported_not_silently_dropped() -> None:
    tables = _tables(2)
    targets, unknown = _list_table._resolve_list_table_selection(tables, [5], [])
    assert targets == []
    assert unknown == [5]


@pytest.mark.unit
def test_out_of_range_skip_ordinal_is_reported() -> None:
    tables = _tables(2)
    targets, unknown = _list_table._resolve_list_table_selection(tables, [], [9])
    assert targets == []
    assert unknown == [9]


@pytest.mark.unit
def test_ordinal_zero_and_negative_are_out_of_range() -> None:
    """Ordinals are 1-based; 0 and negative values are never valid,
    regardless of how many tables exist."""
    tables = _tables(3)
    targets, unknown = _list_table._resolve_list_table_selection(tables, [0, -1], [])
    assert targets == []
    assert unknown == [0, -1]


@pytest.mark.unit
def test_multiple_unknown_ordinals_reported_in_given_order() -> None:
    tables = _tables(2)
    targets, unknown = _list_table._resolve_list_table_selection(tables, [5], [8])
    assert targets == []
    assert unknown == [5, 8]


@pytest.mark.unit
def test_no_tables_and_no_selection_resolves_empty_without_unknown() -> None:
    """An empty file (no tables at all) is not the same failure as an
    out-of-range ordinal — the caller distinguishes them by checking
    whether `tables` itself was empty."""
    targets, unknown = _list_table._resolve_list_table_selection([], [], [])
    assert targets == []
    assert unknown == []


# ---------------------------------------------------------------------------
# Stage 2: mechanical eligibility — which kinds this conversion accepts,
# and span detection (list-table cannot express a merged cell, so any
# non-zero rowspan/colspan must be a hard, explanatory refusal).
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("kind", "eligible"),
    [
        ("grid", True),
        ("simple", True),
        ("table", True),
        ("list", False),
        ("csv", False),
    ],
)
def test_table_eligible_kinds(kind: str, eligible: bool) -> None:
    assert _list_table._table_kind_eligible(kind) is eligible


@pytest.mark.unit
def test_parse_aligned_table_grid() -> None:
    lines = [
        "+-----+-------+",
        "| A   | B     |",
        "+=====+=======+",
        "| 1   | two   |",
        "+-----+-------+",
    ]
    parsed = _list_table._parse_aligned_table(lines)
    assert parsed.colspecs == [5, 7]
    assert len(parsed.header_rows) == 1
    assert len(parsed.body_rows) == 1


@pytest.mark.unit
def test_parse_aligned_table_simple() -> None:
    lines = [
        "=====  =====",
        "A      B",
        "=====  =====",
        "1      2",
        "=====  =====",
    ]
    parsed = _list_table._parse_aligned_table(lines)
    assert len(parsed.header_rows) == 1
    assert len(parsed.body_rows) == 1


@pytest.mark.unit
def test_table_has_span_false_for_ordinary_table() -> None:
    lines = [
        "+-----+-----+",
        "| A   | B   |",
        "+=====+=====+",
        "| 1   | 2   |",
        "+-----+-----+",
    ]
    parsed = _list_table._parse_aligned_table(lines)
    assert _list_table._table_has_span(parsed) is False


@pytest.mark.unit
def test_table_has_span_true_for_rowspan() -> None:
    lines = [
        "+-----+-----+",
        "| A   | B   |",
        "+=====+=====+",
        "| 1   | 2   |",
        "+     +-----+",
        "|     | 4   |",
        "+-----+-----+",
    ]
    parsed = _list_table._parse_aligned_table(lines)
    assert _list_table._table_has_span(parsed) is True


@pytest.mark.unit
def test_table_has_span_true_for_colspan() -> None:
    lines = [
        "+-----+-----+",
        "| A   | B   |",
        "+=====+=====+",
        "| 1         |",
        "+-----+-----+",
    ]
    parsed = _list_table._parse_aligned_table(lines)
    assert _list_table._table_has_span(parsed) is True


# ---------------------------------------------------------------------------
# Stage 3: candidate evaluation — locate a table's exact inner source span
# (dedented, ready for _parse_aligned_table) and optional caption, folding
# in kind/span/option checks from stage 2 into one refuse-or-ready verdict
# per table.  Options shared by table and list-table are preserved; only a
# mapping that cannot prove equivalent Docutils structure is refused.
# ---------------------------------------------------------------------------

_GRID = "+-----+-------+\n| A   | B     |\n+=====+=======+\n| 1   | two   |\n+-----+-------+\n"
_SIMPLE = "=====  =====\nA      B\n=====  =====\n1      2\n=====  =====\n"


@pytest.mark.integration
def test_candidate_ready_for_bare_grid_table(tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n#####\n\n" + _GRID)
    entry = _document.find_tables(p)[0]
    candidate = _list_table._evaluate_list_table_candidate(p.read_text(encoding="utf-8").splitlines(), entry)
    assert candidate.refusal is None
    assert candidate.caption is None
    assert candidate.parsed is not None
    assert candidate.parsed.colspecs == [5, 7]


@pytest.mark.integration
def test_candidate_ready_for_bare_simple_table(tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n#####\n\n" + _SIMPLE)
    entry = _document.find_tables(p)[0]
    candidate = _list_table._evaluate_list_table_candidate(p.read_text(encoding="utf-8").splitlines(), entry)
    assert candidate.refusal is None
    assert candidate.caption is None
    assert candidate.parsed is not None


@pytest.mark.integration
def test_candidate_ready_for_table_directive_with_caption(tmp_path: Path) -> None:
    text = "Title\n#####\n\n.. table:: My Caption\n\n   " + _GRID.replace("\n", "\n   ").rstrip() + "\n"
    p = _rst(tmp_path, text)
    entry = _document.find_tables(p)[0]
    candidate = _list_table._evaluate_list_table_candidate(p.read_text(encoding="utf-8").splitlines(), entry)
    assert candidate.refusal is None
    assert candidate.caption == "My Caption"
    assert candidate.parsed is not None
    assert candidate.parsed.colspecs == [5, 7]


@pytest.mark.integration
def test_plan_converts_table_directive_with_continued_caption(tmp_path: Path) -> None:
    """Both RSTTable and ListTable accept one optional argument with
    final whitespace, so a caption may continue on indented source lines.
    The converter must carry that valid directive argument rather than
    mistake it for unknown content before the table body."""
    text = (
        "Title\n#####\n\n"
        ".. table:: First caption line\n"
        "   second caption line\n"
        "   :name: continued-caption\n\n"
        "   " + _GRID.replace("\n", "\n   ").rstrip() + "\n"
    )
    p = _rst(tmp_path, text)

    result = _list_table._plan_list_table_file(p, only=[], skip=[])

    assert result.fatal is None
    assert result.refusals == []
    assert result.converted == [1]
    assert ".. list-table:: First caption line\n   second caption line\n" in result.candidate
    assert "   :name: continued-caption\n" in result.candidate
    assert _list_table._list_table_conversion_preserves_semantics(p, result.original, result.candidate)


@pytest.mark.integration
def test_candidate_ready_for_table_directive_without_caption(tmp_path: Path) -> None:
    text = "Title\n#####\n\n.. table::\n\n   " + _GRID.replace("\n", "\n   ").rstrip() + "\n"
    p = _rst(tmp_path, text)
    entry = _document.find_tables(p)[0]
    candidate = _list_table._evaluate_list_table_candidate(p.read_text(encoding="utf-8").splitlines(), entry)
    assert candidate.refusal is None
    assert candidate.caption is None


@pytest.mark.integration
def test_candidate_preserves_table_directive_name_option(tmp_path: Path) -> None:
    text = "Title\n#####\n\n.. table:: Caption\n   :name: mytable\n\n   " + _GRID.replace("\n", "\n   ").rstrip() + "\n"
    p = _rst(tmp_path, text)
    entry = _document.find_tables(p)[0]
    candidate = _list_table._evaluate_list_table_candidate(p.read_text(encoding="utf-8").splitlines(), entry)
    assert candidate.refusal is None
    assert candidate.options == (("name", "mytable"),)


@pytest.mark.integration
def test_candidate_refuses_already_list_table(tmp_path: Path) -> None:
    text = "Title\n#####\n\n.. list-table::\n   :header-rows: 1\n\n   * - A\n     - B\n   * - 1\n     - 2\n"
    p = _rst(tmp_path, text)
    entry = _document.find_tables(p)[0]
    candidate = _list_table._evaluate_list_table_candidate(p.read_text(encoding="utf-8").splitlines(), entry)
    assert candidate.refusal is not None
    assert "list-table" in candidate.refusal


@pytest.mark.integration
def test_candidate_refuses_csv_table(tmp_path: Path) -> None:
    text = 'Title\n#####\n\n.. csv-table::\n\n   "A","B"\n   "1","2"\n'
    p = _rst(tmp_path, text)
    entry = _document.find_tables(p)[0]
    candidate = _list_table._evaluate_list_table_candidate(p.read_text(encoding="utf-8").splitlines(), entry)
    assert candidate.refusal is not None
    assert "csv" in candidate.refusal


@pytest.mark.integration
def test_candidate_refuses_table_with_span(tmp_path: Path) -> None:
    spanned = (
        "+-----+-----+\n| A   | B   |\n+=====+=====+\n| 1   | 2   |\n+     +-----+\n|     | 4   |\n+-----+-----+\n"
    )
    p = _rst(tmp_path, "Title\n#####\n\n" + spanned)
    entry = _document.find_tables(p)[0]
    candidate = _list_table._evaluate_list_table_candidate(p.read_text(encoding="utf-8").splitlines(), entry)
    assert candidate.refusal is not None
    assert "span" in candidate.refusal


# ---------------------------------------------------------------------------
# Stage 4: the conversion algorithm — emit `.. list-table::` RST text from
# a ParsedTable, preserving every cell's own source verbatim (never
# re-serializing through a parsed tree) and passing colspecs straight
# through as :widths: so the resulting doctree's colwidth matches the
# original exactly (confirmed by direct probe: :widths: values pass
# through to colwidth unchanged, not normalized/scaled).
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_render_list_table_basic_shape() -> None:
    lines = [
        "+-----+-------+",
        "| A   | B     |",
        "+=====+=======+",
        "| 1   | two   |",
        "+-----+-------+",
    ]
    parsed = _list_table._parse_aligned_table(lines)
    text = _list_table._render_list_table(parsed, caption=None)
    assert text == (
        ".. list-table::\n   :header-rows: 1\n   :widths: 5 7\n\n   * - A\n     - B\n   * - 1\n     - two\n"
    )


@pytest.mark.unit
def test_render_list_table_with_caption() -> None:
    lines = ["=====  =====", "A      B", "=====  =====", "1      2", "=====  ====="]
    parsed = _list_table._parse_aligned_table(lines)
    text = _list_table._render_list_table(parsed, caption="My Caption")
    assert text.splitlines()[0] == ".. list-table:: My Caption"


@pytest.mark.unit
def test_render_list_table_no_header_omits_header_rows_option() -> None:
    lines = ["=====  =====", "1      2", "3      4", "=====  ====="]
    parsed = _list_table._parse_aligned_table(lines)
    assert parsed.header_rows == []
    text = _list_table._render_list_table(parsed, caption=None)
    assert ":header-rows:" not in text


@pytest.mark.unit
def test_render_list_table_multiline_cell_indented_under_content_column() -> None:
    lines = [
        "+-----------+------------------------+",
        "|Form       |Text                    |",
        "+===========+========================+",
        "|current    |``**Author filter**``   |",
        "|           |multi-line continued    |",
        "+-----------+------------------------+",
    ]
    parsed = _list_table._parse_aligned_table(lines)
    text = _list_table._render_list_table(parsed, caption=None)
    assert "   * - current\n     - ``**Author filter**``\n       multi-line continued\n" in text


@pytest.mark.unit
def test_render_list_table_never_emits_trailing_whitespace() -> None:
    lines = [
        "+-----------+------+",
        "|Form       |Text  |",
        "+===========+======+",
        "|current    |      |",
        "|           |cont  |",
        "+-----------+------+",
    ]
    parsed = _list_table._parse_aligned_table(lines)
    text = _list_table._render_list_table(parsed, caption=None)
    assert all(line == line.rstrip() for line in text.splitlines())


# ---------------------------------------------------------------------------
# Stage 5: semantic validation — the whole-file gate before any write.
# Reuses _text_space_evidence's exact canonical-tree modeling technique
# (class identity, frozen attributes, children, recursively), but with NO
# permitted delta: :widths: passthrough (stage 4) already makes a correct
# conversion's doctree byte-identical to the original, confirmed by direct
# probe, so exact equality is the right bar, not a documented exception.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_equivalent_conversion_passes_validation(tmp_path: Path) -> None:
    original = "Title\n#####\n\n" + _GRID
    p = _rst(tmp_path, original)
    entry = _document.find_tables(p)[0]
    candidate = _list_table._evaluate_list_table_candidate(original.splitlines(), entry)
    assert candidate.refusal is None
    assert candidate.parsed is not None
    rendered = _list_table._render_list_table(candidate.parsed, candidate.caption)
    lines = original.splitlines()
    new_text = "\n".join((*lines[: entry.lineno - 1], rendered.rstrip(), *lines[entry.end :])) + "\n"
    assert _list_table._list_table_conversion_preserves_semantics(p, original, new_text)


@pytest.mark.integration
def test_corrupted_conversion_fails_validation(tmp_path: Path) -> None:
    """A candidate text that drops a cell's content must be rejected, not
    silently accepted — the same all-or-nothing rule --fix already uses."""
    original = "Title\n#####\n\n" + _GRID
    p = _rst(tmp_path, original)
    corrupted = original.replace("two", "WRONG")
    assert not _list_table._list_table_conversion_preserves_semantics(p, original, corrupted)


@pytest.mark.integration
def test_divergence_reason_names_the_changed_text(tmp_path: Path) -> None:
    """Found live (a real --apply run failed with only 'converted result
    failed semantic validation — file left untouched', no way to tell
    where or why without a manual bisection of the whole file).  The
    plain bool _list_table_conversion_preserves_semantics stays cheap for
    the common, passing case; this is the diagnostic counterpart, paid
    for only once validation has already failed.

    Same-length substitution deliberately, confirmed by direct probe:
    replacing "two" with the longer "WRONG" shifts a fixed-width grid
    table's own column alignment, so docutils no longer parses a table
    there at all (a 'table' node becomes a 'system_message' node) — a
    real, useful divergence reason in its own right, but a structural
    one, not the plain text-substitution case this test isolates."""
    original = "Title\n#####\n\n" + _GRID
    p = _rst(tmp_path, original)
    corrupted = original.replace("two", "TWO")
    reason = _list_table._list_table_divergence_reason(p, original, corrupted)
    assert "two" in reason
    assert "TWO" in reason


@pytest.mark.integration
def test_divergence_reason_names_a_dropped_node(tmp_path: Path) -> None:
    """A structural difference (not just changed text) must be described
    too — a dropped table row changes child COUNT, not any one text
    value, so the divergence report must not assume every mismatch is a
    text substitution."""
    original = "Title\n#####\n\n" + _GRID
    p = _rst(tmp_path, original)
    # Corrupt by removing the whole second column from every row, forcing
    # a structural rather than purely textual mismatch.
    corrupted = "Title\n#####\n\n+-----+\n| A   |\n+=====+\n| 1   |\n+-----+\n"
    reason = _list_table._list_table_divergence_reason(p, original, corrupted)
    assert reason
    assert "converted result failed semantic validation" not in reason


@pytest.mark.integration
def test_identical_text_has_no_divergence_reason(tmp_path: Path) -> None:
    """Two identical trees have nothing to report — confirms the function
    does not manufacture a spurious reason on the passing path."""
    original = "Title\n#####\n\n" + _GRID
    p = _rst(tmp_path, original)
    assert _list_table._list_table_divergence_reason(p, original, original) == ""


# A lone "#" cell trips docutils' own title/transition heuristic (a line
# consisting entirely of one repeated punctuation character *might* be a
# title overline or a transition marker) even inside a table cell; too
# short to be one, so docutils resolves it as ordinary text but still
# records an INFO system_message about the ambiguity — confirmed live,
# a real downstream table used "#" as an ordinal-column header.
_GRID_WITH_AMBIGUOUS_HEADER = "+---+-------+\n| # | Value |\n+===+=======+\n| 1 | x     |\n+---+-------+\n"


@pytest.mark.integration
def test_docutils_system_message_line_shift_does_not_fail_validation(
    tmp_path: Path,
) -> None:
    """Found live: a table with a lone '#' header cell always failed
    list-table conversion, even though the conversion itself was
    correct. Root cause confirmed by direct probe: docutils attaches an
    INFO system_message ('Unexpected possible title overline or
    transition... too short') to that cell, and the message's own
    'line' attribute necessarily shifts when the cell moves to a
    different physical line under list-table syntax — position
    bookkeeping, not semantic content, the same category of thing
    _canonical_doctree_model's existing 'colwidths-given' exception
    already carves out for a different docutils-internal artifact."""
    original = "Title\n#####\n\n" + _GRID_WITH_AMBIGUOUS_HEADER
    p = _rst(tmp_path, original)
    entry = _document.find_tables(p)[0]
    candidate = _list_table._evaluate_list_table_candidate(original.splitlines(), entry)
    assert candidate.refusal is None
    assert candidate.parsed is not None
    rendered = _list_table._render_list_table(candidate.parsed, candidate.caption)
    lines = original.splitlines()
    new_text = "\n".join((*lines[: entry.lineno - 1], rendered.rstrip(), *lines[entry.end :])) + "\n"
    assert new_text != original  # the line genuinely moved, or this test proves nothing
    assert _list_table._list_table_conversion_preserves_semantics(p, original, new_text)


@pytest.mark.integration
def test_identical_text_passes_validation(tmp_path: Path) -> None:
    original = "Title\n#####\n\n" + _GRID
    p = _rst(tmp_path, original)
    assert _list_table._list_table_conversion_preserves_semantics(p, original, original)


# ---------------------------------------------------------------------------
# Stage 7a: per-file orchestration — resolve selection, evaluate/render
# every in-scope table, splice approved conversions, re-validate the whole
# file before any write. Read-only at this stage (no writing yet — that's
# the CLI-level --apply wiring, tested through the full cli.main()
# in test_check_rst.py).
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_plan_converts_single_eligible_table(tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n#####\n\n" + _GRID)
    result = _list_table._plan_list_table_file(p, only=[], skip=[])
    assert result.fatal is None
    assert result.converted == [1]
    assert result.refusals == []
    assert result.changed is True
    assert ".. list-table::" in result.candidate


@pytest.mark.integration
def test_plan_no_tables_is_unchanged_and_not_fatal(tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n#####\n\nJust prose, no tables here.\n")
    result = _list_table._plan_list_table_file(p, only=[], skip=[])
    assert result.fatal is None
    assert result.converted == []
    assert result.changed is False
    assert result.candidate == result.original


@pytest.mark.integration
def test_plan_default_scope_reports_refusal_without_blocking_others(
    tmp_path: Path,
) -> None:
    """No --only given: a spanned table among several is reported, not
    fatal — the other eligible tables in the same file still convert."""
    spanned = (
        "+-----+-----+\n| A   | B   |\n+=====+=====+\n| 1   | 2   |\n+     +-----+\n|     | 4   |\n+-----+-----+\n"
    )
    text = "Title\n#####\n\n" + _GRID + "\nMid\n---\n\n" + spanned
    p = _rst(tmp_path, text)
    result = _list_table._plan_list_table_file(p, only=[], skip=[])
    assert result.fatal is None
    assert result.converted == [1]
    assert len(result.refusals) == 1
    assert result.refusals[0].ordinal == 2
    assert "span" in result.refusals[0].reason
    assert result.changed is True


@pytest.mark.integration
def test_plan_explicit_only_on_refused_table_is_fatal(tmp_path: Path) -> None:
    """--only naming exactly one table that turns out refused is fatal —
    the user asked for that table specifically, unlike the default scope."""
    spanned = (
        "+-----+-----+\n| A   | B   |\n+=====+=====+\n| 1   | 2   |\n+     +-----+\n|     | 4   |\n+-----+-----+\n"
    )
    p = _rst(tmp_path, "Title\n#####\n\n" + spanned)
    result = _list_table._plan_list_table_file(p, only=[1], skip=[])
    assert result.fatal is not None
    assert result.fatal.code == "list-table.span"
    assert result.candidate == result.original


@pytest.mark.integration
def test_plan_skip_excludes_table_entirely_no_refusal_reported(tmp_path: Path) -> None:
    spanned = (
        "+-----+-----+\n| A   | B   |\n+=====+=====+\n| 1   | 2   |\n+     +-----+\n|     | 4   |\n+-----+-----+\n"
    )
    text = "Title\n#####\n\n" + _GRID + "\nMid\n---\n\n" + spanned
    p = _rst(tmp_path, text)
    result = _list_table._plan_list_table_file(p, only=[], skip=[2])
    assert result.fatal is None
    assert result.converted == [1]
    assert result.refusals == []


@pytest.mark.integration
def test_plan_unknown_ordinal_is_fatal_and_leaves_candidate_unchanged(
    tmp_path: Path,
) -> None:
    p = _rst(tmp_path, "Title\n#####\n\n" + _GRID)
    result = _list_table._plan_list_table_file(p, only=[5], skip=[])
    assert result.fatal is not None
    assert result.fatal.code == "list-table.unknown-ordinal"
    assert "5" in result.fatal.reason
    assert result.candidate == result.original


@pytest.mark.integration
def test_plan_multiple_tables_all_convert_preserving_document_order(
    tmp_path: Path,
) -> None:
    text = "Title\n#####\n\n" + _GRID + "\nMid\n---\n\n" + _SIMPLE
    p = _rst(tmp_path, text)
    result = _list_table._plan_list_table_file(p, only=[], skip=[])
    assert result.fatal is None
    assert result.converted == [1, 2]
    assert result.candidate.count(".. list-table::") == 2
    # the converted result must itself be valid, re-parseable RST with no
    # structural regression versus the original.
    assert _list_table._list_table_conversion_preserves_semantics(p, result.original, result.candidate)


@pytest.mark.integration
def test_plan_ordinals_include_existing_list_and_csv_tables(tmp_path: Path) -> None:
    text = (
        """\
Title
#####

.. list-table:: Existing

   * - A
     - B

.. csv-table:: CSV

   "A","B"

"""
        + _GRID
    )
    p = _rst(tmp_path, text)

    result = _list_table._plan_list_table_file(p, only=[], skip=[])

    assert result.fatal is None
    assert result.converted == [3]
    assert [(issue.ordinal, issue.code, issue.category) for issue in result.refusals] == [
        (1, "list-table.already-list-table", "unchanged"),
        (2, "list-table.csv-table", "unsupported"),
    ]


@pytest.mark.integration
def test_plan_preserves_crlf_outside_the_replaced_table(tmp_path: Path) -> None:
    """A semantic doctree comparison cannot detect newline damage in
    unrelated source.  Conversion owns the selected table block only."""
    p = tmp_path / "doc.rst"
    original = ("Title\n#####\n\n" + _GRID + "\nAfter.\n").replace("\n", "\r\n")
    p.write_bytes(original.encode())

    result = _list_table._plan_list_table_file(p, only=[], skip=[])

    assert result.fatal is None
    assert result.converted == [1]
    assert result.candidate.startswith("Title\r\n#####\r\n\r\n")
    assert result.candidate.endswith("\r\nAfter.\r\n")
    assert ".. list-table::\r\n" in result.candidate


@pytest.mark.integration
def test_plan_converts_simple_table_with_multiline_final_row(tmp_path: Path) -> None:
    simple = (
        "=====  ==========\nA      B\n=====  ==========\n1      first line\n       second line\n=====  ==========\n"
    )
    p = _rst(tmp_path, "Title\n#####\n\n" + simple)

    result = _list_table._plan_list_table_file(p, only=[], skip=[])

    assert result.fatal is None
    assert result.converted == [1]
    assert "first line\n       second line" in result.candidate
    assert _list_table._list_table_conversion_preserves_semantics(p, result.original, result.candidate)


@pytest.mark.integration
def test_plan_accepts_multiple_blank_lines_before_table_directive_body(tmp_path: Path) -> None:
    body = "\n".join(f"   {line}" if line else "" for line in _GRID.splitlines())
    p = _rst(tmp_path, "Title\n#####\n\n.. table:: Caption\n\n\n" + body + "\n")

    result = _list_table._plan_list_table_file(p, only=[], skip=[])

    assert result.fatal is None
    assert result.converted == [1]
    assert ".. list-table:: Caption" in result.candidate


@pytest.mark.integration
def test_plan_reports_docutils_table_parser_failure_without_a_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = _rst(tmp_path, "Title\n#####\n\n" + _GRID)

    def fail_parse(lines: list[str]) -> _types.ParsedTable:
        raise docutils.parsers.rst.tableparser.TableMarkupError("probe failure")

    monkeypatch.setattr(_list_table, "_parse_aligned_table", fail_parse)
    result = _list_table._plan_list_table_file(p, only=[], skip=[])

    assert result.fatal is None
    assert result.converted == []
    assert len(result.refusals) == 1
    assert result.refusals[0].code == "list-table.source-model"
    assert "probe failure" in result.refusals[0].reason


@pytest.mark.integration
def test_cli_reports_source_model_failure_as_contextual_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = _rst(tmp_path, "Title\n#####\n\n" + _GRID)

    def fail_parse(lines: list[str]) -> _types.ParsedTable:
        raise docutils.parsers.rst.tableparser.TableMarkupError("probe failure")

    monkeypatch.setattr(_list_table, "_parse_aligned_table", fail_parse)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", str(p)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert f"{p}:4: ERROR [list-table.source-model]" in out
    assert "Impact: table 1 unchanged" in out
    assert "Action: Inspect the reported source range" in out
    assert "1 table error(s)" in out


@pytest.mark.integration
def test_plan_preserves_enclosing_list_indentation(tmp_path: Path) -> None:
    nested = "\n".join(f"  {line}" if line else "" for line in _GRID.splitlines()) + "\n"
    p = _rst(tmp_path, "Title\n#####\n\n* Item\n\n" + nested)

    result = _list_table._plan_list_table_file(p, only=[], skip=[])

    assert result.fatal is None
    assert result.converted == [1]
    assert "\n  .. list-table::\n" in result.candidate
    assert _list_table._list_table_conversion_preserves_semantics(p, result.original, result.candidate)


@pytest.mark.integration
def test_plan_preserves_directives_lists_and_paragraphs_inside_a_cell(tmp_path: Path) -> None:
    rich = (
        "+--------------------+\n"
        "| Content            |\n"
        "+====================+\n"
        "| .. note::          |\n"
        "|                    |\n"
        "|    Nested note.    |\n"
        "|                    |\n"
        "| * first            |\n"
        "| * second           |\n"
        "|                    |\n"
        "| Final paragraph.   |\n"
        "+--------------------+\n"
    )
    p = _rst(tmp_path, "Title\n#####\n\n" + rich)

    result = _list_table._plan_list_table_file(p, only=[], skip=[])

    assert result.fatal is None
    assert result.converted == [1]
    assert "   * - .. note::" in result.candidate
    assert "       * first\n       * second" in result.candidate
    assert "       Final paragraph." in result.candidate
    assert _list_table._list_table_conversion_preserves_semantics(p, result.original, result.candidate)


@pytest.mark.integration
def test_plan_preserves_supported_table_directive_options(tmp_path: Path) -> None:
    body = "\n".join(f"   {line}" if line else "" for line in _GRID.splitlines())
    p = _rst(
        tmp_path,
        "Title\n#####\n\n"
        ".. table:: Caption\n"
        "   :class: compact striped\n"
        "   :name: sample-table\n"
        "   :align: center\n"
        "   :width: 80%\n"
        "   :widths: 5 7\n\n"
        f"{body}\n",
    )

    result = _list_table._plan_list_table_file(p, only=[], skip=[])

    assert result.fatal is None
    assert result.converted == [1]
    for option in (
        ":class: compact striped",
        ":name: sample-table",
        ":align: center",
        ":width: 80%",
        ":widths: 5 7",
    ):
        assert option in result.candidate


@pytest.mark.integration
def test_plan_maps_widths_grid_to_effective_column_widths(tmp_path: Path) -> None:
    body = "\n".join(f"   {line}" if line else "" for line in _GRID.splitlines())
    p = _rst(tmp_path, "Title\n#####\n\n.. table::\n   :widths: grid\n\n" + body + "\n")

    result = _list_table._plan_list_table_file(p, only=[], skip=[])

    assert result.fatal is None
    assert result.converted == [1]
    assert ":widths: 5 7" in result.candidate


_NESTED_ALIGNED_TABLE = """\
+-----------------------------+
| Outer                       |
+=============================+
| .. table:: Inner            |
|                             |
|    +-----+-----+            |
|    | A   | B   |            |
|    +=====+=====+            |
|    | 1   | 2   |            |
|    +-----+-----+            |
+-----------------------------+
"""


@pytest.mark.integration
def test_plan_converts_nested_aligned_tables_safely_in_two_passes(tmp_path: Path) -> None:
    """An inner table has no independently editable source block while
    its text is framed by an outer grid.  Converting the ancestor makes
    that directive ordinary list-item content, so the next pass can
    convert it without rebuilding the outer table."""
    p = _rst(tmp_path, "Title\n#####\n\n" + _NESTED_ALIGNED_TABLE)

    outer = _list_table._plan_list_table_file(p, only=[], skip=[])

    assert outer.fatal is None
    assert outer.converted == [1]
    assert [issue.code for issue in outer.refusals] == ["list-table.nested-aligned-table"]
    assert "ancestor first" in outer.refusals[0].action

    p.write_text(outer.candidate, encoding="utf-8")
    inner = _list_table._plan_list_table_file(p, only=[2], skip=[])

    assert inner.fatal is None
    assert inner.converted == [2]
    assert inner.candidate.count(".. list-table::") == 2
    assert _list_table._list_table_conversion_preserves_semantics(p, inner.original, inner.candidate)


@pytest.mark.integration
def test_plan_refuses_inner_table_only_until_ancestor_is_converted(tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n#####\n\n" + _NESTED_ALIGNED_TABLE)

    result = _list_table._plan_list_table_file(p, only=[2], skip=[])

    assert result.fatal is not None
    assert result.fatal.code == "list-table.nested-aligned-table"
    assert "file left untouched" in result.fatal.impact
    assert result.candidate == result.original


@pytest.mark.integration
def test_plan_refuses_widths_auto_with_specific_blocker(tmp_path: Path) -> None:
    body = "\n".join(f"   {line}" if line else "" for line in _GRID.splitlines())
    p = _rst(tmp_path, "Title\n#####\n\n.. table::\n   :widths: auto\n\n" + body + "\n")

    result = _list_table._plan_list_table_file(p, only=[], skip=[])

    assert result.fatal is None
    assert result.converted == []
    assert len(result.refusals) == 1
    assert "widths-auto" in result.refusals[0].code
    assert "changes the table's column-width model" in result.refusals[0].reason


@pytest.mark.integration
def test_widths_auto_list_table_has_a_different_canonical_model(tmp_path: Path) -> None:
    body = "\n".join(f"   {line}" if line else "" for line in _GRID.splitlines())
    original = "Title\n#####\n\n.. table::\n   :widths: auto\n\n" + body + "\n"
    candidate = (
        "Title\n#####\n\n"
        ".. list-table::\n"
        "   :header-rows: 1\n"
        "   :widths: auto\n\n"
        "   * - A\n"
        "     - B\n"
        "   * - 1\n"
        "     - two\n"
    )
    p = _rst(tmp_path, original)

    assert not _list_table._list_table_conversion_preserves_semantics(p, original, candidate)
    assert "attributes changed" in _list_table._list_table_divergence_reason(p, original, candidate)


@pytest.mark.integration
def test_cli_refusal_explains_context_impact_and_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spanned = (
        "+-----+-----+\n| A   | B   |\n+=====+=====+\n| 1   | 2   |\n+     +-----+\n|     | 4   |\n+-----+-----+\n"
    )
    p = _rst(tmp_path, "Title\n#####\n\n" + spanned)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", str(p)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert f"{p}:4: REFUSED [list-table.span]" in out
    assert "table 1 (grid, 3x2)" in out
    assert "Impact: table 1 unchanged" in out
    assert "Action:" in out
    assert "1 table(s) refused" in out
    assert "no eligible tables to convert" not in out


@pytest.mark.integration
def test_cli_semantic_proof_failure_is_a_contextual_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = _rst(tmp_path, "Title\n#####\n\n" + _GRID)
    monkeypatch.setattr(_list_table, "_list_table_conversion_preserves_semantics", lambda *_args: False)
    monkeypatch.setattr(_list_table, "_list_table_divergence_reason", lambda *_args: "probe divergence")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", str(p)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert f"{p}:4: ERROR [list-table.semantic-proof]" in out
    assert "probe divergence" in out
    assert "1 table error(s)" in out
    assert p.read_text(encoding="utf-8") == "Title\n#####\n\n" + _GRID


@pytest.mark.integration
def test_cli_combined_semantic_proof_failure_leaves_the_file_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = "Title\n#####\n\n" + _GRID + "\n" + _SIMPLE
    p = _rst(tmp_path, original)
    validation_results = iter((True, True, False))
    monkeypatch.setattr(
        _list_table,
        "_list_table_conversion_preserves_semantics",
        lambda *_args: next(validation_results),
    )
    monkeypatch.setattr(_list_table, "_list_table_divergence_reason", lambda *_args: "combined divergence")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", "--apply", str(p)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert p.read_text(encoding="utf-8") == original
    out = capsys.readouterr().out
    assert f"{p}:1: ERROR [list-table.semantic-proof]" in out
    assert "combined divergence" in out
    assert "0 file(s) converted" in out


# ---------------------------------------------------------------------------
# Acceptance fixture: a real-world grid table (from a Journal calendar
# entry comparing RST heading styles by line cost — genericized, no
# project-specific content; the surrounding discussion is exactly the kind
# of real evidence "Author filter" already appears as an illustrative
# example for in docs/rules.rst). Multi-line cell, inline-literal spans,
# and a header row make this better coverage than a synthetic fixture.
# ---------------------------------------------------------------------------

_REAL_WORLD_TABLE = (
    "+------------------------------+---------------------------------------------------------+-------+\n"
    "| Form                         | Text                                                    | Lines |\n"
    "+==============================+=========================================================+=======+\n"
    "| current                      | ``**Author filter** — keep only commits by...``         | 1     |\n"
    "+------------------------------+---------------------------------------------------------+-------+\n"
    "| real heading                 | ``#### Author filter``\\ ⏎⏎\\ ``Keep only commits by...`` | 3     |\n"
    "+------------------------------+---------------------------------------------------------+-------+\n"
    "| def-list                     | ``Author filter``\\ ⏎\\ ``:   Keep only commits by...``   | 2     |\n"
    "| (``Term\\n:   text``)         |                                                         |       |\n"
    "+------------------------------+---------------------------------------------------------+-------+\n"
)


@pytest.mark.integration
def test_acceptance_real_world_table_converts_and_preserves_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = "#######\nTable\n#######\n\n" + _REAL_WORLD_TABLE
    p = _rst(tmp_path, original)
    result = _list_table._plan_list_table_file(p, only=[], skip=[])
    assert result.fatal is None
    assert result.refusals == []
    assert result.converted == [1]
    assert result.changed is True

    # Every cell's own inline-literal span survives verbatim, byte for byte
    # — never re-serialized through a parsed tree.
    assert "``**Author filter** — keep only commits by...``" in result.candidate
    assert "``#### Author filter``\\ ⏎⏎\\ ``Keep only commits by...``" in result.candidate
    assert "``Author filter``\\ ⏎\\ ``:   Keep only commits by...``" in result.candidate

    # The multi-line first cell's continuation line is indented under its
    # own content column, not left at column 0 or misaligned.
    assert "   * - def-list\n       (``Term\\n:   text``)\n" in result.candidate

    # The definitive check: re-parsing the whole converted document is
    # structurally equivalent to the original, not merely "looks right".
    assert _list_table._list_table_conversion_preserves_semantics(p, result.original, result.candidate)

    # And the tool's own full CLI validation loop is clean on the written,
    # converted result — not just the internal model.
    p.write_text(result.candidate, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--no-config", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert "ERROR" not in capsys.readouterr().out


_LIST_TABLE_GRID = "+-----+-------+\n| A   | B     |\n+=====+=======+\n| 1   | two   |\n+-----+-------+\n"


@pytest.mark.integration
def test_tables_list_table_with_caption_and_header(tmp_path: Path) -> None:
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
    entries = _document.find_tables(p)
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == "list"
    assert e.caption == "Quarterly Numbers"
    assert e.dims == (2, 2)
    assert e.preview == "Quarter Revenue Q1 100"  # both rows chained, header first
    assert e.lineno == 4  # the directive's own line


@pytest.mark.integration
def test_cli_list_table_dry_run_prints_diff_and_exits_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "doc.rst"
    p.write_text("Title\n#####\n\n" + _LIST_TABLE_GRID, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "-+-----+-------+" in out
    assert "+.. list-table::" in out
    assert p.read_text(encoding="utf-8") == "Title\n#####\n\n" + _LIST_TABLE_GRID  # untouched
    assert "1 file(s) would change" in out


@pytest.mark.integration
def test_cli_list_table_apply_writes_file_and_exits_0(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "doc.rst"
    original = "Title\n#####\n\n" + _LIST_TABLE_GRID
    p.write_text(original, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", "--apply", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    written = p.read_text(encoding="utf-8")
    assert ".. list-table::" in written
    assert written != original
    out = capsys.readouterr().out
    assert "converted table(s) 1" in out
    assert "1 file(s) converted" in out


@pytest.mark.integration
def test_cli_apply_writes_proven_tables_despite_an_ordinary_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spanned = (
        "+-----+-----+\n| A   | B   |\n+=====+=====+\n| 1   | 2   |\n+     +-----+\n|     | 4   |\n+-----+-----+\n"
    )
    p = _rst(tmp_path, "Title\n#####\n\n" + _GRID + "\n" + spanned)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", "--apply", str(p)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    written = p.read_text(encoding="utf-8")
    assert written.count(".. list-table::") == 1
    assert "+     +-----+" in written
    out = capsys.readouterr().out
    assert "REFUSED [list-table.span]" in out
    assert "1 table(s) converted, 1 table(s) refused" in out


@pytest.mark.integration
def test_cli_apply_writes_other_proven_tables_but_exits_1_on_table_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = _rst(tmp_path, "Title\n#####\n\n" + _GRID + "\n" + _SIMPLE)
    validation_results = iter((False, True, True))
    monkeypatch.setattr(
        _list_table,
        "_list_table_conversion_preserves_semantics",
        lambda *_args: next(validation_results),
    )
    monkeypatch.setattr(_list_table, "_list_table_divergence_reason", lambda *_args: "probe divergence")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", "--apply", str(p)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    written = p.read_text(encoding="utf-8")
    assert written.count(".. list-table::") == 1
    assert _GRID in written
    out = capsys.readouterr().out
    assert "ERROR [list-table.semantic-proof]" in out
    assert "1 file(s) converted" in out
    assert "1 table error(s)" in out


@pytest.mark.integration
def test_cli_list_table_no_eligible_tables_is_clean_exit_0(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "doc.rst"
    p.write_text("Title\n#####\n\nJust prose.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert "no eligible tables to convert" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_list_table_unknown_ordinal_is_fatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "doc.rst"
    p.write_text("Title\n#####\n\n" + _LIST_TABLE_GRID, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", "--only", "5", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "unknown table ordinal(s): 5" in out
    assert p.read_text(encoding="utf-8") == "Title\n#####\n\n" + _LIST_TABLE_GRID  # untouched


@pytest.mark.integration
def test_cli_list_table_skip_excludes_table_from_conversion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "doc.rst"
    p.write_text("Title\n#####\n\n" + _LIST_TABLE_GRID, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", "--skip", "1", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert "no eligible tables to convert" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_list_table_quiet_keeps_only_the_final_summary_on_a_clean_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "doc.rst"
    p.write_text("Title\n#####\n\nJust prose.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", "--quiet", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("check_rst: 1 file(s) checked")
    assert "0 file(s) would change" in out
    assert "no eligible tables to convert" not in out


@pytest.mark.integration
def test_cli_list_table_quiet_keeps_refusals_and_the_final_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spanned = (
        "+-----+-----+\n| A   | B   |\n+=====+=====+\n| 1   | 2   |\n+     +-----+\n|     | 4   |\n+-----+-----+\n"
    )
    p = _rst(tmp_path, "Title\n#####\n\n" + spanned)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", "--quiet", str(p)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "REFUSED [list-table.span]" in out
    assert "1 table(s) refused" in out
    assert "no eligible tables to convert" not in out


@pytest.mark.integration
def test_cli_list_table_rejects_sphinx_src(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "doc.rst"
    p.write_text("Title\n#####\n\n" + _LIST_TABLE_GRID, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(tmp_path), "list-table", str(p)],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert "does not use Sphinx" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_list_table_ignores_configured_sphinx_for_foreign_files(
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
        cli.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "not part of --sphinx-src" not in out
    assert "sphinx-src=docs inactive (list-table)" in out
    assert "build-dir=build inactive (list-table)" in out
    assert "+.. list-table::" in out
