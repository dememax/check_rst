# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Tests for semantic comparison state acquisition and hunk ownership — check_rst project

from __future__ import annotations

import pathlib
import subprocess
from typing import TYPE_CHECKING

import pytest

from check_rst import cli
from check_rst.cli import _comparison, _helpers

if TYPE_CHECKING:
    from pathlib import Path

    import pygit2


def _commit_document(repository: Path, path: str, text: str) -> Path:
    document = repository / path
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", path], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-m", f"Add {path}"], check=True)
    return document


@pytest.mark.integration
def test_compare_git_states_reads_head_and_worktree_with_zero_context_hunk(tmp_git_repo: Path) -> None:
    old_text = "#######\nTitle\n#######\n\nOld.\n"
    new_text = "#######\nTitle\n#######\n\nNew.\n"
    document = _commit_document(tmp_git_repo, "doc.rst", old_text)
    document.write_text(new_text, encoding="utf-8")

    comparison = _comparison.compare_git_states(
        tmp_git_repo,
        _comparison.GitState.revision_state("HEAD"),
        _comparison.GitState.worktree(),
    )

    assert comparison.old.label == "HEAD"
    assert comparison.new.label == "worktree"
    assert comparison.files == (
        _comparison.GitFileChange(
            status="modified",
            old_path="doc.rst",
            new_path="doc.rst",
            old_text=old_text,
            new_text=new_text,
            hunks=(_comparison.GitHunk(old_start=5, old_lines=1, new_start=5, new_lines=1),),
        ),
    )


@pytest.mark.integration
def test_compare_git_states_keeps_staged_unstaged_and_cumulative_texts_distinct(tmp_git_repo: Path) -> None:
    head_text = "#######\nTitle\n#######\n\nHEAD.\n"
    index_text = "#######\nTitle\n#######\n\nIndex.\n"
    worktree_text = "#######\nTitle\n#######\n\nWorktree.\n"
    document = _commit_document(tmp_git_repo, "doc.rst", head_text)
    document.write_text(index_text, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_git_repo), "add", "doc.rst"], check=True)
    document.write_text(worktree_text, encoding="utf-8")

    staged = _comparison.compare_git_states(
        tmp_git_repo,
        _comparison.GitState.revision_state("HEAD"),
        _comparison.GitState.index(),
    )
    unstaged = _comparison.compare_git_states(
        tmp_git_repo,
        _comparison.GitState.index(),
        _comparison.GitState.worktree(),
    )
    cumulative = _comparison.compare_git_states(
        tmp_git_repo,
        _comparison.GitState.revision_state("HEAD"),
        _comparison.GitState.worktree(),
    )

    assert [(change.old_text, change.new_text) for change in staged.files] == [(head_text, index_text)]
    assert [(change.old_text, change.new_text) for change in unstaged.files] == [(index_text, worktree_text)]
    assert [(change.old_text, change.new_text) for change in cumulative.files] == [(head_text, worktree_text)]


@pytest.mark.integration
def test_compare_git_states_reports_rst_file_lifecycle_without_silent_omissions(tmp_git_repo: Path) -> None:
    deleted_text = "#########\nDeleted\n#########\n"
    renamed_text = "#########\nRenamed\n#########\n"
    staged_text = "########\nStaged\n########\n"
    untracked_text = "###########\nUntracked\n###########\n"
    deleted = _commit_document(tmp_git_repo, "deleted.rst", deleted_text)
    _commit_document(tmp_git_repo, "old-name.rst", renamed_text)
    deleted.unlink()
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "mv", "old-name.rst", "new-name.rst"],
        check=True,
    )
    staged = tmp_git_repo / "staged.rst"
    staged.write_text(staged_text, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_git_repo), "add", "staged.rst"], check=True)
    (tmp_git_repo / "untracked.rst").write_text(untracked_text, encoding="utf-8")

    comparison = _comparison.compare_git_states(
        tmp_git_repo,
        _comparison.GitState.revision_state("HEAD"),
        _comparison.GitState.worktree(),
    )

    changes = {(change.old_path, change.new_path): change for change in comparison.files}
    assert set(changes) == {
        ("deleted.rst", "deleted.rst"),
        ("old-name.rst", "new-name.rst"),
        ("staged.rst", "staged.rst"),
        ("untracked.rst", "untracked.rst"),
    }
    assert changes[("deleted.rst", "deleted.rst")].status == "deleted"
    assert changes[("deleted.rst", "deleted.rst")].new_text is None
    assert changes[("old-name.rst", "new-name.rst")].status == "renamed"
    assert changes[("old-name.rst", "new-name.rst")].old_text == renamed_text
    assert changes[("old-name.rst", "new-name.rst")].new_text == renamed_text
    assert changes[("staged.rst", "staged.rst")].status == "added"
    assert changes[("staged.rst", "staged.rst")].old_text is None
    assert changes[("untracked.rst", "untracked.rst")].status == "untracked"
    assert changes[("untracked.rst", "untracked.rst")].old_text is None


