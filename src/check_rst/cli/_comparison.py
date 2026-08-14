# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Semantic comparison state acquisition and Git hunk ownership — check_rst project

from __future__ import annotations

import collections
import dataclasses
import enum
import os
import pathlib
from typing import TYPE_CHECKING, cast

import pygit2

from . import _helpers
from ._document import Document

if TYPE_CHECKING:
    from collections.abc import Iterable


class GitStateKind(enum.StrEnum):
    REVISION = "revision"
    INDEX = "index"
    WORKTREE = "worktree"


@dataclasses.dataclass(frozen=True, slots=True)
class GitState:
    kind: GitStateKind
    revision: str | None = None

    @classmethod
    def revision_state(cls, revision: str) -> GitState:
        return cls(GitStateKind.REVISION, revision)

    @classmethod
    def index(cls) -> GitState:
        return cls(GitStateKind.INDEX)

    @classmethod
    def worktree(cls) -> GitState:
        return cls(GitStateKind.WORKTREE)

    @property
    def label(self) -> str:
        return self.revision if self.kind is GitStateKind.REVISION and self.revision is not None else self.kind.value


@dataclasses.dataclass(frozen=True, slots=True)
class SectionOwner:
    id: str
    title: str
    depth: int
    char: str
    start: int
    end: int


@dataclasses.dataclass(frozen=True, slots=True)
class GitHunk:
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    old_owners: tuple[SectionOwner, ...] = ()
    new_owners: tuple[SectionOwner, ...] = ()
    ownership: str = "unmapped"


