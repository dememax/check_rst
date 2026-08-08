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

import pytest

if TYPE_CHECKING:
    import types
    from pathlib import Path


@pytest.fixture(scope="session")
def check_rst() -> types.ModuleType:
    from check_rst import cli

    return cli


def _tables(n: int) -> list[object]:
    """n placeholder TableEntry-shaped stand-ins — the resolver only ever
    counts and indexes them, never reads their fields."""
    return [object() for _ in range(n)]


def _rst(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "doc.rst"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.mark.unit
def test_no_only_no_skip_selects_everything(check_rst: types.ModuleType) -> None:
    tables = _tables(3)
    targets, unknown = check_rst._resolve_list_table_selection(tables, [], [])
    assert targets == tables
    assert unknown == []


@pytest.mark.unit
def test_only_narrows_to_exactly_those_ordinals(check_rst: types.ModuleType) -> None:
    tables = _tables(3)
    targets, unknown = check_rst._resolve_list_table_selection(tables, [2], [])
    assert targets == [tables[1]]
    assert unknown == []


@pytest.mark.unit
def test_only_preserves_document_order_regardless_of_argument_order(check_rst: types.ModuleType) -> None:
    tables = _tables(3)
    targets, unknown = check_rst._resolve_list_table_selection(tables, [3, 1], [])
    assert targets == [tables[0], tables[2]]
    assert unknown == []


@pytest.mark.unit
def test_skip_removes_exactly_those_ordinals(check_rst: types.ModuleType) -> None:
    tables = _tables(3)
    targets, unknown = check_rst._resolve_list_table_selection(tables, [], [2])
    assert targets == [tables[0], tables[2]]
    assert unknown == []


@pytest.mark.unit
def test_only_and_skip_combine_only_then_skip(check_rst: types.ModuleType) -> None:
    """The documented combination rule: the eligible set starts as
    everything, narrows to --only if given, then --skip removes from
    whatever that is — not the reverse order."""
    tables = _tables(5)
    targets, unknown = check_rst._resolve_list_table_selection(tables, [1, 2, 3], [2])
    assert targets == [tables[0], tables[2]]
    assert unknown == []


@pytest.mark.unit
def test_only_and_skip_the_same_ordinal_resolves_empty(check_rst: types.ModuleType) -> None:
    """A direct contradiction — --only 2 --skip 2 — resolves to an empty
    target list, not an error by itself; the caller decides whether an
    empty result is fatal (it is, for the actual CLI, but this function
    stays pure)."""
    tables = _tables(3)
    targets, unknown = check_rst._resolve_list_table_selection(tables, [2], [2])
    assert targets == []
    assert unknown == []


@pytest.mark.unit
def test_out_of_range_only_ordinal_is_reported_not_silently_dropped(check_rst: types.ModuleType) -> None:
    tables = _tables(2)
    targets, unknown = check_rst._resolve_list_table_selection(tables, [5], [])
    assert targets == []
    assert unknown == [5]


@pytest.mark.unit
def test_out_of_range_skip_ordinal_is_reported(check_rst: types.ModuleType) -> None:
    tables = _tables(2)
    targets, unknown = check_rst._resolve_list_table_selection(tables, [], [9])
    assert targets == []
    assert unknown == [9]


@pytest.mark.unit
def test_ordinal_zero_and_negative_are_out_of_range(check_rst: types.ModuleType) -> None:
    """Ordinals are 1-based; 0 and negative values are never valid,
    regardless of how many tables exist."""
    tables = _tables(3)
    targets, unknown = check_rst._resolve_list_table_selection(tables, [0, -1], [])
    assert targets == []
    assert unknown == [0, -1]


@pytest.mark.unit
def test_multiple_unknown_ordinals_reported_in_given_order(check_rst: types.ModuleType) -> None:
    tables = _tables(2)
    targets, unknown = check_rst._resolve_list_table_selection(tables, [5], [8])
    assert targets == []
    assert unknown == [5, 8]


@pytest.mark.unit
def test_no_tables_and_no_selection_resolves_empty_without_unknown(check_rst: types.ModuleType) -> None:
    """An empty file (no tables at all) is not the same failure as an
    out-of-range ordinal — the caller distinguishes them by checking
    whether `tables` itself was empty."""
    targets, unknown = check_rst._resolve_list_table_selection([], [], [])
    assert targets == []
    assert unknown == []


# ---------------------------------------------------------------------------
# Stage 2: mechanical eligibility — which kinds this conversion accepts,
# and span detection (list-table cannot express a merged cell, so any
# non-zero rowspan/colspan must be a hard, explanatory refusal).
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("kind", "eligible"), [("grid", True), ("simple", True), ("table", True), ("list", False), ("csv", False)]
)
def test_table_eligible_kinds(check_rst: types.ModuleType, kind: str, eligible: bool) -> None:
    assert check_rst._table_kind_eligible(kind) is eligible