@pytest.mark.integration
def test_compare_git_states_keeps_rst_renamed_to_a_non_rst_path_visible(tmp_git_repo: Path) -> None:
    _commit_document(tmp_git_repo, "retired.rst", "Title\n=====\n")
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "mv", "retired.rst", "retired.txt"],
        check=True,
    )

    comparison = _comparison.compare_git_states(
        tmp_git_repo,
        _comparison.GitState.revision_state("HEAD"),
        _comparison.GitState.worktree(),
    )

    assert [(change.status, change.old_path, change.new_path) for change in comparison.files] == [
        ("renamed", "retired.rst", "retired.txt")
    ]


@pytest.mark.integration
def test_compare_git_states_treats_relative_paths_as_a_git_change_allowlist(tmp_git_repo: Path) -> None:
    first = _commit_document(tmp_git_repo, "first.rst", "First\n=====\n")
    second = _commit_document(tmp_git_repo, "second.rst", "Second\n======\n")
    first.write_text("First changed\n=============\n", encoding="utf-8")
    second.write_text("Second changed\n==============\n", encoding="utf-8")

    comparison = _comparison.compare_git_states(
        tmp_git_repo,
        _comparison.GitState.revision_state("HEAD"),
        _comparison.GitState.worktree(),
        paths=(pathlib.Path("first.rst"),),
    )

    assert [(change.old_path, change.new_path) for change in comparison.files] == [("first.rst", "first.rst")]


@pytest.mark.integration
def test_compare_git_states_uses_an_absent_head_for_an_unborn_repository(tmp_path: Path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    text = "#######\nTitle\n#######\n"
    (tmp_path / "doc.rst").write_text(text, encoding="utf-8")

    comparison = _comparison.compare_git_states(
        tmp_path,
        _comparison.GitState.revision_state("HEAD"),
        _comparison.GitState.worktree(),
    )

    assert comparison.files == (
        _comparison.GitFileChange(
            status="untracked",
            old_path="doc.rst",
            new_path="doc.rst",
            old_text=None,
            new_text=text,
            hunks=(_comparison.GitHunk(old_start=0, old_lines=0, new_start=1, new_lines=3),),
        ),
    )


@pytest.mark.integration
def test_compare_git_states_reads_two_revision_trees(tmp_git_repo: Path) -> None:
    old_text = "#######\nTitle\n#######\n\nOld.\n"
    new_text = "#######\nTitle\n#######\n\nNew.\n"
    document = _commit_document(tmp_git_repo, "doc.rst", old_text)
    document.write_text(new_text, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_git_repo), "add", "doc.rst"], check=True)
    subprocess.run(["git", "-C", str(tmp_git_repo), "commit", "-m", "Edit document"], check=True)

    comparison = _comparison.compare_git_states(
        tmp_git_repo,
        _comparison.GitState.revision_state("HEAD^"),
        _comparison.GitState.revision_state("HEAD"),
    )

    assert comparison.old.label == "HEAD^"
    assert comparison.new.label == "HEAD"
    assert [(change.old_text, change.new_text) for change in comparison.files] == [(old_text, new_text)]


