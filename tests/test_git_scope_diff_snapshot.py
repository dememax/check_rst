# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Regression tests for invocation-scoped Git line-range snapshots — check_rst project
"""Pin one changed-line repository diff per invocation, without stale ranges."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygit2
import pytest
from _support import _git

from check_rst import cli

if TYPE_CHECKING:
    from pathlib import Path


type DiffCall = tuple[tuple[object, ...], dict[str, object]]
type CliOutcome = tuple[int | None, str, str | None]


def _title(text: str, char: str = "#") -> str:
    return _heading(text, char) + "Body.\n"


def _heading(text: str, char: str = "#") -> str:
    bar = char * (len(text) + 2)
    return f"{bar}\n{text}\n{bar}\n\n"


def _malformed_title(text: str) -> str:
    return f"########\n{text}\n########\n\nBody.\n"


def _prepare_changed_files(repo: Path, count: int) -> list[Path]:
    selected = [repo / f"selected-{index}.rst" for index in range(count)]
    for index, path in enumerate(selected):
        path.write_text(_title(f"Page {index}"), encoding="utf-8")
    (repo / "unchanged.rst").write_text(_title("Unchanged"), encoding="utf-8")
    (repo / "unselected.txt").write_text("Original.\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")

    for index, path in enumerate(selected):
        path.write_text(_malformed_title(f"Expanded page {index}"), encoding="utf-8")
    (repo / "unselected.txt").write_text("Changed but not selected.\n", encoding="utf-8")
    (repo / "untracked.rst").write_text(_title("Untracked"), encoding="utf-8")
    return selected


def _spy_repository_diffs(monkeypatch: pytest.MonkeyPatch) -> list[DiffCall]:
    calls: list[DiffCall] = []
    original = pygit2.repository.BaseRepository.diff

    def diff(
        self: pygit2.repository.BaseRepository,
        a: str | bytes | pygit2.Commit | pygit2.Oid | pygit2.Reference | None = None,
        b: str | bytes | pygit2.Commit | pygit2.Oid | pygit2.Reference | None = None,
        cached: bool = False,
        flags: pygit2.enums.DiffOption = pygit2.enums.DiffOption.NORMAL,
        context_lines: int = 3,
        interhunk_lines: int = 0,
    ) -> pygit2.Diff | pygit2.Patch:
        args: tuple[object, ...] = (a, b)
        kwargs: dict[str, object] = {
            "cached": cached,
            "flags": flags,
            "context_lines": context_lines,
            "interhunk_lines": interhunk_lines,
        }
        calls.append((args, kwargs))
        return original(
            self,
            a,
            b,
            cached=cached,
            flags=flags,
            context_lines=context_lines,
            interhunk_lines=interhunk_lines,
        )

    monkeypatch.setattr(pygit2.repository.BaseRepository, "diff", diff)
    return calls


def _run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> tuple[int, str]:
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--no-config", *args])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert isinstance(exc.value.code, int)
    return exc.value.code, capsys.readouterr().out


def _run_capturing_oserror(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> CliOutcome:
    """Represent the unrelated-file regression as an assertion failure."""
    try:
        exit_code, output = _run(monkeypatch, capsys, *args)
    except OSError as exc:
        return None, capsys.readouterr().out, f"{type(exc).__name__}: {exc}"
    return exit_code, output, None


def _range_diff_calls(calls: list[DiffCall]) -> list[DiffCall]:
    return [
        call
        for call in calls
        if call[0][:2] == ("HEAD", None) and call[1].get("context_lines") == 0 and call[1].get("flags") is not None
    ]


@pytest.mark.integration
@pytest.mark.parametrize("count", [3, 6], ids=["n3", "n6"])
@pytest.mark.parametrize(
    ("row", "argv", "expected_diffs"),
    [
        ("bare-check", ("check",), 1),
        ("git-scope-check", ("check", "--git-scope", "{files}"), 1),
        ("git-scope-diff", ("diff", "--git-scope", "{files}"), 1),
        ("git-scope-fix", ("fix", "--git-scope", "{files}"), 2),
        ("bare-fix-fast", ("fix", "--fast"), 1),
    ],
    ids=["bare-check", "git-scope-check", "git-scope-diff", "git-scope-fix", "bare-fix-fast"],
)
def test_git_scoped_ranges_construct_fixed_diffs_per_invocation(
    tmp_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    count: int,
    row: str,
    argv: tuple[str, ...],
    expected_diffs: int,
) -> None:
    monkeypatch.chdir(tmp_git_repo)
    selected = _prepare_changed_files(tmp_git_repo, count)
    calls = _spy_repository_diffs(monkeypatch)
    selected_names = [path.name for path in selected]
    expanded_argv = tuple(selected_names if item == "{files}" else [item] for item in argv)
    flat_argv = tuple(item for group in expanded_argv for item in group)

    exit_code, output = _run(monkeypatch, capsys, *flat_argv)

    if "fix" in row:
        assert exit_code == 0
        for index, path in enumerate(selected):
            assert path.read_text(encoding="utf-8") == _title(f"Expanded page {index}")
    else:
        assert exit_code == 1
        for index, path in enumerate(selected):
            if row.endswith("check"):
                assert f"{path.name}:2: ERROR: adornment must be {len(f'Expanded page {index}') + 2} chars" in output
            else:
                assert f"--- {path.name}\n+++ {path.name}\n" in output
    assert (tmp_git_repo / "unchanged.rst").read_text(encoding="utf-8") == _title("Unchanged")
    assert (tmp_git_repo / "unselected.txt").read_text(encoding="utf-8") == "Changed but not selected.\n"

    range_calls = _range_diff_calls(calls)
    assert len(range_calls) == expected_diffs
    assert all(call[0][:2] == ("HEAD", None) for call in range_calls)


@pytest.mark.integration
def test_full_fix_refreshes_ranges_after_all_writes(
    tmp_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_git_repo)
    document = tmp_git_repo / "stale-guard.rst"
    original = _heading("Primary") + "Section\n=======\n\nPlain paragraph.\n"
    document.write_text(original, encoding="utf-8")
    _git(tmp_git_repo, "add", document.name)
    _git(tmp_git_repo, "commit", "-m", "stale guard baseline")
    document.write_text(
        _heading("Primary") + "Changed section\n=======\n\nSome **bold *inner* text** inside.\n",
        encoding="utf-8",
    )

    exit_code, output = _run(monkeypatch, capsys, "fix", "--git-scope", document.name)

    assert exit_code == 0
    assert "WARNING: nested inline markup in bold span" in output
    expected = _heading("Primary") + _heading("Changed section", "*") + "Some **bold *inner* text** inside.\n"
    assert document.read_text(encoding="utf-8") == expected


@pytest.mark.integration
@pytest.mark.parametrize(
    ("row", "argv", "unreadable_name"),
    [
        ("after-bare-check", ("check",), "zz-unreadable.txt"),
        ("after-git-scope-check", ("check", "--git-scope", "{file}"), "zz-unreadable.txt"),
        ("after-bare-fix-fast", ("fix", "--fast"), "zz-unreadable.txt"),
        ("before-bare-check", ("check",), "aa-unreadable.txt"),
    ],
    ids=["after-bare-check", "after-git-scope-check", "after-bare-fix-fast", "before-bare-check"],
)
def test_unrelated_unreadable_file_does_not_affect_git_scoped_run(
    tmp_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    row: str,
    argv: tuple[str, ...],
    unreadable_name: str,
) -> None:
    monkeypatch.chdir(tmp_git_repo)
    selected = tmp_git_repo / "m.rst"
    selected.write_text(_title("Page"), encoding="utf-8")
    _git(tmp_git_repo, "add", selected.name)
    _git(tmp_git_repo, "commit", "-m", "selected baseline")
    malformed = _malformed_title("Expanded page")
    selected.write_text(malformed, encoding="utf-8")
    expanded_argv = tuple(selected.name if item == "{file}" else item for item in argv)

    expected = _run_capturing_oserror(monkeypatch, capsys, *expanded_argv)
    expected_bytes = selected.read_bytes()
    selected.write_text(malformed, encoding="utf-8")
    unreadable = tmp_git_repo / unreadable_name
    unreadable.write_text("Invented unrelated input.\n", encoding="utf-8")
    unreadable.chmod(0)
    try:
        try:
            unreadable.read_bytes()
        except PermissionError:
            pass
        else:
            pytest.skip("chmod 000 files remain readable by this process")

        actual = _run_capturing_oserror(monkeypatch, capsys, *expanded_argv)
    finally:
        unreadable.chmod(0o600)

    assert actual == expected, row
    assert selected.read_bytes() == expected_bytes
