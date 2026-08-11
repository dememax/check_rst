# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Subprocess coverage for combined command-line workflows — check_rst project
"""Exercise the real module entry point without importing CLI implementation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "combined_sphinx"


def _run_cli(cwd: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the worktree module through a genuine interpreter boundary."""
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(PROJECT_ROOT / "src"), existing_pythonpath) if part
    )
    return subprocess.run(
        [sys.executable, "-m", "check_rst", *arguments],
        cwd=cwd,
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )


@pytest.fixture
def black_box_project(tmp_path: Path) -> Path:
    """Copy and commit the standing multi-construct Sphinx project."""
    shutil.copytree(FIXTURE_ROOT, tmp_path, dirs_exist_ok=True)
    commands = (
        ("init", "--quiet"),
        ("config", "user.email", "test@example.com"),
        ("config", "user.name", "Test User"),
        ("add", "."),
        ("commit", "--quiet", "-m", "fixture baseline"),
    )
    for command in commands:
        subprocess.run(["git", *command], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


@pytest.mark.integration
@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ([], "the following arguments are required: COMMAND"),
        (["unknown-command"], "argument COMMAND: invalid choice"),
        (["check", "--unknown-option"], "unrecognized arguments: --unknown-option"),
        (["--sphinx-src"], "argument --sphinx-src: expected one argument"),
        (["context", "entry"], "the following arguments are required: FILE"),
        (["check", "--config", "project.toml"], "unrecognized arguments: --config"),
        (["diff-json", "old.json"], "the following arguments are required: NEW.json"),
        (["list-table", "--only", "not-an-integer"], "argument --only: invalid int value"),
    ],
)
def test_black_box_argparse_errors_use_stderr_and_status_2(
    tmp_path: Path,
    arguments: list[str],
    message: str,
) -> None:
    result = _run_cli(tmp_path, *arguments)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "usage: check_rst" in result.stderr
    assert message in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.integration
@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--config", "a.toml", "--no-config", "check"], "--no-config is incompatible with --config"),
        (["--build-dir", "build", "check"], "--build-dir requires verified Sphinx mode"),
        (["--sphinx-src", "docs", "hierarchy"], "hierarchy is self-contained"),
        (["--config", "a.toml", "diff-json", "old.json", "new.json"], "diff-json is self-contained"),
        (["outline", "--max-output-lines", "1"], "--max-output-lines must be >= 2"),
    ],
)
def test_black_box_runtime_argument_conflicts_use_stdout_and_status_1(
    tmp_path: Path,
    arguments: list[str],
    message: str,
) -> None:
    result = _run_cli(tmp_path, *arguments)

    assert result.returncode == 1
    assert message in result.stdout
    assert result.stderr == ""
    assert "Traceback" not in result.stdout


@pytest.mark.integration
def test_black_box_bare_check_staged_file_before_first_commit(tmp_path: Path) -> None:
    """An unborn HEAD has no diff base, so staged files use whole-file scope."""
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True, capture_output=True)
    document = tmp_path / "new.rst"
    document.write_text("#######\nTitle\n#######\n", encoding="utf-8")
    subprocess.run(["git", "add", "new.rst"], cwd=tmp_path, check=True, capture_output=True)

    result = _run_cli(tmp_path, "check")

    assert result.returncode == 0
    assert result.stderr == ""
    assert "1 file(s) checked, 0 error(s)" in result.stdout
    assert "Traceback" not in result.stdout


@pytest.mark.integration
def test_black_box_reviewer_combines_verified_json_git_scope_and_sphinx_failure(
    black_box_project: Path,
) -> None:
    full = _run_cli(black_box_project, "check", "--format", "json", "guide.rst")

    assert full.returncode == 0
    assert full.stderr == ""
    report = json.loads(full.stdout)
    assert report["mode"] == "verified"
    assert report["config"]["applied"] == ["sphinx-src=.", "build-dir=_build"]
    assert report["summary"]["files_checked"] == 1
    assert report["summary"]["errors"] == 0
    assert report["summary"]["warnings"] == 4

    document = report["files"][0]
    assert {(entry["kind"], entry["depth"]) for entry in document["tables"]} == {("list", 5)}
    assert {(entry["kind"], entry["depth"]) for entry in document["admonitions"]} == {("note", 5)}
    assert any(entry["kind"] == "bullet" and entry["depth"] == 4 for entry in document["lists"])
    finding_text = "\n".join(finding["text"] for finding in document["findings"])
    assert "bold paragraph opener" in finding_text
    assert "mistyped directive" in finding_text
    assert "Аuthor" in finding_text  # noqa: RUF001
    assert "reference.rst mentioned as plain text" in finding_text

    with (black_box_project / "guide.rst").open("a", encoding="utf-8") as stream:
        stream.write("\nA changed line contains a broken :ref:`missing-target`.\n")
    changed = _run_cli(black_box_project, "check")

    assert changed.returncode == 0
    assert changed.stderr == ""
    assert "guide.rst" in changed.stdout
    assert "undefined label: 'missing-target'" in changed.stdout
    assert "1 file(s) checked" in changed.stdout
    assert "0 error(s)" in changed.stdout
    assert "Traceback" not in changed.stdout

    with (black_box_project / "conf.py").open("a", encoding="utf-8") as stream:
        stream.write('\nraise RuntimeError("black-box configuration failure")\n')
    failed_build = _run_cli(black_box_project, "check")
    assert failed_build.returncode == 1
    assert failed_build.stderr == ""
    assert "Sphinx environment build failed" in failed_build.stdout
    assert "black-box configuration failure" in failed_build.stdout


