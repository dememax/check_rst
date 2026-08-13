# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Generic text/git/doctree utilities used across check_rst.cli — check_rst project

from __future__ import annotations

import collections
import contextlib
import os
import pathlib
import re
import stat
import subprocess
import tempfile
import unicodedata
from typing import TYPE_CHECKING, NoReturn, cast

import docutils.frontend
import docutils.nodes
import docutils.parsers.rst
import docutils.parsers.rst.states
import docutils.utils
import pygit2

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


from ._types import (
    _NON_PROSE_NODE_TYPES,
    BlockCorrection,
    Finding,
    FixCounts,
    Severity,
    TitleBlock,
    UnderlineOnlyCandidate,
)

# Resolved at startup from the invocation directory — project-agnostic.
PROJECT_ROOT = pathlib.Path.cwd()


# Cheap instrumentation counters (Max, 2026-07-19): a plain increment at the
# top of each expensive or suspicion-prone entry point.  Zero measurable
# production cost; in tests they make the execution stack DETERMINISTIC —
# assert or inspect how many times something ran instead of guessing from
# wall-clock or sprinkling debug output.
CALL_COUNTS: collections.Counter[str] = collections.Counter()


_JSON_SCHEMA_VERSION = 1


def _atomic_write_bytes(path: pathlib.Path, data: bytes) -> None:
    """Replace *path* with *data* without exposing a partial destination.

    The temporary file lives beside the destination so ``os.replace`` stays
    on one filesystem.  Resolve a symlink first: the historical in-place
    writers updated its target, and an atomic rename over the link itself
    would silently change that contract.  Ownership and permission bits are
    copied before the candidate is flushed and made visible.  A multiply
    linked target is refused: replacing one directory entry cannot update the
    shared inode and would silently split the other names onto stale content.
    """
    destination = path.resolve(strict=True) if path.is_symlink() else path
    metadata = destination.stat()
    if metadata.st_nlink != 1:
        raise OSError(f"{destination} has {metadata.st_nlink} hard links; refusing atomic replacement")
    fd, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.check_rst-",
        suffix=".tmp",
    )
    temporary = pathlib.Path(temporary_name)
    descriptor_open = True
    try:
        # chown can clear set-id mode bits, so restore ownership first and
        # apply the complete original mode afterward.
        os.fchown(fd, metadata.st_uid, metadata.st_gid)
        os.fchmod(fd, stat.S_IMODE(metadata.st_mode))
        with os.fdopen(fd, "wb") as stream:
            descriptor_open = False
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        current = destination.stat()
        if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise OSError(f"{destination} changed identity during atomic replacement")
        if current.st_nlink != 1:
            raise OSError(f"{destination} has {current.st_nlink} hard links; refusing atomic replacement")
        os.replace(temporary, destination)
    except BaseException:
        if descriptor_open:
            os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise


