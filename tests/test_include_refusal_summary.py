# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Fix-summary include qualifications and structural-refusal ordering — check_rst project

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
_POSSIBLE_INCLUDER_REFUSAL = (
    "check_rst: structural changes refused in 1 file(s): possible includer (see the ERROR above)"
)


def _includer_hint(count: int, *, fast: bool) -> str:
    possible = "possible " if fast else ""
    return (
        f"check_rst: {count} {possible}includer(s) of the selected file(s) not judged by fix; "
        "run check on the same files to judge them"
    )


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


def _run_fix(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    path: Path,
    *,
    fast: bool,
    quiet: bool = False,
    extra_paths: tuple[Path, ...] = (),
) -> tuple[int, str]:
    command = ["fix"]
    if fast:
        command.append("--fast")
    if quiet:
        command.append("--quiet")
    command.extend(str(item) for item in (path, *extra_paths))
    return _run(monkeypatch, capsys, *command)


def _write_fragment_graph(repo: Path, *, transitive: bool = False) -> tuple[Path, ...]:
    main = repo / ("top.rst" if transitive else "main.rst")
    middle = repo / "mid.rst"
    fragment = repo / "frag.rst"
    if transitive:
        main.write_text("Top paragraph.\n\n.. include:: mid.rst\n", encoding="utf-8")
        middle.write_text("Middle paragraph.\n\n.. include:: frag.rst\n", encoding="utf-8")
    else:
        main.write_text("Main\n====\n\n.. include:: frag.rst\n", encoding="utf-8")
    fragment.write_text("Fragment paragraph.\n", encoding="utf-8")
    return (fragment, middle, main) if transitive else (fragment, main)


def _write_fixable_fragment(repo: Path) -> tuple[Path, Path]:
    host = repo / "host.rst"
    fragment = repo / "sfrag.rst"
    host.write_text("#####\nHost\n#####\n\n.. include:: sfrag.rst\n", encoding="utf-8")
    fragment.write_text("Sub\n---\n\nFragment paragraph.\n", encoding="utf-8")
    return fragment, host


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


@pytest.mark.integration
@pytest.mark.parametrize("fast", [False, True], ids=("full", "fast"))
def test_fix_points_to_check_for_an_unselected_includer(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    fast: bool,
) -> None:
    fragment, _main = _write_fragment_graph(rst_repo)
    monkeypatch.chdir(rst_repo)

    code, out = _run_fix(monkeypatch, capsys, fragment, fast=fast)

    assert code == 0, out
    assert out.splitlines()[-2] == _includer_hint(1, fast=fast)
    assert out.splitlines()[-1].startswith("check_rst: 1 file(s)")


@pytest.mark.integration
@pytest.mark.parametrize("fast", [False, True], ids=("full", "fast"))
def test_fix_counts_distinct_transitive_unselected_includers(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    fast: bool,
) -> None:
    fragment, _middle, _top = _write_fragment_graph(rst_repo, transitive=True)
    monkeypatch.chdir(rst_repo)

    code, out = _run_fix(monkeypatch, capsys, fragment, fast=fast)

    assert code == 0, out
    assert out.splitlines()[-2] == _includer_hint(2, fast=fast)


@pytest.mark.integration
def test_full_fix_keeps_the_hint_after_fixing_the_selected_fragment(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fragment, _host = _write_fixable_fragment(rst_repo)
    monkeypatch.chdir(rst_repo)

    first_code, first_out = _run_fix(monkeypatch, capsys, fragment, fast=False)
    check_code, check_out = _run(monkeypatch, capsys, "check", str(fragment))
    second_code, second_out = _run_fix(monkeypatch, capsys, fragment, fast=False)

    assert first_code == 0, first_out
    assert "1 file(s) fixed" in first_out.splitlines()[-1]
    assert check_code == 1, check_out
    assert "host.rst:2: ERROR: adornment must be 6 chars for title 'Host'" in check_out
    assert second_code == 0, second_out
    assert "0 error(s)" in second_out.splitlines()[-1]
    assert first_out.splitlines()[-2] == _includer_hint(1, fast=False)
    assert second_out.splitlines()[-2] == _includer_hint(1, fast=False)


@pytest.mark.integration
def test_fast_hint_precedes_the_structural_refusal_status(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fragment, _host = _write_fixable_fragment(rst_repo)
    monkeypatch.chdir(rst_repo)

    code, out = _run_fix(monkeypatch, capsys, fragment, fast=True)

    assert code == 1, out
    assert out.splitlines()[-3] == _includer_hint(1, fast=True)
    assert out.splitlines()[-2] == _POSSIBLE_INCLUDER_REFUSAL
    assert out.splitlines()[-1].startswith("check_rst: 1 file(s) processed")


@pytest.mark.integration
@pytest.mark.parametrize("fast", [False, True], ids=("full", "fast"))
def test_quiet_fix_keeps_the_unjudged_includer_hint(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    fast: bool,
) -> None:
    fragment, _main = _write_fragment_graph(rst_repo)
    monkeypatch.chdir(rst_repo)

    code, out = _run_fix(monkeypatch, capsys, fragment, fast=fast, quiet=True)

    assert code == 0, out
    assert len(out.splitlines()) == 2
    assert out.splitlines()[-2:] == [_includer_hint(1, fast=fast), out.splitlines()[-1]]


@pytest.mark.integration
@pytest.mark.parametrize("fast", [False, True], ids=("full", "fast"))
def test_fix_omits_the_hint_when_all_includers_are_selected(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    fast: bool,
) -> None:
    fragment, middle, top = _write_fragment_graph(rst_repo, transitive=True)
    monkeypatch.chdir(rst_repo)

    code, out = _run_fix(monkeypatch, capsys, fragment, fast=fast, extra_paths=(middle, top))

    assert code == 0, out
    assert "includer(s) of the selected file(s) not judged by fix" not in out


@pytest.mark.integration
@pytest.mark.parametrize("fast", [False, True], ids=("full", "fast"))
def test_fix_omits_the_hint_for_a_standalone_file(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    fast: bool,
) -> None:
    standalone = rst_repo / "standalone.rst"
    standalone.write_text("Standalone paragraph.\n", encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run_fix(monkeypatch, capsys, standalone, fast=fast)

    assert code == 0, out
    assert "includer(s) of the selected file(s) not judged by fix" not in out


@pytest.mark.integration
def test_check_keeps_its_joined_includer_output_without_the_fix_hint(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fragment, _main = _write_fragment_graph(rst_repo)
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "check", str(fragment))

    assert code == 1, out
    assert "check_rst: also checking main.rst, which includes frag.rst (whole-file, read-only)" in out
    assert "includer(s) of the selected file(s) not judged by fix" not in out
