# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Tests for check_rst.cli's _document domain (the Document facade) — check_rst project

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from _support import _GOOD_BLOCK, _rst

from check_rst import cli
from check_rst.cli import _document, _helpers

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.integration
def test_document_reads_and_parses_once(tmp_path: Path) -> None:
    """Accessing every facade property costs exactly one read and one
    docutils parse."""
    p = _rst(tmp_path, "Title\n=====\n\nText.\n\n    Quoted.\n")
    _helpers.CALL_COUNTS.clear()
    doc = _document.Document(p)
    _ = doc.text, doc.lines, doc.hygiene, doc.outline, doc.block_quotes
    _ = doc.doctree
    assert _helpers.CALL_COUNTS["_read_source"] == 1
    assert _helpers.CALL_COUNTS["_parse_rst"] == 1


@pytest.mark.integration
def test_cli_check_run_reads_each_file_once(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The whole check pipeline (hygiene + adornments + hierarchy +
    directives + footer stats) shares one Document: one read, one parse
    per file.  Before the facade: five reads per file."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    _helpers.CALL_COUNTS.clear()
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    assert _helpers.CALL_COUNTS["_read_source"] == 1
    assert _helpers.CALL_COUNTS["_parse_rst"] == 1


@pytest.mark.integration
def test_cli_outline_run_still_one_read_one_parse(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--outline reuses the Phase 1 Document across phases — the Phase 2
    outline loop must not re-read or re-parse."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    _helpers.CALL_COUNTS.clear()
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    assert _helpers.CALL_COUNTS["_read_source"] == 1
    assert _helpers.CALL_COUNTS["_parse_rst"] == 1