@pytest.mark.unit
def test_parse_aligned_table_grid(check_rst: types.ModuleType) -> None:
    lines = [
        "+-----+-------+",
        "| A   | B     |",
        "+=====+=======+",
        "| 1   | two   |",
        "+-----+-------+",
    ]
    parsed = check_rst._parse_aligned_table(lines)
    assert parsed.colspecs == [5, 7]
    assert len(parsed.header_rows) == 1
    assert len(parsed.body_rows) == 1


@pytest.mark.unit
def test_parse_aligned_table_simple(check_rst: types.ModuleType) -> None:
    lines = [
        "=====  =====",
        "A      B",
        "=====  =====",
        "1      2",
        "=====  =====",
    ]
    parsed = check_rst._parse_aligned_table(lines)
    assert len(parsed.header_rows) == 1
    assert len(parsed.body_rows) == 1


@pytest.mark.unit
def test_table_has_span_false_for_ordinary_table(check_rst: types.ModuleType) -> None:
    lines = [
        "+-----+-----+",
        "| A   | B   |",
        "+=====+=====+",
        "| 1   | 2   |",
        "+-----+-----+",
    ]
    parsed = check_rst._parse_aligned_table(lines)
    assert check_rst._table_has_span(parsed) is False


@pytest.mark.unit
def test_table_has_span_true_for_rowspan(check_rst: types.ModuleType) -> None:
    lines = [
        "+-----+-----+",
        "| A   | B   |",
        "+=====+=====+",
        "| 1   | 2   |",
        "+     +-----+",
        "|     | 4   |",
        "+-----+-----+",
    ]
    parsed = check_rst._parse_aligned_table(lines)
    assert check_rst._table_has_span(parsed) is True


@pytest.mark.unit
def test_table_has_span_true_for_colspan(check_rst: types.ModuleType) -> None:
    lines = [
        "+-----+-----+",
        "| A   | B   |",
        "+=====+=====+",
        "| 1         |",
        "+-----+-----+",
    ]
    parsed = check_rst._parse_aligned_table(lines)
    assert check_rst._table_has_span(parsed) is True


# ---------------------------------------------------------------------------
# Stage 3: candidate evaluation — locate a table's exact inner source span
# (dedented, ready for _parse_aligned_table) and optional caption, folding
# in the kind/span checks from stage 2 into one refuse-or-ready verdict per
# table.  Scope for this version: bare tables and directive-wrapped tables
# with an optional caption only — :name:/:class:/:align: are an explicit,
# reported refusal, never silently ignored or mishandled.
# ---------------------------------------------------------------------------

_GRID = "+-----+-------+\n| A   | B     |\n+=====+=======+\n| 1   | two   |\n+-----+-------+\n"
_SIMPLE = "=====  =====\nA      B\n=====  =====\n1      2\n=====  =====\n"


