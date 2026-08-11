# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Tests for check_rst.cli's top-level pipeline (_main/_run_*, CLI-level behavior) — check_rst project

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import pytest
from _support import _BAD_BLOCK, _GOOD_BLOCK, _git

from check_rst import cli
from check_rst.cli import _formatting, _helpers, _pipeline, _reports, _sphinx

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.integration
def test_recursive_discovers_nested_rst_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--recursive DIR discovers *.rst files at any depth under DIR."""
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b").mkdir()
    top = tmp_path / "top.rst"
    nested = tmp_path / "a" / "mid.rst"
    deep = tmp_path / "a" / "b" / "deep.rst"
    for p in (top, nested, deep):
        p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--recursive", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert str(top) in out
    assert str(nested) in out
    assert str(deep) in out


@pytest.mark.integration
def test_recursive_multiple_directories_merged_no_duplicates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Overlapping --recursive directories don't check the same file twice.

    tmp_path and tmp_path/sub both reach sub/a.rst via rglob, so passing
    both must still process it exactly once — not once per directory that
    happens to reach it.
    """
    (tmp_path / "sub").mkdir()
    f = tmp_path / "sub" / "a.rst"
    f.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "check", "--recursive", str(tmp_path), str(tmp_path / "sub")],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    # Each file gets exactly 2 status lines (adornments+hierarchy, directives)
    # when processed once — 4 would mean it was checked twice.
    assert out.count(str(f)) == 2


@pytest.mark.integration
def test_recursive_exclude_pattern_skips_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--exclude PATTERN skips a matching discovered file entirely — its
    errors never appear, even though it has a real adornment violation."""
    keep = tmp_path / "keep.rst"
    skip = tmp_path / "skip.rst"
    keep.write_text(_GOOD_BLOCK, encoding="utf-8")
    skip.write_text(_BAD_BLOCK, encoding="utf-8")  # would flag "must be 7 chars"

    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "check",
            "--recursive",
            "--exclude",
            "skip.rst",
            str(tmp_path),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert str(keep) in out
    assert str(skip) not in out
    assert "must be 7 chars" not in out


@pytest.mark.integration
def test_recursive_multiple_exclude_patterns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--exclude is repeatable: each pattern excludes its own file."""
    keep = tmp_path / "keep.rst"
    skip1 = tmp_path / "skip1.rst"
    skip2 = tmp_path / "skip2.rst"
    for p in (keep, skip1, skip2):
        p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "check",
            "--recursive",
            "--exclude",
            "skip1.rst",
            "--exclude",
            "skip2.rst",
            str(tmp_path),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert str(keep) in out
    assert str(skip1) not in out
    assert str(skip2) not in out


