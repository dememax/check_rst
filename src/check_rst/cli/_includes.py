# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Discovery roots and the lexical reverse include graph (CR-43) — check_rst project
"""Find the files that may include a given file.

check_rst follows an ``include`` directive only from the includer's side, so
a file meant for inclusion looks like a standalone document when it is
selected alone (CR-43).  Judging it in its includers' context first needs the
includers: a reverse, transitive include graph over a defined universe.

The universe (decision D9d):

* the discovery roots: an active configuration's directory, otherwise each
  selected file's Git worktree or, outside Git, the working directory for
  files beneath it; and an active Sphinx source directory as a root of its
  own, with or without configuration.  A selected file outside every root is *uncovered*, and its callers
  must refuse structural changes rather than judge it alone;
* the automatic scan population: files with a source suffix under the roots,
  never Git metadata, never a Git-ignored path, never through a directory
  symlink (cycles, root escapes and duplicate traversal), plus every
  transitively reached include target whatever its suffix.

The graph is lexical.  A lexical scan cannot tell an include directive from
include-looking text inside a comment or a literal block, so every site it
records is only *possible*: a parser-free caller must treat it as real and
refuse, while a parsing caller may confirm it.  Site paths resolve like
Docutils, from the lexical path the containing file is opened by, so a file
reached through a symlink is its own include context; under Sphinx a leading
``/`` names the source directory.  Canonical paths serve only identity:
role membership and matching a target to a selected file.
"""

from __future__ import annotations

import collections
import dataclasses
import fnmatch
import os
import pathlib
import re
from typing import TYPE_CHECKING

from . import _helpers

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    import pygit2

_INCLUDE_RE = re.compile(r"^(?P<indent>[ \t]*)\.\.[ \t]+include::(?:[ \t]+(?P<argument>\S.*?))?[ \t]*$", re.IGNORECASE)
_OPTION_RE = re.compile(r"^[ \t]+:(?P<name>[A-Za-z][\w-]*):(?:[ \t]+(?P<value>.*?))?[ \t]*$")
# A literal or code include renders the file as text: it contributes no
# titles, so it is no structural context for the included file.
_TEXT_ONLY_OPTIONS = frozenset({"literal", "code"})
_GIT_METADATA = ".git"


@dataclasses.dataclass(frozen=True, slots=True)
class LexicalInclude:
    """One possible ``include`` site found by a lexical scan.

    ``includer`` is the absolute *lexical* path of the file holding the
    directive, the path it was opened by, and ``line`` its 1-based physical
    line.  ``target`` is the argument resolved from that lexical path without
    following symlinks, as Docutils resolves it: an includer reached through a
    symlink includes relative to the symlink's directory.  Distinct lexical
    paths therefore stay distinct contexts, while ``canonical_includer`` and
    ``canonical_target`` follow symlinks so that role membership and target
    matching see one real file.
    """

    includer: pathlib.Path
    line: int
    indent: int
    argument: str
    target: pathlib.Path
    options: tuple[tuple[str, str], ...] = ()

    @property
    def structural(self) -> bool:
        """Whether the included file's titles can join the includer's."""
        return not any(name in _TEXT_ONLY_OPTIONS for name, _value in self.options)

    @property
    def canonical_includer(self) -> pathlib.Path:
        return self.includer.resolve()

    @property
    def canonical_target(self) -> pathlib.Path:
        return self.target.resolve()


def _within(path: pathlib.Path, root: pathlib.Path) -> bool:
    return path == root or root in path.parents


def discovery_roots(
    selected: Sequence[pathlib.Path],
    *,
    config_root: pathlib.Path | None,
    sphinx_src: pathlib.Path | None,
    cwd: pathlib.Path,
) -> tuple[tuple[pathlib.Path, ...], tuple[pathlib.Path, ...]]:
    """Return ``(roots, uncovered)`` for the selected files (D9d).

    Roots are canonical and ordered by precedence, with any root inside
    another dropped as redundant.  ``uncovered`` lists, canonically, the
    selected files outside every root.
    """
    roots: list[pathlib.Path] = []
    if config_root is not None:
        roots.append(config_root.resolve())
    else:
        working = cwd.resolve()
        for path in selected:
            real = path.resolve()
            repo = _helpers._discover_repo(real.parent)
            if repo is not None and repo.workdir:
                roots.append(pathlib.Path(repo.workdir).resolve())
            elif _within(real, working):
                roots.append(working)
    # An active Sphinx source is a root of its own, with or without a
    # configuration; inside another root it is redundant and dropped below.
    if sphinx_src is not None:
        roots.append(sphinx_src.resolve())
    established: list[pathlib.Path] = []
    for root in roots:
        if any(_within(root, kept) for kept in established):
            continue
        established = [kept for kept in established if not _within(kept, root)]
        established.append(root)
    uncovered = tuple(
        path.resolve() for path in selected if not any(_within(path.resolve(), root) for root in established)
    )
    return tuple(established), uncovered


