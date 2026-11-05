# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Contextual lexical findings quote physical title text — check_rst project
"""A composed include context may expand a source title's tab for parsing and
geometry, but findings identify that title with its physical source spelling.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from check_rst import cli

if TYPE_CHECKING:
    from pathlib import Path


_HOST = "######\nHost\n######\n\n.. include:: frag.rst\n"
_TABBED_GEOMETRY = "*****\nA\tB\n*****\n\nText.\n"
_TABBED_UNSEPARATED = "Para.\nA\tB\n=========\n\nText.\n"
_REMEDY = (
    "if it is a title, add a blank line before it (before its overline, if it has one); if it is text, "
    "mark the block as literal or break the title-like punctuation"
)


def _write_pair(repo: Path, fragment: str, *, tab_width: int | None = None) -> None:
    option = "" if tab_width is None else f"   :tab-width: {tab_width}\n"
    (repo / "host.rst").write_text(_HOST + option, encoding="utf-8")
    (repo / "frag.rst").write_text(fragment, encoding="utf-8")
    (repo / "alone.rst").write_text(fragment, encoding="utf-8")


def _run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
) -> tuple[int, str]:
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--no-config", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    code = exc.value.code
    return (code if isinstance(code, int) else 1), capsys.readouterr().out


@pytest.mark.integration
@pytest.mark.parametrize(
    ("tab_width", "expected_width"),
    [(None, 11), (4, 7)],
    ids=["default-tab-width", "include-tab-width-four"],
)
def test_contextual_geometry_quotes_the_physical_title(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tab_width: int | None,
    expected_width: int,
) -> None:
    _write_pair(rst_repo, _TABBED_GEOMETRY, tab_width=tab_width)
    monkeypatch.chdir(rst_repo)

    alone_code, alone = _run(monkeypatch, capsys, "check", "alone.rst")
    contextual_code, contextual = _run(monkeypatch, capsys, "check", "frag.rst")

    assert alone_code == contextual_code == 1
    assert "alone.rst:2: ERROR: adornment must be 11 chars for title 'A\\tB' (over=5, under=5)" in alone
    assert (
        f"frag.rst:2: ERROR: in the document host.rst composes, adornment must be {expected_width} chars "
        "for title 'A\\tB' (over=5, under=5)"
    ) in contextual


@pytest.mark.integration
def test_contextual_unseparated_finding_quotes_the_physical_title(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pair(rst_repo, _TABBED_UNSEPARATED)
    monkeypatch.chdir(rst_repo)

    alone_code, alone = _run(monkeypatch, capsys, "check", "alone.rst")
    contextual_code, contextual = _run(monkeypatch, capsys, "check", "frag.rst")

    assert alone_code == 0
    assert contextual_code == 1
    assert (
        "alone.rst:2: WARNING: 'A\\tB' and the line under it directly follow a non-blank line, so Docutils "
        f"reads them as paragraph text — {_REMEDY}"
    ) in alone
    assert (
        "frag.rst:2: ERROR: in the document host.rst composes, 'A\\tB' directly follows a non-blank line, "
        f"so fix cannot tell whether it is a section title — {_REMEDY}"
    ) in contextual


@pytest.mark.integration
def test_contextual_json_finding_quotes_the_physical_title(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pair(rst_repo, _TABBED_GEOMETRY, tab_width=4)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "check", "--format=json", "frag.rst")

    assert code == 1
    findings = json.loads(out)["files"][0]["findings"]
    finding = next(item for item in findings if item["code"] == "adornment.length")
    assert finding["text"] == (
        "in the document host.rst composes, adornment must be 7 chars for title 'A\\tB' (over=5, under=5)"
    )


@pytest.mark.integration
@pytest.mark.parametrize("command", ["fix", "diff"])
def test_contextual_modifier_finding_quotes_the_physical_title(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    _write_pair(rst_repo, _TABBED_UNSEPARATED)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, command, "frag.rst")

    assert code == 1
    assert (
        "frag.rst:2: ERROR: in the document host.rst composes, 'A\\tB' directly follows a non-blank line, "
        f"so fix cannot tell whether it is a section title — {_REMEDY}"
    ) in out


@pytest.mark.integration
@pytest.mark.parametrize(
    ("fragment", "quoted"),
    [
        ("*******\n A B\n*******\n\nText.\n", "A B"),
        ("****\nA B   \n****\n\nText.\n", "A B"),
    ],
    ids=["ordinary-space", "trailing-spaces"],
)
def test_contextual_and_standalone_quotes_already_agree_without_tabs(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fragment: str,
    quoted: str,
) -> None:
    _write_pair(rst_repo, fragment)
    monkeypatch.chdir(rst_repo)

    _alone_code, alone = _run(monkeypatch, capsys, "check", "alone.rst")
    _contextual_code, contextual = _run(monkeypatch, capsys, "check", "frag.rst")

    assert f"title {quoted!r}" in alone
    assert f"title {quoted!r}" in contextual


@pytest.mark.integration
def test_contextual_ambiguous_style_refusal_still_quotes_no_title(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fragment = "===========\nA\tB\n===========\n\nC\tD\n===========\n"
    _write_pair(rst_repo, fragment)
    monkeypatch.chdir(rst_repo)

    _alone_code, alone = _run(monkeypatch, capsys, "check", "alone.rst")
    _contextual_code, contextual = _run(monkeypatch, capsys, "check", "frag.rst")

    assert "underline-only title 'C\\tD'" in alone
    assert "line 2: 'A\\tB'" in alone
    assert "the titles are ambiguous" in contextual
    assert "A       B" not in contextual
    assert "C       D" not in contextual


@pytest.mark.integration
def test_partial_title_origin_keeps_the_composed_refusal_without_a_title_quote(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fragment = "prefixA\tB\n*****\n\nText.\n"
    (rst_repo / "host.rst").write_text(
        _HOST + "   :start-after: prefix\n",
        encoding="utf-8",
    )
    (rst_repo / "frag.rst").write_text(fragment, encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "check", "frag.rst")

    assert code == 1
    assert "its title change also needs frag.rst:1 to change" in out
    assert "A\\tB" not in out
    assert "A       B" not in out
