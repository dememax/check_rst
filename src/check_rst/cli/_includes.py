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

Docutils clips an included file before it parses it, so a clip can create a
directive no physical line starts (``PREFIX.. include::`` after
``:start-after: PREFIX``), or drop the line that made one invalid.  Discovery
therefore scans every *effective input*: a file as one include reads it,
clipped and tab-expanded, recursively.  Each site records the variant it was
found in.

The graph is lexical.  A lexical scan cannot tell an include directive from
include-looking text inside a comment or a literal block, so every site it
records is only *possible*: a parser-free caller must treat it as real and
refuse, while a parsing caller may confirm it.  Site paths resolve like
Docutils, from the lexical path the containing file is opened by, so a file
reached through a symlink is its own include context; under Sphinx a leading
``/`` names the source directory.  With no Sphinx source known, every
structural site with a leading ``/`` is *unresolved*: Docutils reads it from
the filesystem root, and that target is recorded and followed, but Sphinx
reads it from its source directory whether or not that file exists
(``BuildEnvironment.relfn2path``), so the other target stays unknown and the
graph is incomplete.  Canonical paths serve only identity:
role membership and matching a target to a selected file.
"""

from __future__ import annotations

import bisect
import collections
import dataclasses
import errno
import fnmatch
import os
import pathlib
import re
import stat
from typing import TYPE_CHECKING

from . import _helpers

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    import pygit2

_INCLUDE_RE = re.compile(r"^(?P<indent>[ \t]*)\.\.[ \t]+include::(?:[ \t]+(?P<argument>\S.*?))?[ \t]*$", re.IGNORECASE)
_OPTION_RE = re.compile(r"^[ \t]+:(?P<name>[A-Za-z][\w-]*):(?:[ \t]+(?P<value>.*?))?[ \t]*$")
# A literal or code include renders the file as text: it contributes no
# titles, so it is no structural context for the included file.
_TEXT_ONLY_OPTIONS = frozenset({"literal", "code"})
# The include options that shape the text Docutils inserts: its effective
# input variant.  The empty variant is a whole file at the default width 8.
_VARIANT_OPTIONS = ("start-line", "end-line", "start-after", "end-before", "tab-width")
type Variant = tuple[tuple[str, str], ...]
type Selection = list[tuple[str, int, bool]]
_GIT_METADATA = ".git"
# A path that fails with one of these names no file, so it can hide nothing.
_NO_FILE_ERRNOS = frozenset({errno.ENOENT, errno.ENOTDIR, errno.ELOOP})


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
    # The 1-based number of the block's last line: the directive, any
    # continued argument, and its options.  Docutils inserts the included
    # lines after it (CR-43 composition).
    block_end: int = 0
    # The effective input variant of the includer this site was found in.
    variant: Variant = ()

    @property
    def target_variant(self) -> Variant:
        """The variant in which this include reads its target."""
        return tuple((name, value) for name, value in self.options if name in _VARIANT_OPTIONS)

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


def _walk(root: pathlib.Path, blocked: list[pathlib.Path]) -> Iterator[tuple[str, list[str], list[str]]]:
    """``os.walk`` that records, in *blocked*, every directory it cannot list.

    Plain ``os.walk`` skips such a directory silently, and with it every
    includer inside: a fragment would then look unincluded.
    """

    def record(error: OSError) -> None:
        blocked.append(pathlib.Path(error.filename))

    return os.walk(root, followlinks=False, onerror=record)


def _stat_or_block(path: pathlib.Path, blocked: list[pathlib.Path], *, follow: bool) -> os.stat_result | None:
    """Stat *path*, recording it in *blocked* when it exists but cannot be
    reached, as in a directory that can be listed but not searched."""
    try:
        return path.stat() if follow else path.lstat()
    except OSError as error:
        if error.errno not in _NO_FILE_ERRNOS:
            blocked.append(path)
        return None


def _scan(
    roots: Iterable[pathlib.Path], suffixes: Sequence[str]
) -> tuple[tuple[pathlib.Path, ...], tuple[pathlib.Path, ...]]:
    """Return the scan population and the paths that blocked the scan."""
    root_list = [root.resolve() for root in roots]
    found: set[pathlib.Path] = set()
    blocked: list[pathlib.Path] = []
    for root in root_list:
        repo = _helpers._discover_repo(root)
        workdir = pathlib.Path(repo.workdir).resolve() if repo is not None and repo.workdir else None
        for dirpath, dirnames, filenames in _walk(root, blocked):
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
                status = _stat_or_block(candidate, blocked, follow=True)
                if status is None or not stat.S_ISREG(status.st_mode):
                    continue
                if any(_within(candidate.resolve(), kept) for kept in root_list):
                    found.add(candidate)
    return tuple(sorted(found)), tuple(sorted(set(blocked)))


def scan_population(
    roots: Iterable[pathlib.Path],
    *,
    suffixes: Sequence[str] = (".rst",),
) -> tuple[pathlib.Path, ...]:
    """Return the automatic includer scan population under *roots*.

    Paths are lexical, under the canonical roots: a file symlink keeps its own
    path, because an includer resolves its includes from the path it is
    opened by.  It counts only when it resolves to a regular file inside a
    root.  ``IncludeGraph.scan`` also reports what the scan could not read.
    """
    return _scan(roots, suffixes)[0]


# What str.splitlines() breaks a line at, and Phase 0's physical line breaks:
# the same without VT and FF, which Phase 0 and Docutils' string2lines both
# turn into spaces.
_SPLITLINES = re.compile("\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]")
_PHYSICAL_BREAKS = re.compile("\r\n|[\n\r\x1c\x1d\x1e\x85\u2028\u2029]")
_CONTROL_WHITESPACE = re.compile("[\v\f]")


def _spans(text: str, breaks: re.Pattern[str]) -> list[tuple[int, int]]:
    """Return the (start, end) offset of each line ``str.splitlines()`` yields,
    breaking only at *breaks*."""
    spans: list[tuple[int, int]] = []
    position = 0
    for match in breaks.finditer(text):
        spans.append((position, match.start()))
        position = match.end()
    if position < len(text):
        spans.append((position, len(text)))
    return spans


def docutils_text(raw: str) -> str:
    """Return decoded text as Docutils' text-mode FileInput reads it, which an
    include's default or Sphinx's encoding selects: universal newlines, and
    no byte-order mark."""
    text = raw.removeprefix("\ufeff")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def tab_width(variant: Variant) -> int | None:
    """The width Docutils expands this variant's tabs to; None if invalid."""
    try:
        return int(dict(variant).get("tab-width", "8"))
    except ValueError:
        return None


