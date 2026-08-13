# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Tests for check_rst.cli's _output domain (console output/budget-sink) — check_rst project

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from _support import _BAD_BLOCK, _GOOD_BLOCK

from check_rst import cli
from check_rst.cli import _helpers, _output, _types

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_outline_levels_legend_chooses_first_free_char_in_canonical_order(
    capsys: pytest.CaptureFixture[str],
) -> None:
    entries: list[_types.MergedEntry] = [
        _types.OutlineEntry(1, 1, "#", "Root"),
        _types.OutlineEntry(2, 2, "=", "Sub"),
    ]

    _output._print_outline_entries(entries, None, False, sections_only=True)

    legend = capsys.readouterr().out.splitlines()[0]
    assert legend.endswith("2 sections total; next free section char: '*'")


@pytest.mark.unit
def test_outline_levels_legend_reports_when_every_section_char_is_used(
    capsys: pytest.CaptureFixture[str],
) -> None:
    entries: list[_types.MergedEntry] = [
        _types.OutlineEntry(index, index, char, f"Level {index}")
        for index, char in enumerate(_helpers.HIERARCHY, start=1)
    ]

    _output._print_outline_entries(entries, None, False, sections_only=True)

    legend = capsys.readouterr().out.splitlines()[0]
    assert legend.endswith(f"{len(_helpers.HIERARCHY)} sections total; no free section char")


@pytest.mark.unit
def test_second_top_level_title_hint_points_to_outline_legend(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _output._hints_shown.clear()
    finding = _types.Finding(
        2,
        _types.Severity.ERROR,
        "second effective top-level title 'Second'",
    )

    assert _output._print_findings([finding], "doc.rst", no_warnings=False) == (1, 0)

    output = capsys.readouterr().out
    assert "check_rst outline's levels legend reports the next free section char" in output


@pytest.mark.unit
def test_suppressed_warning_does_not_leak_its_shared_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _output._hints_shown.clear()
    finding = _types.Finding(
        1,
        _types.Severity.WARNING,
        "nested inline markup in strong span",
    )

    assert _output._print_findings([finding], "doc.rst", no_warnings=True) == (0, 0)
    assert capsys.readouterr().out == ""


@pytest.mark.unit
@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--max-output-lines", "10"], 10),
        (["--max-output-lines=7"], 7),
        (["--max-output-lines", "10", "--max-output-lines=2"], 2),
        (["--", "--max-output-lines", "10"], None),
        (["--max-output-lines", "1"], None),
        (["--help", "--max-output-lines", "10"], None),
    ],
)
def test_requested_output_limit_matches_cli_bootstrap_rules(argv: list[str], expected: int | None) -> None:
    assert cli._requested_output_limit(argv) == expected


@pytest.mark.integration
def test_cli_max_output_lines_rejects_values_below_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "test.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "check", "--max-output-lines", "1", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert "--max-output-lines must be >= 2" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_max_output_lines_two_reserves_statistics_and_failed_footer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "test.rst"
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "check", "--quiet", "--max-output-lines", "2", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert lines[0] == (
        "check_rst: output limited — 0 of 1 detail line(s) shown, 1 skipped (1 ERROR); full output requires 3 lines"
    )
    assert lines[1].startswith("check_rst: 1 file(s) checked, 1 error(s)")


@pytest.mark.integration
def test_cli_max_output_lines_reports_zero_suppression_without_padding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "test.rst"
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "check", "--quiet", "--max-output-lines", "10", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    assert lines[0].startswith(f"{document}:")
    assert lines[1] == (
        "check_rst: output limited — 1 of 1 detail line(s) shown, 0 skipped; full output requires 3 lines"
    )
    assert lines[2].startswith("check_rst: 1 file(s) checked, 1 error(s)")