@pytest.mark.integration
def test_compare_git_states_reports_an_exact_staged_copy(tmp_git_repo: Path) -> None:
    text = "#######\nSource\n#######\n"
    _commit_document(tmp_git_repo, "source.rst", text)
    (tmp_git_repo / "copy.rst").write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_git_repo), "add", "copy.rst"], check=True)

    comparison = _comparison.compare_git_states(
        tmp_git_repo,
        _comparison.GitState.revision_state("HEAD"),
        _comparison.GitState.index(),
    )

    assert comparison.files == (
        _comparison.GitFileChange(
            status="copied",
            old_path="source.rst",
            new_path="copy.rst",
            old_text=text,
            new_text=text,
            hunks=(),
        ),
    )


@pytest.mark.integration
def test_compare_git_states_does_not_guess_a_copy_among_duplicate_sources(tmp_git_repo: Path) -> None:
    text = "#######\nShared\n#######\n"
    _commit_document(tmp_git_repo, "first.rst", text)
    _commit_document(tmp_git_repo, "second.rst", text)
    (tmp_git_repo / "third.rst").write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_git_repo), "add", "third.rst"], check=True)

    comparison = _comparison.compare_git_states(
        tmp_git_repo,
        _comparison.GitState.revision_state("HEAD"),
        _comparison.GitState.index(),
    )

    assert [(change.status, change.old_path, change.new_path) for change in comparison.files] == [
        ("added", "third.rst", "third.rst")
    ]


@pytest.mark.integration
def test_compare_git_states_rejects_non_utf8_rst_content(tmp_git_repo: Path) -> None:
    document = _commit_document(tmp_git_repo, "doc.rst", "Title\n=====\n")
    document.write_bytes(b"Title\n=====\n\xff\n")

    with pytest.raises(UnicodeDecodeError):
        _comparison.compare_git_states(
            tmp_git_repo,
            _comparison.GitState.revision_state("HEAD"),
            _comparison.GitState.worktree(),
        )