def effective_input(text: str, variant: Variant) -> Selection | None:
    """Return the lines Docutils parses from *text* read in *variant*.

    Each entry is a parsed line, its 0-based physical line, and whether it is
    only part of that line.  Docutils' own order, which no single
    normalization reproduces:
    1. a line clip counts lines with a raw ``splitlines()``, which breaks at
       a vertical tab or a form feed, and joins them with newlines;
    2. ``:start-after:`` and ``:end-before:`` search the result;
    3. ``string2lines`` turns VT and FF into spaces, splits, expands tabs at
       the variant's width, and strips trailing whitespace.
    Physical lines are Phase 0's, which keep VT and FF inside a line, as step
    3 does.  Character offsets map each parsed line back to one.  None means
    an option is malformed or a text clip matches nothing, which Docutils
    reports as an error; an empty text clip is refused too, because its
    meaning differs between Docutils versions.
    """
    options = dict(variant)
    width = tab_width(variant)
    try:
        start = int(options["start-line"]) if "start-line" in options else None
        end = int(options["end-line"]) if "end-line" in options else None
    except ValueError:
        return None
    if width is None:
        return None
    clipped, offsets = text, list(range(len(text)))
    if start or end is not None:  # Docutils' own test: a start line of 0 alone clips nothing
        pieces = _spans(text, _SPLITLINES)[start:end]
        parts: list[str] = []
        offsets = []
        for number, (piece_start, piece_end) in enumerate(pieces):
            if number:
                parts.append("\n")
                offsets.append(pieces[number - 1][1])
            parts.append(text[piece_start:piece_end])
            offsets.extend(range(piece_start, piece_end))
        clipped = "".join(parts)
    after = options.get("start-after")
    if after is not None:
        match = clipped.find(after) if after else -1
        if match < 0:
            return None
        clipped, offsets = clipped[match + len(after) :], offsets[match + len(after) :]
    before = options.get("end-before")
    if before is not None:
        match = clipped.find(before) if before else -1
        if match < 0:
            return None
        clipped, offsets = clipped[:match], offsets[:match]
    converted = _CONTROL_WHITESPACE.sub(" ", clipped)
    physical = _spans(text, _PHYSICAL_BREAKS)
    starts = [line_start for line_start, _line_end in physical]
    selection: Selection = []
    for line_start, line_end in _spans(converted, _SPLITLINES):
        if line_start < line_end:
            first, last = offsets[line_start], offsets[line_end - 1] + 1
        else:  # an empty line: its offset is that of the break ending it
            first = offsets[line_start] if line_start < len(offsets) else (offsets[-1] + 1 if offsets else 0)
            last = first
        index = max(bisect.bisect_right(starts, first) - 1, 0)
        span_start, span_end = physical[index] if physical else (0, 0)
        whole = first <= span_start and not text[last:span_end].strip()
        selection.append((converted[line_start:line_end].expandtabs(width).rstrip(), index, not whole))
    return selection


