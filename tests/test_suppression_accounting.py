# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Visible and suppressed finding accounting tests — check_rst project
"""A summary never presents hidden findings as though none existed.

--no-warnings and --skip-fixable are deliberate filters, not verbosity
controls.  The summary and JSON keep visible and suppressed counts distinct
(additive under schema_version 1, decided 2026-09-26), and no success line
is printed for a finding family that a filter merely hid.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from check_rst import cli

if TYPE_CHECKING:
    from pathlib import Path

_ONE_WARNING = "#######\nTitle\n#######\n\n**Opener.** text follows.\n"
_TWO_FIXABLE = "####\nTitle\n####\n\n*******\nSection\n*******\n\nText.\n"


def _run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    monkeypatch.setattr("sys.argv", ["check_rst.py", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return int(exc.value.code or 0), capsys.readouterr().out


def _doc(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "doc.rst"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.integration
def test_no_warnings_summary_reports_the_hidden_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _doc(tmp_path, _ONE_WARNING)

    code, out = _run(monkeypatch, capsys, "--no-config", "check", "--no-warnings", str(path))

    assert code == 0
    assert "0 error(s), 0 warning(s) (1 suppressed by --no-warnings)" in out
    assert "directives OK" not in out


@pytest.mark.integration
def test_no_warnings_json_keeps_visible_and_suppressed_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _doc(tmp_path, _ONE_WARNING)

    _code, out = _run(monkeypatch, capsys, "--no-config", "check", "--no-warnings", "--format=json", str(path))
    data = json.loads(out)

    assert data["schema_version"] == 1
    assert data["files"][0]["findings"] == []
    assert data["summary"]["warnings"] == 0
    assert data["summary"]["suppressed"] == {"warnings": 1, "fixable": 0, "restatements": 0}


@pytest.mark.integration
def test_skip_fixable_summary_and_json_count_suppressed_fixable_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _doc(tmp_path, _TWO_FIXABLE)

    code, out = _run(monkeypatch, capsys, "--no-config", "check", "--skip-fixable", str(path))
    _code, json_out = _run(monkeypatch, capsys, "--no-config", "check", "--skip-fixable", "--format=json", str(path))

    assert code == 0
    assert "0 error(s), 0 warning(s), 2 auto-fixable finding(s) suppressed" in out
    assert json.loads(json_out)["summary"]["suppressed"] == {"warnings": 0, "fixable": 2, "restatements": 0}


@pytest.mark.integration
def test_phase3_never_claims_clean_when_warnings_were_hidden(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\nroot_doc = "doc"\n', encoding="utf-8")
    path = _doc(rst_repo, "#######\nTitle\n#######\n\nSee :doc:`missing`.\n")
    argv = ["--sphinx-src", str(rst_repo), "--build-dir", str(rst_repo / "_build"), "check", "--no-warnings"]

    _code, out = _run(monkeypatch, capsys, *argv, str(path))

    assert "no warnings or errors in the checked files" not in out
    assert "↷ sphinx: 1 warning(s) suppressed by --no-warnings" in out
    assert "(1 suppressed by --no-warnings)" in out


@pytest.mark.integration
def test_phase3_reports_suppressed_proven_restatements(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\nroot_doc = "doc"\n', encoding="utf-8")
    path = _doc(rst_repo, "=======\nTitle\n-------\n\nText.\n")
    argv = ["--sphinx-src", str(rst_repo), "--build-dir", str(rst_repo / "_build"), "check", "--skip-fixable"]

    code, out = _run(monkeypatch, capsys, *argv, str(path))
    _code, json_out = _run(monkeypatch, capsys, *argv, "--format=json", str(path))

    assert code == 0
    assert "no warnings or errors in the checked files" not in out
    assert "↷ sphinx: 1 proven fixable restatement(s) suppressed" in out
    assert json.loads(json_out)["summary"]["suppressed"]["restatements"] == 1