@pytest.mark.integration
def test_compare_git_states_fails_if_worktree_changes_during_materialization(
    tmp_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_text = "#######\nTitle\n#######\n\nOld.\n"
    first_text = "#######\nTitle\n#######\n\nFirst.\n"
    second_text = "#######\nTitle\n#######\n\nSecond.\n"
    document = _commit_document(tmp_git_repo, "doc.rst", old_text)
    document.write_text(first_text, encoding="utf-8")
    real_state_text = _comparison._state_text
    mutated = False

    def mutate_after_read(
        repo: pygit2.Repository,
        worktree_root: Path,
        state: _comparison.GitState,
        path: str | None,
        oid: pygit2.Oid,
    ) -> str | None:
        nonlocal mutated
        text = real_state_text(repo, worktree_root, state, path, oid)
        if not mutated:
            document.write_text(second_text, encoding="utf-8")
            mutated = True
        return text

    monkeypatch.setattr(_comparison, "_state_text", mutate_after_read)

    with pytest.raises(RuntimeError, match="worktree changed during Git comparison"):
        _comparison.compare_git_states(
            tmp_git_repo,
            _comparison.GitState.revision_state("HEAD"),
            _comparison.GitState.worktree(),
        )


@pytest.mark.integration
def test_assign_hunk_owners_maps_a_prose_edit_to_its_deepest_section(tmp_git_repo: Path) -> None:
    old_text = "#######\nTitle\n#######\n\nFirst\n=====\n\nOld prose.\n\nSecond\n======\n\nUntouched.\n"
    new_text = old_text.replace("Old prose.", "New prose.")
    document = _commit_document(tmp_git_repo, "doc.rst", old_text)
    document.write_text(new_text, encoding="utf-8")
    comparison = _comparison.compare_git_states(
        tmp_git_repo,
        _comparison.GitState.revision_state("HEAD"),
        _comparison.GitState.worktree(),
    )

    owned = _comparison.assign_hunk_owners(comparison, tmp_git_repo)

    hunk = owned.files[0].hunks[0]
    assert hunk.ownership == "owned"
    assert [(owner.id, owner.title) for owner in hunk.old_owners] == [("doc:First", "First")]
    assert [(owner.id, owner.title) for owner in hunk.new_owners] == [("doc:First", "First")]


@pytest.mark.unit
def test_assign_hunk_owners_keeps_cross_section_and_unsectioned_ranges_visible(tmp_path: Path) -> None:
    sectioned = "Title\n=====\n\nFirst\n-----\n\nA.\n\nSecond\n------\n\nB.\n"
    mixed_comparison = _comparison.GitComparison(
        old=_comparison.GitState.revision_state("HEAD"),
        new=_comparison.GitState.worktree(),
        files=(
            _comparison.GitFileChange(
                status="modified",
                old_path="doc.rst",
                new_path="doc.rst",
                old_text=sectioned,
                new_text=sectioned,
                hunks=(_comparison.GitHunk(old_start=7, old_lines=6, new_start=7, new_lines=6),),
            ),
        ),
    )
    unsectioned_comparison = _comparison.GitComparison(
        old=_comparison.GitState.revision_state("HEAD"),
        new=_comparison.GitState.worktree(),
        files=(
            _comparison.GitFileChange(
                status="modified",
                old_path="notes.rst",
                new_path="notes.rst",
                old_text="Plain prose.\n",
                new_text="Changed prose.\n",
                hunks=(_comparison.GitHunk(old_start=1, old_lines=1, new_start=1, new_lines=1),),
            ),
        ),
    )

    mixed = _comparison.assign_hunk_owners(mixed_comparison, tmp_path)
    unmapped = _comparison.assign_hunk_owners(unsectioned_comparison, tmp_path)

    assert mixed.files[0].hunks[0].ownership == "mixed"
    assert unmapped.files[0].hunks[0].ownership == "unmapped"


@pytest.mark.integration
def test_git_patch_context_changes_presentation_without_changing_semantic_hunks(
    tmp_git_repo: Path,
) -> None:
    old_text = "Title\n=====\n\nBefore.\nOld.\nAfter.\n"
    new_text = old_text.replace("Old.", "New.")
    document = _commit_document(tmp_git_repo, "doc.rst", old_text)
    document.write_text(new_text, encoding="utf-8")
    old = _comparison.GitState.revision_state("HEAD")
    new = _comparison.GitState.worktree()

    semantic_before = _comparison.compare_git_states(tmp_git_repo, old, new)
    zero_context = _comparison.git_patch_text(tmp_git_repo, old, new, context_lines=0)
    two_lines = _comparison.git_patch_text(tmp_git_repo, old, new, context_lines=2)
    semantic_after = _comparison.compare_git_states(tmp_git_repo, old, new)

    assert "\n Before.\n" not in zero_context
    assert "\n After.\n" not in zero_context
    assert "\n Before.\n" in two_lines
    assert "\n After.\n" in two_lines
    assert semantic_after == semantic_before


@pytest.mark.integration
def test_compare_cli_reports_cumulative_change_and_both_component_sources(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old_text = "Title\n=====\n\nFirst.\n"
    staged_text = old_text.replace("First.", "Second.")
    worktree_text = old_text.replace("First.", "Third.")
    document = _commit_document(rst_repo, "doc.rst", old_text)
    document.write_text(staged_text, encoding="utf-8")
    subprocess.run(["git", "-C", str(rst_repo), "add", "doc.rst"], check=True)
    document.write_text(worktree_text, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst", "compare"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "Comparison: HEAD -> worktree (1 staged hunk, 1 unstaged hunk)" in output
    assert "doc.rst: modified, 1 hunk (+1 -1)" in output
    assert "staged: doc.rst 4 -> 4" in output
    assert "unstaged: doc.rst 4 -> 4" in output
    assert 'section "Title"' in output


@pytest.mark.integration
def test_compare_cli_reuses_section_comparison_for_live_git_text(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old_text = "#######\nTitle\n#######\n"
    new_text = "*******\nTitle\n*******\n"
    document = _commit_document(rst_repo, "doc.rst", old_text)
    document.write_text(new_text, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst", "compare"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "topology unchanged" in output
    assert "adornment changed: doc:Title ('#' -> '*')" in output


@pytest.mark.integration
def test_compare_cli_handles_default_state_selection_before_the_first_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "new.rst").write_text("Title\n=====\n", encoding="utf-8")
    monkeypatch.setattr(_helpers, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["check_rst", "compare"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "Comparison: HEAD -> worktree" in output
    assert "new.rst: untracked" in output