def variant_sites(
    path: pathlib.Path, text: str, variant: Variant, *, sphinx_src: pathlib.Path | None = None
) -> tuple[LexicalInclude, ...]:
    """Return the sites in *path*'s effective input *variant*, read from its
    Docutils *text*, with their lines and blocks mapped to physical lines."""
    selection = effective_input(text, variant)
    if selection is None:
        return ()
    return tuple(
        dataclasses.replace(
            site,
            line=selection[site.line - 1][1] + 1,
            block_end=selection[site.block_end - 1][1] + 1,
            variant=variant,
        )
        for site in lexical_includes(
            path, text="\n".join(line for line, _index, _cut in selection), sphinx_src=sphinx_src
        )
    )


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
                block_end=cursor,
            )
        )
    return tuple(sites)


class IncludeGraph:
    """The reverse, transitive graph of possible structural include sites."""

    def __init__(
        self,
        sites: Iterable[LexicalInclude],
        unreadable: Iterable[pathlib.Path] = (),
        unresolved: Iterable[LexicalInclude] = (),
    ) -> None:
        self.sites = tuple(sites)
        # A file that could not be read cannot prove it includes nothing, and
        # an unresolved site cannot say what it includes; callers that need
        # the graph to be complete can refuse on either.
        self.unreadable = tuple(unreadable)
        self.unresolved = tuple(unresolved)
        self._by_target: dict[pathlib.Path, list[LexicalInclude]] = collections.defaultdict(list)
        for site in self.sites:
            if site.structural:
                self._by_target[site.canonical_target].append(site)

    @classmethod
    def scan(
        cls,
        roots: Iterable[pathlib.Path],
        *,
        sphinx_src: pathlib.Path | None = None,
        suffixes: Sequence[str] = (".rst",),
    ) -> IncludeGraph:
        """Build the graph over the scan population of *roots*.

        A directory the scan cannot list, or a file it cannot reach, is
        unreadable like a file it cannot decode: it may hold any include.
        """
        population, blocked = _scan(roots, suffixes)
        return cls.build(population, sphinx_src=sphinx_src, unreadable=blocked)

    @classmethod
    def build(
        cls,
        population: Iterable[pathlib.Path],
        *,
        sphinx_src: pathlib.Path | None = None,
        unreadable: Iterable[pathlib.Path] = (),
    ) -> IncludeGraph:
        """Scan *population* and every structural include target it reaches.

        Each population file is scanned whole; each target is scanned in the
        effective input its include reads, so a site a clip creates or makes
        valid is found.  *unreadable* seeds the paths already known to hide
        possible sites.
        """
        empty: Variant = ()
        queue = collections.deque((pathlib.Path(os.path.abspath(path)), empty) for path in population)
        seen: set[tuple[pathlib.Path, Variant]] = set()
        texts: dict[pathlib.Path, str | None] = {}
        sites: list[LexicalInclude] = []
        unreadable = list(unreadable)
        unresolved: list[LexicalInclude] = []
        while queue:
            path, variant = queue.popleft()
            if (path, variant) in seen:
                continue
            seen.add((path, variant))
            if path not in texts:
                try:
                    texts[path] = docutils_text(path.read_bytes().decode("utf-8"))
                except OSError, UnicodeDecodeError:
                    texts[path] = None
                    unreadable.append(path)
            text = texts[path]
            if text is None:
                continue
            for site in variant_sites(path, text, variant, sphinx_src=sphinx_src):
                sites.append(site)
                # The filesystem target is Docutils' reading only; Sphinx's
                # names a file under a source directory nobody configured.
                is_unresolved = site.structural and sphinx_src is None and site.argument.startswith("/")
                if is_unresolved and all(
                    (other.includer, other.line) != (site.includer, site.line) for other in unresolved
                ):
                    unresolved.append(site)
                # Follow the lexical target in the variant its include reads:
                # its own includes resolve from the path Docutils opens it by.
                if site.structural and site.target.is_file():
                    queue.append((site.target, site.target_variant))
        return cls(sites, unreadable, unresolved)

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

    def root_contexts(
        self, path: pathlib.Path, *, standalone: frozenset[pathlib.Path] = frozenset()
    ) -> tuple[tuple[pathlib.Path, ...], LexicalInclude | None]:
        """Return the lexical root documents that compose *path*, and a site
        on an include cycle among its includers, if any.

        A root is a transitive includer that nothing includes, or one declared
        standalone.  Each lexical path of a root is its own context, because
        its includes resolve from the path it is opened by.  On a cycle no
        document is provably the root, so the caller must treat the contexts
        as unavailable.
        """
        real = path.resolve()
        roots: list[pathlib.Path] = []
        visited: set[pathlib.Path] = {real}
        queue = collections.deque([real])
        while queue:
            current = queue.popleft()
            for site in self._by_target.get(current, ()):
                includer = site.canonical_includer
                # A root is recorded per lexical path, before the canonical
                # walk below skips an includer it already expanded: two
                # aliases of one root are two contexts.
                is_root = not self._by_target.get(includer) or includer in standalone
                if is_root and site.includer not in roots:
                    roots.append(site.includer)
                if includer in visited:
                    if self._reaches(includer, current):
                        # Name the file's own inclusion when it is on the
                        # cycle: that is the context the reader looks for.
                        own = next(
                            (
                                edge
                                for edge in self._by_target.get(real, ())
                                if self._reaches(edge.canonical_includer, real)
                            ),
                            site,
                        )
                        return (), own
                    continue
                visited.add(includer)
                if self._by_target.get(includer):
                    queue.append(includer)
        return tuple(roots), None

    def _reaches(self, start: pathlib.Path, goal: pathlib.Path) -> bool:
        """Whether *goal* includes *start*, directly or transitively: then the
        edge from *start* into *goal* closes a cycle."""
        seen: set[pathlib.Path] = set()
        queue = collections.deque([start])
        while queue:
            current = queue.popleft()
            if current == goal:
                return True
            for site in self._by_target.get(current, ()):
                if site.canonical_includer not in seen:
                    seen.add(site.canonical_includer)
                    queue.append(site.canonical_includer)
        return False


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


