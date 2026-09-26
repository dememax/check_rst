# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Source-ordered findings within each phase — check_rst project
"""Findings follow source order within each phase (decided 2026-09-26).

The Phase 1/2/3 sections stay.  Within a phase, findings follow effective
composition order — an included finding sits at its include directive —
then physical line, then a deterministic rule order, whichever checker
produced them.  A shared explanation prints after the first finding it
explains, so it can never look attached to an unrelated earlier finding.
JSON follows the same order.
"""

from __future__ import annotations

import json
import textwrap
from typing import TYPE_CHECKING

import pytest

from check_rst import cli

if TYPE_CHECKING:
    from pathlib import Path

# One finding per line from every Phase 1 family, deliberately out of
# checker order: adornment ERROR 2, homoglyph 7, bold opener 9, nested
# inline 11, rubric 13, homoglyph 15, mistyped directive 17, nested bold 21.
_MIXED = textwrap.dedent("""\
    ####
    Title
    ####

    Plain paragraph.

    See \u0410uthor here.

    **Opener.** text follows.

    Some **bold *em* text** inside.

    .. rubric:: Rubric

    Again \u0410gain here.

    .. code: bash

       echo hidden

    Tail with **nested *inner* bold** words.
    """)


def _run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--no-config", *argv])
    with pytest.raises(SystemExit):
        cli.main()
    return capsys.readouterr().out


def _finding_lines(out: str, path: Path) -> list[str]:
    return [line for line in out.splitlines() if line.startswith(f"{path}:")]


@pytest.mark.integration
def test_phase1_findings_follow_source_order_across_checkers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "doc.rst"
    path.write_text(_MIXED, encoding="utf-8")

    out = _run(monkeypatch, capsys, "check", str(path))

    lines = [int(line.split(":")[1]) for line in _finding_lines(out, path)]
    assert lines == [2, 7, 9, 11, 13, 15, 17, 21]


@pytest.mark.integration
def test_shared_explanation_follows_the_first_finding_it_explains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "doc.rst"
    path.write_text(_MIXED, encoding="utf-8")

    out = _run(monkeypatch, capsys, "check", str(path)).splitlines()

    opener = next(i for i, line in enumerate(out) if line.startswith(f"{path}:9: WARNING: bold paragraph opener"))
    nested = next(i for i, line in enumerate(out) if line.startswith(f"{path}:11: WARNING: nested inline markup"))
    assert out[opener + 1].startswith("  (bold paragraph opener:")
    assert out[nested + 1].startswith("  (nested inline markup:")
    assert sum(line.startswith("  (nested inline markup:") for line in out) == 1


@pytest.mark.integration
def test_json_findings_follow_the_same_source_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "doc.rst"
    path.write_text(_MIXED, encoding="utf-8")

    data = json.loads(_run(monkeypatch, capsys, "check", "--format=json", str(path)))

    assert [finding["lineno"] for finding in data["files"][0]["findings"]] == [2, 7, 9, 11, 13, 15, 17, 21]


@pytest.mark.integration
def test_grid_cell_traversal_does_not_disturb_source_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Docutils visits grid cells column by column; output must not."""
    path = tmp_path / "doc.rst"
    path.write_text(
        textwrap.dedent("""\
            #######
            Title
            #######

            +-----------------+-----------------+
            | first           | **b *nested***  |
            |                 |                 |
            | **c *nested***  | plain           |
            +-----------------+-----------------+
            """),
        encoding="utf-8",
    )

    out = _run(monkeypatch, capsys, "check", str(path))

    assert [int(line.split(":")[1]) for line in _finding_lines(out, path)] == [6, 8]  # b before c


@pytest.mark.integration
def test_included_findings_sit_at_their_include_directive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Composition order, not filename order: the fragment's findings come
    between the root findings before and after its include directive."""
    (tmp_path / "frag.rst").write_text("**Frag first.** text\n\nMore.\n\n**Frag last.** text\n", encoding="utf-8")
    root = tmp_path / "main.rst"
    root.write_text(
        "#######\nMain\n#######\n\n**Root before.** text\n\n.. include:: frag.rst\n\n**Root after.** text\n",
        encoding="utf-8",
    )

    out = _run(monkeypatch, capsys, "check", str(root))

    openers = [line.split("'")[1] for line in out.splitlines() if "bold paragraph opener" in line and "'" in line]
    assert openers == ["Root before.", "Frag first.", "Frag last.", "Root after."]