@pytest.mark.integration
def test_black_box_modifier_previews_then_applies_two_proven_transformations(
    black_box_project: Path,
) -> None:
    draft = black_box_project / "draft.rst"
    original_draft = draft.read_text(encoding="utf-8")
    preview = _run_cli(black_box_project, "diff", "--fast", "draft.rst")

    assert preview.returncode == 1
    assert preview.stderr == ""
    assert "+#######" in preview.stdout
    assert draft.read_text(encoding="utf-8") == original_draft

    fixed = _run_cli(black_box_project, "fix", "--fast", "draft.rst")
    assert fixed.returncode == 0
    assert "1 file(s) fixed" in fixed.stdout
    assert "#######\nDraft\n#######" in draft.read_text(encoding="utf-8")
    assert _run_cli(black_box_project, "diff", "--fast", "draft.rst").returncode == 0

    tables = black_box_project / "tables.rst"
    original_tables = tables.read_text(encoding="utf-8")
    table_preview = _run_cli(black_box_project, "list-table", "tables.rst")
    assert table_preview.returncode == 1
    assert "2 table(s) converted" in table_preview.stdout
    assert table_preview.stdout.count(".. list-table::") == 2
    assert tables.read_text(encoding="utf-8") == original_tables

    applied = _run_cli(black_box_project, "list-table", "--apply", "tables.rst")
    assert applied.returncode == 0
    assert "2 table(s) converted" in applied.stdout
    converted_tables = tables.read_text(encoding="utf-8")
    assert converted_tables.count(".. list-table::") == 2

    stable = _run_cli(black_box_project, "list-table", "tables.rst")
    assert stable.returncode == 0
    assert stable.stdout.count("UNCHANGED [list-table.already-list-table]") == 2
    assert "0 file(s) would change" in stable.stdout
    assert tables.read_text(encoding="utf-8") == converted_tables

    checked = _run_cli(black_box_project, "--no-config", "check", "draft.rst", "tables.rst")
    assert checked.returncode == 0
    assert "2 file(s) checked, 0 error(s)" in checked.stdout


@pytest.mark.integration
def test_black_box_reader_navigates_toctree_context_and_live_references(
    black_box_project: Path,
) -> None:
    tree = _run_cli(black_box_project, "outline", "index.rst")
    assert tree.returncode == 0
    assert tree.stderr == ""
    assert "toctree (4 entries, maxdepth=2)" in tree.stdout
    assert "guide:" in tree.stdout
    assert "# Complex guide" in tree.stdout
    assert "reference:" in tree.stdout
    assert "# Shared reference" in tree.stdout
    assert "tables:" in tree.stdout
    assert "# Nested tables" in tree.stdout

    nested = _run_cli(black_box_project, "outline", "guide.rst")
    assert nested.returncode == 0
    assert "bullet list ('*', 2 items)" in nested.stdout
    assert "admonition (note): The admonition is inside a list item." in nested.stdout
    assert 'Table (list, 2x2), "Nested status"' in nested.stdout

    context = _run_cli(black_box_project, "context", "guide:Nested operations", "guide.rst")
    assert context.returncode == 0
    assert "selector: guide:Nested operations" in context.stdout
    assert "guide:bullet-list@" in context.stdout
    assert "mistyped directive" in context.stdout
    assert "ref -> shared-target (reference)" in context.stdout
    assert "reference:" in context.stdout
    assert "doc -> guide" in context.stdout

    references = _run_cli(black_box_project, "refs", "reference.rst")
    assert references.returncode == 0
    assert "outgoing:" in references.stdout
    assert "doc -> guide (guide)" in references.stdout
    assert "incoming:" in references.stdout
    assert "guide:" in references.stdout
    assert "ref -> shared-target" in references.stdout
    assert "index:" in references.stdout