def _role_domain(roots: Sequence[pathlib.Path]) -> tuple[tuple[pathlib.Path, ...], tuple[pathlib.Path, ...]]:
    """Return the role-pattern domain, every file under the roots lexically,
    and the paths that could not be read.

    Unlike the automatic scan population it includes Git-ignored files, so an
    explicit declaration can protect an ignored or generated fragment.  It
    still never enters Git metadata or descends through a directory symlink.
    """
    found: set[pathlib.Path] = set()
    blocked: list[pathlib.Path] = []
    for root in roots:
        for dirpath, dirnames, filenames in _walk(root, blocked):
            current = pathlib.Path(dirpath)
            dirnames[:] = sorted(
                name for name in dirnames if name != _GIT_METADATA and not (current / name).is_symlink()
            )
            for name in filenames:
                candidate = current / name
                if name == _GIT_METADATA:
                    continue
                status = _stat_or_block(candidate, blocked, follow=False)
                if status is not None and (stat.S_ISLNK(status.st_mode) or stat.S_ISREG(status.st_mode)):
                    found.add(candidate)
    return tuple(sorted(found)), tuple(sorted(set(blocked)))


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


def _may_match_below(names: Sequence[str], patterns: Sequence[str]) -> bool:
    """Whether some file below the directory *names* may match *patterns*,
    with ``_parts_match``'s rules."""
    if not names:
        return bool(patterns)
    if not patterns:
        return False
    head, rest = patterns[0], patterns[1:]
    if head == "**":
        if _may_match_below(names, rest):
            return True
        return not names[0].startswith(".") and _may_match_below(names[1:], patterns)
    return _component_matches(names[0], head) and _may_match_below(names[1:], rest)


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
    domain, blocked = _role_domain(canonical_roots)
    shown_roots = ", ".join(str(root) for root in canonical_roots) or "none"
    members: dict[str, set[pathlib.Path]] = {"standalone": set(), "fragments": set()}
    matches: list[tuple[RolePattern, tuple[pathlib.Path, ...]]] = []
    for item in declared:
        prefix, globs = _absolute_pattern(item)
        if not any(_within(prefix, root) or _within(root, prefix) for root in canonical_roots):
            raise RolePatternError(item, f"is outside the discovery roots: {shown_roots}")
        pattern_parts = (*prefix.parts, *globs)
        # A partial match set would silently drop part of the declaration's
        # protection, so a path it may reach but cannot read fails it.
        for path in blocked:
            if _parts_match(path.parts, pattern_parts) or _may_match_below(path.parts, pattern_parts):
                raise RolePatternError(item, f"may match a file in {path}, which cannot be read")
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
    incomplete), ``"unresolved"`` (a rooted include has an unknown Sphinx
    reading) or
    ``"includes"`` (the file itself has a possible structural include).  ``evidence`` is what the message cites: the
    declaring pattern, the first include site, the roots, the unreadable
    files, or the included target and its site's line.
    """

    kind: str
    evidence: str
    # Why an include cannot be composed, for the "uncomposable" kind.
    reason: str = ""


def _first_structural_site(path: pathlib.Path, *, sphinx_src: pathlib.Path | None) -> LexicalInclude | None:
    """Return the first possible structural include site in *path*.

    Only a literal or code include is lexically proven to add no structure.
    Any other may add sections that no adornment line in its source shows:
    through another ``:parser:``, a Sphinx ``include-read`` or
    ``source-read`` handler, or an extension directive.
    """
    try:
        sites = lexical_includes(path, sphinx_src=sphinx_src)
    except OSError, UnicodeDecodeError:
        return None
    return next((site for site in sites if site.structural), None)


class IncludeUniverse:
    """The discovery roots, the include graph and the declared roles of one
    run, shared by fast mode's guards and full mode's composed planning."""

    def __init__(
        self,
        files: Sequence[pathlib.Path],
        *,
        roles: DeclaredRoles | None,
        config_root: pathlib.Path | None,
        sphinx_src: pathlib.Path | None,
        cwd: pathlib.Path,
        suffixes: Sequence[str] = (".rst",),
    ) -> None:
        self.working = cwd.resolve()
        self.sphinx_src = sphinx_src
        self.roots, self.uncovered = discovery_roots(files, config_root=config_root, sphinx_src=sphinx_src, cwd=cwd)
        self.graph = IncludeGraph.scan(self.roots, sphinx_src=sphinx_src, suffixes=suffixes)
        self.declared: dict[pathlib.Path, RolePattern] = {}
        self.standalone: frozenset[pathlib.Path] = roles.standalone if roles is not None else frozenset()
        if roles is not None:
            for item, matched in roles.matches:
                if item.role == "fragments":
                    for path in matched:
                        self.declared.setdefault(path.resolve(), item)

    def shown(self, path: pathlib.Path) -> str:
        absolute = pathlib.Path(os.path.abspath(path))
        if absolute.is_relative_to(self.working):
            return absolute.relative_to(self.working).as_posix()
        return absolute.as_posix()

    def unavailable_guard(self, path: pathlib.Path) -> IncludeGuard | None:
        """Return why *path* has an include context no parse can compose:
        a declared fragment, no root covering it, or an incomplete graph."""
        real = path.resolve()
        if real in self.declared:
            item = self.declared[real]
            return IncludeGuard("fragment", f"{item.source} {item.pattern!r}")
        if real in self.uncovered:
            return IncludeGuard("uncovered", ", ".join(str(root) for root in self.roots) or "none")
        if unreadable := [item for item in self.graph.unreadable if item.resolve() != real]:
            # A file's own read failure is its command's to report, as for
            # any file it cannot read; only another file can hide an include.
            return IncludeGuard("unreadable", ", ".join(self.shown(item) for item in unreadable))
        if unresolved := [site for site in self.graph.unresolved if site.canonical_includer != real]:
            # As for a read failure, a file's own site cannot hide its includer.
            first = unresolved[0]
            more = f" (and {len(unresolved) - 1} more)" if len(unresolved) > 1 else ""
            return IncludeGuard(
                "unresolved", f"{self.shown(first.includer)}:{first.line} includes {first.argument!r}{more}"
            )
        return None

    def fast_guard(self, path: pathlib.Path) -> IncludeGuard | None:
        """Return why a parser-free caller cannot judge *path* alone.

        Any of these reasons is enough for it to refuse a change to the file's
        title model.  One reason is reported, the most specific first.
        """
        real = path.resolve()
        guard = self.unavailable_guard(path)
        if guard is not None and guard.kind == "fragment":
            return guard
        if sites := self.graph.includers(real):
            others = len({site.includer for site in sites}) - 1
            more = f" and {others} more" if others else ""
            return IncludeGuard("included", f"{self.shown(sites[0].includer)}:{sites[0].line}{more}")
        if guard is not None:
            return guard
        if (site := _first_structural_site(path, sphinx_src=self.sphinx_src)) is not None:
            # Q1: the includer's own plan ignores whatever its fragments add,
            # so changing its styles could restructure the composed document.
            return IncludeGuard("includes", f"{self.shown(site.target)} at line {site.line}")
        return None


def fast_include_guards(
    files: Sequence[pathlib.Path],
    *,
    roles: DeclaredRoles | None,
    config_root: pathlib.Path | None,
    sphinx_src: pathlib.Path | None,
    cwd: pathlib.Path,
) -> dict[pathlib.Path, IncludeGuard]:
    """Return, by canonical path, the fast-mode guard of each selected file
    that has one."""
    universe = IncludeUniverse(files, roles=roles, config_root=config_root, sphinx_src=sphinx_src, cwd=cwd)
    guards: dict[pathlib.Path, IncludeGuard] = {}
    for path in files:
        if (guard := universe.fast_guard(path)) is not None:
            guards[path.resolve()] = guard
    return guards