def _is_ignored(
    repo: pygit2.Repository | None, workdir: pathlib.Path | None, path: pathlib.Path, *, directory: bool
) -> bool:
    if repo is None or workdir is None or not _within(path, workdir) or path == workdir:
        return False
    relative = path.relative_to(workdir).as_posix()
    try:
        relative.encode("utf-8")
    except UnicodeEncodeError:
        # pygit2 asks libgit2 only about a UTF-8-encodable path.  A
        # surrogate-escaped name cannot be proven ignored, so it is scanned:
        # an extra possible include site can only add a refusal.
        return False
    return bool(repo.path_is_ignored(relative) or (directory and repo.path_is_ignored(relative + "/")))


def scan_population(
    roots: Iterable[pathlib.Path],
    *,
    suffixes: Sequence[str] = (".rst",),
) -> tuple[pathlib.Path, ...]:
    """Return the automatic includer scan population under *roots*.

    Paths are lexical, under the canonical roots: a file symlink keeps its own
    path, because an includer resolves its includes from the path it is
    opened by.  It counts only when it resolves to a regular file inside a
    root.
    """
    root_list = [root.resolve() for root in roots]
    found: set[pathlib.Path] = set()
    for root in root_list:
        repo = _helpers._discover_repo(root)
        workdir = pathlib.Path(repo.workdir).resolve() if repo is not None and repo.workdir else None
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            current = pathlib.Path(dirpath)
            dirnames[:] = sorted(
                name
                for name in dirnames
                if name != _GIT_METADATA
                and not (current / name).is_symlink()
                and not _is_ignored(repo, workdir, current / name, directory=True)
            )
            for name in sorted(filenames):
                candidate = current / name
                if name == _GIT_METADATA or candidate.suffix not in suffixes:
                    continue
                if _is_ignored(repo, workdir, candidate, directory=False):
                    continue
                real = candidate.resolve()
                if real.is_file() and any(_within(real, kept) for kept in root_list):
                    found.add(candidate)
    return tuple(sorted(found))


def _indent_width(prefix: str) -> int:
    return len(prefix.expandtabs(8))


def lexical_includes(
    path: pathlib.Path,
    *,
    text: str | None = None,
    sphinx_src: pathlib.Path | None = None,
) -> tuple[LexicalInclude, ...]:
    """Return every possible structural or text ``include`` site in *path*.

    Standard Docutils data includes (``<isonum.txt>``) name no project file
    and are skipped.  An argument may continue on the next indented line.
    """
    includer = pathlib.Path(os.path.abspath(path))
    lines = (path.read_text(encoding="utf-8") if text is None else text).splitlines()
    sites: list[LexicalInclude] = []
    for index, line in enumerate(lines):
        match = _INCLUDE_RE.match(line)
        if match is None:
            continue
        indent = _indent_width(match["indent"])
        argument = match["argument"]
        cursor = index + 1
        if argument is None and cursor < len(lines):
            follow = lines[cursor]
            continued = follow.strip() and _indent_width(follow[: len(follow) - len(follow.lstrip())]) > indent
            if continued and _OPTION_RE.match(follow) is None:
                argument = follow.strip()
                cursor += 1
        if not argument or (argument.startswith("<") and argument.endswith(">")):
            continue
        options: list[tuple[str, str]] = []
        # An option belongs to the directive only inside its indented block:
        # a shallower ":name:" line is outside it, as Docutils parses it.
        while cursor < len(lines):
            option = _OPTION_RE.match(lines[cursor])
            if (
                option is None
                or _indent_width(lines[cursor][: len(lines[cursor]) - len(lines[cursor].lstrip())]) <= indent
            ):
                break
            options.append((option["name"].lower(), option["value"] or ""))
            cursor += 1
        if argument.startswith("/") and sphinx_src is not None:
            target = sphinx_src.resolve() / argument.lstrip("/")
        else:
            target = includer.parent / argument
        sites.append(
            LexicalInclude(
                includer=includer,
                line=index + 1,
                indent=indent,
                argument=argument,
                target=pathlib.Path(os.path.normpath(target)),
                options=tuple(options),
            )
        )
    return tuple(sites)


