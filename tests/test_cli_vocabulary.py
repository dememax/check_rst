# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Current command vocabulary and exact help contract tests — check_rst project
"""Runtime output and help name today's commands and describe real behavior.

The subcommand redesign turned --fix, --outline, --context, --refs, and
their siblings into commands.  A message still recommending a retired flag
sends the reader to a spelling argparse rejects.  Help must also describe
what an option actually filters and how each reader command sets its exit
status.
"""

from __future__ import annotations

import io
import pathlib
import re
import tokenize
from typing import TYPE_CHECKING

import pytest
from _support import _rst

from check_rst import cli
from check_rst.cli import _formatting, _helpers

if TYPE_CHECKING:
    from pathlib import Path

_SRC = pathlib.Path(cli.__file__).parent
# Retired command-as-flag spellings.  Current options that merely share a
# prefix (--outline-depth) or a word (a command's own --verbose) are allowed.
_RETIRED = re.compile(r"--(?:outline-only|outline(?!-depth)|fix-only|fix(?![-\w])|diff-only|json|refs|context)\b")


def _runtime_strings(path: pathlib.Path) -> list[tuple[int, str]]:
    """Every string literal except docstrings, with its line."""
    tokens = [
        token
        for token in tokenize.generate_tokens(io.StringIO(path.read_text(encoding="utf-8")).readline)
        if token.type not in (tokenize.NL, tokenize.COMMENT)
    ]
    found: list[tuple[int, str]] = []
    for index, token in enumerate(tokens):
        if token.type not in (tokenize.STRING, tokenize.FSTRING_MIDDLE):
            continue
        before = tokens[index - 1].type if index else tokenize.NEWLINE
        after = tokens[index + 1].type if index + 1 < len(tokens) else tokenize.NEWLINE
        is_docstring = (
            token.type == tokenize.STRING
            and before in (tokenize.INDENT, tokenize.NEWLINE, tokenize.DEDENT)
            and after == tokenize.NEWLINE
        )
        if not is_docstring:
            found.append((token.start[0], token.string))
    return found


def _run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    monkeypatch.setattr("sys.argv", ["check_rst.py", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return int(exc.value.code or 0), capsys.readouterr().out


@pytest.mark.unit
def test_runtime_strings_use_current_command_vocabulary() -> None:
    stale = [
        f"{path.name}:{line}: {text}"
        for path in sorted(_SRC.glob("*.py"))
        for line, text in _runtime_strings(path)
        if _RETIRED.search(text)
    ]
    assert stale == []


@pytest.mark.unit
def test_hygiene_findings_name_the_fix_command() -> None:
    _normalized, findings, _counts = _helpers._normalize_source_detailed("﻿Title\r\nline\rnext\vtext  \n")
    messages = [finding.text for finding in findings]
    assert any(message.endswith("(fix removes it)") for message in messages)
    assert any(message.endswith("(fix converts to LF)") for message in messages)
    assert any(message.endswith("(fix converts to space)") for message in messages)
    assert any(message.endswith("(fix strips it from the source)") for message in messages)


@pytest.mark.integration
def test_hierarchy_remap_finding_names_the_fix_command(tmp_path: Path) -> None:
    findings = _formatting.check_hierarchy(_rst(tmp_path, "*****\nA\n*****\n\nText.\n"))
    assert any("(fix remaps '*' to '#')" in finding.text for finding in findings)


@pytest.mark.integration
def test_heuristic_phase2_names_the_outline_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _code, out = _run(monkeypatch, capsys, "check", str(_rst(tmp_path, "#####\nTitle\n#####\n")))
    assert "(nothing to check — run outline to see the resolved structure)" in out


@pytest.mark.integration
def test_context_errors_name_the_context_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = _rst(tmp_path, "#####\nTitle\n#####\n\n*\nA\n*\n\n*\nA\n*\n")
    other = tmp_path / "notes.txt"
    other.write_text("x\n", encoding="utf-8")

    _code, empty = _run(monkeypatch, capsys, "context", "  ", str(doc))
    _code, wrong_suffix = _run(monkeypatch, capsys, "context", "Title", str(other))
    _code, ambiguous = _run(monkeypatch, capsys, "context", "A", str(doc))

    assert "context ENTRY must not be empty" in empty
    assert "context requires exactly one positional .rst file" in wrong_suffix
    assert "context 'A' is ambiguous" in ambiguous
    assert "--context" not in empty + wrong_suffix + ambiguous


@pytest.mark.integration
def test_refs_without_sphinx_names_the_refs_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run(monkeypatch, capsys, "--no-config", "refs", str(_rst(tmp_path, "#####\nTitle\n#####\n")))
    assert code == 1
    assert "check_rst: refs requires verified Sphinx mode" in out


@pytest.mark.integration
def test_entitle_help_names_the_fix_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _code, out = _run(monkeypatch, capsys, "entitle", "--help")
    assert "the same hierarchy/adornment fixer that fix already uses" in " ".join(out.split())


@pytest.mark.integration
def test_top_level_help_gives_every_command_a_role_within_79_columns(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _code, out = _run(monkeypatch, capsys, "--help")
    compact = " ".join(out.split())
    assert "outline, context, refs, targets, and hierarchy serve the reader role" in compact
    assert "compare serves the reader/reviewer role" in compact
    assert [line for line in cli._TOP_LEVEL_HELP.splitlines() if len(line) > 79] == []


@pytest.mark.integration
def test_outline_help_states_findings_and_exit_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _code, out = _run(monkeypatch, capsys, "outline", "--help")
    compact = " ".join(out.split())
    assert "--with-findings restores the complete validation report" in compact
    assert "validation ERRORs still make outline exit 1" in compact
    assert "every finding, the phase banners, and runtime provenance" in compact
    assert "layers bold/rubric WARNINGs" not in compact
    assert "layer bold/rubric WARNING findings" not in compact


@pytest.mark.integration
def test_no_directives_help_names_exactly_what_it_suppresses(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _code, out = _run(monkeypatch, capsys, "check", "--help")
    compact = " ".join(out.split())
    assert (
        "skip pseudo-heading warnings (standalone bold, bold paragraph openers, rubric) "
        "and the mistyped-directive warning" in compact
    )
    assert "nested-markup and homoglyph warnings stay" in compact


@pytest.mark.integration
def test_outline_tells_how_to_show_hidden_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = _rst(tmp_path, "####\nTitle\n####\n\nText.\n")
    code, out = _run(monkeypatch, capsys, "--no-config", "outline", str(doc))
    lines = out.splitlines()
    assert code == 1
    assert "  (1 error(s) not shown — rerun with --with-findings to see them)" in lines
    assert lines[-1].startswith("check_rst: 1 file(s) checked, 1 error(s)")