def _freeze_node_attribute(value: object) -> object:
    """Convert docutils attribute values into stable comparison primitives."""
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze_node_attribute(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_node_attribute(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted((_freeze_node_attribute(item) for item in value), key=repr))
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return repr(value)


# Every character docutils itself recognizes as a valid title/adornment
# character, derived directly from docutils' own definition — not hardcoded
# — so it stays correct if a future docutils version ever changes it.
_NONALPHANUM_7BIT_PATTERN = docutils.parsers.rst.states.Body.pats["nonalphanum7bit"]


VALID_ADORNMENT_CHARS = "".join(chr(c) for c in range(33, 127) if re.match(_NONALPHANUM_7BIT_PATTERN, chr(c)))


# The 6 characters the tool's opinionated default policy prefers, in order.
# Used only to decide whether check_hierarchy's WARNING fires for a
# character that — while now fully part of HIERARCHY below — isn't among
# these traditionally-preferred ones.
PREFERRED_HIERARCHY = '#*=-^"'


# Full canonical hierarchy: the preferred 6 first (unchanged order), then
# every other valid RST adornment character appended in docutils' own
# natural order. Docutils itself has no universal cross-document order at
# all (a document's own first-appearance order is all it requires) and
# there's no principled way to rank the remaining ~26 characters relative
# to each other or to the preferred 6 — but giving every valid character
# SOME defined, deterministic rank (even an arbitrary one past the first 6)
# lets check_hierarchy's ERROR-level "skipped level"/"wrong order" checks,
# and --fix's remap, apply uniformly to any valid adornment character, not
# only the preferred 6.
HIERARCHY = PREFERRED_HIERARCHY + "".join(c for c in VALID_ADORNMENT_CHARS if c not in PREFERRED_HIERARCHY)


# Minimum length for an adornment line glued directly to text to be treated
# as an underline-only title candidate (not compared against the title's
# length — see check_adornments). Below this it's too easy to confuse with
# a stray one-or-two-char mark that isn't a title attempt at all.
MIN_UNDERLINE_ONLY_LEN = 4


def _is_adornment(line: str) -> bool:
    """Return True if *line* consists entirely of one repeated adornment character.

    Exactly ``..`` is excluded: docutils' explicit-markup pattern
    (``\\.\\.( +|$)``) takes precedence over the title-line pattern, so a
    lone ``..`` is always a comment marker to docutils, never an over/
    underline.  Treating it as an adornment made two ``..`` comment lines
    around an indented note match the over/title/under shape — and --fix
    rewrote the comment into a dotted section title (confirmed by direct
    testing, 2026-07-18).  Three or more dots don't match the comment
    pattern and stay valid adornments.
    """
    if line == "..":
        return False
    return bool(line) and line[0] in VALID_ADORNMENT_CHARS and len(set(line)) == 1


def _discover_repo(root: pathlib.Path) -> pygit2.Repository | None:
    """Return the Git repository containing *root*, or None outside any Git
    repository entirely.

    pygit2.discover_repository returns None cleanly here — no locale-
    dependent stderr text to misparse, unlike the ``git rev-parse`` subprocess
    call this replaced, whose "not a git repository" detection previously
    substring-matched Git's own human-readable (and therefore locale-
    dependent) diagnostic.
    """
    try:
        discovered = pygit2.discover_repository(str(root))
        return pygit2.Repository(discovered) if discovered is not None else None
    except pygit2.GitError as exc:
        _git_failure("repository discovery", exc)


def _git_failure(action: str, exc: Exception) -> NoReturn:
    """Exit with Git's real diagnostic instead of mislabeling every failure."""
    print(f"check_rst: git {action} failed: {exc}")
    raise SystemExit(1)


def _repo_for_root(project_root: pathlib.Path | None) -> pygit2.Repository:
    """Return the Git repository for the selected project root, or exit with
    a clean diagnostic.

    Exits with a clean one-line diagnostic when the selected root is not
    inside a git repository — including a bare repository, which has no
    worktree for check_rst to operate on: bare invocation's contract is git
    auto-detection, so a git-less directory is a usage error, same fail-
    loudly precedent as a --sphinx-src without conf.py, never a raw
    traceback (which is what this printed before, found by direct probing
    2026-07-18).
    """
    root = PROJECT_ROOT if project_root is None else project_root
    repo = _discover_repo(root)
    if repo is None or repo.workdir is None:
        print(
            "check_rst: not a git repository — bare invocation auto-detects "
            "changed files via git; name files explicitly or use --recursive"
        )
        raise SystemExit(1)
    return repo


def _status_paths_with_surrogateescape(worktree_root: pathlib.Path) -> list[str]:
    """Return status paths when pygit2 cannot decode a Git filename.

    Git paths are byte strings. Its NUL-delimited porcelain format preserves
    those bytes exactly, so os.fsdecode can apply the platform's
    surrogateescape policy without requiring a HEAD revision.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=worktree_root,
            check=False,
            capture_output=True,
            # Porcelain stdout is locale-stable, but Git's failure diagnostics
            # are translated. Preserve PATH and Git-specific environment while
            # keeping this exceptional CLI boundary deterministic.
            env=os.environ | {"LC_ALL": "C"},
        )
    except OSError as exc:
        _git_failure("status", exc)
    if result.returncode != 0:
        detail = os.fsdecode(result.stderr).strip() or os.fsdecode(result.stdout).strip() or "unknown Git error"
        _git_failure("status", RuntimeError(detail))

    paths: list[str] = []
    entries = result.stdout.split(b"\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        status = entry[:2]
        paths.append(os.fsdecode(entry[3:]))
        if b"R" in status or b"C" in status:
            index += 1  # consume the separate original-path field
    return paths


def _git_worktree_root(project_root: pathlib.Path | None = None) -> pathlib.Path:
    """Return the repository worktree root for the selected project root."""
    repo = _repo_for_root(project_root)
    assert repo.workdir is not None  # _repo_for_root already exited otherwise
    return pathlib.Path(repo.workdir)


def _indented_extent(
    lines: list[str],
    start: int,
    *,
    allow_same_indent: bool = False,
) -> int:
    """Return the final content line in the block anchored at *start*.

    Directive bodies and list-item continuations must be deeper than their
    marker's source column.  A block quote is different: all its source lines
    share the quote's already-indented column, so its caller opts into equal
    indentation.  Blank separators extend a candidate only when later content
    still satisfies that relative indentation predicate.
    """
    if not 1 <= start <= len(lines):
        return start

    def indent_width(line: str) -> int:
        content = line.lstrip(" \t")
        leading = line[: len(line) - len(content)]
        return len(leading.expandtabs(8))

    anchor = lines[start - 1]
    anchor_indent = indent_width(anchor)
    end = start
    i = start  # 0-based index of the line AFTER start
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        indent = indent_width(line)
        if indent > anchor_indent or (allow_same_indent and indent == anchor_indent):
            end = i + 1
            i += 1
            continue
        break
    return end


def _changed_rst_files(
    project_root: pathlib.Path | None = None,
) -> list[pathlib.Path]:
    """Return modified + untracked *.rst files from the selected Git project.

    Exits with a clean one-line diagnostic when PROJECT_ROOT is not inside
    a git repository: bare invocation's contract is git auto-detection, so
    a git-less directory is a usage error — same fail-loudly precedent as
    a --sphinx-src without conf.py, never a CalledProcessError traceback
    (which is what this printed before, found by direct probing 2026-07-18).
    """
    repo = _repo_for_root(project_root)
    assert repo.workdir is not None  # _repo_for_root already exited otherwise
    worktree_root = pathlib.Path(repo.workdir)
    try:
        status: Iterable[str] = repo.status(untracked_files="all")
    except UnicodeDecodeError:
        # Git filenames are byte strings; status()'s str-keyed dict cannot
        # represent one that isn't valid UTF-8. Use Git's byte-oriented,
        # machine-readable status only for this compatibility path; unlike a
        # diff fallback, it works equally before and after the first commit.
        status = _status_paths_with_surrogateescape(worktree_root)
    except pygit2.GitError as exc:
        _git_failure("status", exc)
    files: list[pathlib.Path] = []
    # A rename reports as a separate delete (the dead original path, dropped
    # below by is_file() since nothing is there anymore) plus add (the live
    # new path) — no special-casing needed, unlike the single combined "R"
    # porcelain entry the previous subprocess-based parser had to skip the
    # original-path field of.
    for path in status:
        candidate = worktree_root / path
        if candidate.suffix == ".rst" and candidate.is_file():
            files.append(candidate)
    return files


def _unmerged_files(files: list[pathlib.Path]) -> list[pathlib.Path]:
    """Return selected files with unresolved entries in Git's index.

    Explicit files can be checked outside Git, so a non-repository working
    directory simply has no authoritative unmerged state.  Once a worktree
    is found, however, its conflicted index entries are definitive and avoid
    both false positives from documented marker examples and false negatives
    from custom conflict-marker widths.
    """
    repos: dict[pathlib.Path, pygit2.Repository] = {}
    buckets: dict[pathlib.Path, list[pathlib.Path]] = {}

    for path in files:
        resolved = path.resolve()
        # Containment does not establish repository ownership: a repository
        # may be nested inside another one.  Discover from the file itself,
        # then cache by the authoritative nearest worktree returned by Git.
        candidate_repo = _discover_repo(resolved.parent)
        if candidate_repo is None or candidate_repo.workdir is None:
            continue
        worktree_root = pathlib.Path(candidate_repo.workdir).resolve()
        repos.setdefault(worktree_root, candidate_repo)
        buckets.setdefault(worktree_root, [])
        buckets[worktree_root].append(resolved)

    unmerged: set[pathlib.Path] = set()
    for worktree_root, candidates in buckets.items():
        if not candidates:
            continue
        candidate_set = set(candidates)
        try:
            conflicts = repos[worktree_root].index.conflicts
        except pygit2.GitError as exc:
            _git_failure("ls-files --unmerged", exc)
        if conflicts is None:
            continue
        for ancestor, ours, theirs in conflicts:
            entry = ancestor or ours or theirs
            if entry is None:
                continue
            resolved_conflict = (worktree_root / entry.path).resolve()
            if resolved_conflict in candidate_set:
                unmerged.add(resolved_conflict)
    return [path for path in files if path.resolve() in unmerged]


# git diff -U0 HEAD's default semantics (staged AND unstaged changes to
# tracked paths, never purely untracked ones) don't map onto a single
# pygit2 flag combination: plain Tree.diff_to_workdir() silently drops
# staged-new files (confirmed against real `git diff -U0 HEAD` output), and
# adding INCLUDE_UNTRACKED alone reports them with no hunk content. This
# combination reports both staged-new and purely-untracked paths with full
# hunks — _changed_line_ranges filters the latter back out via repo.index
# membership, which is the same distinction git itself draws.
_DIFF_SINCE_HEAD_FLAGS = (
    pygit2.enums.DiffOption.INCLUDE_UNTRACKED
    | pygit2.enums.DiffOption.RECURSE_UNTRACKED_DIRS
    | pygit2.enums.DiffOption.SHOW_UNTRACKED_CONTENT
)


def _changed_line_ranges(path: pathlib.Path, project_root: pathlib.Path | None = None) -> list[tuple[int, int]] | None:
    """Return 1-based (start, end) line ranges changed since HEAD, or None.

    None means "check the whole file": the file is untracked or git is
    unavailable.  An empty list means the file is tracked but unchanged.
    """
    root = PROJECT_ROOT if project_root is None else project_root
    repo = _discover_repo(root)
    if repo is None or repo.workdir is None:
        return None  # tolerated: no diffable state → check the whole file
    if repo.head_is_unborn:
        return None  # no HEAD tree exists yet → check the whole file
    worktree_root = pathlib.Path(repo.workdir).resolve()
    try:
        relative = path.resolve().relative_to(worktree_root)
    except ValueError:
        return None  # outside the repository → not diffable, check whole file
    # Git paths are bytes.  os.fsencode reverses Python's surrogateescape
    # representation on Unix, while pygit2's text path APIs reject those
    # surrogates and DiffFile.path tries strict UTF-8 decoding.
    relative_raw = os.fsencode(relative)
    ranges: list[tuple[int, int]] = []
    try:
        if relative_raw not in repo.index:
            return None  # untracked → not diffable, check whole file
        diff = repo.diff("HEAD", None, context_lines=0, flags=_DIFF_SINCE_HEAD_FLAGS)
        # Diff is lazy: repo.diff() itself is cheap, and libgit2 only walks
        # the worktree once patches are actually consumed below.  A file
        # changing mid-iteration (TOCTOU) therefore raises GitError from
        # this loop, not from the call above — both must fail the same way.
        for patch in diff:
            if patch is None or patch.delta.new_file.raw_path != relative_raw:
                continue
            for hunk in patch.hunks:
                start, count = hunk.new_start, hunk.new_lines
                ranges.append((start, start + count - 1) if count > 0 else (start, start + 1))
            break
    except pygit2.GitError as exc:
        # All legitimate no-diff states were classified above.  A repository
        # failure here cannot safely mean "whole file": in fix mode that would
        # silently widen selective Git scope and authorize unrelated edits.
        raise RuntimeError(f"git diff failed: {exc}") from exc
    return ranges


def _in_scope(ranges: list[tuple[int, int]] | None, first: int, last: int) -> bool:
    """Return True if any line in [first, last] overlaps the changed ranges."""
    if ranges is None:
        return True
    return any(s <= last and first <= e for s, e in ranges)


# Separator characters str.splitlines() treats as line breaks but git does
# not.  FS/GS/RS (\x1c-\x1e), NEL (\x85), LS (U+2028), PS (U+2029) are real
# line separators — normalized to \n.  VT/FF are whitespace — normalized to
# a space, matching docutils' own convert_whitespace (string2lines) handling.
_SEPARATORS_TO_LF = "\x1c\x1d\x1e\x85\u2028\u2029"


_SEPARATORS_TO_SPACE = "\v\f"


def _read_source(path: pathlib.Path, encoding: str = "utf-8") -> str:
    """Decode *path* with NO newline translation, preserving \\r evidence."""
    CALL_COUNTS["_read_source"] += 1
    return path.read_bytes().decode(encoding)


def _relative_to_root(resolved_path: pathlib.Path, root: pathlib.Path) -> pathlib.Path | None:
    """Return an already-resolved *resolved_path* relative to *root*, or
    None if it isn't under *root* (only *root* is resolved here; callers
    that need the resolved *path* for another purpose too — e.g. an
    identity check — resolve it once themselves and pass that in, rather
    than this function resolving it again).

    Found by review, independently in two rounds: this exact
    resolve/relative_to/except-ValueError shape was copy-pasted across
    several call sites (see each one's own comment), each supplying its
    own fallback for the None case — an absolute path, a bare stem, or
    the unrelativized value itself. Those fallbacks differ meaningfully
    by site and are NOT flattened into one generic default here.
    """
    try:
        return resolved_path.relative_to(root.resolve())
    except ValueError:
        return None


def _char_label(ch: str) -> str:
    """Return 'U+XXXX (NAME)' for a character, for hygiene finding messages."""
    name = unicodedata.name(ch, "control character")
    return f"U+{ord(ch):04X} ({name})"


def _normalize_source_detailed(
    text: str,
) -> tuple[str, list[Finding], FixCounts]:
    """Return normalized text, hygiene findings, and structured fix counts.

    Pure function — the single definition of Phase 0.  Every finding is
    ERROR-level and resolved exactly by the returned normalization:
    BOM stripped; CRLF / lone CR / exotic line separators → LF; VT/FF →
    space; trailing whitespace stripped from every source line, matching
    docutils' own pre-parse normalization.
    """
    findings: list[Finding] = []
    bom = 0
    crlf = 0
    lone_cr = 0
    line_separators = 0
    control_whitespace = 0
    trailing_whitespace = 0

    def err(lineno: int, msg: str) -> None:
        findings.append(Finding(lineno=lineno, severity=Severity.ERROR, text=msg, fixable=True))

    if text.startswith("\ufeff"):
        text = text[1:]
        bom = 1
        err(1, "UTF-8 BOM at start of file — policy: no BOM (--fix removes it)")

    crlf = text.count("\r\n")
    if crlf:
        err(
            text.count("\n", 0, text.find("\r\n")) + 1,
            f"CRLF (Windows) line ending on {crlf} line(s), first here — policy: Unix LF only (--fix converts to LF)",
        )
        text = text.replace("\r\n", "\n")
    lone_cr = text.count("\r")
    if lone_cr:
        err(
            text.count("\n", 0, text.find("\r")) + 1,
            f"lone CR line break ({lone_cr} occurrence(s), first here) — "
            "a line break to Python/docutils "
            "but not to git, desynchronizing line numbers "
            "(--fix converts to LF)",
        )
        text = text.replace("\r", "\n")

    for ch in _SEPARATORS_TO_LF:
        n = text.count(ch)
        if n:
            line_separators += n
            err(
                text.count("\n", 0, text.find(ch)) + 1,
                f"line separator {_char_label(ch)} ({n} occurrence(s), first "
                "here) — splits lines for "
                "Python/docutils but not for git, desynchronizing line "
                "numbers (--fix converts to LF)",
            )
            text = text.replace(ch, "\n")
    for ch in _SEPARATORS_TO_SPACE:
        n = text.count(ch)
        if n:
            control_whitespace += n
            err(
                text.count("\n", 0, text.find(ch)) + 1,
                f"control whitespace {_char_label(ch)} ({n} occurrence(s), first "
                "here) — docutils "
                "treats it as a space (--fix converts to space)",
            )
            text = text.replace(ch, " ")

    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if stripped != line:
            trailing_whitespace += 1
            if _is_adornment(stripped):
                message = (
                    "trailing whitespace on adornment line — docutils ignores it "
                    "but it hides the adornment from structure checks "
                    "(--fix strips it)"
                )
            else:
                message = (
                    "trailing whitespace — docutils strips it before parsing, "
                    "so it has no RST meaning (--fix strips it from the source)"
                )
            err(i + 1, message)
            lines[i] = stripped

    counts = FixCounts(
        bom=bom,
        crlf=crlf,
        lone_cr=lone_cr,
        line_separators=line_separators,
        control_whitespace=control_whitespace,
        trailing_whitespace=trailing_whitespace,
    )
    return "\n".join(lines), findings, counts


def _normalize_source(text: str) -> tuple[str, list[Finding]]:
    """Return normalized text and findings using Phase 0's detailed plan."""
    normalized, findings, _counts = _normalize_source_detailed(text)
    return normalized, findings


def _read_normalized(path: pathlib.Path) -> str:
    """Read *path* with Phase 0 normalization applied in memory.

    All Phase 1/2 readers use this so a hygiene defect (reported once by
    check_hygiene) can't cascade into misdiagnosed — and destructively
    'fixed' — adornment findings.
    """
    return _normalize_source(_read_source(path))[0]


def iter_title_blocks(lines: list[str]) -> Iterator[TitleBlock]:
    """Yield every complete overline+title+underline block, in document order.

    A block is three consecutive lines: adornment, non-empty non-adornment
    text, adornment.  Char/length agreement is NOT checked here — that is
    check_adornments' job; this only defines what a block *is*.
    """
    for i in range(1, len(lines) - 1):
        over, title, under = lines[i - 1], lines[i], lines[i + 1]
        if _is_adornment(over) and _is_adornment(under) and not _is_adornment(title) and title:
            yield TitleBlock(i, over, title, under)


def iter_underline_only(lines: list[str]) -> Iterator[UnderlineOnlyCandidate]:
    """Yield every underline-only title candidate, in document order.

    A candidate is a flush-left adornment line of at least
    MIN_UNDERLINE_ONLY_LEN chars glued directly under non-blank,
    non-adornment text.  Skipped when lines[index - 2] is an adornment —
    that makes this the underline of a valid overline+title+underline
    block, not a new underline-only title.

    The candidate's length is NOT compared against the title's: an
    adornment line glued directly to non-blank text (no blank line before
    it) is *always* parsed by docutils as a title-underline attempt,
    regardless of length relative to the title — never as a transition/
    divider (those require blank lines on both sides, already excluded by
    the "prev must be non-blank" check).  Confirmed against real
    sphinx-build output for every project adornment char (#*=-^"): a
    too-short underline glued to text always produces "Title underline
    too short", never a silent divider interpretation.  Still enforce
    MIN_UNDERLINE_ONLY_LEN as an absolute floor — a one- or two-char mark
    is too easy to confuse with something that isn't a title attempt at
    all.  (Flush-left is implied by _is_adornment: an indented line starts
    with whitespace, which is not a valid adornment character.)
    """
    for i in range(1, len(lines)):
        adorn = lines[i]
        if not _is_adornment(adorn) or len(adorn) < MIN_UNDERLINE_ONLY_LEN:
            continue
        prev = lines[i - 1]
        if not prev.strip() or _is_adornment(prev):
            continue
        if i >= 2 and _is_adornment(lines[i - 2]):
            continue
        yield UnderlineOnlyCandidate(i, prev, adorn)


def _canonical_title(title: str) -> tuple[str, int]:
    """Return (canonical title, required adornment length) — THE +2 rule.

    The canonical title is stripped; the required length is its display
    width (docutils.utils.column_width — what docutils itself measures)
    plus 2.  Single definition, consumed by check_adornments and by both
    branches of _compute_adornment_fixes.
    """
    stripped = title.strip()
    return stripped, docutils.utils.column_width(stripped) + 2


def analyze_block(block: TitleBlock) -> BlockCorrection:
    """Compute a block's canonical form and its rule deviations."""
    char = block.over[0]
    title, expected = _canonical_title(block.title)
    return BlockCorrection(
        char=char,
        title=title,
        expected=expected,
        char_mismatch=block.under[0] != char,
        wrong_length=len(block.over) != expected or len(block.under) != expected,
        title_spaces=block.title != title,
    )


# docutils' OWN minimum for a title-underline attempt to register as a
# section at all — confirmed by direct probe, 2026-07-21: a 1-char
# underline glued to text produces only an INFO "Possible title underline,
# too short" and NO section; a 2-char underline is already a real section,
# no message at all.  Deliberately NOT MIN_UNDERLINE_ONLY_LEN (4): that is
# check_rst's OWN, stricter promotion-safety floor for --fix (avoiding
# false-positive auto-promotion of a stray short adornment-like line into
# a full block) — a different job from "is this a real title docutils
# would parse", which is what hierarchy detection below actually needs.
_DOCUTILS_MIN_ADORNMENT_LEN = 2


def _parse_rst(
    path: pathlib.Path,
    text: str | None = None,
    *,
    track_composition: bool = False,
) -> docutils.nodes.document:
    """Parse an RST source file into a docutils document tree.

    text, when given, is the already-normalized source (Document facade) —
    saves the re-read; the parse itself is counted either way.
    """
    CALL_COUNTS["_parse_rst"] += 1
    settings = docutils.frontend.get_default_settings(docutils.parsers.rst.Parser())
    settings.halt_level = 5  # never halt on parse errors
    settings.report_level = 5  # suppress system messages to stderr
    doc = docutils.utils.new_document(str(path), settings)
    source = text if text is not None else _read_normalized(path)
    if track_composition:
        # Imported lazily: _composition owns parser instrumentation while
        # _helpers remains the low-level parse home used by formatters too.
        from ._composition import tracked_docutils_include

        with tracked_docutils_include():
            docutils.parsers.rst.Parser().parse(source, doc)
    else:
        docutils.parsers.rst.Parser().parse(source, doc)
    return doc


def _node_line(node: docutils.nodes.Node) -> int:
    """Return the best available 1-based line number for a docutils node.

    Inline nodes (strong, etc.) often have node.line == None; walking up
    to the parent paragraph usually finds it.
    """
    n: docutils.nodes.Node | None = node
    while n is not None:
        line = getattr(n, "line", None)
        if isinstance(line, int):
            return line
        n = n.parent
    return 0


def _inline_node_line(node: docutils.nodes.Node) -> int:
    """Return an inline node's physical line within a multiline parent.

    Docutils leaves inline ``node.line`` unset and _node_line therefore falls
    back to the paragraph's first line.  Reconstruct only the newline offset
    from preceding siblings: their rawsource preserves explicit markup while a
    Text sibling's value preserves the same line breaks.  Exact columns are not
    needed, but the exact line is a scoping predicate as well as a diagnostic.
    """
    parent = node.parent
    if parent is None:
        return _node_line(node)
    base = _node_line(parent)
    preceding = ""
    for child in parent.children:
        if child is node:
            return base + preceding.count("\n")
        rawsource = getattr(child, "rawsource", None)
        preceding += str(rawsource) if rawsource else str(child)
    return _node_line(node)


def _enclosing_section_title(node: docutils.nodes.Node) -> str | None:
    """Return the title text of the nearest ancestor section, if any."""
    n = node.parent
    while n is not None:
        if isinstance(n, docutils.nodes.section):
            for child in n.children:
                if isinstance(child, docutils.nodes.title):
                    # docutils ships no stubs (see pyproject.toml's
                    # docutils.* override): astext() resolves as Any:
                    # always a str at runtime, str() satisfies mypy.
                    return str(child.astext())
            return None
        n = n.parent
    return None


def _findall_node_types(
    root: docutils.nodes.Node,
    node_types: tuple[type[docutils.nodes.Element], ...],
) -> Iterator[docutils.nodes.Element]:
    """Yield descendants matching *node_types* across supported docutils.

    Docutils 0.23 accepts a tuple of classes directly as ``Node.findall``'s
    condition, while 0.22 accepts only one class or a callable.  The callable
    form has identical behavior on both versions and keeps the PyPI-compatible
    Sphinx stack and Gentoo's newer docutils stack on one code path.

    Narrowed to Element (not the broader Node): both current callers pass
    Element-subclass tuples, and Element is what gives them .rawsource/.get.
    """
    yield from cast(
        "Iterator[docutils.nodes.Element]",
        root.findall(lambda node: isinstance(node, node_types)),
    )


def _block_depth(node: docutils.nodes.Node) -> int:
    """The shared depth computation for every non-heading outline entry
    kind: 1 + every ancestor section/bullet_list/enumerated_list/
    definition_list/list_item.

    Originally list-only (a list CONTAINER node or a standalone
    definition_list_item), generalized 2026-07-26 to every block finder
    (find_admonitions/find_block_quotes/find_comments/find_tables/
    find_code_blocks/find_code_blocks_heuristic) after a real output
    evaluation caught the inconsistency: a list-table added inside a
    bullet item (this project's own "Nested inline markup detection"
    example) printed at the SAME depth as its enclosing bullet list
    container, because every OTHER finder's depth walk only ever counted
    `section` ancestors — harmless before ListEntry existed (nothing else
    tracked "inside a list item" as its own depth level), visibly wrong
    once ListEntry's list_item-aware depth gave lists genuine sub-section
    granularity.  Reduces to the exact old section-only behavior whenever
    there is no enclosing list (no bullet_list/enumerated_list/
    definition_list/list_item ancestor exists to count), so every
    pre-existing depth expectation for the non-nested-in-a-list case is
    unaffected by this generalization.

    list_item (the shared wrapper for both bullet and enumerated items)
    DOES count — confirmed by direct probe, 2026-07-26: a sub-list nested
    inside a bullet item must land one level deeper than that item
    (container_depth+1, assigned manually in find_lists), not merely
    match the OUTER container's own depth, which is what walking past
    the intervening list_item silently produced before this was caught.
    ListEntry's own item entries are never computed via this function —
    their depth is always container_depth+1, assigned directly in
    find_lists — so double-counting list_item here only affects a NESTED
    container's, a nested definition_list_item's, or another finder's
    block's own depth, exactly where the extra level belongs.
    """
    depth = 1
    n: docutils.nodes.Node | None = node.parent
    while n is not None:
        if isinstance(
            n,
            (
                docutils.nodes.section,
                docutils.nodes.bullet_list,
                docutils.nodes.enumerated_list,
                docutils.nodes.definition_list,
                docutils.nodes.list_item,
            ),
        ):
            depth += 1
        n = n.parent
    return depth


def _has_non_prose_ancestor(
    text_node: docutils.nodes.Node,
    extra_types: tuple[type[docutils.nodes.Node], ...] = (),
) -> bool:
    """Is *text_node* (a docutils Text node) nested inside a literal_block,
    comment, raw passthrough, generated topic, or system_message —
    apparatus the tool must never treat as author-written prose?

    Found by code review: this exact ancestor walk was copy-pasted
    identically into three call sites (Document.prose_text,
    check_homoglyphs, check_bare_filenames), each starting at
    text_node.parent and climbing to the document root checking
    isinstance against _NON_PROSE_NODE_TYPES. check_bare_filenames
    alone widens the skip-set further (reference/pending_xref, so a
    filename already inside a real cross-reference is never flagged as
    a MISSING one) — *extra_types* exists for exactly that one caller;
    every other caller passes none.
    """
    node: docutils.nodes.Node | None = text_node.parent
    while node is not None:
        if isinstance(node, (*_NON_PROSE_NODE_TYPES, *extra_types)):
            return True
        node = node.parent
    return False


def _int_to_alpha(n: int) -> str:
    """1->a, 2->b, ..., 26->z, 27->aa, ... (bijective base-26)."""
    result = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(ord("a") + rem) + result
    return result


_ROMAN_TABLE = (
    (1000, "m"),
    (900, "cm"),
    (500, "d"),
    (400, "cd"),
    (100, "c"),
    (90, "xc"),
    (50, "l"),
    (40, "xl"),
    (10, "x"),
    (9, "ix"),
    (5, "v"),
    (4, "iv"),
    (1, "i"),
)


def _int_to_roman(n: int) -> str:
    parts = []
    for value, numeral in _ROMAN_TABLE:
        count, n = divmod(n, value)
        parts.append(numeral * count)
    return "".join(parts)


def _enum_marker(node: docutils.nodes.Element, position: int) -> str:
    """The rendered marker ('1.', '#.', 'a)', 'iv.', ...) for the item at
    0-based *position* in an enumerated_list — never stored in the
    doctree itself (docutils renders enumerated-list numbering at write
    time only), so it is computed here from enumtype/prefix/suffix/start,
    the same facts a real build would use.  Every real occurrence in this
    corpus is 'arabic' (explicit digits or '#.' auto-numbering, confirmed
    by direct corpus scan, 2026-07-26); alpha/roman are supported for
    completeness, not because this project uses them."""
    enumtype = node.get("enumtype", "arabic")
    prefix = node.get("prefix", "")
    suffix = node.get("suffix", ".")
    start = node.get("start", 1)
    n = start + position
    if enumtype == "loweralpha":
        numeral = _int_to_alpha(n)
    elif enumtype == "upperalpha":
        numeral = _int_to_alpha(n).upper()
    elif enumtype == "lowerroman":
        numeral = _int_to_roman(n)
    elif enumtype == "upperroman":
        numeral = _int_to_roman(n).upper()
    else:
        numeral = str(n)
    return f"{prefix}{numeral}{suffix}"