class IncludeGraph:
    """The reverse, transitive graph of possible structural include sites."""

    def __init__(self, sites: Iterable[LexicalInclude], unreadable: Iterable[pathlib.Path] = ()) -> None:
        self.sites = tuple(sites)
        # A file that could not be read cannot prove it includes nothing;
        # callers that need the graph to be complete can refuse on it.
        self.unreadable = tuple(unreadable)
        self._by_target: dict[pathlib.Path, list[LexicalInclude]] = collections.defaultdict(list)
        for site in self.sites:
            if site.structural:
                self._by_target[site.canonical_target].append(site)

    @classmethod
    def build(
        cls,
        population: Iterable[pathlib.Path],
        *,
        sphinx_src: pathlib.Path | None = None,
    ) -> IncludeGraph:
        """Scan *population* and every structural include target it reaches."""
        queue = collections.deque(pathlib.Path(os.path.abspath(path)) for path in population)
        seen: set[pathlib.Path] = set()
        sites: list[LexicalInclude] = []
        unreadable: list[pathlib.Path] = []
        while queue:
            path = queue.popleft()
            if path in seen:
                continue
            seen.add(path)
            try:
                text = path.read_text(encoding="utf-8")
            except OSError, UnicodeDecodeError:
                unreadable.append(path)
                continue
            for site in lexical_includes(path, text=text, sphinx_src=sphinx_src):
                sites.append(site)
                # Follow the lexical target: its own includes resolve from the
                # path Docutils opens it by.
                if site.structural and site.target not in seen and site.target.is_file():
                    queue.append(site.target)
        return cls(sites, unreadable)

    def includers(self, path: pathlib.Path) -> tuple[LexicalInclude, ...]:
        """Return the direct structural sites that may include *path*."""
        return tuple(self._by_target.get(path.resolve(), ()))

    def transitive_includers(self, path: pathlib.Path) -> tuple[pathlib.Path, ...]:
        """Return the canonical files that may include *path*, nearest first."""
        order: list[pathlib.Path] = []
        queue = collections.deque([path.resolve()])
        visited: set[pathlib.Path] = set()
        while queue:
            current = queue.popleft()
            for site in self._by_target.get(current, ()):
                includer = site.canonical_includer
                if includer not in visited:
                    visited.add(includer)
                    order.append(includer)
                    queue.append(includer)
        return tuple(order)

    def may_be_included(self, path: pathlib.Path) -> bool:
        return bool(self._by_target.get(path.resolve()))


# ---------------------------------------------------------------------------
# Declared include roles (D9a)
# ---------------------------------------------------------------------------

_GLOB_CHARS = re.compile(r"[*?\[]")


@dataclasses.dataclass(frozen=True, slots=True)
class RolePattern:
    """One declared role pattern and where it came from.

    ``role`` is ``"standalone"`` or ``"fragments"``; ``source`` names the
    configuration file or the command-line option; ``base`` is the directory a
    relative pattern starts from: the configuration file's directory, or the
    working directory for a command-line pattern.
    """

    role: str
    pattern: str
    source: str
    base: pathlib.Path


class RolePatternError(Exception):
    """A declared role pattern that cannot be honoured; the message names it."""

    def __init__(self, declared: RolePattern, problem: str) -> None:
        super().__init__(f"{declared.role} pattern {declared.pattern!r} {problem}")
        self.declared = declared


@dataclasses.dataclass(frozen=True, slots=True)
class DeclaredRoles:
    """Canonical role membership plus each pattern's lexical matches."""

    standalone: frozenset[pathlib.Path]
    fragments: frozenset[pathlib.Path]
    matches: tuple[tuple[RolePattern, tuple[pathlib.Path, ...]], ...]


