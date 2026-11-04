# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Structural-refusal status coverage for fix modes — check_rst project

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from check_rst import cli

if TYPE_CHECKING:
    from pathlib import Path


_STRUCTURAL_CHANGE = "========\nShared\n========\n\nBody.   \n"
_HYGIENE_ONLY = "########\nShared\n########\n\nBody.   \n"
_REFUSAL_STATUS = (
    "check_rst: structural changes refused in 1 file(s): outside every discovery root (see the ERROR above)"
)


def _run_fix(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    path: Path,
    *,
    fast: bool,
) -> tuple[int, str]:
    command = ["check_rst.py", "--no-config", "fix"]
    if fast:
        command.append("--fast")
    command.append(str(path))
    monkeypatch.setattr("sys.argv", command)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    code = exc.value.code
    return (code if isinstance(code, int) else 1), capsys.readouterr().out


@pytest.mark.integration
@pytest.mark.parametrize("fast", [False, True], ids=["full", "fast"])
def test_fix_names_an_uncovered_structural_refusal_immediately_before_the_final_status(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    fast: bool,
) -> None:
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    path = elsewhere / "part.rst"
    path.write_text(_STRUCTURAL_CHANGE, encoding="utf-8")
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))

    code, out = _run_fix(monkeypatch, capsys, path, fast=fast)

    expected_status = (
        "check_rst: 1 file(s) processed, 1 error(s), 1 file(s) fixed [fast]"
        if fast
        else (
            "check_rst: 1 file(s) checked, 2 error(s), 0 warning(s), 1 file(s) fixed, "
            "32 char(s) (= bytes, 12 distinct, 9 once), 0 space(s) (0%)"
        )
    )
    lines = out.splitlines()
    assert code == 1, out
    assert lines[-2:] == [_REFUSAL_STATUS, expected_status]
    assert path.read_text(encoding="utf-8") == _STRUCTURAL_CHANGE.replace("Body.   ", "Body.")


@pytest.mark.integration
@pytest.mark.parametrize("fast", [False, True], ids=["full", "fast"])
def test_fix_omits_the_structural_refusal_status_for_a_covered_hygiene_only_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    fast: bool,
) -> None:
    path = tmp_path / "part.rst"
    path.write_text(_HYGIENE_ONLY, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    code, out = _run_fix(monkeypatch, capsys, path, fast=fast)

    assert code == 0, out
    assert "structural changes refused" not in out
    assert path.read_text(encoding="utf-8") == _HYGIENE_ONLY.replace("Body.   ", "Body.")