@dataclasses.dataclass(frozen=True, slots=True)
class GitFileChange:
    status: str
    old_path: str | None
    new_path: str | None
    old_text: str | None
    new_text: str | None
    hunks: tuple[GitHunk, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class GitComparison:
    old: GitState
    new: GitState
    files: tuple[GitFileChange, ...]


_WORKTREE_DIFF_FLAGS = (
    pygit2.enums.DiffOption.INCLUDE_UNTRACKED
    | pygit2.enums.DiffOption.RECURSE_UNTRACKED_DIRS
    | pygit2.enums.DiffOption.SHOW_UNTRACKED_CONTENT
)


_STATUS_NAMES = {
    pygit2.GIT_DELTA_ADDED: "added",
    pygit2.GIT_DELTA_COPIED: "copied",
    pygit2.GIT_DELTA_DELETED: "deleted",
    pygit2.GIT_DELTA_MODIFIED: "modified",
    pygit2.GIT_DELTA_RENAMED: "renamed",
    pygit2.GIT_DELTA_TYPECHANGE: "typechange",
    pygit2.GIT_DELTA_UNTRACKED: "untracked",
}


def _diff_for_states(
    repo: pygit2.Repository,
    old: GitState,
    new: GitState,
    *,
    context_lines: int = 0,
) -> pygit2.Diff:
    """Return a libgit2 delta for one supported state pair."""
    if old.kind is GitStateKind.REVISION:
        assert old.revision is not None
        if new.kind is GitStateKind.WORKTREE:
            return repo.diff(
                old.revision,
                None,
                flags=_WORKTREE_DIFF_FLAGS,
                context_lines=context_lines,
            )
        if new.kind is GitStateKind.INDEX:
            return repo.diff(old.revision, None, cached=True, context_lines=context_lines)
        if new.kind is GitStateKind.REVISION:
            assert new.revision is not None
            return repo.diff(old.revision, new.revision, context_lines=context_lines)
    if old.kind is GitStateKind.INDEX and new.kind is GitStateKind.WORKTREE:
        return repo.diff(None, None, flags=_WORKTREE_DIFF_FLAGS, context_lines=context_lines)
    raise ValueError(f"unsupported Git comparison: {old.label} -> {new.label}")


def _blob_text(repo: pygit2.Repository, oid: pygit2.Oid) -> str | None:
    if str(oid) == "0" * 40:
        return None
    blob = repo[oid]
    if not isinstance(blob, pygit2.Blob):
        raise RuntimeError(f"Git object {oid} is not a blob")
    return blob.data.decode("utf-8")


def _walk_tree_blobs(
    repo: pygit2.Repository,
    tree: pygit2.Tree,
    prefix: str = "",
) -> Iterable[tuple[str, pygit2.Oid]]:
    for entry in tree:
        path = f"{prefix}{entry.name}"
        value = repo[entry.id]
        if isinstance(value, pygit2.Tree):
            yield from _walk_tree_blobs(repo, value, f"{path}/")
        elif isinstance(value, pygit2.Blob):
            yield path, entry.id


def _old_blob_paths(repo: pygit2.Repository, state: GitState) -> dict[str, list[str]]:
    """Map complete blob identity to old-state paths for exact copy proof."""
    blobs: Iterable[tuple[str, pygit2.Oid]]
    if state.kind is GitStateKind.REVISION:
        assert state.revision is not None
        tree = repo.revparse_single(state.revision).peel(pygit2.Tree)
        blobs = _walk_tree_blobs(repo, tree)
    elif state.kind is GitStateKind.INDEX:
        blobs = ((entry.path, entry.id) for entry in repo.index)
    else:
        return {}
    paths: dict[str, list[str]] = {}
    for path, oid in blobs:
        if pathlib.PurePosixPath(path).suffix == ".rst":
            paths.setdefault(str(oid), []).append(path)
    return paths


def _delta_path(raw_path: bytes | None) -> str | None:
    return os.fsdecode(raw_path) if raw_path is not None else None


def _touches_rst(old_path: str | None, new_path: str | None) -> bool:
    return any(path is not None and pathlib.PurePosixPath(path).suffix == ".rst" for path in (old_path, new_path))


def _state_text(
    repo: pygit2.Repository,
    worktree_root: pathlib.Path,
    state: GitState,
    path: str | None,
    oid: pygit2.Oid,
) -> str | None:
    if path is None:
        return None
    if state.kind is GitStateKind.WORKTREE:
        candidate = worktree_root / path
        if not candidate.is_file():
            return None
        return candidate.read_bytes().decode("utf-8")
    return _blob_text(repo, oid)


def _allowed_paths(worktree_root: pathlib.Path, paths: tuple[pathlib.Path, ...]) -> set[str] | None:
    if not paths:
        return None
    root = worktree_root.resolve()
    allowed: set[str] = set()
    for path in paths:
        candidate = path if path.is_absolute() else worktree_root / path
        try:
            relative = candidate.resolve().relative_to(root)
        except ValueError as exc:
            raise ValueError(f"comparison path is outside the Git worktree: {path}") from exc
        allowed.add(relative.as_posix())
    return allowed


def _section_owners(
    project_root: pathlib.Path,
    path: str | None,
    text: str | None,
) -> tuple[SectionOwner, ...]:
    if path is None or text is None:
        return ()
    source_path = project_root / pathlib.PurePosixPath(path)
    document = Document(source_path, project_root, source_text=text)
    lines = text.splitlines()
    docname = pathlib.PurePosixPath(path).with_suffix("").as_posix()
    occurrences: collections.Counter[str] = collections.Counter()
    owners: list[SectionOwner] = []
    for entry in document.outline:
        base_id = f"{docname}:{entry.title}"
        occurrences[base_id] += 1
        occurrence = occurrences[base_id]
        section_id = base_id if occurrence == 1 else f"{base_id}#{occurrence}"
        start = entry.lineno
        overline_index = entry.lineno - 2
        if overline_index >= 0:
            possible_overline = lines[overline_index]
            if possible_overline and set(possible_overline) == {entry.char}:
                start -= 1
        owners.append(
            SectionOwner(
                id=section_id,
                title=entry.title,
                depth=entry.depth,
                char=entry.char,
                start=start,
                end=entry.end or len(lines),
            )
        )
    return tuple(owners)


def _owners_for_range(
    owners: tuple[SectionOwner, ...],
    start: int,
    count: int,
) -> tuple[SectionOwner, ...]:
    if count <= 0:
        return ()
    selected: dict[str, SectionOwner] = {}
    for lineno in range(start, start + count):
        candidates = [owner for owner in owners if owner.start <= lineno <= owner.end]
        if candidates:
            owner = max(candidates, key=lambda candidate: candidate.depth)
            selected[owner.id] = owner
    return tuple(sorted(selected.values(), key=lambda owner: (owner.start, owner.depth, owner.id)))


def assign_hunk_owners(comparison: GitComparison, project_root: pathlib.Path) -> GitComparison:
    """Attach deepest-section ownership without changing zero-context ranges."""
    files: list[GitFileChange] = []
    for change in comparison.files:
        old_sections = _section_owners(project_root, change.old_path, change.old_text)
        new_sections = _section_owners(project_root, change.new_path, change.new_text)
        hunks: list[GitHunk] = []
        for hunk in change.hunks:
            old_owners = _owners_for_range(old_sections, hunk.old_start, hunk.old_lines)
            new_owners = _owners_for_range(new_sections, hunk.new_start, hunk.new_lines)
            owner_ids = {owner.id for owner in (*old_owners, *new_owners)}
            ownership = "unmapped" if not owner_ids else "owned" if len(owner_ids) == 1 else "mixed"
            hunks.append(
                dataclasses.replace(
                    hunk,
                    old_owners=old_owners,
                    new_owners=new_owners,
                    ownership=ownership,
                )
            )
        files.append(dataclasses.replace(change, hunks=tuple(hunks)))
    return dataclasses.replace(comparison, files=tuple(files))


def _hunks(patch: pygit2.Patch) -> tuple[GitHunk, ...]:
    return tuple(
        GitHunk(
            old_start=hunk.old_start,
            old_lines=hunk.old_lines,
            new_start=hunk.new_start,
            new_lines=hunk.new_lines,
        )
        for hunk in patch.hunks
    )


def _materialize_diff(diff: pygit2.Diff) -> tuple[pygit2.Patch, ...]:
    """Run exact rename detection and force libgit2's lazy diff iteration."""
    try:
        # Complete content identity is sufficient to call a path pair a
        # rename; similarity is deliberately not semantic identity. Include
        # untracked destinations so a filesystem rename is not degraded to a
        # deletion plus an unrelated untracked file.
        diff.find_similar(
            flags=(pygit2.enums.DiffFind.FIND_RENAMES | pygit2.enums.DiffFind.FIND_FOR_UNTRACKED),
            rename_threshold=100,
        )
        return tuple(patch for patch in diff if patch is not None)
    except pygit2.GitError as exc:
        raise RuntimeError(f"git diff failed: {exc}") from exc


def _patch_signature(patches: tuple[pygit2.Patch, ...]) -> tuple[object, ...]:
    """Freeze every source-affecting libgit2 fact for a TOCTOU check."""
    return tuple(
        (
            patch.delta.status,
            patch.delta.old_file.raw_path,
            patch.delta.new_file.raw_path,
            str(patch.delta.old_file.id),
            str(patch.delta.new_file.id),
            tuple(
                (
                    hunk.old_start,
                    hunk.old_lines,
                    hunk.new_start,
                    hunk.new_lines,
                    tuple((line.origin, line.old_lineno, line.new_lineno, line.raw_content) for line in hunk.lines),
                )
                for hunk in patch.hunks
            ),
        )
        for patch in patches
    )


def _unborn_status_paths(repo: pygit2.Repository, worktree_root: pathlib.Path) -> Iterable[str]:
    try:
        return repo.status(untracked_files="all")
    except UnicodeDecodeError:
        return _helpers._status_paths_with_surrogateescape(worktree_root)
    except pygit2.GitError as exc:
        raise RuntimeError(f"git status failed: {exc}") from exc


def _compare_unborn_head(
    repo: pygit2.Repository,
    worktree_root: pathlib.Path,
    old: GitState,
    new: GitState,
    allowed: set[str] | None,
) -> GitComparison:
    """Compare the absent HEAD tree without materializing one in Git's ODB."""
    files: list[GitFileChange] = []
    if new.kind is GitStateKind.WORKTREE:
        for path in sorted(_unborn_status_paths(repo, worktree_root)):
            candidate = worktree_root / path
            if pathlib.PurePosixPath(path).suffix != ".rst" or not candidate.is_file():
                continue
            if allowed is not None and path not in allowed:
                continue
            data = candidate.read_bytes()
            patch = pygit2.Patch.create_from(None, data, old_as_path=path, new_as_path=path, context_lines=0)
            status = "added" if os.fsencode(path) in repo.index else "untracked"
            files.append(
                GitFileChange(
                    status=status,
                    old_path=path,
                    new_path=path,
                    old_text=None,
                    new_text=data.decode("utf-8"),
                    hunks=_hunks(patch),
                )
            )
        return GitComparison(old=old, new=new, files=tuple(files))
    if new.kind is GitStateKind.INDEX:
        for entry in repo.index:
            path = entry.path
            if pathlib.PurePosixPath(path).suffix != ".rst":
                continue
            if allowed is not None and path not in allowed:
                continue
            data = cast("pygit2.Blob", repo[entry.id]).data
            patch = pygit2.Patch.create_from(None, data, old_as_path=path, new_as_path=path, context_lines=0)
            files.append(
                GitFileChange(
                    status="added",
                    old_path=path,
                    new_path=path,
                    old_text=None,
                    new_text=data.decode("utf-8"),
                    hunks=_hunks(patch),
                )
            )
        return GitComparison(old=old, new=new, files=tuple(files))
    raise ValueError(f"unsupported unborn Git comparison: {old.label} -> {new.label}")


def _compare_git_states(
    project_root: pathlib.Path,
    old: GitState,
    new: GitState,
    *,
    paths: tuple[pathlib.Path, ...] = (),
) -> GitComparison:
    repo = _helpers._repo_for_root(project_root)
    assert repo.workdir is not None
    worktree_root = pathlib.Path(repo.workdir)
    allowed = _allowed_paths(worktree_root, paths)
    if repo.head_is_unborn and old.kind is GitStateKind.REVISION and old.revision == "HEAD":
        comparison = _compare_unborn_head(repo, worktree_root, old, new, allowed)
        if new.kind is GitStateKind.WORKTREE:
            verified = _compare_unborn_head(repo, worktree_root, old, new, allowed)
            if verified != comparison:
                raise RuntimeError("worktree changed during Git comparison")
        return comparison
    patches = _materialize_diff(_diff_for_states(repo, old, new))
    initial_signature = _patch_signature(patches)

    files: list[GitFileChange] = []
    for patch in patches:
        delta = patch.delta
        old_path = _delta_path(delta.old_file.raw_path)
        new_path = _delta_path(delta.new_file.raw_path)
        if not _touches_rst(old_path, new_path):
            continue
        if allowed is not None and old_path not in allowed and new_path not in allowed:
            continue
        status = _STATUS_NAMES.get(delta.status, f"unknown-{delta.status}")
        if status == "untracked" and delta.new_file.raw_path in repo.index:
            # libgit2's worktree diff reports a staged-new path as UNTRACKED
            # when SHOW_UNTRACKED_CONTENT is needed to obtain its full hunk.
            # Index membership distinguishes a genuinely untracked file.
            status = "added"
        files.append(
            GitFileChange(
                status=status,
                old_path=old_path,
                new_path=new_path,
                old_text=_state_text(repo, worktree_root, old, old_path, delta.old_file.id),
                new_text=_state_text(repo, worktree_root, new, new_path, delta.new_file.id),
                hunks=_hunks(patch),
            )
        )

    if new.kind is GitStateKind.WORKTREE:
        verified_patches = _materialize_diff(_diff_for_states(repo, old, new))
        if _patch_signature(verified_patches) != initial_signature:
            raise RuntimeError("worktree changed during Git comparison")

    # libgit2 copy detection requires similarity search across unmodified
    # sources.  The semantic-comparison boundary is stricter: a complete blob
    # identity with exactly one old source proves an exact copy; duplicate
    # candidate sources are ambiguous and remain ordinary additions.
    old_sources = _old_blob_paths(repo, old)
    deleted_paths = {change.old_path for change in files if change.status == "deleted"}
    consumed_deletions: set[str] = set()
    classified: list[GitFileChange] = []
    for change in files:
        if change.status not in {"added", "untracked"} or change.new_text is None:
            classified.append(change)
            continue
        sources = old_sources.get(str(pygit2.hash(change.new_text.encode("utf-8"))), [])
        if len(sources) != 1 or sources[0] == change.new_path:
            classified.append(change)
            continue
        source = sources[0]
        copied_status = "renamed" if source in deleted_paths else "copied"
        if copied_status == "renamed":
            consumed_deletions.add(source)
        classified.append(
            dataclasses.replace(
                change,
                status=copied_status,
                old_path=source,
                old_text=change.new_text,
                hunks=(),
            )
        )
    if consumed_deletions:
        classified = [
            change
            for change in classified
            if not (change.status == "deleted" and change.old_path in consumed_deletions)
        ]
    return GitComparison(old=old, new=new, files=tuple(classified))


def compare_git_states(
    project_root: pathlib.Path,
    old: GitState,
    new: GitState,
    *,
    paths: tuple[pathlib.Path, ...] = (),
) -> GitComparison:
    """Compare supported Git states with a stable, diagnosable failure boundary."""
    try:
        return _compare_git_states(project_root, old, new, paths=paths)
    except pygit2.GitError as exc:
        raise RuntimeError(f"Git comparison failed: {exc}") from exc


def _synthetic_patch(change: GitFileChange, context_lines: int) -> str:
    old_data = None if change.old_text is None else change.old_text.encode("utf-8")
    new_data = None if change.new_text is None else change.new_text.encode("utf-8")
    path = change.new_path or change.old_path
    if path is None:
        raise RuntimeError("Git change has no source path")
    patch = pygit2.Patch.create_from(
        old_data,
        new_data,
        old_as_path=change.old_path or path,
        new_as_path=change.new_path or path,
        context_lines=context_lines,
    )
    return patch.text or ""


def git_patch_text(
    project_root: pathlib.Path,
    old: GitState,
    new: GitState,
    *,
    paths: tuple[pathlib.Path, ...] = (),
    context_lines: int = 3,
) -> str:
    """Render an optional Git patch without changing semantic hunk geometry."""
    if context_lines < 0:
        raise ValueError("Git patch context cannot be negative")
    comparison = compare_git_states(project_root, old, new, paths=paths)
    repo = _helpers._repo_for_root(project_root)
    assert repo.workdir is not None
    worktree_root = pathlib.Path(repo.workdir)
    allowed = _allowed_paths(worktree_root, paths)
    if repo.head_is_unborn and old.kind is GitStateKind.REVISION and old.revision == "HEAD":
        return "".join(_synthetic_patch(change, context_lines) for change in comparison.files)

    patches = _materialize_diff(
        _diff_for_states(repo, old, new, context_lines=context_lines),
    )
    rendered: list[str] = []
    for patch in patches:
        old_path = _delta_path(patch.delta.old_file.raw_path)
        new_path = _delta_path(patch.delta.new_file.raw_path)
        if not _touches_rst(old_path, new_path):
            continue
        if allowed is not None and old_path not in allowed and new_path not in allowed:
            continue
        rendered.append(patch.text or "")

    if compare_git_states(project_root, old, new, paths=paths) != comparison:
        raise RuntimeError("worktree changed during Git patch rendering")
    return "".join(rendered)


def _plural(count: int, singular: str) -> str:
    return f"{count} {singular}{'' if count == 1 else 's'}"


def _owner_description(hunk: GitHunk) -> str:
    owners = {owner.id: owner for owner in (*hunk.old_owners, *hunk.new_owners)}
    if len(owners) == 1:
        owner = next(iter(owners.values()))
        return f'section "{owner.title}"'
    if owners:
        return "mixed sections: " + ", ".join(f'"{owner.title}"' for owner in owners.values())
    return "unmapped"


def format_git_comparison(
    comparison: GitComparison,
    *,
    staged_hunks: int | None = None,
    unstaged_hunks: int | None = None,
) -> str:
    """Render compact Git facts and zero-context section ownership."""
    components = ""
    if staged_hunks is not None and unstaged_hunks is not None:
        components = f" ({_plural(staged_hunks, 'staged hunk')}, {_plural(unstaged_hunks, 'unstaged hunk')})"
    lines = [f"Comparison: {comparison.old.label} -> {comparison.new.label}{components}"]
    if not comparison.files:
        lines.append("  no changed RST files")
        return "\n".join(lines)
    for change in comparison.files:
        path = change.new_path or change.old_path
        if change.old_path and change.new_path and change.old_path != change.new_path:
            path = f"{change.old_path} -> {change.new_path}"
        additions = sum(hunk.new_lines for hunk in change.hunks)
        deletions = sum(hunk.old_lines for hunk in change.hunks)
        lines.append(f"{path}: {change.status}, {_plural(len(change.hunks), 'hunk')} (+{additions} -{deletions})")
        for hunk in change.hunks:
            lines.append(f"  {hunk.old_start} -> {hunk.new_start}: {_owner_description(hunk)} [{hunk.ownership}]")
    return "\n".join(lines)


def format_git_change_sources(
    staged: GitComparison,
    unstaged: GitComparison,
) -> str:
    """Keep cumulative output attributable to its two underlying Git deltas."""
    lines = ["Change sources:"]
    for label, component in (("staged", staged), ("unstaged", unstaged)):
        for change in component.files:
            path = change.new_path or change.old_path
            if change.old_path and change.new_path and change.old_path != change.new_path:
                path = f"{change.old_path} -> {change.new_path}"
            if not change.hunks:
                lines.append(f"  {label}: {path} ({change.status})")
            else:
                lines.extend(f"  {label}: {path} {hunk.old_start} -> {hunk.new_start}" for hunk in change.hunks)
    return "\n".join(lines) if len(lines) > 1 else ""