def _role_domain(roots: Sequence[pathlib.Path]) -> tuple[pathlib.Path, ...]:
    """Return the role-pattern domain: every file under the roots, lexically.

    Unlike the automatic scan population it includes Git-ignored files, so an
    explicit declaration can protect an ignored or generated fragment.  It
    still never enters Git metadata or descends through a directory symlink.
    """
    found: set[pathlib.Path] = set()
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            current = pathlib.Path(dirpath)
            dirnames[:] = sorted(
                name for name in dirnames if name != _GIT_METADATA and not (current / name).is_symlink()
            )
            for name in filenames:
                candidate = current / name
                if name != _GIT_METADATA and (candidate.is_symlink() or candidate.is_file()):
                    found.add(candidate)
    return tuple(sorted(found))


def _component_matches(name: str, pattern: str) -> bool:
    """Match one path component; a hidden name needs an explicit leading dot."""
    if name.startswith(".") and not pattern.startswith("."):
        return False
    return fnmatch.fnmatchcase(name, pattern)


def _parts_match(names: Sequence[str], patterns: Sequence[str]) -> bool:
    """Match path components against pattern components.

    ``**`` as a whole component matches zero or more *directory* components,
    never a hidden one and never the final file name, so a pattern that names
    only directories matches no file.
    """
    if not patterns:
        return not names
    head, rest = patterns[0], patterns[1:]
    if head == "**":
        for skip in range(len(names)):
            if skip > 0 and names[skip - 1].startswith("."):
                return False
            if _parts_match(names[skip:], rest):
                return True
        return False
    return bool(names) and _component_matches(names[0], head) and _parts_match(names[1:], rest)


def _absolute_pattern(declared: RolePattern) -> tuple[pathlib.Path, tuple[str, ...]]:
    """Return the pattern's resolved literal prefix and its glob components."""
    raw = declared.pattern
    joined = raw if os.path.isabs(raw) else os.path.join(str(declared.base), raw)
    parts = pathlib.PurePosixPath(os.path.normpath(joined)).parts
    literal = next((index for index, part in enumerate(parts) if _GLOB_CHARS.search(part)), len(parts))
    prefix = pathlib.Path(*parts[:literal])
    # Resolve the literal directories only.  A literal final file name stays
    # lexical, so a symlinked file is judged by where it resolves, not by
    # silently becoming its target.
    prefix = prefix.parent.resolve() / prefix.name if literal == len(parts) else prefix.resolve()
    return prefix, tuple(parts[literal:])


def resolve_roles(declared: Sequence[RolePattern], roots: Sequence[pathlib.Path]) -> DeclaredRoles:
    """Match every declared pattern over the role-pattern domain.

    Raises RolePatternError for a pattern whose literal part lies outside every
    root, one that matches a symlink resolving outside the roots, and one that
    matches no regular file: a typo must never silently disable a declaration
    that protects a document's structure.
    """
    canonical_roots = tuple(root.resolve() for root in roots)
    domain = _role_domain(canonical_roots)
    shown_roots = ", ".join(str(root) for root in canonical_roots) or "none"
    members: dict[str, set[pathlib.Path]] = {"standalone": set(), "fragments": set()}
    matches: list[tuple[RolePattern, tuple[pathlib.Path, ...]]] = []
    for item in declared:
        prefix, globs = _absolute_pattern(item)
        if not any(_within(prefix, root) or _within(root, prefix) for root in canonical_roots):
            raise RolePatternError(item, f"is outside the discovery roots: {shown_roots}")
        pattern_parts = (*prefix.parts, *globs)
        matched: list[pathlib.Path] = []
        for candidate in domain:
            if not _parts_match(candidate.parts, pattern_parts):
                continue
            real = candidate.resolve()
            if not real.is_file():
                continue
            if not any(_within(real, root) for root in canonical_roots):
                raise RolePatternError(
                    item, f"matches {candidate}, a symlink that resolves outside the discovery roots"
                )
            matched.append(candidate)
            members[item.role].add(real)
        if not matched:
            raise RolePatternError(item, f"matches no file under the discovery roots: {shown_roots}")
        matches.append((item, tuple(matched)))
    return DeclaredRoles(
        standalone=frozenset(members["standalone"]),
        fragments=frozenset(members["fragments"]),
        matches=tuple(matches),
    )