@pytest.mark.integration
def test_cli_max_output_lines_classifies_suppressed_warnings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "test.rst"
    document.write_text(
        _GOOD_BLOCK + "\n**Bold opener** starts a paragraph.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "check", "--quiet", "--max-output-lines", "2", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert "1 WARNING" in lines[0]
    assert lines[1].startswith("check_rst: 1 file(s) checked, 0 error(s), 1 warning(s)")


@pytest.mark.integration
def test_cli_max_output_lines_applies_after_outline_filters_and_classifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "test.rst"
    document.write_text(
        "#######\nTitle\n#######\n\n*******\nChild\n*******\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "outline",
            "--sections-only",
            "--max-output-lines",
            "3",
            str(document),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    assert lines[0] == f"Outline: {document}"
    assert "skipped" in lines[1]
    assert "outline" in lines[1]
    assert lines[2].startswith("check_rst: 1 file(s) checked, 0 error(s)")


@pytest.mark.integration
def test_cli_max_output_lines_early_failure_has_hint_and_status_footer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing.rst"
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "check", "--max-output-lines", "2", str(missing)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert "rerun without --max-output-lines for complete diagnostics" in lines[0]
    assert lines[1] == ("check_rst: command failed before producing a run summary, exit status 1")


@pytest.mark.integration
def test_cli_max_output_lines_keeps_footer_last_after_verbose_statistics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "test.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "check",
            "--verbose",
            "--max-output-lines",
            "5",
            str(document),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 5
    assert lines[-2].startswith("check_rst: output limited")
    assert lines[-1].startswith("check_rst: 1 file(s) checked, 0 error(s)")


@pytest.mark.integration
def test_cli_max_output_lines_supports_fix_only_without_masking_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "test.rst"
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "fix", "--fast", "--max-output-lines", "2", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert document.read_text(encoding="utf-8") == _GOOD_BLOCK
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert "0 of 2 detail line(s) shown, 2 skipped" in lines[0]
    assert lines[1] == ("check_rst: 1 file(s) processed, 0 error(s), 1 file(s) fixed [fast]")


@pytest.mark.integration
def test_cli_max_output_lines_rejects_format_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Of the old incompatible_budget_mode rule's six modes, --format=json
    is the only one that survives as a value-level check under the
    subcommand redesign — see _validate_check_args. The other five
    (diff/diff --fast/refs/context/diff-json, tested below) never define
    --max-output-lines on their own parser at all now."""
    document = tmp_path / "test.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "check",
            "--format=json",
            "--max-output-lines",
            "10",
            str(document),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    lines = capsys.readouterr().out.splitlines()
    assert any("--max-output-lines" in line and "incompatible" in line for line in lines)
    assert lines[-1] == ("check_rst: command failed before producing a run summary, exit status 1")


@pytest.mark.integration
@pytest.mark.parametrize(
    "argv_tail",
    [
        ["diff", "--max-output-lines", "10", "FILE"],
        ["diff", "--fast", "--max-output-lines", "10", "FILE"],
        ["refs", "--max-output-lines", "10", "FILE"],
        ["context", "Title", "--max-output-lines", "10", "FILE"],
        ["diff-json", "--max-output-lines", "10", "old.json", "new.json"],
    ],
)
def test_cli_max_output_lines_absent_from_structured_or_copyable_verbs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv_tail: list[str],
) -> None:
    """--max-output-lines is now an ordinary argparse "unrecognized
    arguments" error on every verb that used to need a custom
    incompatible_budget_mode rejection for it — none of diff/refs/context/
    diff-json define the flag on their own parser. Still exit 2, but on
    stdout, not stderr: --max-output-lines being present anywhere in raw
    argv activates main()'s OutputBudgetSink (_requested_output_limit's own
    pre-argparse raw scan) before argparse ever runs, which merges
    stdout/stderr into one captured stream — same architecture the passing
    test_cli_max_output_lines_rejects_format_json above already relies on."""
    document = tmp_path / "test.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    argv = ["check_rst.py", *[str(document) if a == "FILE" else a for a in argv_tail]]
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_quiet_suppresses_progress_keeps_summary(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--quiet drops phase banners and per-file OK lines; the summary line
    stays — a clean run prints essentially one line."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Phase 1" not in out
    assert "✓" not in out
    assert "check_rst: 1 file(s) checked" in out


@pytest.mark.integration
def test_cli_findings_match_de_facto_compiler_output_shape(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every finding line is bare 'path:line: LEVEL: message' — no leading
    glyph, nothing before the path (Max, 2026-07-20: "we break de-facto
    compiler alike output... will it be better to delete them?" — added
    to the contract, see projects/journal/check_rst.rst, "De-facto
    compiler output").  This is the shape generic tooling (IDE problem
    matchers, editor jump-to-error) already knows how to parse."""
    p = rst_repo / "test.rst"
    p.write_text(_BAD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    finding_lines = [ln for ln in out.splitlines() if ": ERROR: " in ln or ": WARNING: " in ln]
    assert finding_lines
    for ln in finding_lines:
        assert re.match(r"^\S.*:\d+: (ERROR|WARNING): .+$", ln), ln
        assert not ln.startswith(("✗", "⚠", " "))


@pytest.mark.integration
def test_cli_quiet_keeps_findings(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--quiet never hides findings — exactly the WARNING:/ERROR: lines the
    old grep '^⚠' workaround was extracting (glyph-less since 2026-07-20,
    same findings-survive-quiet contract)."""
    p = rst_repo / "test.rst"
    p.write_text(_BAD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "must be 7 chars" in out
    assert "ERROR:" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_cli_quiet_keeps_requested_outline(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--quiet suppresses noise, not requested reports: --outline output
    still prints."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", "--quiet", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "Outline:" in out
    assert "Title" in out
    assert "Phase 2" not in out