@pytest.mark.integration
def test_candidate_ready_for_bare_grid_table(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n#####\n\n" + _GRID)
    entry = check_rst.find_tables(p)[0]
    candidate = check_rst._evaluate_list_table_candidate(p.read_text(encoding="utf-8").splitlines(), entry)
    assert candidate.refusal is None
    assert candidate.caption is None
    assert candidate.parsed is not None
    assert candidate.parsed.colspecs == [5, 7]


@pytest.mark.integration
def test_candidate_ready_for_bare_simple_table(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n#####\n\n" + _SIMPLE)
    entry = check_rst.find_tables(p)[0]
    candidate = check_rst._evaluate_list_table_candidate(p.read_text(encoding="utf-8").splitlines(), entry)
    assert candidate.refusal is None
    assert candidate.caption is None
    assert candidate.parsed is not None


@pytest.mark.integration
def test_candidate_ready_for_table_directive_with_caption(check_rst: types.ModuleType, tmp_path: Path) -> None:
    text = "Title\n#####\n\n.. table:: My Caption\n\n   " + _GRID.replace("\n", "\n   ").rstrip() + "\n"
    p = _rst(tmp_path, text)
    entry = check_rst.find_tables(p)[0]
    candidate = check_rst._evaluate_list_table_candidate(p.read_text(encoding="utf-8").splitlines(), entry)
    assert candidate.refusal is None
    assert candidate.caption == "My Caption"
    assert candidate.parsed is not None
    assert candidate.parsed.colspecs == [5, 7]


@pytest.mark.integration
def test_candidate_ready_for_table_directive_without_caption(check_rst: types.ModuleType, tmp_path: Path) -> None:
    text = "Title\n#####\n\n.. table::\n\n   " + _GRID.replace("\n", "\n   ").rstrip() + "\n"
    p = _rst(tmp_path, text)
    entry = check_rst.find_tables(p)[0]
    candidate = check_rst._evaluate_list_table_candidate(p.read_text(encoding="utf-8").splitlines(), entry)
    assert candidate.refusal is None
    assert candidate.caption is None


@pytest.mark.integration
def test_candidate_refuses_table_directive_with_name_option(check_rst: types.ModuleType, tmp_path: Path) -> None:
    text = "Title\n#####\n\n.. table:: Caption\n   :name: mytable\n\n   " + _GRID.replace("\n", "\n   ").rstrip() + "\n"
    p = _rst(tmp_path, text)
    entry = check_rst.find_tables(p)[0]
    candidate = check_rst._evaluate_list_table_candidate(p.read_text(encoding="utf-8").splitlines(), entry)
    assert candidate.refusal is not None
    assert "name" in candidate.refusal


@pytest.mark.integration
def test_candidate_refuses_already_list_table(check_rst: types.ModuleType, tmp_path: Path) -> None:
    text = "Title\n#####\n\n.. list-table::\n   :header-rows: 1\n\n   * - A\n     - B\n   * - 1\n     - 2\n"
    p = _rst(tmp_path, text)
    entry = check_rst.find_tables(p)[0]
    candidate = check_rst._evaluate_list_table_candidate(p.read_text(encoding="utf-8").splitlines(), entry)
    assert candidate.refusal is not None
    assert "list-table" in candidate.refusal


@pytest.mark.integration
def test_candidate_refuses_csv_table(check_rst: types.ModuleType, tmp_path: Path) -> None:
    text = 'Title\n#####\n\n.. csv-table::\n\n   "A","B"\n   "1","2"\n'
    p = _rst(tmp_path, text)
    entry = check_rst.find_tables(p)[0]
    candidate = check_rst._evaluate_list_table_candidate(p.read_text(encoding="utf-8").splitlines(), entry)
    assert candidate.refusal is not None
    assert "csv" in candidate.refusal


@pytest.mark.integration
def test_candidate_refuses_table_with_span(check_rst: types.ModuleType, tmp_path: Path) -> None:
    spanned = (
        "+-----+-----+\n| A   | B   |\n+=====+=====+\n| 1   | 2   |\n+     +-----+\n|     | 4   |\n+-----+-----+\n"
    )
    p = _rst(tmp_path, "Title\n#####\n\n" + spanned)
    entry = check_rst.find_tables(p)[0]
    candidate = check_rst._evaluate_list_table_candidate(p.read_text(encoding="utf-8").splitlines(), entry)
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
def test_render_list_table_basic_shape(check_rst: types.ModuleType) -> None:
    lines = [
        "+-----+-------+",
        "| A   | B     |",
        "+=====+=======+",
        "| 1   | two   |",
        "+-----+-------+",
    ]
    parsed = check_rst._parse_aligned_table(lines)
    text = check_rst._render_list_table(parsed, caption=None)
    assert text == (
        ".. list-table::\n   :header-rows: 1\n   :widths: 5 7\n\n   * - A\n     - B\n   * - 1\n     - two\n"
    )


@pytest.mark.unit
def test_render_list_table_with_caption(check_rst: types.ModuleType) -> None:
    lines = ["=====  =====", "A      B", "=====  =====", "1      2", "=====  ====="]
    parsed = check_rst._parse_aligned_table(lines)
    text = check_rst._render_list_table(parsed, caption="My Caption")
    assert text.splitlines()[0] == ".. list-table:: My Caption"


@pytest.mark.unit
def test_render_list_table_no_header_omits_header_rows_option(check_rst: types.ModuleType) -> None:
    lines = ["=====  =====", "1      2", "3      4", "=====  ====="]
    parsed = check_rst._parse_aligned_table(lines)
    assert parsed.header_rows == []
    text = check_rst._render_list_table(parsed, caption=None)
    assert ":header-rows:" not in text


@pytest.mark.unit
def test_render_list_table_multiline_cell_indented_under_content_column(check_rst: types.ModuleType) -> None:
    lines = [
        "+-----------+------------------------+",
        "|Form       |Text                    |",
        "+===========+========================+",
        "|current    |``**Author filter**``   |",
        "|           |multi-line continued    |",
        "+-----------+------------------------+",
    ]
    parsed = check_rst._parse_aligned_table(lines)
    text = check_rst._render_list_table(parsed, caption=None)
    assert "   * - current\n     - ``**Author filter**``\n       multi-line continued\n" in text


@pytest.mark.unit
def test_render_list_table_never_emits_trailing_whitespace(check_rst: types.ModuleType) -> None:
    lines = [
        "+-----------+------+",
        "|Form       |Text  |",
        "+===========+======+",
        "|current    |      |",
        "|           |cont  |",
        "+-----------+------+",
    ]
    parsed = check_rst._parse_aligned_table(lines)
    text = check_rst._render_list_table(parsed, caption=None)
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
def test_equivalent_conversion_passes_validation(check_rst: types.ModuleType, tmp_path: Path) -> None:
    original = "Title\n#####\n\n" + _GRID
    p = _rst(tmp_path, original)
    entry = check_rst.find_tables(p)[0]
    candidate = check_rst._evaluate_list_table_candidate(original.splitlines(), entry)
    assert candidate.refusal is None
    rendered = check_rst._render_list_table(candidate.parsed, candidate.caption)
    lines = original.splitlines()
    new_text = "\n".join((*lines[: entry.lineno - 1], rendered.rstrip(), *lines[entry.end :])) + "\n"
    assert check_rst._list_table_conversion_preserves_semantics(p, original, new_text)


@pytest.mark.integration
def test_corrupted_conversion_fails_validation(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A candidate text that drops a cell's content must be rejected, not
    silently accepted — the same all-or-nothing rule --fix already uses."""
    original = "Title\n#####\n\n" + _GRID
    p = _rst(tmp_path, original)
    corrupted = original.replace("two", "WRONG")
    assert not check_rst._list_table_conversion_preserves_semantics(p, original, corrupted)


@pytest.mark.integration
def test_divergence_reason_names_the_changed_text(check_rst: types.ModuleType, tmp_path: Path) -> None:
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
    reason = check_rst._list_table_divergence_reason(p, original, corrupted)
    assert "two" in reason
    assert "TWO" in reason


@pytest.mark.integration
def test_divergence_reason_names_a_dropped_node(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A structural difference (not just changed text) must be described
    too — a dropped table row changes child COUNT, not any one text
    value, so the divergence report must not assume every mismatch is a
    text substitution."""
    original = "Title\n#####\n\n" + _GRID
    p = _rst(tmp_path, original)
    # Corrupt by removing the whole second column from every row, forcing
    # a structural rather than purely textual mismatch.
    corrupted = "Title\n#####\n\n+-----+\n| A   |\n+=====+\n| 1   |\n+-----+\n"
    reason = check_rst._list_table_divergence_reason(p, original, corrupted)
    assert reason
    assert "converted result failed semantic validation" not in reason


@pytest.mark.integration
def test_identical_text_has_no_divergence_reason(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Two identical trees have nothing to report — confirms the function
    does not manufacture a spurious reason on the passing path."""
    original = "Title\n#####\n\n" + _GRID
    p = _rst(tmp_path, original)
    assert check_rst._list_table_divergence_reason(p, original, original) == ""


# A lone "#" cell trips docutils' own title/transition heuristic (a line
# consisting entirely of one repeated punctuation character *might* be a
# title overline or a transition marker) even inside a table cell; too
# short to be one, so docutils resolves it as ordinary text but still
# records an INFO system_message about the ambiguity — confirmed live,
# a real downstream table used "#" as an ordinal-column header.
_GRID_WITH_AMBIGUOUS_HEADER = "+---+-------+\n| # | Value |\n+===+=======+\n| 1 | x     |\n+---+-------+\n"


@pytest.mark.integration
def test_docutils_system_message_line_shift_does_not_fail_validation(
    check_rst: types.ModuleType, tmp_path: Path
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
    entry = check_rst.find_tables(p)[0]
    candidate = check_rst._evaluate_list_table_candidate(original.splitlines(), entry)
    assert candidate.refusal is None
    rendered = check_rst._render_list_table(candidate.parsed, candidate.caption)
    lines = original.splitlines()
    new_text = "\n".join((*lines[: entry.lineno - 1], rendered.rstrip(), *lines[entry.end :])) + "\n"
    assert new_text != original  # the line genuinely moved, or this test proves nothing
    assert check_rst._list_table_conversion_preserves_semantics(p, original, new_text)


@pytest.mark.integration
def test_identical_text_passes_validation(check_rst: types.ModuleType, tmp_path: Path) -> None:
    original = "Title\n#####\n\n" + _GRID
    p = _rst(tmp_path, original)
    assert check_rst._list_table_conversion_preserves_semantics(p, original, original)


# ---------------------------------------------------------------------------
# Stage 7a: per-file orchestration — resolve selection, evaluate/render
# every in-scope table, splice approved conversions, re-validate the whole
# file before any write. Read-only at this stage (no writing yet — that's
# the CLI-level --apply wiring, tested through the full check_rst.main()
# in test_check_rst.py).
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_plan_converts_single_eligible_table(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n#####\n\n" + _GRID)
    result = check_rst._plan_list_table_file(p, only=[], skip=[])
    assert result.fatal is None
    assert result.converted == [1]
    assert result.refusals == []
    assert result.changed is True
    assert ".. list-table::" in result.candidate


@pytest.mark.integration
def test_plan_no_tables_is_unchanged_and_not_fatal(check_rst: types.ModuleType, tmp_path: Path) -> None:
    p = _rst(tmp_path, "Title\n#####\n\nJust prose, no tables here.\n")
    result = check_rst._plan_list_table_file(p, only=[], skip=[])
    assert result.fatal is None
    assert result.converted == []
    assert result.changed is False
    assert result.candidate == result.original


@pytest.mark.integration
def test_plan_default_scope_reports_refusal_without_blocking_others(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    """No --only given: a spanned table among several is reported, not
    fatal — the other eligible tables in the same file still convert."""
    spanned = (
        "+-----+-----+\n| A   | B   |\n+=====+=====+\n| 1   | 2   |\n+     +-----+\n|     | 4   |\n+-----+-----+\n"
    )
    text = "Title\n#####\n\n" + _GRID + "\nMid\n---\n\n" + spanned
    p = _rst(tmp_path, text)
    result = check_rst._plan_list_table_file(p, only=[], skip=[])
    assert result.fatal is None
    assert result.converted == [1]
    assert len(result.refusals) == 1
    assert result.refusals[0][0] == 2
    assert "span" in result.refusals[0][1]
    assert result.changed is True


@pytest.mark.integration
def test_plan_explicit_only_on_refused_table_is_fatal(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """--only naming exactly one table that turns out refused is fatal —
    the user asked for that table specifically, unlike the default scope."""
    spanned = (
        "+-----+-----+\n| A   | B   |\n+=====+=====+\n| 1   | 2   |\n+     +-----+\n|     | 4   |\n+-----+-----+\n"
    )
    p = _rst(tmp_path, "Title\n#####\n\n" + spanned)
    result = check_rst._plan_list_table_file(p, only=[1], skip=[])
    assert result.fatal is not None
    assert "span" in result.fatal
    assert result.candidate == result.original


@pytest.mark.integration
def test_plan_skip_excludes_table_entirely_no_refusal_reported(check_rst: types.ModuleType, tmp_path: Path) -> None:
    spanned = (
        "+-----+-----+\n| A   | B   |\n+=====+=====+\n| 1   | 2   |\n+     +-----+\n|     | 4   |\n+-----+-----+\n"
    )
    text = "Title\n#####\n\n" + _GRID + "\nMid\n---\n\n" + spanned
    p = _rst(tmp_path, text)
    result = check_rst._plan_list_table_file(p, only=[], skip=[2])
    assert result.fatal is None
    assert result.converted == [1]
    assert result.refusals == []


@pytest.mark.integration
def test_plan_unknown_ordinal_is_fatal_and_leaves_candidate_unchanged(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    p = _rst(tmp_path, "Title\n#####\n\n" + _GRID)
    result = check_rst._plan_list_table_file(p, only=[5], skip=[])
    assert result.fatal is not None
    assert "5" in result.fatal
    assert result.candidate == result.original


@pytest.mark.integration
def test_plan_multiple_tables_all_convert_preserving_document_order(
    check_rst: types.ModuleType, tmp_path: Path
) -> None:
    text = "Title\n#####\n\n" + _GRID + "\nMid\n---\n\n" + _SIMPLE
    p = _rst(tmp_path, text)
    result = check_rst._plan_list_table_file(p, only=[], skip=[])
    assert result.fatal is None
    assert result.converted == [1, 2]
    assert result.candidate.count(".. list-table::") == 2
    # the converted result must itself be valid, re-parseable RST with no
    # structural regression versus the original.
    assert check_rst._list_table_conversion_preserves_semantics(p, result.original, result.candidate)


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
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = "#######\nTable\n#######\n\n" + _REAL_WORLD_TABLE
    p = _rst(tmp_path, original)
    result = check_rst._plan_list_table_file(p, only=[], skip=[])
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
    assert check_rst._list_table_conversion_preserves_semantics(p, result.original, result.candidate)

    # And the tool's own full CLI validation loop is clean on the written,
    # converted result — not just the internal model.
    p.write_text(result.candidate, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--no-config", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    assert "ERROR" not in capsys.readouterr().out