# ---------------------------------------------------------------------------
# The conservative fast refusal (rule 7)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class IncludeGuard:
    """Why a selected file's title model cannot be judged alone, parser-free.

    ``kind`` is ``"fragment"`` (a declared fragment), ``"included"`` (a
    possible structural include site names the file), ``"uncovered"`` (no
    discovery root covers it), ``"unreadable"`` (the include graph is
    incomplete) or ``"includes"`` (the file itself includes a fragment that
    may contribute titles).  ``evidence`` is what the message cites: the
    declaring pattern, the first include site, the roots, the unreadable
    files, or the included target and its site's line.
    """

    kind: str
    evidence: str


def _may_contribute_titles(
    target: pathlib.Path,
    *,
    sphinx_src: pathlib.Path | None,
    visiting: set[pathlib.Path],
) -> bool:
    """Whether an included *target* may add titles to its includer.

    Any line that could be a title adornment counts, so a transition or a
    literal ``::`` does too: a parser-free caller may over-refuse but must
    never miss a title.  A target that cannot be read proves nothing, and the
    question follows the target's own structural includes, once per file.
    """
    real = target.resolve()
    if real in visiting:
        return False
    visiting.add(real)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return True
    if any(_helpers._is_adornment(line.rstrip()) for line in text.splitlines()):
        return True
    return any(
        _may_contribute_titles(site.target, sphinx_src=sphinx_src, visiting=visiting)
        for site in lexical_includes(target, text=text, sphinx_src=sphinx_src)
        if site.structural
    )


def _title_contributing_site(path: pathlib.Path, *, sphinx_src: pathlib.Path | None) -> LexicalInclude | None:
    """Return the first structural include in *path* that may add titles."""
    try:
        sites = lexical_includes(path, sphinx_src=sphinx_src)
    except OSError, UnicodeDecodeError:
        return None
    visiting = {path.resolve()}
    for site in sites:
        if site.structural and _may_contribute_titles(site.target, sphinx_src=sphinx_src, visiting=visiting):
            return site
    return None


def fast_include_guards(
    files: Sequence[pathlib.Path],
    *,
    roles: DeclaredRoles | None,
    config_root: pathlib.Path | None,
    sphinx_src: pathlib.Path | None,
    cwd: pathlib.Path,
) -> dict[pathlib.Path, IncludeGuard]:
    """Return, by canonical path, the guard of each selected file that has one.

    A parser-free caller cannot confirm or compose an include context, so any
    of these reasons is enough for it to refuse a change to the file's title
    model.  One reason is reported per file, the most specific first.
    """
    working = cwd.resolve()

    def shown(path: pathlib.Path) -> str:
        absolute = pathlib.Path(os.path.abspath(path))
        return absolute.relative_to(working).as_posix() if absolute.is_relative_to(working) else absolute.as_posix()

    roots, uncovered = discovery_roots(files, config_root=config_root, sphinx_src=sphinx_src, cwd=cwd)
    graph = IncludeGraph.build(scan_population(roots), sphinx_src=sphinx_src)
    declared: dict[pathlib.Path, RolePattern] = {}
    if roles is not None:
        for item, matched in roles.matches:
            if item.role == "fragments":
                for path in matched:
                    declared.setdefault(path.resolve(), item)
    guards: dict[pathlib.Path, IncludeGuard] = {}
    for path in files:
        real = path.resolve()
        sites = graph.includers(real)
        if real in declared:
            item = declared[real]
            guards[real] = IncludeGuard("fragment", f"{item.source} {item.pattern!r}")
        elif sites:
            others = len({site.includer for site in sites}) - 1
            more = f" and {others} more" if others else ""
            guards[real] = IncludeGuard("included", f"{shown(sites[0].includer)}:{sites[0].line}{more}")
        elif real in uncovered:
            guards[real] = IncludeGuard("uncovered", ", ".join(str(root) for root in roots) or "none")
        elif unreadable := [item for item in graph.unreadable if item.resolve() != real]:
            # A file's own read failure is its command's to report, as for
            # any file it cannot read; only another file can hide an include.
            guards[real] = IncludeGuard("unreadable", ", ".join(shown(item) for item in unreadable))
        elif (site := _title_contributing_site(path, sphinx_src=sphinx_src)) is not None:
            # Q1: the includer's own plan ignores the titles its fragments
            # contribute, so changing its styles could restructure the
            # composed document.
            guards[real] = IncludeGuard("includes", f"{shown(site.target)} at line {site.line}")
    return guards