@pytest.mark.integration
def test_cli_missing_explicit_file_stops_before_all_check_phases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An explicit missing file is invalid input, so no check/build phase runs."""
    (tmp_path / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    missing = tmp_path / "does_not_exist.rst"

    def unexpected_sphinx(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Sphinx must not run when no input files exist")

    monkeypatch.setattr(_sphinx, "_build_sphinx_env", unexpected_sphinx)
    monkeypatch.setattr(_sphinx, "run_sphinx", unexpected_sphinx)
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(tmp_path), "check", str(missing)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert f"{missing}: file not found" in out
    assert "Phase 1" not in out
    assert "Phase 2" not in out
    assert "Phase 3" not in out


@pytest.mark.integration
@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["outline", "--outline-depth", "0"], "--outline-depth must be >= 1"),
        (["outline", "--outline-depth", "-1"], "--outline-depth must be >= 1"),
        (["check", "--exclude", "skip.rst"], "--exclude requires --recursive"),
        (["check", "--git-scope"], "--git-scope requires at least one file"),
        (
            ["check", "--git-scope", "--recursive", "docs"],
            "--git-scope is incompatible with --recursive",
        ),
    ],
)
def test_cli_rejects_semantically_incompatible_arguments_before_actions(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    message: str,
) -> None:
    """The remaining value-level/peer-flag rules that still need a runtime
    check under the subcommand redesign (docs/roadmap.rst, "Subcommands:
    flag-soup incompatibilities become verbs") — every combination this
    parametrize used to cover that the redesign made structurally
    impossible (e.g. --outline-only + --fix, --refs + --json, --diff-json +
    --config) was removed rather than converted: those now fail as an
    ordinary argparse "unrecognized argument" (exit 2, message on stderr),
    which is argparse's own behavior, not this project's logic to pin down
    with a regression test. --outline-depth requiring --outline is likewise
    gone: the flag only exists on outline's own parser now."""
    monkeypatch.setattr("sys.argv", ["check_rst.py", *argv])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert message in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_cli_help_uses_launcher_name(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--help"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    first_line = out.splitlines()[0]
    assert first_line.startswith("usage: check_rst ")
    assert "check_rst.py" not in first_line


@pytest.mark.integration
def test_cli_help_covers_examples_and_self_contained_modes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Top-level help discovers every mode without leaking documentation
    source syntax into a terminal or pretending a required verb is optional."""
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--help"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Examples:" in out
    assert "check_rst refs doc.rst" in out
    assert "check_rst diff-json before.json after.json" in out
    assert "check_rst fix --fast" in out
    assert "check_rst list-table doc.rst" in out
    compact = " ".join(out.split())
    assert "Preview commands diff and list-table also return 1" in compact
    assert "reviewer/auditor" in out
    assert "modifier" in out
    assert "reader role" in out
    assert "check .rst files against project formatting rules (default verb)" not in out
    assert "2 command-line usage error" in out
    assert "https://github.com/dememax/check_rst/blob/main/docs/guide.rst" in out
    assert "Copyright (C) 2026 Maxime P. DEMENTYEV" in out
    assert "License: GPL-3.0-only" in out
    assert len(out.splitlines()) < 80


@pytest.mark.integration
@pytest.mark.parametrize(
    "argv",
    [
        ["--help"],
        ["check", "--help"],
        ["fix", "--help"],
        ["diff", "--help"],
        ["outline", "--help"],
        ["diff-json", "--help"],
        ["refs", "--help"],
        ["context", "--help"],
        ["list-table", "--help"],
        ["hierarchy", "--help"],
    ],
)
def test_cli_help_is_terminal_native_plain_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["check_rst.py", *argv])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert ":doc:`" not in out
    assert "``" not in out
    assert "Common examples::" not in out


@pytest.mark.integration
@pytest.mark.parametrize(
    ("verb", "needle"),
    [
        ("fix", "unresolved Git merge entry"),
        ("check", "Phase 0 byte hygiene remains enabled"),
        ("outline", "never affects the exit code"),
        ("list-table", "gated by whole-file tree equality"),
    ],
)
def test_cli_verb_help_stays_concise_and_points_to_docs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    verb: str,
    needle: str,
) -> None:
    """Reworded (2026-08-08) from a philosophy this project reversed:
    --help used to BE the complete reference, so this test once asserted
    long safety-explanation phrases stayed present verbatim.  Now --help
    is deliberately concise (docs/guide.rst's own note on the change) and
    points back at the guide for the explanation instead
    of restating it — so this pins two different things: the safety-
    relevant FACT is still named, in one short clause, and the page stays
    genuinely concise (a fixed, generous line budget) rather than
    creeping back toward the page this project deliberately moved away
    from."""
    monkeypatch.setattr("sys.argv", ["check_rst.py", verb, "--help"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert needle in " ".join(out.split())
    assert len(out.splitlines()) < 60


@pytest.mark.integration
def test_cli_list_table_help_states_runtime_and_exit_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["check_rst.py", "list-table", "--help"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    compact = " ".join(out.split())
    assert "bare Docutils" in compact
    assert "ancestor-first" in compact
    assert "merged cells remain unchanged" in compact
    assert "parsed grid geometry" not in compact
    assert "Dry-run returns 1 when files would change" in compact
    assert "N counts every table shown by outline" in compact


@pytest.mark.integration
def test_cli_outline_help_distinguishes_git_and_structure_scope(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--help"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    compact = " ".join(capsys.readouterr().out.split())
    assert "select files through Git" in compact
    assert "whole-document structure" in compact
    assert "findings use changed-line scope" in compact


@pytest.mark.integration
def test_cli_hierarchy_prints_the_live_runtime_order(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["check_rst.py", "hierarchy"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("Adornment hierarchy for this Docutils runtime:\n")
    assert " 1. '#' (preferred)" in out
    assert f"{len(_helpers.HIERARCHY):2d}. {_helpers.HIERARCHY[-1]!r}" in out


@pytest.mark.integration
def test_cli_explicit_non_rst_input_is_a_documented_no_op(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    markdown = tmp_path / "README.md"
    markdown.write_text("# Markdown\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--no-config", "check", str(markdown)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "no .rst files in the list — nothing to do" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_cli_file_valued_build_dir_stops_before_fix_or_phases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Invalid output scope is input validation, not a post-Phase-1 traceback."""
    (tmp_path / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    p = tmp_path / "index.rst"
    original = "\ufeffTitle\n=====\n"
    p.write_text(original, encoding="utf-8")
    build_file = tmp_path / "not-a-directory"
    build_file.write_text("occupied", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(tmp_path),
            "--build-dir",
            str(build_file),
            "fix",
            str(p),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert p.read_text(encoding="utf-8") == original
    out = capsys.readouterr().out
    assert "not a directory" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_cli_explicit_build_dir_requires_resolved_sphinx_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "doc.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--build-dir",
            str(tmp_path / "_build"),
            "check",
            str(document),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--build-dir requires verified Sphinx mode" in out
    assert "--sphinx-src DIR" in out
    assert "--config FILE" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_cli_no_toctree_requires_resolved_sphinx_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "doc.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "outline", "--with-findings", "--no-toctree", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--no-toctree requires verified Sphinx mode" in out
    assert "--config FILE" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_cli_no_toctree_requires_format_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Under the subcommand redesign, --no-toctree's "requires one of
    --outline/--outline-only/--json/--context" half narrows to "requires
    --format=json" on check's own parser — outline and context each
    guarantee the condition structurally now (see _validate_check_args)."""
    (tmp_path / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    document = tmp_path / "doc.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(tmp_path),
            "check",
            "--no-toctree",
            str(document),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--no-toctree requires --format=json" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_cli_foreign_sphinx_file_stops_before_fix_or_phases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verified mode must never mutate a file outside its Sphinx source tree."""
    sphinx_src = tmp_path / "docs"
    sphinx_src.mkdir()
    (sphinx_src / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    (sphinx_src / "index.rst").write_text("Index\n=====\n", encoding="utf-8")
    foreign = tmp_path / "foreign.rst"
    original = "\ufeffForeign\n=======\n"
    foreign.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(sphinx_src), "fix", str(foreign)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert foreign.read_text(encoding="utf-8") == original
    out = capsys.readouterr().out
    assert "not part of --sphinx-src" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_cli_unmerged_file_stops_before_fix_and_preserves_markers(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Git's unmerged index is authoritative; --fix must be atomic and inert."""
    p = rst_repo / "conflict.rst"
    p.write_text("Base\n####\n", encoding="utf-8")
    _git(rst_repo, "add", "conflict.rst")
    _git(rst_repo, "commit", "-m", "base")
    _git(rst_repo, "checkout", "-b", "other")
    p.write_text("Theirs\n######\n", encoding="utf-8")
    _git(rst_repo, "add", "conflict.rst")
    _git(rst_repo, "commit", "-m", "theirs")
    _git(rst_repo, "checkout", "master")
    p.write_text("Ours\n####\n", encoding="utf-8")
    _git(rst_repo, "add", "conflict.rst")
    _git(rst_repo, "commit", "-m", "ours")
    merge = subprocess.run(
        ["git", "-C", str(rst_repo), "merge", "other"],
        capture_output=True,
        check=False,
    )
    assert merge.returncode != 0
    original = p.read_bytes()
    assert b"<<<<<<<" in original
    invocation_dir = rst_repo.parent / "outside-invocation"
    invocation_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(_helpers, "PROJECT_ROOT", invocation_dir)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", str(p)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert p.read_bytes() == original
    out = capsys.readouterr().out
    assert "unresolved Git merge conflict" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_cli_unmerged_file_uses_nested_owning_repository(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An outer invocation must not hide an inner repository's conflict."""
    inner = rst_repo / "inner"
    inner.mkdir()
    _git(inner, "init")
    _git(inner, "config", "user.email", "test@example.com")
    _git(inner, "config", "user.name", "Test User")
    document = inner / "conflict.rst"
    document.write_text("Base\n####\n", encoding="utf-8")
    _git(inner, "add", "conflict.rst")
    _git(inner, "commit", "-m", "base")
    _git(inner, "checkout", "-b", "other")
    document.write_text("Theirs\n######\n", encoding="utf-8")
    _git(inner, "commit", "-am", "theirs")
    _git(inner, "checkout", "master")
    document.write_text("Ours\n####\n", encoding="utf-8")
    _git(inner, "commit", "-am", "ours")
    merge = subprocess.run(
        ["git", "-C", str(inner), "merge", "other"],
        capture_output=True,
        check=False,
    )
    assert merge.returncode != 0
    original = document.read_bytes()
    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", str(document)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert document.read_bytes() == original
    output = capsys.readouterr().out
    assert "unresolved Git merge conflict" in output
    assert "Phase 1" not in output


@pytest.mark.integration
def test_unmerged_filter_ignores_conflict_in_unselected_file(rst_repo: Path) -> None:
    conflict = rst_repo / "conflict.rst"
    selected = rst_repo / "selected.rst"
    conflict.write_text("Base\n####\n", encoding="utf-8")
    selected.write_text(_GOOD_BLOCK, encoding="utf-8")
    _git(rst_repo, "add", "conflict.rst", "selected.rst")
    _git(rst_repo, "commit", "-m", "base")
    _git(rst_repo, "checkout", "-b", "other")
    conflict.write_text("Theirs\n######\n", encoding="utf-8")
    _git(rst_repo, "commit", "-am", "theirs")
    _git(rst_repo, "checkout", "master")
    conflict.write_text("Ours\n####\n", encoding="utf-8")
    _git(rst_repo, "commit", "-am", "ours")
    merge = subprocess.run(
        ["git", "-C", str(rst_repo), "merge", "other"],
        capture_output=True,
        check=False,
    )
    assert merge.returncode != 0

    assert _helpers._unmerged_files([selected]) == []
    assert _helpers._unmerged_files([conflict]) == [conflict]


@pytest.mark.integration
def test_recursive_nonexistent_directory_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A --recursive argument that doesn't exist is a hard error, not a
    silent empty result — same fail-loud precedent as --sphinx-src."""
    missing = tmp_path / "does_not_exist"
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--recursive", str(missing)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "not a directory" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_recursive_file_argument_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A --recursive argument that is a file, not a directory, is a hard error."""
    p = tmp_path / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--recursive", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "not a directory" in out


@pytest.mark.integration
def test_recursive_no_directories_given_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--recursive with no positional directories is a clear error, not a
    silent no-op or an implicit fallback to some other scope."""
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--recursive"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--recursive" in out


@pytest.mark.integration
def test_recursive_no_rst_files_found_exits_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A --recursive directory with no *.rst files anywhere under it is not
    an error — same "nothing to do" convention as the no-files-changed case."""
    (tmp_path / "empty").mkdir()
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--recursive", str(tmp_path / "empty")])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0


@pytest.mark.integration
def test_recursive_filename_with_spaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Regression guard for the exact historical bug: a filename containing
    spaces (e.g. a saved AI chat transcript) must be discovered and checked
    correctly, not word-split into bogus fragments. pathlib.rglob has no
    shell involved at all, so this is structural, not a patched special case.
    """
    spaced = tmp_path / "saved chat transcript.rst"
    spaced.write_text(_BAD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--recursive", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert str(spaced) in out
    assert "must be 7 chars" in out
    assert "file not found" not in out


@pytest.mark.integration
def test_recursive_implies_whole_file_scoping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--recursive is a deliberate scope selection, same as naming files
    explicitly: it must check discovered files in full, not diff-scoped —
    there is no git relationship implied by a directory sweep at all."""
    p = tmp_path / "test.rst"
    p.write_text(_BAD_BLOCK, encoding="utf-8")  # pre-existing-style violation, no git involved

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--recursive", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "must be 7 chars" in out
    assert "must be 7 chars" in out


@pytest.mark.integration
def test_cli_summary_line_always_printed(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every run ends with one machine-parseable summary line — no flag
    needed; kills the grep -c / exit-code-probe post-processing class."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "check_rst: 1 file(s) checked, 0 error(s), 0 warning(s)" in out


@pytest.mark.integration
def test_cli_summary_counts_errors_and_warnings(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(_BAD_BLOCK + "\n**Bold Heading**\n\nText after.\n", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "check_rst: 1 file(s) checked, 1 error(s), 1 warning(s)" in out


@pytest.mark.integration
def test_cli_summary_fix_mode_reports_fixed_files(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(_BAD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "1 file(s) fixed" in out


@pytest.mark.integration
def test_cli_summary_diff_mode_reports_would_change(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--diff counts files that would change — the observed workaround was
    counting '^---' diff headers."""
    p = rst_repo / "test.rst"
    p.write_text(_BAD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "diff", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "1 file(s) would change" in out


@pytest.mark.integration
def test_cli_diff_only_prints_preview_without_checks_or_writes(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    original = document.read_bytes()

    def unexpected_check(*_args: object, **_kwargs: object) -> None:
        pytest.fail("--diff-only must not run Sphinx")

    monkeypatch.setattr(_sphinx, "_build_sphinx_env", unexpected_check)
    monkeypatch.setattr(_sphinx, "run_sphinx", unexpected_check)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "diff", "--fast", str(document)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert document.read_bytes() == original
    out = capsys.readouterr().out
    assert f"--- {document}" in out
    assert "1 file(s) would change" in out
    assert "Phase 1" not in out
    assert "Phase 2" not in out
    assert "Phase 3" not in out


@pytest.mark.integration
def test_cli_diff_only_clean_file_exits_zero(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "diff", "--fast", str(document)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert "0 file(s) would change" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_fix_only_composes_hygiene_and_structure_with_structured_output(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The fast mode applies both mutators in their required order and
    reports what changed without continuing into validation phases."""
    document = rst_repo / "test.rst"
    document.write_bytes(b"\xef\xbb\xbf#########\r\n Title A \r\n#####\r\n\r\nText.\r\n")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", "--fast", str(document)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert document.read_bytes() == b"#########\nTitle A\n#########\n\nText.\n"
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == ("check_rst: fast scope — explicit/whole-file; hygiene and hierarchy are whole-file")
    assert lines[1] == (
        f"{document}: fixed — BOM 1, CRLF line endings 5, trailing whitespace lines 1, structural lines 2"
    )
    assert lines[-1] == ("check_rst: 1 file(s) processed, 0 error(s), 1 file(s) fixed [fast]")
    assert "Phase 1" not in "\n".join(lines)
    assert "Phase 2" not in "\n".join(lines)
    assert "Phase 3" not in "\n".join(lines)


@pytest.mark.integration
def test_cli_fix_only_plans_all_inputs_before_writing_invalid_utf8(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One undecodable sibling aborts the operation before a valid plan writes."""
    fixable = rst_repo / "fixable.rst"
    invalid = rst_repo / "invalid.rst"
    original = b"######\nTitle\n######\n"
    fixable.write_bytes(original)
    invalid.write_bytes(b"Title\n\xff\n")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "fix", "--fast", str(fixable), str(invalid)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert fixable.read_bytes() == original
    lines = capsys.readouterr().out.splitlines()
    assert any(f"{invalid}:2: ERROR: not valid UTF-8" in line for line in lines)
    assert not any(": fixed —" in line for line in lines)
    assert lines[-1] == ("check_rst: 2 file(s) processed, 1 error(s), 0 file(s) fixed [fast]")


@pytest.mark.integration
def test_cli_normal_fix_plans_all_inputs_before_writing_invalid_utf8(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The full fix pipeline shares fast fix's complete-selection preflight."""
    fixable = rst_repo / "fixable.rst"
    invalid = rst_repo / "invalid.rst"
    original = b"######\nTitle\n######\n"
    fixable.write_bytes(original)
    invalid.write_bytes(b"Title\n\xff\n")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "fix", str(fixable), str(invalid)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert fixable.read_bytes() == original
    lines = capsys.readouterr().out.splitlines()
    assert any(f"{invalid}:2: ERROR: not valid UTF-8" in line for line in lines)
    assert not any("fix applied" in line for line in lines)
    assert lines[-1] == "check_rst: 2 file(s) selected, 1 input error(s), 0 file(s) fixed"


@pytest.mark.integration
def test_cli_normal_fix_write_failure_is_clean_and_keeps_final_status(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    original = _BAD_BLOCK
    document.write_text(original, encoding="utf-8")

    def fail_write(_plan: object) -> None:
        raise OSError("read-only filesystem")

    monkeypatch.setattr(_pipeline, "_apply_fix_plan", fail_write)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", str(document)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert document.read_text(encoding="utf-8") == original
    lines = capsys.readouterr().out.splitlines()
    assert any("ERROR: cannot write fix: read-only filesystem" in line for line in lines)
    assert lines[-1].startswith("check_rst: 1 file(s) checked, 1 error(s), 0 warning(s), 0 file(s) fixed")


@pytest.mark.integration
def test_cli_fix_only_missing_sibling_aborts_before_writing(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Path preflight has the same whole-operation atomicity as decode planning."""
    fixable = rst_repo / "fixable.rst"
    missing = rst_repo / "missing.rst"
    original = b"######\nTitle\n######\n"
    fixable.write_bytes(original)
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "fix", "--fast", str(fixable), str(missing)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert fixable.read_bytes() == original
    lines = capsys.readouterr().out.splitlines()
    assert f"check_rst: {missing}: file not found" in lines
    assert lines[-1] == ("check_rst: 2 file(s) processed, 1 error(s), 0 file(s) fixed [fast]")


@pytest.mark.integration
def test_cli_fix_only_ignores_configured_sphinx_and_never_parses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Config still roots selection, but its Sphinx settings are inactive."""
    document = tmp_path / "test.rst"
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    config = tmp_path / "check-rst.toml"
    config.write_text(
        'sphinx-src = "missing-docs"\nbuild-dir = "missing-build"\n',
        encoding="utf-8",
    )

    def unexpected_phase(*_args: object, **_kwargs: object) -> None:
        pytest.fail("--fix-only must not parse RST or construct/run Sphinx")

    monkeypatch.setattr(_helpers, "_parse_rst", unexpected_phase)
    monkeypatch.setattr(_sphinx, "_build_sphinx_env", unexpected_phase)
    monkeypatch.setattr(_sphinx, "run_sphinx", unexpected_phase)
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--config", str(config), "fix", "--fast", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "sphinx-src=missing-docs inactive (--fast)" in out
    assert "build-dir=missing-build inactive (--fast)" in out
    assert _helpers.CALL_COUNTS["_parse_rst"] == 0
    assert _helpers.CALL_COUNTS["_build_sphinx_env"] == 0
    assert _helpers.CALL_COUNTS["run_sphinx"] == 0


@pytest.mark.integration
def test_cli_diff_fast_ignores_configured_sphinx_and_never_parses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """diff --fast's sibling of the fix --fast case above — found live: the
    config-inactive branch checked only args.fix_only, so diff --fast
    silently applied a configured sphinx-src/build-dir instead of reporting
    them inactive (confirmed by direct reproduction before the fix: fix
    --fast printed 'inactive (--fast)' on this exact config, diff --fast
    printed the values as if active, with no inactive marker at all)."""
    document = tmp_path / "test.rst"
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    config = tmp_path / "check-rst.toml"
    config.write_text(
        'sphinx-src = "missing-docs"\nbuild-dir = "missing-build"\n',
        encoding="utf-8",
    )

    def unexpected_phase(*_args: object, **_kwargs: object) -> None:
        pytest.fail("diff --fast must not parse RST or construct/run Sphinx")

    monkeypatch.setattr(_helpers, "_parse_rst", unexpected_phase)
    monkeypatch.setattr(_sphinx, "_build_sphinx_env", unexpected_phase)
    monkeypatch.setattr(_sphinx, "run_sphinx", unexpected_phase)
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--config", str(config), "diff", "--fast", str(document)],
    )

    with pytest.raises(SystemExit):
        cli.main()

    out = capsys.readouterr().out
    assert "sphinx-src=missing-docs inactive (--fast)" in out
    assert "build-dir=missing-build inactive (--fast)" in out
    assert _helpers.CALL_COUNTS["_parse_rst"] == 0
    assert _helpers.CALL_COUNTS["_build_sphinx_env"] == 0
    assert _helpers.CALL_COUNTS["run_sphinx"] == 0


@pytest.mark.integration
@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--sphinx-src", "docs"], "fix --fast is self-contained"),
        (["--build-dir", "build"], "fix --fast is self-contained"),
        (["--skip-fixable"], "fix --fast is self-contained"),
    ],
)
def test_cli_fix_only_rejects_meaningless_options_before_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra: list[str],
    message: str,
) -> None:
    document = tmp_path / "test.rst"
    original = _BAD_BLOCK
    document.write_text(original, encoding="utf-8")
    # --sphinx-src/--build-dir are global now (before the verb); --skip-fixable
    # stays on fix's own parser (after the verb) — each extra goes wherever its
    # own flag actually parses, exercising the same _validate_fast_allowlist
    # rejection either way.
    global_flags = {"--sphinx-src", "--build-dir"}
    if extra and extra[0] in global_flags:
        argv = ["check_rst.py", *extra, "fix", "--fast", str(document)]
    else:
        argv = ["check_rst.py", "fix", "--fast", *extra, str(document)]
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert document.read_text(encoding="utf-8") == original
    assert message in capsys.readouterr().out


@pytest.mark.integration
def test_cli_fix_only_no_adornments_is_hygiene_only(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    document.write_bytes(_BAD_BLOCK.replace("\n", "\r\n").encode())
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "fix", "--fast", "--no-adornments", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert document.read_text(encoding="utf-8") == _BAD_BLOCK
    out = capsys.readouterr().out
    assert "CRLF line endings 7" in out
    assert "structural lines" not in out


@pytest.mark.integration
def test_cli_fix_only_quiet_emits_only_the_status_footer(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", "--fast", "--quiet", str(document)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert capsys.readouterr().out.splitlines() == [
        "check_rst: 1 file(s) processed, 0 error(s), 1 file(s) fixed [fast]"
    ]


@pytest.mark.integration
def test_cli_fix_only_write_failure_is_nonzero_and_keeps_final_status(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    original = _BAD_BLOCK
    document.write_text(original, encoding="utf-8")

    def fail_write(_plan: object) -> None:
        raise OSError("read-only filesystem")

    monkeypatch.setattr(_formatting, "_apply_fix_plan", fail_write)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", "--fast", str(document)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert document.read_text(encoding="utf-8") == original
    lines = capsys.readouterr().out.splitlines()
    assert any("ERROR: cannot write fix: read-only filesystem" in line for line in lines)
    assert lines[-1] == ("check_rst: 1 file(s) processed, 1 error(s), 0 file(s) fixed [fast]")


@pytest.mark.integration
def test_cli_fix_only_is_convergent_and_verbose_names_clean_files(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", "--fast", str(document)])
    with pytest.raises(SystemExit) as first:
        cli.main()
    assert first.value.code == 0
    capsys.readouterr()

    monkeypatch.setattr("sys.argv", ["check_rst.py", "fix", "--fast", "--verbose", str(document)])
    with pytest.raises(SystemExit) as second:
        cli.main()

    assert second.value.code == 0
    lines = capsys.readouterr().out.splitlines()
    assert f"{document}: no fixable changes" in lines
    assert lines[-1] == ("check_rst: 1 file(s) processed, 0 error(s), 0 file(s) fixed [fast]")


@pytest.mark.integration
def test_outline_blocks_summary_hidden_by_default(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """'blocks:' requires --verbose; 'levels:' does not — the one line
    demoted out of the two the a6ea216-era design originally paired."""
    p = rst_repo / "test.rst"
    p.write_text(
        "Root\n####\n\n.. code-block:: bash\n\n   echo one\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", "--quiet", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "levels:" in out
    assert "blocks:" not in out


@pytest.mark.integration
def test_outline_blocks_summary_shown_with_verbose(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "Root\n####\n\n.. code-block:: bash\n\n   echo one\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "outline", "--with-findings", "--quiet", "--verbose", str(p)],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "blocks: 1 code block" in out


@pytest.mark.integration
def test_footer_lines_words_hidden_by_default(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "check_rst: 1 file(s) checked" in out  # Line 1 always prints
    assert "lines:" not in out
    assert "words:" not in out


@pytest.mark.integration
def test_footer_lines_words_shown_with_verbose(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "lines:" in out
    assert "words:" in out


@pytest.mark.integration
def test_default_run_never_computes_word_frequency(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The default level (no --verbose, no --word-samples) must not even
    CALL the stopword/stemmer machinery — display suppression alone would
    still pay the computation cost for output nobody sees."""

    def _must_not_run(*_a: object, **_k: object) -> None:
        raise AssertionError("word-frequency computation must be skipped")

    monkeypatch.setattr(_reports, "_top_prose_words", _must_not_run)
    monkeypatch.setattr(_reports, "_rare_prose_words", _must_not_run)
    p = rst_repo / "test.rst"
    p.write_text("#######\nTitle\n#######\n\nSome real prose content here.\n", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0


@pytest.mark.integration
def test_word_samples_zero_disables_even_under_verbose(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--word-samples 0 overrides --verbose's own default of 10 — an
    explicit request always wins, in either direction."""

    def _must_not_run(*_a: object, **_k: object) -> None:
        raise AssertionError("word-frequency computation must be skipped")

    monkeypatch.setattr(_reports, "_top_prose_words", _must_not_run)
    monkeypatch.setattr(_reports, "_rare_prose_words", _must_not_run)
    p = rst_repo / "test.rst"
    p.write_text("#######\nTitle\n#######\n\nSome real prose content here.\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "check",
            "--quiet",
            "--verbose",
            "--word-samples",
            "0",
            str(p),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "top prose words:" not in out
    assert "rare prose words:" not in out


@pytest.mark.integration
def test_word_samples_promotes_top_rare_words_under_quiet(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--word-samples N promotes the prose-word lines at ANY level,
    --quiet included — the one line-4 exception to the verbosity
    ladder (Max: 'promote in any level to output them')."""
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\nproduct server product server product.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--word-samples", "5", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "top prose words: product (3 @" in out
    # lines:/words: stay hidden — --word-samples promotes only line 4.
    # (Line-start check: "words:" alone is a substring of "rare prose
    # words:", which IS expected to be present here.)
    assert not any(ln.startswith("lines:") or ln.startswith("words:") for ln in out.splitlines())


@pytest.mark.integration
def test_json_word_samples_disabled_by_default(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--json without --verbose/--word-samples: top_words/rare_words are
    null, not the old always-populated N=10 — same skip-entirely contract
    as the text footer, unifying the two previously-independent defaults
    (footer 13, JSON 10) into one shared, flag-controlled value."""
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\nproduct server product server.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    data = json.loads(capsys.readouterr().out)
    stats = data["files"][0]["stats"]
    assert stats["top_words"] is None
    assert stats["rare_words"] is None
    assert stats["word_stats_error"] is None  # null ≠ error: simply not requested


@pytest.mark.integration
def test_word_samples_rejects_negative(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--word-samples", "-1", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--word-samples must be >= 0" in out
