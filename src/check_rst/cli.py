#!/usr/bin/env python3.14
# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Check .rst files against project reStructuredText formatting rules — check_rst project
"""
Check .rst files against a project's reStructuredText formatting rules.

--config/--no-config/--sphinx-src/--build-dir are global options, given
before the verb (e.g. ``check_rst --sphinx-src docs check file.rst``), same
as ``git``'s own ``-C``/``--git-dir``: by default the working directory is
the project root; --config FILE explicitly selects another project from
anywhere, --no-config skips .check_rst.toml/pyproject.toml discovery
entirely, and --sphinx-src DIR names the Sphinx source directory for Phase 2
(e.g. the repo root, or docs/ when the source is a subdir). Install its
``check_rst`` console entry point once and call it from any project without
maintaining per-project copies.

Four phases:

Phase 0 — Byte-level hygiene (policy: Unix LF line endings, no BOM)
    Runs on the raw bytes before anything parses the file — ERROR on:
    - UTF-8 BOM at the start of the file;
    - CRLF or lone-CR line endings;
    - exotic line separators (FS/GS/RS, NEL, U+2028/U+2029) and VT/FF —
      Python and docutils split lines on these, git does not, so one such
      character silently desynchronizes every line number after it;
    - trailing whitespace on any line (docutils's own string2lines() strips it
      before parsing, so retaining it cannot affect the RST doctree; on an
      adornment it additionally hides the title shape from raw-line checks).

    Every Phase 0 finding is --fix-able (BOM stripped, line breaks
    normalized to LF, VT/FF to a space, every source line rstripped) and
    suppressed by --skip-fixable.  Hygiene fixes are whole-file by nature,
    like the hierarchy check.  All later phases read the file through the
    same normalization in memory, so a hygiene defect is reported once as
    its root cause instead of cascading into bogus — and destructively
    auto-"fixable" — adornment findings (pre-Phase-0, a BOM or a trailing
    space on an overline made --fix insert a duplicate overline into an
    otherwise valid block; confirmed by direct testing, 2026-07-18).

Phase 1 — Python RST rules
    Adornment lint (unless --no-adornments) — ERROR on violation:
    - every section title has BOTH an overline and an underline;
    - overline and underline use the same adornment character;
    - both adornment lines are exactly two characters longer than the
      title's display width (docutils.utils.column_width — what docutils
      itself measures: CJK/emoji count 2 columns, combining marks 0; for
      plain ASCII/Cyrillic this equals the character count);
    - the title has no leading or trailing spaces;
    - an empty separator line before the overline;
    - an empty separator line after the underline;
    - adornment characters, in first-appearance order, form a prefix of
      HIERARCHY (every valid RST adornment character, ranked — the
      preferred #*=-^" first, then every other one): the top level must be
      '#', with no skipped or reordered ranks (whole-file check, not
      diff-scoped).  This is the SAME computation --fix's remap uses, so
      the check flags exactly what --fix would rewrite — nothing more,
      nothing less.  A character outside the preferred 6 also gets a
      WARNING, not an ERROR.

    Adornment fixer (--fix / --diff):
        --fix applies corrections in-place; --diff shows a unified diff without
        writing.  Fixable: wrong length, mismatched chars, title spaces, missing
        blank lines, underline-only titles (overline inferred from underline char;
        the underline must be >= MIN_UNDERLINE_ONLY_LEN chars — currently 4 — to be
        recognized as one at all, independent of the title's own length); out-of-
        order/skipped hierarchy characters are remapped to match #*=-^".
        NOT fixable: which hierarchy LEVEL a section conceptually belongs to —
        only its adornment character is remapped; promoting/demoting a section
        to a different level is a semantic decision, left to a human.

    Editorial spacing modifiers (--fix / --diff, opt-in only):
        --collapse-title-spaces collapses internal ASCII-space runs in visible
        section-title text.  --single-space-prose applies the corresponding
        explicit style policy to eligible paragraph text.  Neither belongs to
        default --fix: internal whitespace survives docutils parsing and may be
        intentional.  Both compare complete canonical doctrees, preserving
        structure, attributes, targets, and ids while permitting only the exact
        requested Text-node space-run reductions.  Literal, raw, code, math,
        syntax-only, indentation, tab, and non-ASCII whitespace remain intact.

    Directive lint (unless --no-directives) — WARNING on suspicious patterns:
    - '.. rubric::' at the start of a line: may substitute a section title;
    - bold text alone on a line (**…**): may substitute a section title;
    - bold paragraph opener (**phrase.** rest…): an AI writing pattern where
      a bold phrase at the start of a line acts as an informal heading;
    - comment that looks like a mistyped directive ('.. code: bash' — a
      single colon): legal RST, so it silently hides its content and
      nothing else ever flags it.
    Nothing inside a blockquote (quoted material) is ever flagged — bold
    or rubric alike; the whole subtree is skipped via SkipNode in
    visit_block_quote, the same idiom as literal blocks.  Known, accepted
    limitation: an accidentally indented paragraph IS a blockquote to RST,
    so mis-indented pseudo-headings are exempt too.

    Nested inline markup lint — WARNING when strong/emphasis/literal content,
    re-parsed through docutils' own inline grammar, contains another explicit
    inline construct.  RST does not nest inline roles: only the outer role is
    rendered.  Implicit URL/email recognition and invalid/unbalanced markup
    are excluded because neither proves nested source markup.

    Warnings do NOT affect the exit code.  Use --no-warnings to suppress them.
    They are hints for human review, not hard violations.

Phase 2 — Python Sphinx rules
    Always runs, in one of two modes — never skipped, unlike Phase 3:

    --sphinx-src DIR given: builds a real, in-process Sphinx environment
        (the "dummy" builder — full read/resolve, no HTML output) and
        derives --outline's structure from it instead of Phase 1's bare
        docutils parse. This exists because bare docutils cannot parse
        Sphinx-only directive options (code-block's :caption:/:linenos:/
        etc.) — the directive fails and silently vanishes rather than
        being detected. A real Sphinx environment resolves these correctly.

    --sphinx-src omitted: falls back to a heuristic, pure-text-search
        code-block detector (find_code_blocks_heuristic) — no docutils or
        Sphinx parsing involved, which restores full recall for the same
        Sphinx-only options, at the cost of a known, accepted limitation: a
        ".. code-block::" merely quoted as example text inside another real
        code-block is double-counted (there is no AST to guard against it).
        Clearly labeled as heuristic in the output.

    --sphinx-src is NEVER auto-detected, even when a conf.py is sitting
    right there in cwd or an ancestor directory — this is deliberate: a
    tool that sometimes guesses your Sphinx config and sometimes doesn't,
    with no way to suppress the guess, is worse than one that is always
    explicit. Pass --sphinx-src whenever you want verified (non-heuristic)
    results.

    Either way, code-block entries in --outline only ever appear here,
    never from Phase 1: showing a file's structure once, correctly-or-
    honestly-labeled-as-best-effort, beats a same-named partial version
    split across two phases.

Phase 3 — Sphinx build integrity check
    Skipped entirely unless --sphinx-src DIR is given — there is no default
    directory to guess at.  When given, DIR must contain conf.py or the
    script errors out immediately (before Phase 1 runs); a typo'd or
    non-Sphinx path is a mistake worth failing loudly on, not silently
    skipping.  Runs sphinx-build in a unique temporary directory and reports
    every WARNING/ERROR line that references one of the checked files.  The
    temp directory is removed after the run unless --build-dir is given
    explicitly (the user is then responsible for cleanup).

File selection and scope (Phase 1):
    With no file arguments, the changed + untracked *.rst files from
    ``git status`` in the selected project are checked (cwd by default, or
    the explicit --config file's directory), and the adornment/directive lint
    is restricted to lines changed since HEAD — pre-existing deviations in
    lines you didn't touch are left alone deliberately (project policy: never
    renormalize pre-existing adornment widths; fix only files you changed).
    Untracked files have no HEAD state, so they're checked in full even in
    this mode.  Naming files explicitly on the command line is a deliberate
    "check this" instruction, so explicit files are always checked in full,
    regardless of git state.  The hierarchy check is always whole-file either
    way.

    --recursive treats each positional argument as a directory instead of a
    file, and discovers *.rst files under it via pathlib.Path.rglob — same
    full-check treatment as naming files explicitly.  --exclude PATTERN
    (repeatable) skips matching discovered files.  Resolving a scope (a
    calendar month, a docs/ tree) into a file list is check_rst's own job
    now, not hand-rolled shell (`find ... -print0 | mapfile -d ''`) repeated
    per call site — and pathlib has no shell word-splitting at all, so
    filenames containing spaces are handled correctly by construction.

Exit codes:
    0  No errors (warnings may still be present without --no-warnings).
    1  One or more ERROR-level violations found.

Common examples::

    check_rst check                         # changed *.rst (git), diff-scoped; Phase 2 heuristic, Phase 3 skipped
    check_rst --sphinx-src . check          # Phase 2/3 verified via real Sphinx (conf.py at repo root)
    check_rst --config /repo/.check_rst.toml check /repo/doc.rst  # select a project config from any cwd
    check_rst --config /repo/.check_rst.toml check  # changed *.rst in that config's Git project
    check_rst --no-config check             # skip .check_rst.toml/pyproject.toml discovery entirely
    check_rst check --git-scope doc.rst     # allowlisted changed file, still diff-scoped
    check_rst check calendar/.../Notes.rst  # explicit file(s), full check, Phase 2 heuristic, Phase 3 skipped
    check_rst check --no-warnings calendar/...  # errors only, suppress warnings
    check_rst --sphinx-src docs/ check docs/ota.rst  # Phase 2/3 verified when Sphinx src is a subdir
    check_rst check -- $(git diff --name-only HEAD)  # explicit list, full check; non-.rst skipped
    check_rst fix --git-scope doc.rst       # fix only an allowlisted changed file
    check_rst fix --fast                    # fast mutation pass; run a full check afterwards
    check_rst diff calendar/.../Notes.rst   # preview fixes, then run all check phases
    check_rst diff --normalize-blank-lines doc.rst  # preview parser-equivalent separator cleanup
    check_rst diff --collapse-title-spaces doc.rst  # preview visible title-space edits
    check_rst diff --single-space-prose doc.rst     # preview explicit prose-style edits
    check_rst diff --fast doc.rst           # fast fix preview, no check/Sphinx phases
    check_rst check --skip-fixable          # pre-fix pass: hide only auto-fixable ERRORs
    check_rst check --recursive calendar/2026/01  # every *.rst under a directory, full check
    check_rst check --recursive docs/ --exclude coding-standards.rst --exclude testing.rst
    check_rst outline doc.rst               # complete structure without finding lines
    check_rst check --max-output-lines 40 doc.rst  # bounded report with suppression facts + final status
    check_rst check --format=json doc.rst > snapshot.json  # structured model for automation
    check_rst context 'doc:Section' doc.rst  # one entry's pre-edit briefing
    check_rst refs doc.rst                  # configured project's incoming/outgoing references
    check_rst diff-json before.json after.json  # compare two prior --format=json snapshots
    check_rst list-table doc.rst             # preview every eligible table converted to list-table
    check_rst list-table --apply doc.rst     # write the conversion
    check_rst list-table --only 2 --apply doc.rst  # convert just the 2nd table, leave the rest aligned
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import dataclasses
import difflib
import enum
import functools
import importlib.metadata
import json
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unicodedata
from typing import TYPE_CHECKING, Any, NoReturn

import docutils.frontend
import docutils.nodes
import docutils.parsers.rst
import docutils.parsers.rst.languages
import docutils.parsers.rst.languages.en
import docutils.parsers.rst.states
import docutils.parsers.rst.tableparser
import docutils.statemachine
import docutils.utils

from check_rst import __version__

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from typing import TextIO

    import sphinx.environment

# Resolved at startup from the invocation directory — project-agnostic.
PROJECT_ROOT = pathlib.Path.cwd()

# Cheap instrumentation counters (Max, 2026-07-19): a plain increment at the
# top of each expensive or suspicion-prone entry point.  Zero measurable
# production cost; in tests they make the execution stack DETERMINISTIC —
# assert or inspect how many times something ran instead of guessing from
# wall-clock or sprinkling debug output.
CALL_COUNTS: collections.Counter[str] = collections.Counter()

_JSON_SCHEMA_VERSION = 1


class OutputBudgetSink:
    """A line-oriented report sink that retains only a bounded prefix.

    The checker still emits and computes its complete report.  This sink keeps
    the first ``limit - 2`` detail lines, counts all later records by their
    semantic kind, and reserves the final two lines for honest suppression
    statistics and the authoritative status supplied through
    :func:`_emit_final_status`.
    """

    def __init__(self, limit: int, target: TextIO) -> None:
        self.limit = limit
        self.target = target
        self.prefix: list[str] = []
        self.total = 0
        self.skipped_by_kind: collections.Counter[str] = collections.Counter()
        self.final_status: str | None = None
        self._pending = ""
        self._pending_kind = "detail"

    @property
    def encoding(self) -> str | None:
        return self.target.encoding

    def isatty(self) -> bool:
        return self.target.isatty()

    def fileno(self) -> int:
        return self.target.fileno()

    def write(self, text: str) -> int:
        if not self._pending:
            self._pending_kind = _OUTPUT_KIND
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._record(line, self._pending_kind)
            self._pending_kind = _OUTPUT_KIND
        return len(text)

    def flush(self) -> None:
        """Satisfy the text-stream protocol; finalization owns emission."""

    def set_final_status(self, text: str) -> None:
        self.final_status = text

    def _record(self, line: str, kind: str) -> None:
        self.total += 1
        if len(self.prefix) < self.limit - 2:
            self.prefix.append(line)
        else:
            self.skipped_by_kind[kind] += 1

    def finish(self, exit_code: int) -> None:
        if self._pending:
            self._record(self._pending, self._pending_kind)
            self._pending = ""

        shown = len(self.prefix)
        skipped = self.total - shown
        for line in self.prefix:
            self.target.write(f"{line}\n")

        classification = [
            f"{count} {kind}" for kind in ("ERROR", "WARNING", "outline") if (count := self.skipped_by_kind[kind])
        ]
        skipped_detail = f" ({', '.join(classification)})" if classification else ""
        statistics = (
            f"check_rst: output limited — {shown} of {self.total} detail line(s) "
            f"shown, {skipped} skipped{skipped_detail}; full output requires "
            f"{self.total + 2} lines"
        )
        if self.final_status is None:
            statistics += (
                "; run ended before normal summary — rerun without --max-output-lines for complete diagnostics"
            )
            outcome = "failed" if exit_code else "completed"
            self.final_status = f"check_rst: command {outcome} before producing a run summary, exit status {exit_code}"
        self.target.write(f"{statistics}\n{self.final_status}\n")
        self.target.flush()


_ACTIVE_OUTPUT_BUDGET: OutputBudgetSink | None = None
_OUTPUT_KIND = "detail"


@contextlib.contextmanager
def _report_kind(kind: str) -> Iterator[None]:
    """Tag lines emitted in this one-threaded process for sink statistics."""
    global _OUTPUT_KIND
    previous = _OUTPUT_KIND
    _OUTPUT_KIND = kind
    try:
        yield
    finally:
        _OUTPUT_KIND = previous


def _emit_final_status(text: str) -> None:
    """Emit normally, or reserve *text* as a bounded report's last line."""
    if _ACTIVE_OUTPUT_BUDGET is None:
        print(text)
    else:
        _ACTIVE_OUTPUT_BUDGET.set_final_status(text)


def _emit_report_line(text: str, kind: str = "detail") -> None:
    """Print one line with a semantic kind understood by the report sink."""
    with _report_kind(kind):
        print(text)


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

# Sphinx warning line formats:
#   /abs/path/file.rst:line: WARNING: message [tag]
#   /abs/path/file.rst: WARNING: message [tag]
# Some project/configuration diagnostics have no source line.  Preserve those
# with line 0 instead of silently dropping them.
_WARNING_RE = re.compile(
    r"^(?P<path>.+\.rst)(?::(?P<line>\d+))?: "
    r"(?P<level>WARNING|ERROR): (?P<msg>.+)$"
)

# Strips ANSI SGR escape codes (colored terminal output) before _WARNING_RE
# matching.  Confirmed necessary (2026-07-20): Sphinx's IN-PROCESS build
# colorizes its console stream even when the target is an io.StringIO()
# with no real isatty() — the leading "\x1b[31m" breaks _WARNING_RE's '^'
# anchor, silently dropping every match.  Defensive on the subprocess path
# too (run_sphinx): if sphinx-build's own color detection ever disagrees
# with ours, the same anchor break would apply there.
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")

# Docutils/Sphinx restatements of Phase 0/1 defects that --fix resolves.
# Under --skip-fixable these are duplicates, not human-review warnings.
_FIXABLE_SPHINX_MESSAGES = (
    "Title overline too short",
    "Title underline too short",
    "Title overline & underline mismatch",
    "Inconsistent title style",
)


# ---------------------------------------------------------------------------
# Finding — carries severity so callers can distinguish errors from warnings
# ---------------------------------------------------------------------------


class Severity(enum.StrEnum):
    """Finding.severity's two levels. A StrEnum (not a plain Enum): members
    compare equal to and format identically to the plain "ERROR"/"WARNING"
    strings the CLI output, JSON schema, and _WARNING_RE regex group all
    already commit to — found by code review: a bare str field compared
    via ~8 scattered string literals had no type-checker signal to catch
    a mistyped literal like "Warning" (silently failing every downstream
    == comparison). str(Severity.ERROR) == "ERROR", not "Severity.ERROR"
    (confirmed by direct probe) — dataclasses.asdict()+json.dumps() and
    every f"{finding.severity}" call site keep their exact prior output."""

    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclasses.dataclass(frozen=True, slots=True)
class Finding:
    """A lint finding with a severity level (ERROR or WARNING)."""

    lineno: int
    severity: Severity
    text: str

    def __str__(self) -> str:
        return f"{self.lineno}: {self.severity}: {self.text}"

    def __contains__(self, item: object) -> bool:
        """Support ``"substring" in finding`` for test assertions."""
        if not isinstance(item, str):
            return False
        return item in str(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _git_at(cwd: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a Git command at *cwd* and return the completed process.

    Centralizes the invocation boilerplate only (cwd, captured text output)
    — deliberately NEVER check=True: the call sites have three different,
    deliberate returncode semantics (must-succeed with a clean diagnostic,
    tolerate-as-check-whole-file, returncode-is-the-answer), which stay
    explicit at each site rather than being configured into a helper.
    """
    CALL_COUNTS["_git"] += 1
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        errors="surrogateescape",
    )


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    """Run a Git command in PROJECT_ROOT."""
    return _git_at(PROJECT_ROOT, *args)


def _git_failure(action: str, result: subprocess.CompletedProcess[str]) -> NoReturn:
    """Exit with Git's real diagnostic instead of mislabeling every failure."""
    detail = result.stderr.strip() or result.stdout.strip() or "unknown Git error"
    if "not a git repository" in detail:
        print(
            "check_rst: not a git repository — bare invocation auto-detects "
            "changed files via git; name files explicitly or use --recursive"
        )
    else:
        print(f"check_rst: git {action} failed: {detail}")
    raise SystemExit(1)


def _git_for_root(project_root: pathlib.Path | None, *args: str) -> subprocess.CompletedProcess[str]:
    """Run Git at an explicit project root, or PROJECT_ROOT by default."""
    if project_root is None:
        return _git(*args)
    return _git_at(project_root, *args)


def _git_worktree_root(project_root: pathlib.Path | None = None) -> pathlib.Path:
    """Return the repository worktree root for the selected project root."""
    result = _git_for_root(project_root, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        _git_failure("rev-parse", result)
    return pathlib.Path(result.stdout.rstrip("\n"))


def _indented_extent(lines: list[str], start: int) -> int:
    """Return the last line (1-based) of the indented block anchored at
    1-based *start*: following lines that are blank or indented belong to
    the block; the extent ends at the last indented non-blank line.
    Shared by blockquote and code-block range computation — the same
    arithmetic previously re-derived by hand to feed sed/Read ranges.
    """
    end = start
    i = start  # 0-based index of the line AFTER start
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith((" ", "\t")):
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
    # ``-z`` is the machine-readable form: paths are not C-quoted (so
    # non-ASCII names need no ad-hoc unescaping), entries are NUL-delimited,
    # and a rename/copy's original path is a separate following field.
    worktree_root = _git_worktree_root(project_root)
    result = _git_for_root(project_root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if result.returncode != 0:
        _git_failure("status", result)
    files: list[pathlib.Path] = []
    entries = result.stdout.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if not entry:
            continue
        status = entry[:2]
        path = entry[3:]
        if "R" in status or "C" in status:
            i += 1  # consume the separate original-path field
        candidate = worktree_root / path
        if candidate.suffix == ".rst" and candidate.is_file():
            files.append(candidate)
    return files


def _unmerged_files(files: list[pathlib.Path], project_root: pathlib.Path | None = None) -> list[pathlib.Path]:
    """Return selected files with unresolved entries in Git's index.

    Explicit files can be checked outside Git, so a non-repository working
    directory simply has no authoritative unmerged state.  Once a worktree
    is found, however, ``git ls-files --unmerged`` is definitive and avoids
    both false positives from documented marker examples and false negatives
    from custom conflict-marker widths.
    """
    repositories: dict[pathlib.Path, list[pathlib.Path]] = {}
    root = PROJECT_ROOT if project_root is None else project_root
    invocation_root = _git_at(root, "rev-parse", "--show-toplevel")
    if invocation_root.returncode == 0:
        root = pathlib.Path(invocation_root.stdout.rstrip("\n")).resolve()
        repositories[root] = []

    for path in files:
        resolved = path.resolve()
        worktree_root = next(
            (root for root in repositories if resolved.is_relative_to(root)),
            None,
        )
        if worktree_root is None:
            root_result = _git_at(resolved.parent, "rev-parse", "--show-toplevel")
            if root_result.returncode != 0:
                continue
            worktree_root = pathlib.Path(root_result.stdout.rstrip("\n")).resolve()
            repositories.setdefault(worktree_root, [])
        repositories[worktree_root].append(resolved)

    unmerged: set[pathlib.Path] = set()
    for worktree_root, candidates in repositories.items():
        if not candidates:
            continue
        result = _git_at(
            worktree_root,
            "ls-files",
            "--unmerged",
            "-z",
            "--",
            *(str(path) for path in candidates),
        )
        if result.returncode != 0:
            _git_failure("ls-files --unmerged", result)
        unmerged.update(
            (worktree_root / record.split("\t", 1)[1]).resolve()
            for record in result.stdout.split("\0")
            if "\t" in record
        )
    return [path for path in files if path.resolve() in unmerged]


def _changed_line_ranges(path: pathlib.Path, project_root: pathlib.Path | None = None) -> list[tuple[int, int]] | None:
    """Return 1-based (start, end) line ranges changed since HEAD, or None.

    None means "check the whole file": the file is untracked or git is
    unavailable.  An empty list means the file is tracked but unchanged.
    """
    diff = _git_for_root(project_root, "diff", "-U0", "HEAD", "--", str(path))
    if diff.returncode != 0:
        return None  # tolerated: no diffable state → check the whole file
    # returncode IS the answer here: 0 = tracked, nonzero = untracked.
    tracked = _git_for_root(project_root, "ls-files", "--error-unmatch", str(path)).returncode == 0
    if not tracked:
        return None
    ranges: list[tuple[int, int]] = []
    for line in diff.stdout.splitlines():
        if not line.startswith("@@"):
            continue
        # Hunk header: @@ -a,b +start[,count] @@ (count omitted means 1).
        new_part = line.split("+")[1].split(" ")[0]
        start_s, _, count_s = new_part.partition(",")
        start, count = int(start_s), int(count_s) if count_s else 1
        ranges.append((start, start + count - 1) if count > 0 else (start, start + 1))
    return ranges


def _in_scope(ranges: list[tuple[int, int]] | None, first: int, last: int) -> bool:
    """Return True if any line in [first, last] overlaps the changed ranges."""
    if ranges is None:
        return True
    return any(s <= last and first <= e for s, e in ranges)


# ---------------------------------------------------------------------------
# Phase 0 — byte-level hygiene (all findings are ERROR, all --fix-able)
#
# Project policy: Unix LF line endings only, no BOM.  Runs on the raw bytes,
# BEFORE any line splitting or parsing, because every check downstream
# assumes git, Python, and docutils agree on what a "line" is:
#
# - Path.read_text() universal-newline mode hides \r evidence (it translates
#   \r\n and lone \r to \n before the caller ever sees them), so hygiene
#   reads bytes directly.
# - str.splitlines() splits on \v \f \x1c \x1d \x1e \x85 U+2028 U+2029 —
#   git diff counts only \n.  One such character silently desynchronizes
#   every reported line number and the diff-scoping ranges after it.
# - A UTF-8 BOM glues U+FEFF to the first overline; a trailing space on an
#   adornment line makes _is_adornment() reject it.  Both made a VALID title
#   block look underline-only — and --fix then inserted a duplicate overline,
#   corrupting the block (confirmed by direct testing, 2026-07-18).
#
# All other check/fix/diff functions therefore read through
# _read_normalized(), which applies the same normalization in memory: a
# hygiene defect is reported once, here, as its root cause — it no longer
# cascades into bogus (and destructively "fixable") Phase 1 findings.
# Stripping trailing whitespace from every line is semantically free for RST:
# docutils.statmachine.string2lines() itself expands tabs and then rstrips every
# source line before parsing.  Phase 0 now materializes that parser-normalized
# form in the source instead of retaining bytes no doctree can observe.
# ---------------------------------------------------------------------------

# Separator characters str.splitlines() treats as line breaks but git does
# not.  FS/GS/RS (\x1c-\x1e), NEL (\x85), LS (U+2028), PS (U+2029) are real
# line separators — normalized to \n.  VT/FF are whitespace — normalized to
# a space, matching docutils' own convert_whitespace (string2lines) handling.
_SEPARATORS_TO_LF = "\x1c\x1d\x1e\x85\u2028\u2029"
_SEPARATORS_TO_SPACE = "\v\f"


@dataclasses.dataclass(frozen=True, slots=True)
class FixCounts:
    """Structured counts for the deterministic mutation stages."""

    bom: int = 0
    crlf: int = 0
    lone_cr: int = 0
    line_separators: int = 0
    control_whitespace: int = 0
    trailing_whitespace: int = 0
    structural_lines: int = 0

    def with_structural_lines(self, count: int) -> FixCounts:
        """Return these hygiene counts plus the Phase 1 line-change count."""
        return dataclasses.replace(self, structural_lines=count)

    def describe(self) -> str:
        """Return stable, human-readable non-zero categories."""
        categories = (
            ("BOM", self.bom),
            ("CRLF line endings", self.crlf),
            ("lone CR line endings", self.lone_cr),
            ("exotic line separators", self.line_separators),
            ("control whitespace", self.control_whitespace),
            ("trailing whitespace lines", self.trailing_whitespace),
            ("structural lines", self.structural_lines),
        )
        return ", ".join(f"{label} {count}" for label, count in categories if count)


@dataclasses.dataclass(frozen=True, slots=True)
class FixPlan:
    """A fully computed, converged file mutation that has not been written."""

    path: pathlib.Path
    original: str
    fixed: str
    counts: FixCounts

    @property
    def changed(self) -> bool:
        return self.original != self.fixed


@dataclasses.dataclass(frozen=True, slots=True)
class FixResult:
    """The structured outcome of applying one :class:`FixPlan`."""

    path: pathlib.Path
    changed: bool
    counts: FixCounts


def _read_source(path: pathlib.Path) -> str:
    """Read *path* as UTF-8 with NO newline translation — \\r evidence intact."""
    CALL_COUNTS["_read_source"] += 1
    return path.read_bytes().decode("utf-8")


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
        findings.append(Finding(lineno=lineno, severity=Severity.ERROR, text=msg))

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


def check_hygiene(path: pathlib.Path) -> list[Finding]:
    """Phase 0 lint.  All findings have severity ERROR and are --fix-able."""
    return Document(path).hygiene


def fix_hygiene(path: pathlib.Path) -> bool:
    """Apply Phase 0 normalization to *path* in-place.

    Returns True if the file was modified.  Must run before the adornment/
    hierarchy fixers in a --fix pass, so they read the cleaned bytes.
    Whole-file by nature (like the hierarchy check): a line-ending policy
    can't be meaningfully diff-scoped.
    """
    raw = _read_source(path)
    normalized, _ = _normalize_source(raw)
    if normalized == raw:
        return False
    path.write_bytes(normalized.encode("utf-8"))
    return True


# ---------------------------------------------------------------------------
# Raw-line title scanning — the single definition of the two title shapes
#
# check_adornments, check_hierarchy, and both fixers all consume these two
# generators, so the recognition predicates cannot drift between check and
# fix — the failure mode where the check reports X but --fix does Y (the
# pre-Phase-0 duplicate-overline corruption was exactly that class).
# These MUST stay raw-line scanning, not docutils: docutils normalises
# adornment style away — it records section nesting depth but not which
# character was used or how long the adornment line was (see the Phase 1c
# design note).
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class TitleBlock:
    """A complete overline+title+underline block, found by raw-line scan."""

    index: int  # 0-based index of the title line in the lines list
    over: str
    title: str
    under: str

    @property
    def lineno(self) -> int:
        """1-based line number of the title text."""
        return self.index + 1


@dataclasses.dataclass(frozen=True, slots=True)
class UnderlineOnlyCandidate:
    """An adornment line glued directly under text — an underline-only title."""

    index: int  # 0-based index of the adornment (underline) line
    title: str  # the text line directly above (unstripped)
    under: str


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


# ---------------------------------------------------------------------------
# Rule layer — canonical values shared by checkers and fixers
#
# The checker turns deviations from the canonical form into Findings; the
# fixer turns the same canonical values into edits.  One computation, two
# consumers — so the reported expectation and the applied fix cannot
# diverge.  (They did: the checker measured the unstripped title and
# reported "must be 11 chars" for a spaced title --fix would correctly
# size to 9; found 2026-07-18 while evaluating check/fix rule duplication.)
# ---------------------------------------------------------------------------


def _canonical_title(title: str) -> tuple[str, int]:
    """Return (canonical title, required adornment length) — THE +2 rule.

    The canonical title is stripped; the required length is its display
    width (docutils.utils.column_width — what docutils itself measures)
    plus 2.  Single definition, consumed by check_adornments and by both
    branches of _compute_adornment_fixes.
    """
    stripped = title.strip()
    return stripped, docutils.utils.column_width(stripped) + 2


@dataclasses.dataclass(frozen=True, slots=True)
class BlockCorrection:
    """A TitleBlock's canonical form, plus which rules it currently violates.

    Produced by analyze_block.  Blank-line requirements are deliberately
    NOT here: the checker evaluates them against the original lines and
    the fixer against the buffer it is mutating — surrounding context,
    not block-local rules.
    """

    char: str  # canonical adornment character (the overline's)
    title: str  # canonical title (stripped)
    expected: int  # canonical adornment length (display width + 2)
    char_mismatch: bool
    wrong_length: bool
    title_spaces: bool


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


def _title_char_events(lines: list[str]) -> list[tuple[int, str]]:
    """Return (0-based line index, char) for EVERY title occurrence, in
    document order — full overline+title+underline blocks AND underline-only
    titles alike (including ones too short for iter_underline_only's own
    MIN_UNDERLINE_ONLY_LEN floor; that floor exists purely to avoid
    mis-promoting a stray short line during --fix, and has nothing to do
    with whether docutils itself already sees a real title there).

    THE shared event scan: _first_appearance_adornments collapses this to
    one entry per distinct char (first occurrence only); check_single_top_level
    needs every occurrence, not just the first, so both derive from this one
    scan rather than duplicating it.
    """
    events: list[tuple[int, str]] = []  # (0-based line index, char)
    for block in iter_title_blocks(lines):
        events.append((block.index, block.over[0]))
    for i in range(1, len(lines)):
        adorn = lines[i]
        if not _is_adornment(adorn) or len(adorn) < _DOCUTILS_MIN_ADORNMENT_LEN:
            continue
        prev = lines[i - 1]
        if not prev.strip() or _is_adornment(prev):
            continue
        if i >= 2 and _is_adornment(lines[i - 2]):
            continue  # underline of a full block, already counted above
        events.append((i - 1, adorn[0]))  # i - 1: the title line's index
    events.sort(key=lambda e: e[0])
    return events


def _first_appearance_adornments(lines: list[str]) -> list[tuple[str, int]]:
    """Return (char, 1-based lineno) for each distinct adornment character's
    first appearance as a title, in document order.

    Found by direct reproduction (2026-07-21, on a document with two
    genuine but short titles like "Doc"/"###" and "Sub"/"***", 3-char
    underlines, never yet promoted to full blocks): the previous
    title-blocks-only scan was blind to them entirely, so the FIRST
    character it had ever seen was whichever established, longer-titled
    heading came later in the document — and the remap then "corrected"
    that character to HIERARCHY's rank-1 slot, silently colliding it with
    a DIFFERENT heading already using that slot.  The result was a
    genuinely inconsistent document (the same char at two different
    depths) that no later --fix run could ever converge out of, since the
    scanner's blind spot never changes: check_rst itself never saw an
    error, only a fresh, independent docutils/Sphinx parse did.
    """
    seen: dict[str, int] = {}
    for idx, char in _title_char_events(lines):
        seen.setdefault(char, idx + 1)
    return list(seen.items())


def check_single_top_level(path: pathlib.Path, doc: Document | None = None) -> list[Finding]:
    """A document may have only one level-1 title — it is the document's
    own title, and Sphinx/docutils only promote a top-level section to
    that role when it is the SOLE one (Max, 2026-07-23: "the level-1
    heading can only be one — it represents the document's title").

    A second top-level section is syntactically valid RST — confirmed
    live, 2026-07-26: a real sphinx-build at -vv/-n emits nothing about
    it, at any verbosity — but neither section then gets promoted, and a
    real HTML build's toctree entry pointing at that file shows BOTH
    sections as separate top-level entries instead of one: a real, silent
    defect, not a style preference.

    WARNING, not ERROR: unlike adornment/hierarchy violations, --fix
    cannot resolve this on its own (demoting one of the sections is a
    real content decision), so this follows check_directives' severity
    convention — ERROR is reserved for what --fix actually fixes.

    The "level-1" character is whichever one is THIS document's own
    first-appearing adornment (via _title_char_events), not hardcoded to
    '#' — the same convention check_hierarchy itself uses.
    """
    events = _title_char_events(_resolve_document(path, doc).lines)
    if not events:
        return []
    level1_char = events[0][1]
    occurrences = [(idx, char) for idx, char in events if char == level1_char]
    return [
        Finding(
            idx + 1,
            Severity.WARNING,
            f"second top-level {char!r} title — a document may have "
            "only one: it is the document's own title, and a second "
            "one leaves neither promoted (confirmed: the file's "
            "toctree entry then shows both as separate top-level "
            "entries)",
        )
        for idx, char in occurrences[1:]
    ]


# ---------------------------------------------------------------------------
# Phase 1a — Adornment lint  (all findings are ERROR)
# ---------------------------------------------------------------------------


def check_adornments(path: pathlib.Path, whole_file: bool, doc: Document | None = None) -> list[Finding]:
    """Lint adornment blocks.  All findings have severity ERROR.

    Reads through _read_normalized() — hygiene defects (BOM, CRLF, trailing
    whitespace) are Phase 0 findings, not cascade errors here.
    Each block is validated against its canonical form from analyze_block —
    the same values _compute_adornment_fixes applies — so a reported
    expectation is always exactly what --fix would produce.  The expected
    length is the canonical (stripped) title's display width + 2; see
    _canonical_title for why display width, not code points.
    """
    doc = _resolve_document(path, doc)
    lines = doc.lines
    ranges: list[tuple[int, int]] | None = None if whole_file else doc.ranges

    def err(lineno: int, text: str) -> Finding:
        return Finding(lineno=lineno, severity=Severity.ERROR, text=text)

    findings: list[Finding] = []

    # Detect underline-only titles (overline is required).  Recognition
    # rationale lives in iter_underline_only's docstring.
    for cand in iter_underline_only(lines):
        if _in_scope(ranges, cand.index, cand.index + 1):
            findings.append(
                err(
                    cand.index + 1,
                    "underline-only title — add matching overline (project rule: overline + underline required)",
                )
            )

    # Validate overline + underline blocks (length, spaces, surrounding blanks)
    # against their canonical form — the same one the fixer applies.
    for block in iter_title_blocks(lines):
        i = block.index
        if not _in_scope(ranges, i - 1, i + 3):
            continue

        lineno = block.lineno  # 1-based line of the title text
        c = analyze_block(block)

        if c.char_mismatch:
            findings.append(
                err(lineno, f"overline char '{block.over[0]}' differs from underline char '{block.under[0]}'")
            )
            continue

        if c.wrong_length:
            findings.append(
                err(
                    lineno,
                    f"adornment must be {c.expected} chars for title "
                    f"{c.title!r} (over={len(block.over)}, under={len(block.under)})",
                )
            )
        if c.title_spaces:
            findings.append(err(lineno, "title has leading or trailing spaces"))
        if i >= 2 and lines[i - 2] != "":
            findings.append(err(lineno - 1, "empty separator line required before the overline"))
        if i + 2 < len(lines) and lines[i + 2] != "":
            findings.append(err(lineno + 2, "empty separator line required after the underline"))

    return findings


# ---------------------------------------------------------------------------
# Phase 1a fixer — auto-correct adornment violations
# ---------------------------------------------------------------------------


def _compute_adornment_fixes(lines: list[str], ranges: list[tuple[int, int]] | None) -> list[str]:
    """Return a new lines list with all auto-fixable adornment violations corrected.

    Fixable:
    - wrong adornment length
    - mismatched overline/underline characters
    - leading/trailing spaces in title
    - missing blank line before overline or after underline
    - underline-only title: overline is added using the same character as the
      underline (underline must be >= MIN_UNDERLINE_ONLY_LEN chars to be
      recognized as one at all, independent of the title's own length)

    NOT handled here: hierarchy character remapping is a separate concern —
    _compute_structure_fixes() composes _compute_hierarchy_remap's remap
    with this function so one --fix run converges.

    All patterns are collected from the original lines and processed in descending
    index order so that line insertions do not shift the positions of patterns
    that have not yet been visited.
    """
    result = list(lines)

    # Collect underline-only patterns (underline at i, title at i-1) and
    # overline+title+underline blocks (title at i) via the shared generators,
    # then process largest-first.  Only the indices are kept: the fix loop
    # below re-reads and re-validates against the mutating `result` list,
    # since an earlier insertion may have shifted a later pattern.
    fixable: list[tuple[int, str]] = [(cand.index, "underline_only") for cand in iter_underline_only(lines)] + [
        (block.index, "block") for block in iter_title_blocks(lines)
    ]

    fixable.sort(key=lambda x: x[0], reverse=True)

    for idx, kind in fixable:
        if kind == "underline_only":
            i = idx
            if not _in_scope(ranges, i, i + 1):
                continue
            if not _is_adornment(result[i]):
                continue  # earlier insertion shifted this index away from the adornment

            char = result[i][0]
            title, expected = _canonical_title(result[i - 1])

            result[i] = char * expected
            result[i - 1] = title
            result.insert(i - 1, char * expected)  # insert overline before title
            # After: overline at i-1, title at i, underline at i+1

            if i + 2 < len(result) and result[i + 2] != "":
                result.insert(i + 2, "")
            if i >= 2 and result[i - 2] != "":
                result.insert(i - 1, "")

        else:  # "block": title at i, overline at i-1, underline at i+1
            i = idx
            if not _in_scope(ranges, i - 1, i + 3):
                continue
            if not (i >= 1 and i + 1 < len(result) and _is_adornment(result[i - 1]) and _is_adornment(result[i + 1])):
                continue  # safety: earlier insertion may have shifted this index

            # Analyze the block as it stands in the mutating buffer — not
            # the original lines — then apply its canonical values.
            c = analyze_block(TitleBlock(i, result[i - 1], result[i], result[i + 1]))

            if c.char_mismatch:
                result[i + 1] = c.char * len(result[i + 1])

            if len(result[i - 1]) != c.expected:
                result[i - 1] = c.char * c.expected
            if len(result[i + 1]) != c.expected:
                result[i + 1] = c.char * c.expected

            if c.title_spaces:
                result[i] = c.title

            if i + 2 < len(result) and result[i + 2] != "":
                result.insert(i + 2, "")
            if i >= 2 and result[i - 2] != "":
                result.insert(i - 1, "")

    return result


# ---------------------------------------------------------------------------
# Phase 1b — Hierarchy check (always whole-file; skipped/wrong-order
# violations are ERROR, a non-preferred character is WARNING)
# ---------------------------------------------------------------------------


def check_hierarchy(path: pathlib.Path, doc: Document | None = None) -> list[Finding]:
    """Verify first-appearance adornment order is a prefix of HIERARCHY.

    Always whole-file — hierarchy is a document-level property.

    THE rule is _compute_hierarchy_remap's: the document's distinct
    adornment characters, in first-appearance order, must equal
    HIERARCHY[:n] exactly — starting at '#', no skipped or reordered
    ranks.  The check consumes the very remap --fix applies, so the two
    cannot disagree: every ERROR here is exactly one remapped character
    there, and a document with no ERRORs is left unmodified by
    the fixer (fix_structure).  (The previous transition-only check validated
    consecutive rank steps but never the starting rank, so a document
    offset from the top — e.g. '*'-only — passed the check yet was
    silently rewritten by --fix; found 2026-07-18 while evaluating
    check/fix rule duplication.)

    A character outside PREFERRED_HIERARCHY (the tool's 6 default
    characters) additionally gets a WARNING, once per distinct
    character at its first appearance — a style suggestion, independent
    of the ERROR-level order rule.
    """
    lines = _resolve_document(path, doc).lines
    remap = _compute_hierarchy_remap(lines)
    findings: list[Finding] = []

    for level, (char, lineno) in enumerate(_first_appearance_adornments(lines), 1):
        if char not in PREFERRED_HIERARCHY:
            findings.append(
                Finding(
                    lineno,
                    Severity.WARNING,
                    f"adornment {char!r} is valid but outside the tool's preferred hierarchy {PREFERRED_HIERARCHY!r}",
                )
            )
        if char in remap:
            findings.append(
                Finding(
                    lineno,
                    Severity.ERROR,
                    f"adornment {char!r} is this document's level {level}, but "
                    f"hierarchy level {level} is {remap[char]!r} — first-appearance "
                    f"order must follow the hierarchy from '#' down "
                    f"(--fix remaps {char!r} to {remap[char]!r})",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Phase 1b fixer — remap adornment characters to the correct hierarchy
# ---------------------------------------------------------------------------


def _compute_hierarchy_remap(lines: list[str]) -> dict[str, str]:
    """Return a char→char mapping that corrects hierarchy violations.

    Extracts the first-appearance order of adornment chars from *lines*,
    computes the correct order (HIERARCHY[:n]), and returns the non-identity
    pairs.  Returns an empty dict when no remapping is needed.

    THE single definition of the hierarchy rule: check_hierarchy derives
    its ERROR findings from this same mapping (one ERROR per pair), so the
    check and --fix cannot disagree about what is a violation.

    Applies uniformly across all of HIERARCHY (all 32 valid RST adornment
    characters), not just PREFERRED_HIERARCHY's 6 — a deliberate choice: a
    document using only a non-preferred character (e.g. '~' throughout) has
    correct == HIERARCHY[:1] == '#', so --fix rewrites it into the preferred
    set the same way it already remaps preferred characters that are merely
    out of order (see rst-formatting.md, "Hierarchy remap in --fix" — this
    was already established behavior for the preferred 6; this extends it
    uniformly rather than special-casing non-preferred characters).
    """
    seen_chars = [char for char, _ in _first_appearance_adornments(lines)]

    correct = list(HIERARCHY[: len(seen_chars)])
    if seen_chars == correct:
        return {}
    return {old: new for old, new in zip(seen_chars, correct, strict=True) if old != new}


# ---------------------------------------------------------------------------
# Phase 1 fixer composition — remap and adornment fixes in ONE pass
# ---------------------------------------------------------------------------


def _compute_structure_fixes(lines: list[str], ranges: list[tuple[int, int]] | None) -> list[str]:
    """Compose the hierarchy remap with adornment fixes — one converging pass.

    The remap is a whole-document property (a character's rank has no
    meaning per-hunk), so it rewrites adornment lines regardless of
    *ranges*.  Every line it rewrites therefore joins the adornment-fix
    scope: after --fix writes the file, git would report those lines as
    changed anyway — fixing their geometry in the same pass is what makes
    bare --fix converge in one run instead of two.  (Found in a downstream project's
    coding-standards.rst, 2026-07-20: pass 1 remapped chars document-wide
    but preserved wrong widths outside the diff scope; only the write
    itself pulled those lines into scope for a second pass.)
    """
    current = _compute_adornment_fixes(lines, ranges)
    # Adornment fixes and the remap feed each other: an in-scope
    # underline-only title only becomes a block (visible to
    # _first_appearance_adornments) once its overline is materialized, and
    # a firing remap widens the scope for the next adornment pass.  Iterate
    # to the fixpoint — each round makes at least one previously invisible
    # block visible, so the round count is bounded by the block count.
    for _ in range(len(lines) + 1):
        remap = _compute_hierarchy_remap(current)
        if not remap:
            break
        extra: list[tuple[int, int]] = []
        for i, line in enumerate(current):
            if _is_adornment(line) and line[0] in remap:
                current[i] = remap[line[0]] * len(line)
                # (i, i+1) covers the rewritten line under both conventions
                # _in_scope is called with (0-based index and 1-based lineno).
                extra.append((i, i + 1))
        if ranges is not None:
            ranges = ranges + extra
        current = _compute_adornment_fixes(current, ranges)
    return current


def fix_structure(
    path: pathlib.Path,
    whole_file: bool,
    *,
    project_root: pathlib.Path | None = None,
) -> bool:
    """Apply hierarchy remap + adornment fixes to *path* in-place, one pass.

    Returns True if the file was modified, False if it was already correct.
    """
    text = _read_normalized(path)
    lines = text.splitlines()
    trailing_newline = text.endswith("\n")
    ranges = None if whole_file else _changed_line_ranges(path, project_root)

    new_lines = _compute_structure_fixes(lines, ranges)
    if new_lines == lines:
        return False

    path.write_text(
        "\n".join(new_lines) + ("\n" if trailing_newline else ""),
        encoding="utf-8",
        newline="\n",
    )
    return True


def diff_structure(path: pathlib.Path, whole_file: bool) -> str:
    """Return a unified diff of what fix_structure would change.

    Returns an empty string when no fixes are needed.  Previews the
    composed result — remapped characters at canonical widths — never
    the remap-only intermediate a two-pass sequence would show.
    """
    text = _read_normalized(path)
    lines = text.splitlines()
    ranges = None if whole_file else _changed_line_ranges(path)

    new_lines = _compute_structure_fixes(lines, ranges)
    if new_lines == lines:
        return ""

    pstr = str(path)
    return "".join(
        difflib.unified_diff(
            [line + "\n" for line in lines],
            [line + "\n" for line in new_lines],
            fromfile=pstr,
            tofile=pstr,
        )
    )


def diff_fixes(
    path: pathlib.Path,
    whole_file: bool,
    *,
    include_structure: bool,
    include_blank_lines: bool = False,
    collapse_title_spaces: bool = False,
    single_space_prose: bool = False,
    project_root: pathlib.Path | None = None,
) -> str:
    """Return one raw-to-final diff for the fix stages enabled by the CLI.

    Hygiene normalization feeds the structure fixer in ``--fix`` mode, and
    the opt-in blank-line stage follows both, so ``--diff`` must preview that
    same composition.  Diffing from the raw source also makes hygiene-only
    changes (including trailing whitespace) visible instead of losing them
    behind ``_read_normalized``.
    """
    plan = _plan_fix(
        path,
        whole_file,
        include_structure=include_structure,
        include_blank_lines=include_blank_lines,
        collapse_title_spaces=collapse_title_spaces,
        single_space_prose=single_space_prose,
        project_root=project_root,
    )
    if not plan.changed:
        return ""

    pstr = str(path)
    return "".join(
        difflib.unified_diff(
            plan.original.splitlines(keepends=True),
            plan.fixed.splitlines(keepends=True),
            fromfile=pstr,
            tofile=pstr,
        )
    )


def _apply_structure_to_text(text: str, ranges: list[tuple[int, int]] | None) -> str:
    """Return *text* after the converging raw-line structural fixer."""
    lines = text.splitlines()
    trailing_newline = text.endswith("\n")
    fixed = "\n".join(_compute_structure_fixes(lines, ranges))
    return fixed + ("\n" if trailing_newline else "")


def _changed_line_count(before: str, after: str) -> int:
    """Count lines affected by replacements, insertions, or deletions."""
    matcher = difflib.SequenceMatcher(a=before.splitlines(), b=after.splitlines(), autojunk=False)
    return sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal")


def _plan_fix(
    path: pathlib.Path,
    whole_file: bool,
    *,
    include_structure: bool,
    include_blank_lines: bool = False,
    collapse_title_spaces: bool = False,
    single_space_prose: bool = False,
    project_root: pathlib.Path | None = None,
) -> FixPlan:
    """Compute and verify a complete deterministic fix without writing.

    Phase 0 feeds the opt-in editorial text stage, then Phase 1 structural
    correction, then the opt-in blank-line normalizer.  Re-applying every
    enabled pure computation to the target is the local convergence
    postcondition; failure aborts the caller's complete plan set before any
    file is mutated.
    """
    original = _read_source(path)
    normalized, _findings, counts = _normalize_source_detailed(original)
    ranges = None if whole_file or not include_structure else _changed_line_ranges(path, project_root)
    editorial_fixed, _space_counts = _normalize_text_spaces(
        path,
        normalized,
        collapse_titles=collapse_title_spaces,
        single_space_prose=single_space_prose,
    )
    structure_fixed = _apply_structure_to_text(editorial_fixed, ranges) if include_structure else editorial_fixed
    fixed = structure_fixed
    if include_blank_lines:
        fixed, _removed = _normalize_blank_lines(path, fixed)
    counts = counts.with_structural_lines(
        _changed_line_count(editorial_fixed, structure_fixed) if include_structure else 0
    )

    converged, _findings, _counts = _normalize_source_detailed(fixed)
    converged, _space_counts = _normalize_text_spaces(
        path,
        converged,
        collapse_titles=collapse_title_spaces,
        single_space_prose=single_space_prose,
    )
    if include_structure:
        converged = _apply_structure_to_text(converged, ranges)
    if include_blank_lines:
        converged, _removed = _normalize_blank_lines(path, converged)
    if converged != fixed:
        raise RuntimeError("deterministic fix plan did not converge in one pass")

    return FixPlan(path=path, original=original, fixed=fixed, counts=counts)


def _apply_fix_plan(plan: FixPlan) -> FixResult:
    """Write one precomputed plan and return its structured result."""
    if plan.changed:
        plan.path.write_bytes(plan.fixed.encode("utf-8"))
    return FixResult(path=plan.path, changed=plan.changed, counts=plan.counts)


# ---------------------------------------------------------------------------
# Phase 1c — Directive lint (all findings are WARNING)
#
# Design: docutils NodeVisitor instead of raw-line regex.
#
# The naive regex r"^\s*\.\.\ rubric::" has no concept of literal-block
# context.  A rubric written as a code example inside ``.. code-block:: rst``
# or a ``::`` paragraph is indented source text — not a real directive —
# but the regex would fire on it anyway (false positive).
#
# docutils solves this cleanly: SkipNode raised in visit_literal_block
# prevents the visitor from ever descending into the subtrees of code-block,
# :: literal-block, doctest, and parsed-literal nodes.  All code-example
# variants map to the same literal_block node type in the AST, so one guard
# covers them all.
#
# Phases 1a (adornments) and 1b (hierarchy) MUST stay as raw-line scanning:
# docutils normalises adornment style away — it records section nesting depth
# but not which character was used or how long the adornment line was.
# The project rules (+2 length, ordered hierarchy #*=-^") require raw text.
# ---------------------------------------------------------------------------


def _parse_rst(path: pathlib.Path, text: str | None = None) -> docutils.nodes.document:
    """Parse an RST source file into a docutils document tree.

    text, when given, is the already-normalized source (Document facade) —
    saves the re-read; the parse itself is counted either way.
    """
    CALL_COUNTS["_parse_rst"] += 1
    settings = docutils.frontend.get_default_settings(docutils.parsers.rst.Parser())
    settings.halt_level = 5  # never halt on parse errors
    settings.report_level = 5  # suppress system messages to stderr
    doc = docutils.utils.new_document(str(path), settings)
    docutils.parsers.rst.Parser().parse(text if text is not None else _read_normalized(path), doc)
    return doc


def _blank_line_candidate(text: str) -> tuple[str, int]:
    """Collapse every redundant separator or EOF blank run mechanically.

    This helper knows only source geometry.  Its result must never be used
    without the doctree-equivalence gate in :func:`_normalize_blank_lines`:
    an apparently empty separator can be content in a literal-like block.
    A leading run before real content is removed completely.  At EOF, the one
    empty ``split`` element that represents a normal final newline is retained;
    duplicates are candidates for the same semantic gate as interior
    separators.  An all-blank source has no first element and is retained.
    """
    lines = text.split("\n")
    output: list[str] = []
    removed = 0
    index = 0
    while index < len(lines):
        if lines[index] != "":
            output.append(lines[index])
            index += 1
            continue

        end = index
        while end < len(lines) and lines[end] == "":
            end += 1
        run_length = end - index
        is_leading_before_content = index == 0 and end < len(lines)
        has_preceding_content = index > 0
        if is_leading_before_content:
            removed += run_length
        elif has_preceding_content and run_length > 1:
            output.append("")
            removed += run_length - 1
        else:
            output.extend(lines[index:end])
        index = end
    return "\n".join(output), removed


def _doctree_fingerprint(path: pathlib.Path, text: str) -> str:
    """Return docutils' semantic tree representation for a source variant."""
    # docutils ships no inline types, so pformat() is Any to mypy even though
    # its runtime contract is text.  Materialize that boundary explicitly.
    return str(_parse_rst(path, text=text).pformat())


def _normalize_blank_lines(path: pathlib.Path, text: str) -> tuple[str, int]:
    """Collapse only separator and EOF blank runs invisible to docutils.

    *text* is the Phase 0-normalized source.  First try the common case as one
    parse: if collapsing every candidate preserves the complete doctree,
    accept it.  If any whitespace-preserving construct makes that batch
    unsafe, retry each run independently so safe block separators elsewhere
    in the same document are still normalized.
    This semantic gate is the reason the operation is opt-in and unavailable
    in the parser-free ``--fix-only`` / ``--diff-only`` modes.
    Contract: ``docs/guide.rst``, "Opt-in blank-line
    normalization".
    """
    candidate, candidate_removed = _blank_line_candidate(text)
    if not candidate_removed:
        return text, 0

    fingerprint = _doctree_fingerprint(path, text)
    if _doctree_fingerprint(path, candidate) == fingerprint:
        return candidate, candidate_removed

    current = text
    removed = 0
    cursor = 0
    while True:
        lines = current.split("\n")
        index = cursor
        while index < len(lines) and lines[index] != "":
            index += 1
        if index == len(lines):
            break
        end = index
        while end < len(lines) and lines[end] == "":
            end += 1
        run_length = end - index
        is_leading_before_content = index == 0 and end < len(lines)
        has_preceding_content = index > 0
        if is_leading_before_content:
            replacement: list[str] = []
            removed_in_trial = run_length
        elif has_preceding_content and run_length > 1:
            replacement = [""]
            removed_in_trial = run_length - 1
        else:
            cursor = end
            continue

        trial = "\n".join([*lines[:index], *replacement, *lines[end:]])
        if _doctree_fingerprint(path, trial) == fingerprint:
            current = trial
            removed += removed_in_trial
            cursor = index + len(replacement)
        else:
            cursor = end
    return current, removed


def fix_blank_lines(path: pathlib.Path) -> int:
    """Apply parser-equivalent blank-separator normalization to *path*.

    Return the number of source lines removed.  A zero result performs no
    write, preserving timestamps and making the operation a fixed point.
    """
    text = _read_normalized(path)
    normalized, removed = _normalize_blank_lines(path, text)
    if removed:
        path.write_text(normalized, encoding="utf-8", newline="\n")
    return removed


_INTERNAL_ASCII_SPACES_RE = re.compile(r"(?<=\S) {2,}(?=\S)")
_TEXT_NODE_SPACES_RE = re.compile(r" {2,}")


@dataclasses.dataclass(frozen=True, slots=True)
class TextSpaceCounts:
    """Accepted editorial space-run changes, separated by visible scope."""

    title_runs: int = 0
    prose_runs: int = 0

    def __add__(self, other: TextSpaceCounts) -> TextSpaceCounts:
        return TextSpaceCounts(
            title_runs=self.title_runs + other.title_runs,
            prose_runs=self.prose_runs + other.prose_runs,
        )

    @property
    def total(self) -> int:
        return self.title_runs + self.prose_runs

    def describe(self) -> str:
        """Return stable, grammatical non-zero editorial categories."""
        parts: list[str] = []
        if self.title_runs:
            noun = "run" if self.title_runs == 1 else "runs"
            parts.append(f"{self.title_runs} title space {noun} collapsed")
        if self.prose_runs:
            noun = "run" if self.prose_runs == 1 else "runs"
            parts.append(f"{self.prose_runs} prose space {noun} collapsed")
        return ", ".join(parts)


@dataclasses.dataclass(frozen=True, slots=True)
class _TextSpaceEdit:
    """One raw-source ASCII-space run and its intended visible-text owner."""

    start: int
    end: int
    scope: str  # ``title`` or ``prose``


@dataclasses.dataclass(frozen=True, slots=True)
class _TextSpaceEvidence:
    """Canonical tree plus eligible repeated-space counts by scope."""

    tree: object
    counts: TextSpaceCounts


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


def _editable_text_scope(node: docutils.nodes.Text) -> str | None:
    """Return the permitted editorial owner for a visible Text node.

    Paragraph and title descendants are eligible, including ordinary
    emphasis/strong/link labels.  Fixed-text and semantic inline constructs
    are protected: their spacing may be payload or lookup syntax rather than
    prose.  Attributes (notably link targets and generated ids) are compared
    separately by the tree model.
    """
    protected = (
        docutils.nodes.literal,
        docutils.nodes.math,
        docutils.nodes.raw,
        docutils.nodes.problematic,
        docutils.nodes.substitution_reference,
    )
    parent = node.parent
    while parent is not None:
        if isinstance(parent, protected):
            return None
        if isinstance(parent, docutils.nodes.title):
            return "title"
        if isinstance(parent, docutils.nodes.paragraph):
            return "prose"
        parent = parent.parent
    return None


def _text_space_evidence(path: pathlib.Path, text: str) -> _TextSpaceEvidence:
    """Build the permitted-delta model for one source variant.

    Eligible Text values are single-spaced in the comparison model while the
    number of original runs is retained separately.  Therefore an accepted
    edit must satisfy both predicates: identical canonical structure and an
    exact run-count reduction matching every proposed source edit.
    """
    document = _parse_rst(path, text=text)
    title_runs = 0
    prose_runs = 0

    def model(node: docutils.nodes.Node) -> object:
        nonlocal title_runs, prose_runs
        if isinstance(node, docutils.nodes.Text):
            value = str(node)
            scope = _editable_text_scope(node)
            if scope is not None:
                run_count = len(_TEXT_NODE_SPACES_RE.findall(value))
                if scope == "title":
                    title_runs += run_count
                else:
                    prose_runs += run_count
                value = _TEXT_NODE_SPACES_RE.sub(" ", value)
            return ("Text", value)

        attributes: object = ()
        if isinstance(node, docutils.nodes.Element):
            attributes = _freeze_node_attribute(node.attributes)
        return (
            node.__class__.__module__,
            node.__class__.__qualname__,
            attributes,
            tuple(model(child) for child in node.children),
        )

    return _TextSpaceEvidence(
        tree=model(document),
        counts=TextSpaceCounts(title_runs=title_runs, prose_runs=prose_runs),
    )


def _title_line_indexes(text: str) -> set[int]:
    """Return exact 0-based source lines owned by complete or short titles."""
    lines = text.splitlines()
    indexes = {block.index for block in iter_title_blocks(lines)}
    indexes.update(candidate.index - 1 for candidate in iter_underline_only(lines))
    return indexes


def _text_space_edits(
    text: str,
    *,
    collapse_titles: bool,
    single_space_prose: bool,
) -> list[_TextSpaceEdit]:
    """Collect internal ASCII-space candidates with source ownership labels."""
    title_lines = _title_line_indexes(text)
    edits: list[_TextSpaceEdit] = []
    offset = 0
    for line_index, physical_line in enumerate(text.splitlines(keepends=True)):
        line = physical_line[:-1] if physical_line.endswith("\n") else physical_line
        if line_index in title_lines:
            scope = "title" if collapse_titles else None
        else:
            scope = "prose" if single_space_prose else None
        if scope is not None:
            edits.extend(
                _TextSpaceEdit(offset + match.start(), offset + match.end(), scope)
                for match in _INTERNAL_ASCII_SPACES_RE.finditer(line)
            )
        offset += len(physical_line)
    return sorted(edits, key=lambda edit: edit.start, reverse=True)


def _apply_text_space_edits(text: str, edits: list[_TextSpaceEdit]) -> str:
    """Apply non-overlapping edits ordered from greatest source offset down."""
    result = text
    for edit in edits:
        result = result[: edit.start] + " " + result[edit.end :]
    return result


def _expected_text_space_counts(edits: list[_TextSpaceEdit]) -> TextSpaceCounts:
    return TextSpaceCounts(
        title_runs=sum(edit.scope == "title" for edit in edits),
        prose_runs=sum(edit.scope == "prose" for edit in edits),
    )


def _is_permitted_text_space_delta(
    before: _TextSpaceEvidence,
    after: _TextSpaceEvidence,
    edits: list[_TextSpaceEdit],
) -> bool:
    """Require unchanged structure plus one eligible Text delta per edit."""
    expected = _expected_text_space_counts(edits)
    return (
        before.tree == after.tree
        and before.counts.title_runs - after.counts.title_runs == expected.title_runs
        and before.counts.prose_runs - after.counts.prose_runs == expected.prose_runs
    )


def _apply_permitted_text_space_edits(
    path: pathlib.Path,
    text: str,
    edits: list[_TextSpaceEdit],
    before: _TextSpaceEvidence,
) -> tuple[str, TextSpaceCounts, _TextSpaceEvidence]:
    """Accept proven edit batches, bisecting mixed safe/unsafe candidates.

    Edits are descending by offset.  The higher-offset half is resolved first,
    so accepted shortening never invalidates offsets in the lower half.  This
    preserves per-source-edit provenance without paying one full parse for
    every candidate in the common all-safe case.
    """
    if not edits:
        return text, TextSpaceCounts(), before

    trial = _apply_text_space_edits(text, edits)
    after = _text_space_evidence(path, trial)
    if _is_permitted_text_space_delta(before, after, edits):
        return trial, _expected_text_space_counts(edits), after
    if len(edits) == 1:
        return text, TextSpaceCounts(), before

    midpoint = len(edits) // 2
    higher = edits[:midpoint]
    lower = edits[midpoint:]
    current, higher_counts, current_evidence = _apply_permitted_text_space_edits(
        path,
        text,
        higher,
        before,
    )
    current, lower_counts, current_evidence = _apply_permitted_text_space_edits(
        path,
        current,
        lower,
        current_evidence,
    )
    return current, higher_counts + lower_counts, current_evidence


def _normalize_text_spaces(
    path: pathlib.Path,
    text: str,
    *,
    collapse_titles: bool,
    single_space_prose: bool,
) -> tuple[str, TextSpaceCounts]:
    """Apply exactly the requested, structurally proven editorial deltas."""
    edits = _text_space_edits(
        text,
        collapse_titles=collapse_titles,
        single_space_prose=single_space_prose,
    )
    if not edits:
        return text, TextSpaceCounts()
    before = _text_space_evidence(path, text)
    normalized, counts, _after = _apply_permitted_text_space_edits(path, text, edits, before)
    return normalized, counts


def fix_text_spaces(
    path: pathlib.Path,
    *,
    collapse_titles: bool,
    single_space_prose: bool,
) -> TextSpaceCounts:
    """Write requested editorial text spacing and return accepted run counts."""
    text = _read_normalized(path)
    normalized, counts = _normalize_text_spaces(
        path,
        text,
        collapse_titles=collapse_titles,
        single_space_prose=single_space_prose,
    )
    if counts.total:
        path.write_text(normalized, encoding="utf-8", newline="\n")
    return counts


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


_BOLD_PREVIEW_LEN = 60

# --outline's own preview length for code-block/blockquote entries (Max,
# 2026-07-20) — deliberately separate from _BOLD_PREVIEW_LEN above (the
# bold-related findings' own text preview, default and --verbose alike):
# different feature, different reader, no reason the two should move
# together.
_OUTLINE_PREVIEW_LEN = 74


def _outline_preview(text: str) -> str:
    """Whitespace-collapsed, length-bounded content preview for --outline's
    code-block/blockquote entries: no leading/trailing or doubled internal
    spaces (any whitespace run, including newlines, collapses to one
    space), truncated with '...' when it doesn't fit — a quick identity,
    not the content."""
    collapsed = " ".join(text.split())
    if len(collapsed) > _OUTLINE_PREVIEW_LEN:
        collapsed = collapsed[:_OUTLINE_PREVIEW_LEN] + "..."
    return collapsed


# Known directive names for the mistyped-directive comment lint: docutils'
# own English directive-name mapping (derived, not hardcoded — includes
# aliases like 'code'/'code-block' equivalents docutils knows), plus the
# Sphinx directives common in this ecosystem.  'todo' is deliberately NOT
# in the supplement: '.. TODO: …' is an extremely common genuine-comment
# idiom, and flagging it would drown the signal in noise.
_SPHINX_DIRECTIVE_NAMES = frozenset(
    {
        "toctree",
        "code-block",
        "sourcecode",
        "literalinclude",
        "seealso",
        "index",
        "glossary",
        "only",
        "highlight",
        "versionadded",
        "versionchanged",
        "deprecated",
        "centered",
        "hlist",
    }
)
_KNOWN_DIRECTIVE_NAMES = frozenset(docutils.parsers.rst.languages.en.directives) | _SPHINX_DIRECTIVE_NAMES

# First line of a comment that looks like a directive typed with ONE colon:
# 'code: bash', 'note:', 'toctree:pages'.  (?!:) exists only for symmetry —
# a valid 'name::' line would have parsed as a directive, not a comment.
_MISTYPED_DIRECTIVE_RE = re.compile(r"([\w-]+):(?!:)")

# Shared by Document.prose_text and check_homoglyphs: what counts as
# author-facing prose rather than markup apparatus.  Code, comments, raw
# passthrough, and generated topics (a '.. contents::' directive's own
# title) are not something an author "wrote" as content — see
# Document.prose_text's docstring for the system_message/parser-vocabulary
# story that motivated the last entry.
_NON_PROSE_NODE_TYPES = (
    docutils.nodes.literal_block,
    docutils.nodes.comment,
    docutils.nodes.raw,
    docutils.nodes.topic,
    docutils.nodes.system_message,
)

# Hand-curated, explicit — "declaration, not auto-detection," the same
# precedent as PREFERRED_HIERARCHY/_KNOWN_DIRECTIVE_NAMES.  No installed
# library provides this on this system (confirmed by direct probe,
# 2026-07-26: confusable_homoglyphs, fontTools, regex, unicodedata2 are all
# absent, and stdlib unicodedata itself has no confusables data at all —
# checked decomposition() for every pair below, none decompose to anything,
# since the visual-twin relationship is encoded ONLY in Unicode's separate
# security-mechanisms data (UTS #39), which nothing installed here exposes).
# Scoped to Cyrillic<->Latin specifically — the only two scripts this
# corpus's Russian/French/English mixing ever produces.  Each pair is a
# genuine glyph-identical or near-identical twin, not a judgment call.
# Every key intentionally triggers the rule this table helps diagnose; keep
# per-line suppressions so RUF001 remains active everywhere else in this file.
_CYRILLIC_LATIN_CONFUSABLES: dict[str, str] = {
    "а": "a",  # noqa: RUF001
    "е": "e",  # noqa: RUF001
    "о": "o",  # noqa: RUF001
    "р": "p",  # noqa: RUF001
    "с": "c",  # noqa: RUF001
    "у": "y",  # noqa: RUF001
    "х": "x",  # noqa: RUF001
    "А": "A",  # noqa: RUF001
    "В": "B",  # noqa: RUF001
    "Е": "E",  # noqa: RUF001
    "К": "K",  # noqa: RUF001
    "М": "M",  # noqa: RUF001
    "Н": "H",  # noqa: RUF001
    "О": "O",  # noqa: RUF001
    "Р": "P",  # noqa: RUF001
    "С": "C",  # noqa: RUF001
    "Т": "T",  # noqa: RUF001
    "Х": "X",  # noqa: RUF001
}
_CONFUSABLE_CHARS = frozenset(_CYRILLIC_LATIN_CONFUSABLES) | frozenset(_CYRILLIC_LATIN_CONFUSABLES.values())

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _char_script(ch: str) -> str | None:
    """Return 'CYRILLIC'/'LATIN' for a letter in either script, else None
    (digits, punctuation, other scripts) — a name-substring proxy, since
    stdlib unicodedata exposes no direct Script property."""
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return None
    if "CYRILLIC" in name:
        return "CYRILLIC"
    if "LATIN" in name:
        return "LATIN"
    return None


def _homoglyph_words_in(text: str) -> Iterator[tuple[int, int, str]]:
    """Yield (start, end, word) for each word in *text* mixing Cyrillic and
    Latin letters where EVERY minority-script letter is a known visual twin
    of a majority-script one (Max, 2026-07-24: "when letters look similar,
    but only one letter is from another alphabet").

    Never flagged merely for mixing scripts — confirmed by real corpus
    evidence (2026-07-26) that mixing alone is too common to be a signal
    (this Journal is deliberately trilingual) and that the "every minority
    letter must be confusable" condition is exactly what separates real
    typos ('Аuthor', 'Сalibration') from legitimate constructions ('VPNом',
    a Latin acronym plus a Cyrillic case ending — 'м' has no Latin twin;
    'jьmati', Proto-Slavic notation — 'ь' has no Latin twin either).  A
    tied majority/minority split is skipped as genuinely ambiguous, not
    guessed at.
    """  # noqa: RUF002
    for m in _WORD_RE.finditer(text):
        word = m.group(0)
        by_script: dict[str, list[str]] = {}
        for ch in word:
            script = _char_script(ch)
            if script is not None:
                by_script.setdefault(script, []).append(ch)
        if len(by_script) != 2:
            continue
        chars_by_size = sorted(by_script.values(), key=len)
        minority_chars, majority_chars = chars_by_size[0], chars_by_size[1]
        if len(minority_chars) == len(majority_chars):
            continue
        if all(ch in _CONFUSABLE_CHARS for ch in minority_chars):
            yield m.start(), m.end(), word


def check_homoglyphs(path: pathlib.Path, doc: Document | None = None) -> list[Finding]:
    """Flag a word mixing Cyrillic and Latin letters that are visual twins
    — a keyboard-layout slip, not intentional content (see
    _homoglyph_words_in for the precise rule).

    Scans the same author-facing prose Text nodes as Document.prose_text
    (_NON_PROSE_NODE_TYPES) — code, comments, raw passthrough, and
    generated topics are apparatus, not something an author "wrote" as
    prose, so a confusable-looking identifier inside a code-block must
    never be flagged.  Unlike check_directives' bold/rubric exemption,
    block_quote content is NOT skipped: a garbled word is still garbled
    regardless of who originally typed it.

    lineno is the exact physical line, not merely the enclosing
    paragraph's first line: a docutils Text node spans its WHOLE
    paragraph, so the count of embedded newlines up to the match's own
    offset is added to _node_line's base — more precise than
    check_directives bothers to be, because a bold/rubric node is always
    short while a homoglyph can be anywhere in a long paragraph.
    """
    document = _resolve_document(path, doc)
    findings: list[Finding] = []
    for text_node in document.doctree.findall(docutils.nodes.Text):
        node: docutils.nodes.Node | None = text_node.parent
        skipped = False
        while node is not None:
            if isinstance(node, _NON_PROSE_NODE_TYPES):
                skipped = True
                break
            node = node.parent
        if skipped:
            continue
        s = str(text_node)
        base_line = _node_line(text_node)
        for start, _end, word in _homoglyph_words_in(s):
            lineno = base_line + s[:start].count("\n")
            findings.append(
                Finding(
                    lineno,
                    Severity.WARNING,
                    f"{word!r} mixes Cyrillic and Latin letters that look "
                    "identical — probably a keyboard-layout slip, not "
                    "intentional",
                )
            )
    return findings


_INLINE_CONTAINER_TYPES = (docutils.nodes.strong, docutils.nodes.emphasis, docutils.nodes.literal)


def _findall_node_types(
    root: docutils.nodes.Node,
    node_types: tuple[type[docutils.nodes.Node], ...],
) -> Iterator[docutils.nodes.Node]:
    """Yield descendants matching *node_types* across supported docutils.

    Docutils 0.23 accepts a tuple of classes directly as ``Node.findall``'s
    condition, while 0.22 accepts only one class or a callable.  The callable
    form has identical behavior on both versions and keeps the PyPI-compatible
    Sphinx stack and Gentoo's newer docutils stack on one code path.
    """
    yield from root.findall(lambda node: isinstance(node, node_types))


def _inline_kind(node: docutils.nodes.Node) -> str:
    """Return an author-facing name for an inline node kind."""
    if isinstance(node, docutils.nodes.strong):
        return "bold"
    if isinstance(node, docutils.nodes.emphasis):
        return "emphasis"
    if isinstance(node, docutils.nodes.literal):
        return "inline literal"
    if isinstance(node, docutils.nodes.title_reference):
        return "interpreted text"
    return type(node).__name__.replace("_", " ")


def _is_implicit_reference(node: docutils.nodes.Node) -> bool:
    """True for URI/email recognition that used no inline-markup syntax.

    Inliner.parse deliberately performs implicit recognition after explicit
    markup.  A URL inside ``literal text`` therefore becomes a reference node
    when re-parsed, but no nested delimiters or role were present.  Its
    refuri plus rawsource==visible-text shape distinguishes it from explicit
    named, phrase, and embedded-link references.
    """
    return isinstance(node, docutils.nodes.reference) and "refuri" in node and str(node.rawsource) == str(node.astext())


def _nested_inline_nodes(
    outer: docutils.nodes.Node,
    document: docutils.nodes.document,
) -> tuple[docutils.nodes.Node, ...]:
    """Re-parse one outer inline span and return explicit inner constructs.

    This is intentionally docutils' Inliner, not a delimiter regex: its own
    whitespace, escape, role, and end-string predicates decide whether the
    leftover text is valid inline markup.  The probe uses a fresh document so
    references/targets discovered during re-parse cannot mutate the real
    doctree's registries or influence later checks.

    Problematic nodes represent invalid or unmatched syntax, not a complete
    nested construct.  Implicit URI/email links are excluded separately by
    _is_implicit_reference because recognition alone does not prove source
    markup was nested.
    """
    CALL_COUNTS["_nested_inline_reparse"] += 1
    probe = docutils.utils.new_document(f"{document.get('source', '<string>')}:inline-probe", document.settings)
    inliner = docutils.parsers.rst.states.Inliner()
    inliner.init_customizations(probe.settings)
    language = docutils.parsers.rst.languages.get_language(probe.settings.language_code, probe.reporter)
    memo = docutils.parsers.rst.states.Struct(
        document=probe,
        reporter=probe.reporter,
        language=language,
        title_styles=[],
        section_level=0,
        section_bubble_up_kludge=False,
        inliner=inliner,
    )
    reparsed, _messages = inliner.parse(str(outer.astext()), _inline_node_line(outer), memo, probe)
    return tuple(
        node
        for node in reparsed
        if not isinstance(node, (docutils.nodes.Text, docutils.nodes.problematic)) and not _is_implicit_reference(node)
    )


def check_nested_inline_markup(
    path: pathlib.Path,
    whole_file: bool,
    doc: Document | None = None,
) -> list[Finding]:
    """Warn when one RST inline role silently contains another.

    RST inline markup never nests: docutils keeps the inner delimiters as the
    outer node's text.  Re-parsing that residual text with Inliner detects the
    real grammar rather than approximating it, in either nesting direction and
    regardless of paragraph position.  Warnings are semantic: RST cannot
    preserve both roles, so choosing which one survives is not auto-fixable.
    """
    document = _resolve_document(path, doc)
    ranges: list[tuple[int, int]] | None = None if whole_file else document.ranges
    findings: list[Finding] = []
    for outer in _findall_node_types(document.doctree, _INLINE_CONTAINER_TYPES):
        nested = document.nested_inline_by_node.get(id(outer), ())
        if not nested:
            continue
        lineno = _inline_node_line(outer)
        if not _in_scope(ranges, lineno, lineno):
            continue
        source = " ".join(str(outer.rawsource).split())
        if len(source) > _BOLD_PREVIEW_LEN:
            source = source[:_BOLD_PREVIEW_LEN] + "…"
        inner_kinds = ", ".join(dict.fromkeys(_inline_kind(node) for node in nested))
        findings.append(
            Finding(
                lineno=lineno,
                severity=Severity.WARNING,
                text=(f"nested inline markup in {_inline_kind(outer)} span {source!r} (contains {inner_kinds})"),
            )
        )
    return findings


def check_directives(
    path: pathlib.Path,
    whole_file: bool,
    verbose: bool = False,
    doc: Document | None = None,
) -> list[Finding]:
    """Detect heading-substitute patterns using the docutils AST.

    Content inside literal blocks (``.. code-block::``, ``::`` paragraphs,
    ``.. doctest::``, ``.. parsed-literal::``) is skipped entirely via
    SkipNode in visit_literal_block — no false positives from code examples.

    All findings have severity WARNING — they require human judgement and do
    not affect the exit code.  Use --no-warnings to suppress them.

    With verbose=True, findings additionally report the actual bold/rubric
    text, a preview of the paragraph text following a bold opener, and the
    title of the nearest enclosing section — none of that detail is computed
    or shown by default.
    """
    document = _resolve_document(path, doc)
    ranges: list[tuple[int, int]] | None = None if whole_file else document.ranges
    doc_tree = document.doctree
    findings: list[Finding] = []
    # A leading/standalone bold span with broken nested markup used to be
    # misdiagnosed as a heading substitute.  The more specific syntax warning
    # must own those nodes: promoting one to a section cannot restore the inner
    # styling that docutils discarded.
    nested_strong_ids = set(document.nested_inline_by_node)

    def warn(node: docutils.nodes.Node, text: str) -> None:
        lineno = _node_line(node)
        if _in_scope(ranges, lineno, lineno):
            findings.append(Finding(lineno=lineno, severity=Severity.WARNING, text=text))

    def section_clause(node: docutils.nodes.Node) -> str:
        title = _enclosing_section_title(node)
        return f"in section {title!r}" if title is not None else "(no enclosing section)"

    class _Visitor(docutils.nodes.NodeVisitor):  # type: ignore[misc]
        # docutils ships no stubs: NodeVisitor resolves as Any, so mypy
        # can't verify this subclass at all — narrowest possible ignore,
        # not a broader docutils.* override change (pyproject.toml already
        # has one, scoped to missing-import only, not to Any-flow errors
        # like this).
        def unknown_visit(self, node: docutils.nodes.Node) -> None:
            pass

        def unknown_departure(self, node: docutils.nodes.Node) -> None:
            pass

        def visit_literal_block(self, node: docutils.nodes.Node) -> None:
            # Skip the entire subtree — content is literal text, not RST structure.
            raise docutils.nodes.SkipNode

        def visit_block_quote(self, node: docutils.nodes.Node) -> None:
            # Skip the entire subtree — an indented blockquote is quoted
            # material (an AI's answer, an email body), not the author's own
            # prose, so nothing inside it (bold OR rubric) is a
            # heading-substitute candidate: promoting would de-indent the
            # quote, misrepresenting a quotation as original structure.
            # Found via a real corpus false positive: 2026-05-02/2026-05-12
            # Notes.rst flagged bold sub-headers inside a quoted
            # answer/email.  KNOWN, ACCEPTED limitation: RST turns any
            # accidentally indented paragraph into a blockquote, so a merely
            # mis-indented pseudo-heading is exempt too — quotation intent
            # is not detectable; in this corpus indented material is
            # overwhelmingly genuine quotation.
            raise docutils.nodes.SkipNode

        def visit_comment(self, node: docutils.nodes.Node) -> None:
            # A single-colon '.. name: …' is a perfectly legal comment, so a
            # mistyped directive silently HIDES its content instead of
            # rendering it — and no phase flags it otherwise: comments are
            # valid RST, so Sphinx and docutils are correctly silent (found
            # via a real '.. code: bash' typo in a calendar note,
            # 2026-07-18).  Warn when the comment's first line starts with a
            # known directive name followed by a single colon.
            first = node.astext().split("\n", 1)[0]
            m = _MISTYPED_DIRECTIVE_RE.match(first)
            if m and m.group(1).lower() in _KNOWN_DIRECTIVE_NAMES:
                name = m.group(1)
                warn(
                    node,
                    f"comment '.. {name}: …' looks like a mistyped directive — "
                    "a single colon makes it a comment that silently hides "
                    f"its content; did you mean '.. {name}::'?",
                )
            raise docutils.nodes.SkipNode

        def visit_rubric(self, node: docutils.nodes.Node) -> None:
            if verbose:
                warn(
                    node,
                    f"'.. rubric:: {node.astext()}' detected {section_clause(node)} — "
                    "verify it is not substituting a section title (rubric is "
                    "excluded from the ToC and cannot be :ref:-ed)",
                )
            else:
                warn(
                    node,
                    "'.. rubric::' detected — verify it is not substituting a section "
                    "title (rubric is excluded from the ToC and cannot be :ref:-ed)",
                )

        def visit_strong(self, node: docutils.nodes.Node) -> None:
            if id(node) in nested_strong_ids:
                return
            parent = node.parent
            if not isinstance(parent, docutils.nodes.paragraph):
                return  # bold inside a title, term, etc. — not a heading substitute
            # NOT exempt merely for being inside a list item (reversed Max,
            # 2026-07-20: "check_rst must warn about those bold texts... it's
            # up to the AI - accept or not").  A bold paragraph opener is the
            # same AI-writing habit whether wrapped in a list item or not —
            # confirmed the hard way: this project independently judged two
            # such lists worth converting to real subsections THIS SAME
            # SESSION, which the old blanket exemption would have silenced.
            # There is no tree-shape test that tells a short "term:" label
            # apart from a full bold-sentence-plus-prose opener — both are
            # "bold first child, more children follow" — so neither is
            # auto-exempt; the tool flags, the human/AI decides, uniformly.
            # The bold text itself, bounded — every finding must name what
            # it is actually flagging (Max, 2026-07-20: "without informing
            # the original text, it's hard to judge in one step" — a
            # multi-finding review pass needs to tell 19 identical-looking
            # findings apart without opening the file for each).  Every
            # OTHER directive finding already does this by default (rubric
            # shows its own text, the mistyped-directive warning shows the
            # actual name); bold was the inconsistent one, printing the
            # same placeholder for every occurrence.
            text = node.astext()
            if len(text) > _BOLD_PREVIEW_LEN:
                text = text[:_BOLD_PREVIEW_LEN] + "…"
            # The rationale ("AI documents often use...") is NOT repeated
            # per finding any more (Max, 2026-07-20: "it repeats... long.
            # Can we inform this as a separate line only once?" — the same
            # "state shared context once, not per entry" principle as the
            # outline's levels: legend).  _print_findings prints it once
            # per run, the first time each of these two prefixes appears —
            # see _FINDING_HINTS.
            if len(parent.children) == 1:
                if verbose:
                    warn(node, f"standalone bold line {text!r} {section_clause(node)}")
                else:
                    warn(node, f"standalone bold line {text!r}")
            elif parent.children[0] is node:
                if verbose:
                    rest = "".join(c.astext() for c in parent.children[1:]).strip()
                    if len(rest) > _BOLD_PREVIEW_LEN:
                        rest = rest[:_BOLD_PREVIEW_LEN] + "…"
                    warn(node, f"bold paragraph opener {text!r} followed by {rest!r} {section_clause(node)}")
                else:
                    warn(node, f"bold paragraph opener {text!r}")

    doc_tree.walkabout(_Visitor(doc_tree))
    return findings


# ---------------------------------------------------------------------------
# Phase 1c — Outline (--outline; informational, never affects exit code)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class OutlineEntry:
    """A single section heading, as reported by --outline.

    children is the number of DIRECT subsections — shown only when
    non-zero, so each outline line is self-contained data (an AI or a
    grep consuming lines individually doesn't have to reconstruct the
    tree to know a section has children), while leaf entries keep the
    exact historical format.

    docname (2026-07-26): set only for a heading recursively pulled in
    from ANOTHER file via find_toctrees — the first entry kind whose
    items can point outside the file being outlined.  Empty/None for
    every local heading, matching every OutlineEntry ever constructed
    before this field existed.  A cross-file heading reuses this SAME
    class deliberately, not a separate one: --sections-only's own
    ``isinstance(e, OutlineEntry)`` filter must keep it (it is a real
    section, just from elsewhere), while the toctree CONTAINER marker
    (ToctreeEntry) is correctly treated as a leaf and hidden — caught
    before implementation began (Max: "--sections-only shouldn't stop
    treating toctree elements").
    """

    lineno: int
    depth: int
    char: str
    title: str
    children: int = 0
    end: int = 0  # last line of the section's content (its extent)
    docname: str | None = None

    def __str__(self) -> str:
        return self.formatted()

    def formatted(self, extra: list[str] | None = None) -> str:
        # Lean format: line RANGE, adornment CHAR, then title (Max,
        # 2026-07-19: "inform the range, not only the start" — the extent
        # is what a follow-up sed/Read needs, previously re-derived from
        # the NEXT entry).  Depth is the indentation (4 spaces per level —
        # recoverable from a lone grepped line).
        #
        # The char WAS omitted here (2026-07-18: "repeating it on every
        # entry was pure noise", relying on the per-document legend
        # instead) — reversed 2026-07-20 after repeated real mistakes
        # writing a NEW heading's placeholder: choosing the adornment
        # character correctly means knowing the established char at that
        # EXACT depth, and cross-referencing the legend against indentation
        # in a large, evolving document is exactly the kind of counting
        # task an LLM is unreliable at — the same class of problem the
        # tool exists to take off the AI's hands for adornment LENGTH.
        # Now every grepped line carries its own answer directly, no
        # legend cross-reference needed: pick the char shown on the line
        # you want to add a sibling under.
        #
        # extra: additional bracket items beyond the subsection count (Max,
        # 2026-07-20) — e.g. nested code-block/blockquote totals, which this
        # entry alone can't know (they come from OTHER entries' line ranges),
        # so _print_outline_entries computes and passes them in; plain str()
        # stays self-contained with subsections only.
        indent = "    " * (self.depth - 1)
        pos = f"{self.lineno}-{self.end}" if self.end > self.lineno else f"{self.lineno}"
        if self.docname:
            pos = f"{self.docname}:{pos}"
        base = f"{indent}{pos}:{self.char} {self.title}"
        parts = []
        if self.children:
            plural = "s" if self.children != 1 else ""
            parts.append(f"{self.children} subsection{plural}")
        if extra:
            parts.extend(extra)
        if parts:
            return f"{base} [{', '.join(parts)}]"
        return base

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return item in str(self)


def build_outline(
    path: pathlib.Path,
    doc: Document | None = None,
    doctree: docutils.nodes.document | None = None,
) -> list[OutlineEntry]:
    """Return every section heading in *path*, in document order.

    depth is this document's own nesting depth (1 = top-level), as docutils
    itself resolved it from first-appearance order — independent of
    check_hierarchy's own HIERARCHY ranking, so the same character can
    legitimately report a different depth in a different file.
    char is the literal adornment character read back from the source at
    the title's underline. Always whole-document — outline context is never
    scoped to changed lines, unlike Finding-producing checks.
    """
    document = _resolve_document(path, doc)
    tree = doctree if doctree is not None else document.doctree
    lines = document.lines
    raw: list[tuple[int, int, str, str, int, int]] = []  # (+ block_start)
    for sec in tree.findall(docutils.nodes.section):
        title_node = sec.children[0]
        underline_row = title_node.line  # docutils reports the underline's 1-based line
        if not isinstance(underline_row, int):
            continue
        title_row = underline_row - 1
        underline_idx = underline_row - 1
        char = "?"
        if 0 <= underline_idx < len(lines):
            underline = lines[underline_idx].strip()
            if _is_adornment(underline):
                char = underline[0]
        depth = 1
        n: docutils.nodes.Node | None = sec.parent
        while n is not None:
            if isinstance(n, docutils.nodes.section):
                depth += 1
            n = n.parent
        children = 0
        for candidate in sec.findall(docutils.nodes.section):
            if candidate is sec:
                continue
            parent = candidate.parent
            while parent is not None and not isinstance(parent, docutils.nodes.section):
                parent = parent.parent
            if parent is sec:
                children += 1
        # The section's block starts at the overline when present — the
        # boundary the PREVIOUS section's extent must stop before.
        has_overline = title_row >= 2 and _is_adornment(lines[title_row - 2].strip())
        block_start = title_row - 1 if has_overline else title_row
        raw.append((title_row, depth, char, title_node.astext(), children, block_start))

    # Extents: a section runs to the line before the next same-or-shallower
    # section's block (findall order is document order), or to EOF; trailing
    # blank separator lines are trimmed.
    entries: list[OutlineEntry] = []
    for i, (title_row, depth, char, title, children, _bs) in enumerate(raw):
        nxt = next((r for r in raw[i + 1 :] if r[1] <= depth), None)
        end = (nxt[5] - 1) if nxt is not None else len(lines)
        while end > title_row and not lines[end - 1].strip():
            end -= 1
        entries.append(OutlineEntry(title_row, depth, char, title, children, end))
    return entries


@dataclasses.dataclass(frozen=True, slots=True)
class CodeBlockEntry:
    """A single real `.. code-block::` directive, as reported by --outline.

    preview is a limited beginning of the block's own content — one
    collapsed line, truncated — the same quick-identity contract as
    BlockQuoteEntry.preview (Max, 2026-07-20: "let's add the beginning of
    the block to the line about it")."""

    lineno: int
    depth: int
    language: str | None
    preview: str = ""
    end: int = 0  # last line of the directive's indented content

    def __str__(self) -> str:
        indent = "    " * (self.depth - 1)
        lang = self.language if self.language is not None else "no language"
        pos = f"{self.lineno}-{self.end}" if self.end > self.lineno else f"{self.lineno}"
        base = f"{indent}{pos}: code-block ({lang})"
        return f"{base}: {self.preview}" if self.preview else base

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return item in str(self)


@dataclasses.dataclass(frozen=True, slots=True)
class BlockQuoteEntry:
    """A single blockquote, as reported by --outline.

    Quote zones are semantically significant since the blockquote
    exemption (nothing inside them is ever a heading-substitute finding):
    seeing them in the outline explains absent warnings and shows
    composition — a note that is 80% quotation reads differently from one
    that is 80% original prose.  preview is a limited beginning of the
    quote's text — one collapsed line, ellipsis-truncated — a quick
    identity, not the content.
    """

    lineno: int
    depth: int
    preview: str
    end: int = 0  # last line of the quoted block

    def __str__(self) -> str:
        indent = "    " * (self.depth - 1)
        pos = f"{self.lineno}-{self.end}" if self.end > self.lineno else f"{self.lineno}"
        return f'{indent}{pos}: blockquote "{self.preview}"'

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return item in str(self)


@dataclasses.dataclass(frozen=True, slots=True)
class AdmonitionEntry:
    """A ``.. note::``/``.. warning::``/etc. admonition, as reported by
    --outline.

    kind is the directive name docutils resolved: one of the 9 named
    admonitions (attention, caution, danger, error, hint, important,
    note, tip, warning) or the generic ``admonition``.  title is the
    generic form's own ``.. admonition:: Title`` argument — the other
    nine never have one, matching a table's optional caption.  preview
    is the body's own content, collapsed and truncated exactly like
    blockquote/code-block/table's own preview — the whole body is the
    input, not just its first line."""

    lineno: int
    depth: int
    kind: str
    title: str | None
    preview: str
    end: int = 0

    def __str__(self) -> str:
        indent = "    " * (self.depth - 1)
        pos = f"{self.lineno}-{self.end}" if self.end > self.lineno else f"{self.lineno}"
        base = f"{indent}{pos}: admonition ({self.kind})"
        if self.title:
            base += f', "{self.title}"'
        return f"{base}: {self.preview}" if self.preview else base

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return item in str(self)


def find_admonitions(path: pathlib.Path, doc: Document | None = None) -> list[AdmonitionEntry]:
    """Return every admonition in *path*, in document order.

    Bare docutils, like find_block_quotes/find_tables — a real Sphinx
    build adds no admonition-type information beyond what bare docutils
    already resolves (docutils.nodes.Admonition covers all 10 kinds
    uniformly), so there is no verified/heuristic split.  depth is
    _block_depth — enclosing sections AND enclosing list nesting, same
    as every other entry kind (2026-07-26).  Found live (2026-07-22):
    a ".. important::" tl;dr this project itself wrote for
    check_rst.rst was entirely invisible to --outline — docutils parses
    it fine, check_rst simply had no entry kind for it.
    """
    document = _resolve_document(path, doc)
    lines = document.lines
    entries: list[AdmonitionEntry] = []
    for node in document.doctree.findall(docutils.nodes.Admonition):
        depth = _block_depth(node)

        title: str | None = None
        body_children = node.children
        if body_children and isinstance(body_children[0], docutils.nodes.title):
            title = body_children[0].astext()
            body_children = body_children[1:]

        preview = _outline_preview(" ".join(c.astext() for c in body_children))
        start = _node_line(node)
        entries.append(
            AdmonitionEntry(
                start,
                depth,
                node.__class__.__name__,
                title,
                preview,
                _indented_extent(lines, start),
            )
        )
    return entries


def find_block_quotes(path: pathlib.Path, doc: Document | None = None) -> list[BlockQuoteEntry]:
    """Return every top-level blockquote in *path*, in document order.

    Bare docutils — blockquotes need no Sphinx environment, so unlike
    code-blocks there is no verified/heuristic split: the same function
    serves both --outline modes.  A quote nested inside another quote is
    not reported separately (the outer entry's preview covers the
    subtree).  depth is _block_depth — enclosing sections AND enclosing
    list nesting, same as every other entry kind (2026-07-26).
    """
    document = _resolve_document(path, doc)
    entries: list[BlockQuoteEntry] = []
    for bq in document.doctree.findall(docutils.nodes.block_quote):
        n: docutils.nodes.Node | None = bq.parent
        nested = False
        while n is not None:
            if isinstance(n, docutils.nodes.block_quote):
                nested = True
                break
            n = n.parent
        if nested:
            continue
        depth = _block_depth(bq)
        preview = _outline_preview(bq.astext())
        start = _node_line(bq)
        entries.append(BlockQuoteEntry(start, depth, preview, _indented_extent(document.lines, start)))
    return entries


@dataclasses.dataclass(frozen=True, slots=True)
class CommentEntry:
    """A single comment (``.. text`` with no ``::``), as reported by
    --outline.

    The mistyped-directive WARNING (visit_comment, above) can only ever
    catch what it recognizes — a known directive name typo'd with a
    single colon on the comment's first line.  A typo of an unlisted
    name, or one buried past the first line, stays invisible to that
    heuristic (Max, 2026-07-22: "we cannot cover all cases... they could
    be more complex cases").  Showing every comment in --outline, same
    as blockquote/code-block/table/admonition, closes that blind spot
    generically instead of chasing more regex cases.  suspicious reuses
    the exact same heuristic as the WARNING, so the flagged case is
    visible right next to its own text instead of a separate,
    disconnected report.
    """

    lineno: int
    depth: int
    preview: str
    suspicious: bool
    end: int = 0

    def __str__(self) -> str:
        indent = "    " * (self.depth - 1)
        pos = f"{self.lineno}-{self.end}" if self.end > self.lineno else f"{self.lineno}"
        base = f'{indent}{pos}: comment "{self.preview}"'
        if self.suspicious:
            base += " [suspicious — looks like a mistyped directive]"
        return base

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return item in str(self)


def find_comments(path: pathlib.Path, doc: Document | None = None) -> list[CommentEntry]:
    """Return every comment in *path*, in document order.

    Bare docutils, same as blockquotes/admonitions/tables — no verified/
    heuristic split.
    """
    document = _resolve_document(path, doc)
    lines = document.lines
    entries: list[CommentEntry] = []
    for node in document.doctree.findall(docutils.nodes.comment):
        depth = _block_depth(node)

        text = node.astext()
        first = text.split("\n", 1)[0]
        m = _MISTYPED_DIRECTIVE_RE.match(first)
        suspicious = bool(m and m.group(1).lower() in _KNOWN_DIRECTIVE_NAMES)

        preview = _outline_preview(text)
        start = _node_line(node)
        entries.append(CommentEntry(start, depth, preview, suspicious, _indented_extent(lines, start)))
    return entries


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


def _enum_marker(node: docutils.nodes.Node, position: int) -> str:
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


@dataclasses.dataclass(frozen=True, slots=True)
class ListEntry:
    """A bullet list, enumerated list, or definition list, as reported by
    --outline (Max, 2026-07-26).

    Two-level for bullet/enumerated lists: a CONTAINER entry for the
    whole list (item_count set, marker is the bullet character or the
    first item's rendered numeral, depth = enclosing_section_depth+1)
    and one entry per ITEM nested one level deeper (item_count=None,
    marker/preview specific to that item) — so --outline-depth can hide
    a long list's individual items while keeping the list's own
    existence and count visible, the same "depth trims display, never
    information" contract sections already use.  Definition lists are
    flatter (Max: "one entry per item"): each definition_list_item
    stands alone with no container — marker is the item's own term
    text, the natural per-item unit since every item has a genuinely
    distinct term (unlike a bullet list's one shared bullet character),
    the same title+body shape as AdmonitionEntry (term=title,
    definition=body).
    """

    lineno: int
    depth: int
    kind: str  # "bullet", "enumerated", "definition"
    marker: str
    preview: str
    item_count: int | None = None  # set only on a bullet/enumerated container
    end: int = 0

    def __str__(self) -> str:
        indent = "    " * (self.depth - 1)
        pos = f"{self.lineno}-{self.end}" if self.end > self.lineno else f"{self.lineno}"
        if self.item_count is not None:
            plural = "s" if self.item_count != 1 else ""
            return f"{indent}{pos}: {self.kind} list ({self.marker!r}, {self.item_count} item{plural})"
        base = f'{indent}{pos}: "{self.marker}"' if self.kind == "definition" else f"{indent}{pos}: {self.marker}"
        return f"{base}: {self.preview}" if self.preview else base

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return item in str(self)


def find_lists(path: pathlib.Path, doc: Document | None = None) -> list[ListEntry]:
    """Return every bullet/enumerated/definition list in *path*, in
    document order — bare docutils, no verified/heuristic split, same as
    blockquotes/admonitions/tables/comments."""
    document = _resolve_document(path, doc)
    lines = document.lines
    entries: list[ListEntry] = []

    for node in document.doctree.findall(docutils.nodes.bullet_list):
        container_depth = _block_depth(node)
        items = list(node.children)
        container_start = _node_line(node)
        container_end = _indented_extent(lines, _node_line(items[-1])) if items else container_start
        bullet = node.get("bullet", "*")
        entries.append(
            ListEntry(
                container_start,
                container_depth,
                "bullet",
                bullet,
                "",
                item_count=len(items),
                end=container_end,
            )
        )
        for item in items:
            start = _node_line(item)
            entries.append(
                ListEntry(
                    start,
                    container_depth + 1,
                    "bullet",
                    bullet,
                    _outline_preview(item.astext()),
                    end=_indented_extent(lines, start),
                )
            )

    for node in document.doctree.findall(docutils.nodes.enumerated_list):
        container_depth = _block_depth(node)
        items = list(node.children)
        container_start = _node_line(node)
        container_end = _indented_extent(lines, _node_line(items[-1])) if items else container_start
        first_marker = _enum_marker(node, 0)
        entries.append(
            ListEntry(
                container_start,
                container_depth,
                "enumerated",
                first_marker,
                "",
                item_count=len(items),
                end=container_end,
            )
        )
        for position, item in enumerate(items):
            start = _node_line(item)
            entries.append(
                ListEntry(
                    start,
                    container_depth + 1,
                    "enumerated",
                    _enum_marker(node, position),
                    _outline_preview(item.astext()),
                    end=_indented_extent(lines, start),
                )
            )

    for node in document.doctree.findall(docutils.nodes.definition_list_item):
        depth = _block_depth(node)
        term, definition = node.children[0], node.children[1]
        start = _node_line(node)
        entries.append(
            ListEntry(
                start,
                depth,
                "definition",
                term.astext(),
                _outline_preview(definition.astext()),
                end=_indented_extent(lines, start),
            )
        )

    return entries


@dataclasses.dataclass(frozen=True, slots=True)
class TableEntry:
    """A single table, as reported by --outline.

    kind is the RST/Sphinx syntax that produced it — 'grid', 'simple',
    'table', 'list', or 'csv' — recovered by scanning the raw source: the
    docutils/Sphinx doctree keeps NO trace of which syntax produced a
    table node (confirmed directly: a grid table, a simple table, and the
    table/list-table/csv-table directives all produce the identical
    <table><tgroup>... shape, even under a real Sphinx build), so this is
    the one fact that only the source text still carries.  dims is
    (rows, cols) — the rows-x-columns convention (matrix notation, NumPy/
    pandas .shape, spreadsheet "RxC"), not cols-x-rows.  caption is the
    table's own title, if any (the '.. table::'/'.. list-table::'/
    '.. csv-table::' directive argument, or docutils' own <title> child)
    — None when the table has none.  preview chains every row's cells in
    document order ("A1 A2 A3 B1 B2 B3 ...", header row first when one
    exists) into a single line, then collapses and truncates it exactly
    like code-block's own preview (Max, 2026-07-20: "the same principle
    as for snippets for code blocks") — the WHOLE table's content is the
    input, same as a code-block's whole body, not just its first row."""

    lineno: int
    depth: int
    kind: str
    dims: tuple[int, int]
    caption: str | None
    preview: str
    end: int = 0

    def __str__(self) -> str:
        indent = "    " * (self.depth - 1)
        pos = f"{self.lineno}-{self.end}" if self.end > self.lineno else f"{self.lineno}"
        rows, cols = self.dims
        base = f"{indent}{pos}: Table ({self.kind}, {rows}x{cols})"
        if self.caption:
            base += f', "{self.caption}"'
        return f"{base}: {self.preview}" if self.preview else base

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return item in str(self)


# Directive-based tables carry their own syntax name in the source; bare
# grid/simple tables don't, so kind falls back to the border/rule shape.
_TABLE_DIRECTIVE_RE = re.compile(r"\.\.\s+(table|list-table|csv-table)::")
_TABLE_DIRECTIVE_KIND = {"table": "table", "list-table": "list", "csv-table": "csv"}
_GRID_TABLE_BORDER_RE = re.compile(r"^[ \t]*\+[-+]+\+[ \t]*$")
# 2+ '='-runs separated by whitespace — never a bare section underline
# (a single '=====' run), which is the one thing this must not match.
_SIMPLE_TABLE_RULE_RE = re.compile(r"^[ \t]*=+(?:[ \t]+=+)+[ \t]*$")
_TABLE_OPTION_RE = re.compile(r"^[ \t]+:([\w-]+):")


def _table_kind_and_start(lines: list[str], anchor: int) -> tuple[str, int]:
    """Best-effort kind + true start line (both 1-based) for the table
    whose earliest located AST line is *anchor* — either its <title>
    child's line (caption present) or the first content paragraph found
    inside it (no caption, so the anchor sits somewhere inside the table's
    own body).

    A directive's own line IS the anchor when there's a caption (docutils
    sets a '.. table:: Caption' title's .line to the directive's own
    line — confirmed directly).  Without a caption, the anchor is either
    still inside an indented directive body (scan upward past the
    indentation to the marker) or somewhere in a raw grid/simple table
    (scan upward, INCLUSIVE of the anchor itself, through consecutive
    border/rule lines to the topmost one) — inclusive because which line
    docutils locates here is version-dependent: confirmed directly that
    docutils 0.23 (gl63) sets the <table> node's OWN .line to the TOP
    border, while this host's docutils leaves it unset and the first
    locatable line is the header content row one line below the border;
    scanning inclusive of the anchor handles both without caring which
    one this docutils build gave us.  KNOWN, ACCEPTED limitation: a
    captionless, headerless directive table (no thead, no title) can't be
    told apart from this scan if its body's own indentation is ambiguous;
    falls back to kind='table' at the anchor itself.
    """
    anchor_idx = anchor - 1
    if not (0 <= anchor_idx < len(lines)):
        return "table", anchor
    anchor_line = lines[anchor_idx]
    m = _TABLE_DIRECTIVE_RE.match(anchor_line.strip())
    if m:
        return _TABLE_DIRECTIVE_KIND[m.group(1)], anchor

    # Where to start looking for the run of border/rule lines: the anchor
    # itself if it's ALREADY one (docutils 0.23/gl63 — table.line is the
    # top border), otherwise one line above it (this host's docutils —
    # the anchor is the header content row sitting just below the border).
    if _GRID_TABLE_BORDER_RE.match(anchor_line) or _SIMPLE_TABLE_RULE_RE.match(anchor_line):
        i = anchor_idx
    else:
        i = anchor_idx - 1
    top: int | None = None
    while i >= 0 and (_GRID_TABLE_BORDER_RE.match(lines[i]) or _SIMPLE_TABLE_RULE_RE.match(lines[i])):
        top = i
        i -= 1
    if top is not None:
        kind = "grid" if lines[top].lstrip().startswith("+") else "simple"
        return kind, top + 1

    anchor_indent = len(anchor_line) - len(anchor_line.lstrip())
    i = anchor_idx - 1
    while i >= 0:
        line = lines[i]
        if not line.strip():
            i -= 1
            continue
        if len(line) - len(line.lstrip()) >= anchor_indent:
            i -= 1
            continue
        m = _TABLE_DIRECTIVE_RE.match(line.strip())
        return (_TABLE_DIRECTIVE_KIND[m.group(1)], i + 1) if m else ("table", anchor)
    return "table", anchor


def _table_end(lines: list[str], last_content_line: int) -> int:
    """Extend *last_content_line* (1-based) through any trailing grid
    border / simple-table rule that belongs to it — the bottom border a
    grid or simple table always ends on, which carries no line info of
    its own in the doctree (only cell paragraphs do).

    First extends through a grid table's own bare ``|``-led continuation
    lines, when the table's last row spans multiple physical source
    lines: docutils' own .line tracking only reports a multi-line cell's
    FIRST physical line, so *last_content_line* can land there instead
    of on the row's real last line — found live building list-table's
    own real-world acceptance fixture, where a border-only extension
    silently truncated a table whose last row was multi-line, not just
    for that feature's own use of this function. Deliberately two
    SEPARATE, sequential passes rather than one merged loop: once a
    border is found, scanning must stop there, never resume matching
    '|'-led lines afterward — a border is only ever followed by more
    table content when another full row (which last_content_line, being
    the max already, would already have reached) is still to come, never
    by an unrelated construct. Found by code review: a merged loop
    covering both cases in either order would keep absorbing a
    '|'-led construct immediately after the closing border into the
    table's own reported end, on top of legitimately malformed input
    where RST's own required blank line after a table is missing."""
    end = last_content_line
    i = last_content_line  # 0-based index of the line right after
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        end = i + 1
        i += 1
    while i < len(lines) and (_GRID_TABLE_BORDER_RE.match(lines[i]) or _SIMPLE_TABLE_RULE_RE.match(lines[i])):
        end = i + 1
        i += 1
    return end


def find_tables(path: pathlib.Path, doc: Document | None = None) -> list[TableEntry]:
    """Return every table in *path*, in document order.

    Bare docutils, like find_block_quotes — a real Sphinx build adds no
    table-type information (confirmed directly), so there is no verified/
    heuristic split here; the same function serves both --outline modes.
    depth is _block_depth — enclosing sections AND enclosing list
    nesting, same as every other entry kind (2026-07-26; found live: a
    list-table added inside a bullet item printed at the same depth as
    the bullet list container itself before this fix).
    """
    document = _resolve_document(path, doc)
    lines = document.lines
    entries: list[TableEntry] = []
    for table in document.doctree.findall(docutils.nodes.table):
        depth = _block_depth(table)

        caption: str | None = None
        anchor: int | None = None
        if table.children and isinstance(table.children[0], docutils.nodes.title):
            title_node = table.children[0]
            caption = title_node.astext()
            if isinstance(title_node.line, int):
                anchor = title_node.line
        if anchor is None:
            anchor = next((n.line for n in table.findall() if isinstance(n.line, int)), None)
        if anchor is None:
            continue  # no locatable content at all — nothing to report

        kind, start = _table_kind_and_start(lines, anchor)

        tgroup = next(table.findall(docutils.nodes.tgroup), None)
        cols = tgroup.get("cols", 0) if tgroup is not None else 0
        table_rows = list(table.findall(docutils.nodes.row))
        rows = len(table_rows)

        # Chain every row's cells in document order (header row first when
        # one exists, via thead-before-tbody document order) into one
        # string, THEN collapse+truncate — the whole table is the input,
        # same as a code-block's whole body feeding its own preview.
        all_cells = [c.astext() for row in table_rows for c in row.children if isinstance(c, docutils.nodes.entry)]
        preview = _outline_preview(" ".join(all_cells))

        content_lines = [n.line for n in table.findall() if isinstance(n.line, int)]
        last_content_line = max(content_lines) if content_lines else start
        end = _table_end(lines, last_content_line)

        entries.append(TableEntry(start, depth, kind, (rows, cols), caption, preview, end))
    return entries


# ---------------------------------------------------------------------------
# list-table conversion (docs/roadmap.rst, "Targeted aligned-table to
# list-table transformation") — built in isolated stages, same as the
# subcommand redesign, before CLI wiring.  Stage 1: the --only/--skip
# ordinal resolver.
# ---------------------------------------------------------------------------


def _resolve_list_table_selection(
    tables: list[TableEntry], only: list[int], skip: list[int]
) -> tuple[list[TableEntry], list[int]]:
    """Resolve --only/--skip ordinals (1-based, document order) against
    *tables* into the tables to convert.

    Returns (targets, unknown_ordinals). unknown_ordinals lists every
    --only/--skip value outside 1..len(tables) — including 0 and negative
    values, which are never valid — in the order given, duplicates
    included, so the caller can report exactly what was wrong; targets is
    always empty when unknown_ordinals is non-empty, a stale/invalid
    selector must never silently convert a different table than the one
    named. Otherwise: the eligible set starts as every table, narrows to
    exactly the --only ordinals if any were given, then --skip removes
    ordinals from whatever that is — a direct --only/--skip contradiction
    (the same ordinal in both) resolves to an empty target list here,
    which this pure function does not itself treat as an error; the
    caller distinguishes "resolved empty because of the selection" from
    "resolved empty because the file has no tables at all" by checking
    whether *tables* was empty to begin with.
    """
    n = len(tables)
    unknown = [ordinal for ordinal in (*only, *skip) if not (1 <= ordinal <= n)]
    if unknown:
        return [], unknown
    selected = set(range(1, n + 1))
    if only:
        selected &= set(only)
    selected -= set(skip)
    targets = [table for position, table in enumerate(tables, start=1) if position in selected]
    return targets, []


# Kinds this conversion accepts: bare/directive-wrapped grid and simple
# tables (a ``.. table::`` directive reports kind='table' regardless of
# which alignment grammar it wraps — TableEntry's own kind detection
# cannot tell the two apart, so the parser choice below inspects the
# actual first content line instead). Already 'list' needs no conversion;
# 'csv' is fundamentally different source (external/inline CSV data, not
# an aligned grid) and stays out of scope.
_LIST_TABLE_ELIGIBLE_KINDS = frozenset({"grid", "simple", "table"})


def _table_kind_eligible(kind: str) -> bool:
    return kind in _LIST_TABLE_ELIGIBLE_KINDS


@dataclasses.dataclass(frozen=True, slots=True)
class ParsedTable:
    """A grid/simple table's parsed structure — docutils' own tableparser
    output, reshaped only enough to be self-describing. colspecs is
    character column widths; each row is a list of cells in
    ``(morerows, morecols, line_offset, StringList)`` shape, or ``None``
    at a position a spanning cell above/to the left already covers —
    docutils' own convention, kept verbatim rather than reinterpreted."""

    colspecs: list[int]
    header_rows: list[list[tuple[int, int, int, docutils.statemachine.StringList] | None]]
    body_rows: list[list[tuple[int, int, int, docutils.statemachine.StringList] | None]]


def _parse_aligned_table(lines: list[str]) -> ParsedTable:
    """Parse a grid or simple table's raw source *lines* (border rows
    included, nothing else) via docutils' own GridTableParser/
    SimpleTableParser — never reimplementing the alignment grammar.
    Grid vs simple is chosen from the first line's own shape ('+' border
    vs '=' rule), not from TableEntry.kind, which collapses both under
    'table' for a directive-wrapped source (see _LIST_TABLE_ELIGIBLE_KINDS)."""
    is_grid = lines[0].lstrip().startswith("+")
    parser: docutils.parsers.rst.tableparser.TableParser = (
        docutils.parsers.rst.tableparser.GridTableParser()
        if is_grid
        else docutils.parsers.rst.tableparser.SimpleTableParser()
    )
    colspecs, header_rows, body_rows = parser.parse(docutils.statemachine.StringList(lines))
    return ParsedTable(colspecs, header_rows, body_rows)


def _table_has_span(parsed: ParsedTable) -> bool:
    """True if any real cell (not a covered/None position) claims extra
    rows or columns.  list-table cannot express a merged cell, so this
    must be a hard, explanatory refusal — never a silent flatten,
    duplication, or guess at a spanned cell's content."""
    for row in (*parsed.header_rows, *parsed.body_rows):
        for cell in row:
            if cell is not None and (cell[0] or cell[1]):
                return True
    return False


@dataclasses.dataclass(frozen=True, slots=True)
class ListTableCandidate:
    """One table judged ready for conversion, or refused with a reason —
    never a silent skip; the caller reports every refusal. parsed and
    caption are populated only when refusal is None."""

    entry: TableEntry
    parsed: ParsedTable | None
    caption: str | None
    refusal: str | None


def _evaluate_list_table_candidate(lines: list[str], entry: TableEntry) -> ListTableCandidate:
    """Judge one table ready for conversion, or refuse it with a reported
    reason. Scope for this version: bare tables and directive-wrapped
    tables with an optional caption only — :name:/:class:/:align: (or any
    other ``.. table::`` option) is an explicit, reported refusal, not
    yet supported (docs/roadmap.rst, "Targeted aligned-table to
    list-table transformation"), never a silent mishandling."""
    if entry.kind == "list":
        return ListTableCandidate(entry, None, None, "already a list-table — nothing to convert")
    if entry.kind == "csv":
        return ListTableCandidate(entry, None, None, "csv-table is out of scope for this conversion")
    if not _table_kind_eligible(entry.kind):
        return ListTableCandidate(entry, None, None, f"kind {entry.kind!r} is not supported")

    directive_line = lines[entry.lineno - 1]
    match = _TABLE_DIRECTIVE_RE.match(directive_line.strip())
    caption: str | None = None
    body_start = entry.lineno - 1
    if match:
        caption = directive_line.strip()[match.end() :].strip() or None
        cursor = entry.lineno  # 0-based index of the line right after the directive
        option_names = []
        while cursor < entry.end:
            option_match = _TABLE_OPTION_RE.match(lines[cursor])
            if option_match is None:
                break
            option_names.append(option_match.group(1))
            cursor += 1
        if option_names:
            return ListTableCandidate(entry, None, caption, f"the {option_names[0]!r} option is not yet supported")
        if cursor < entry.end and not lines[cursor].strip():
            cursor += 1  # the required blank line between options/caption and body
        body_start = cursor

    body_lines = lines[body_start : entry.end]
    indent = len(body_lines[0]) - len(body_lines[0].lstrip()) if body_lines else 0
    dedented = [line[indent:] if len(line) >= indent else line.lstrip() for line in body_lines]

    parsed = _parse_aligned_table(dedented)
    if _table_has_span(parsed):
        return ListTableCandidate(
            entry, None, caption, "contains a merged row or column (span), which list-table cannot express"
        )
    return ListTableCandidate(entry, parsed, caption, None)


_LIST_TABLE_BODY_INDENT = 3
_LIST_TABLE_FIRST_MARKER = "* -"
_LIST_TABLE_OTHER_MARKER = "  -"


def _render_list_table_row(row: list[tuple[int, int, int, docutils.statemachine.StringList] | None]) -> list[str]:
    """One row's worth of ``* -``/``  -`` lines. Every cell's own source
    lines are used verbatim — never re-serialized through a parsed tree
    — indented so continuation lines align under the first line's own
    content column, the same rule RST itself requires for list-item
    bodies. None cells never reach here — spans are rejected before
    rendering (_evaluate_list_table_candidate)."""
    out: list[str] = []
    content_column = _LIST_TABLE_BODY_INDENT + len(_LIST_TABLE_FIRST_MARKER) + 1
    for index, cell in enumerate(row):
        if cell is None:
            raise AssertionError("spanned cell reached the renderer — caller must reject spans first")
        _, _, _, block = cell
        cell_lines = list(block)
        # docutils pads every cell in a row to the row's tallest cell's
        # line count (confirmed by direct probe) — trailing empty entries
        # are that padding, not real trailing blank lines in the cell's
        # own content, so they're dropped; an INTERIOR empty line (a
        # genuine blank line separating two paragraphs in one cell) is
        # kept.
        while cell_lines and cell_lines[-1] == "":
            cell_lines.pop()
        marker = _LIST_TABLE_FIRST_MARKER if index == 0 else _LIST_TABLE_OTHER_MARKER
        prefix = " " * _LIST_TABLE_BODY_INDENT + marker
        if not cell_lines:
            out.append(prefix)
            continue
        out.append(f"{prefix} {cell_lines[0]}".rstrip())
        for extra in cell_lines[1:]:
            out.append(f"{' ' * content_column}{extra}".rstrip())
    return out


def _render_list_table(parsed: ParsedTable, caption: str | None) -> str:
    """Emit RST text for a ``.. list-table::`` directive equivalent to
    *parsed*. :widths: carries colspecs straight through — confirmed by
    direct probe that docutils passes explicit :widths: values through to
    each colspec's own colwidth unchanged, making the resulting doctree's
    column-width representation match the original exactly, not merely
    proportionally."""
    lines = [f".. list-table:: {caption}" if caption else ".. list-table::"]
    if parsed.header_rows:
        lines.append(f"{' ' * _LIST_TABLE_BODY_INDENT}:header-rows: {len(parsed.header_rows)}")
    lines.append(f"{' ' * _LIST_TABLE_BODY_INDENT}:widths: {' '.join(str(width) for width in parsed.colspecs)}")
    lines.append("")
    for row in (*parsed.header_rows, *parsed.body_rows):
        lines.extend(_render_list_table_row(row))
    return "\n".join(lines) + "\n"


def _canonical_doctree_model(node: docutils.nodes.Node) -> object:
    """A structural fingerprint of *node*: class identity, frozen
    attributes, and children, recursively — the same modeling technique
    as _text_space_evidence's permitted-delta model. One permitted delta,
    confirmed by direct probe: docutils marks a <table> node
    'colwidths-given' whenever :widths: is given explicitly on
    list-table, and never otherwise — a grid/simple table never carries
    it regardless of its own widths, since there is no 'auto' alternative
    for that syntax to distinguish it from. _render_list_table always
    emits :widths: (to make colwidth match exactly), so this class is a
    one-directional, deterministic syntax-provenance marker, not semantic
    content — dropped from the comparison, on <table> nodes only."""
    if isinstance(node, docutils.nodes.Text):
        return ("Text", str(node))
    attributes: object = ()
    if isinstance(node, docutils.nodes.Element):
        attributes = dict(node.attributes)
        if isinstance(node, docutils.nodes.table) and "colwidths-given" in attributes.get("classes", ()):
            attributes["classes"] = [c for c in attributes["classes"] if c != "colwidths-given"]
        attributes = _freeze_node_attribute(attributes)
    return (
        node.__class__.__module__,
        node.__class__.__qualname__,
        attributes,
        tuple(_canonical_doctree_model(child) for child in node.children),
    )


def _list_table_conversion_preserves_semantics(path: pathlib.Path, original_text: str, candidate_text: str) -> bool:
    """Parse both whole-file variants and require exact canonical-tree
    equality — the same all-or-nothing rule --fix already uses: a
    changed subtree means the conversion is rejected outright, never
    partially applied or guessed at."""
    original_model = _canonical_doctree_model(_parse_rst(path, text=original_text))
    candidate_model = _canonical_doctree_model(_parse_rst(path, text=candidate_text))
    return original_model == candidate_model


@dataclasses.dataclass(frozen=True, slots=True)
class ListTableFileResult:
    """One file's complete list-table run: which ordinals converted,
    every in-scope refusal (with its reason — never silent), and whether
    an unresolvable --only/--skip ordinal or a failed whole-file
    semantic-validation safety net rejected the file outright."""

    path: pathlib.Path
    original: str
    candidate: str
    converted: list[int]
    refusals: list[tuple[int, str]]
    unknown_ordinals: list[int]
    fatal: str | None

    @property
    def changed(self) -> bool:
        return self.fatal is None and self.candidate != self.original


def _plan_list_table_file(path: pathlib.Path, only: list[int], skip: list[int]) -> ListTableFileResult:
    """Plan one file's conversion — read, resolve --only/--skip, evaluate
    and render every in-scope table, splice approved conversions into
    the whole-file text, then re-validate the whole result before it may
    ever be written. An --only ordinal that turns out refused is fatal
    (the user named that exact table); a refusal among the default,
    unnamed 'every eligible table' scope is reported but does not block
    converting the file's other eligible tables — the same
    review-don't-block spirit as --skip-fixable, not a hard-error either
    way rule."""
    original = _read_source(path)
    plain_lines = original.splitlines()
    tables = find_tables(path)
    targets, unknown = _resolve_list_table_selection(tables, only, skip)
    if unknown:
        bad = ", ".join(str(n) for n in unknown)
        return ListTableFileResult(path, original, original, [], [], unknown, f"unknown table ordinal(s): {bad}")

    ordinal_by_id = {id(table): ordinal for ordinal, table in enumerate(tables, start=1)}
    replacements: list[tuple[int, int, str]] = []
    converted: list[int] = []
    refusals: list[tuple[int, str]] = []
    for table in targets:
        ordinal = ordinal_by_id[id(table)]
        candidate = _evaluate_list_table_candidate(plain_lines, table)
        if candidate.refusal is not None:
            if only:
                return ListTableFileResult(
                    path, original, original, [], [], [], f"table {ordinal}: {candidate.refusal}"
                )
            refusals.append((ordinal, candidate.refusal))
            continue
        assert candidate.parsed is not None
        rendered = _render_list_table(candidate.parsed, candidate.caption)
        replacements.append((table.lineno - 1, table.end, rendered.rstrip("\n")))
        converted.append(ordinal)

    new_lines = list(plain_lines)
    for start, end, text in sorted(replacements, key=lambda item: item[0], reverse=True):
        new_lines[start:end] = text.splitlines()
    candidate_text = "\n".join(new_lines)
    if original.endswith("\n"):
        candidate_text += "\n"

    if candidate_text != original and not _list_table_conversion_preserves_semantics(path, original, candidate_text):
        return ListTableFileResult(
            path, original, original, [], [], [], "converted result failed semantic validation — file left untouched"
        )
    return ListTableFileResult(path, original, candidate_text, converted, refusals, [], None)


# ---------------------------------------------------------------------------
# Phase 2 — Python Sphinx rules (real Sphinx env, requires --sphinx-src)
# ---------------------------------------------------------------------------


def _build_sphinx_env(
    sphinx_src: pathlib.Path,
    build_dir: pathlib.Path,
    files: list[pathlib.Path] | None = None,
) -> tuple[sphinx.environment.BuildEnvironment, str]:
    """Build a real, in-process Sphinx environment rooted at *sphinx_src*.

    Returns (env, warning_text): warning_text is this build's own captured
    console warning stream, in the same 'path:line: LEVEL: msg' shape
    run_sphinx's subprocess produces (parse with
    _findings_from_sphinx_output).  The caller MUST surface it — this
    build's own structural docutils warnings (e.g. an inconsistent title
    style) are otherwise lost for good: they get resolved into the doctree
    this function writes to the shared --build-dir, so Phase 3's separate
    sphinx-build subprocess finds that doctree already fresh and never
    re-parses the file to reproduce them (confirmed by direct
    reproduction, 2026-07-20 — see _findings_from_sphinx_output).

    Uses the "dummy" builder: resolves the full environment and every
    document's doctree (directives, options, cross-references) exactly as a
    real build would, but writes no HTML output. This is what lets Phase 2
    parse Sphinx-only directive options (code-block's :caption:/:linenos:,
    etc.) that Phase 1's bare docutils parser doesn't know about, without
    the AttributeError a hand-registered directive would raise — Sphinx's
    own CodeBlock reaches for self.env, which exists here precisely because
    this is a genuine Sphinx application, not a bare docutils parse (confirmed
    by direct testing: registering Sphinx's real CodeBlock directive onto a
    bare docutils parser crashes on a caption with no explicit language,
    content that already exists in this project's own calendar/ files).

    doctreedir is shared with Phase 3's --build-dir so a doctree computed by
    one phase is reused by the other rather than recomputed twice.

    Building a Sphinx app registers its own directives/roles (its "toctree",
    "code-block", etc.) into docutils' process-global registry, and that
    registration outlives the app — confirmed by direct testing: a bare
    docutils parse running later in the same process inherited Sphinx's
    "toctree" directive and crashed the exact self.env way this function
    exists to avoid, breaking Phase 1 for the rest of the process. Sphinx's
    own docutils_namespace() snapshots and restores that registry, so the
    construction and build are scoped inside it; get_doctree() afterwards is
    a pure unpickle of an already-built tree and needs no registry state.

    When *files* is given, those checked documents are deliberately re-read
    even if Sphinx's incremental environment considers them unchanged.  This
    reproduces persistent read-time diagnostics without discarding the shared
    environment or re-reading unrelated documents: ``env-get-outdated`` is
    Sphinx's supported hook for adding selected docnames to the incremental
    read set.
    """
    CALL_COUNTS["_build_sphinx_env"] += 1
    import io

    from sphinx.application import Sphinx
    from sphinx.util.docutils import docutils_namespace

    warning_stream = io.StringIO()
    with docutils_namespace():
        app = Sphinx(
            srcdir=str(sphinx_src),
            confdir=str(sphinx_src),
            outdir=str(build_dir / "_dummy"),
            doctreedir=str(build_dir / ".doctrees"),
            buildername="dummy",
            status=io.StringIO(),
            warning=warning_stream,
        )
        if files:
            checked_paths = tuple(path.resolve() for path in files)

            def force_checked_docs(
                _app: Sphinx,
                env: sphinx.environment.BuildEnvironment,
                _added: set[str],
                _changed: set[str],
                _removed: set[str],
            ) -> list[str]:
                docnames = []
                for path in checked_paths:
                    docname = env.path2doc(str(path))
                    if docname is not None and docname in env.found_docs:
                        docnames.append(docname)
                return docnames

            app.connect("env-get-outdated", force_checked_docs)
        app.build()
    return app.env, warning_stream.getvalue()


def _build_sphinx_env_checked(
    sphinx_src: pathlib.Path,
    build_dir: pathlib.Path,
    files: list[pathlib.Path] | None = None,
) -> tuple[sphinx.environment.BuildEnvironment, str]:
    """CLI boundary for _build_sphinx_env: one diagnostic, never a traceback."""
    try:
        return _build_sphinx_env(sphinx_src, build_dir, files)
    except Exception as exc:
        detail = " ".join(str(exc).splitlines())
        print(f"check_rst: Sphinx environment build failed: {type(exc).__name__}: {detail}")
        raise SystemExit(1) from exc


def _docname_for(env: sphinx.environment.BuildEnvironment, path: pathlib.Path) -> str | None:
    """Return the Sphinx docname for *path*, or None if it isn't part of
    this Sphinx project's document tree (not reachable from --sphinx-src).

    env.path2doc() is a pure path transform — it happily returns a docname-
    shaped string for a path outside srcdir entirely (confirmed by direct
    testing), so reachability is checked separately against env.found_docs,
    the set of documents Sphinx actually read.
    """
    docname = env.path2doc(str(path.resolve()))
    if docname is None or docname not in env.found_docs:
        return None
    return docname


@dataclasses.dataclass(frozen=True, slots=True)
class ReferenceEntry:
    """One role or toctree document reference, as reported by --refs.

    docname is the entry's OWN document — the referring file for an
    OUTGOING entry (find_references), the file pointing IN for an
    INCOMING entry (find_incoming_references); the same shape serves both
    directions.  For roles, target is the raw text the author wrote (a
    relative path for :doc:, a label id for :ref:/:term:).  For toctrees,
    target is Sphinx's resolved docname — including each document produced
    by a glob.  resolved is the real docname it points at, or None when a
    role reference is broken (Phase 3 already reports why — this is not a
    substitute for that WARNING).
    """

    docname: str
    lineno: int
    reftype: str
    target: str
    resolved: str | None

    def __str__(self) -> str:
        return f"{self.docname}:{self.lineno}: {self.reftype} -> {self.target}"


def _resolve_xref_target(
    env: sphinx.environment.BuildEnvironment, refdoc: str, reftype: str, target: str
) -> str | None:
    """Resolve a pending_xref's raw target to the real docname it points
    at, or None if unresolvable.

    The SAME lookup Sphinx itself performs — sphinx.util.docname_join for
    :doc: (confirmed by direct read of sphinx.domains.std's own
    _resolve_doc_xref), env.domaindata['std']['anonlabels'] for :ref:/
    :term: (confirmed by direct probe: docutils already lowercases a
    :ref: role's target at parse time, matching anonlabels' own keys) —
    so a reference this reports as resolved is exactly one Phase 3 would
    accept.  Any other reftype (a domain this tool has no resolver for)
    returns None rather than guessing.
    """
    if reftype == "doc":
        from sphinx.util import docname_join

        docname = docname_join(refdoc, target)
        return docname if docname in env.found_docs else None
    if reftype in ("ref", "term"):
        anonlabels = env.domaindata.get("std", {}).get("anonlabels", {})
        entry = anonlabels.get(target.lower())
        return entry[0] if entry else None
    return None


def find_references(env: sphinx.environment.BuildEnvironment, docname: str) -> list[ReferenceEntry]:
    """Every role and toctree reference *docname* itself writes, in document
    order — its OUTGOING document graph.

    Reads the raw, still-unresolved sphinx.addnodes.pending_xref nodes
    env.get_doctree() carries: resolution happens later, during a
    builder's write phase, and is never written back to the pickled
    doctree (confirmed by direct probe, 2026-07-22) — exactly the target
    text the author wrote, before Sphinx joins/looks it up.

    Toctree nodes are different: Sphinx resolves them during reading and
    stores the actual child docnames in ``includefiles``.  Consuming that
    list includes explicit entries and every glob expansion while excluding
    external URLs, exactly matching the live document graph.
    """
    from sphinx.addnodes import pending_xref, toctree

    doc = env.get_doctree(docname)
    entries: list[ReferenceEntry] = []
    for node in doc.findall():
        if isinstance(node, pending_xref):
            reftype = node.get("reftype", "")
            target = node.get("reftarget", "")
            resolved = _resolve_xref_target(env, docname, reftype, target)
            entries.append(ReferenceEntry(docname, _node_line(node), reftype, target, resolved))
        elif isinstance(node, toctree):
            entries.extend(
                ReferenceEntry(
                    docname,
                    _node_line(node),
                    "toctree",
                    target,
                    target,
                )
                for target in node.get("includefiles", ())
            )
    return entries


def find_incoming_references(env: sphinx.environment.BuildEnvironment, target_docname: str) -> list[ReferenceEntry]:
    """Every OTHER document's reference that resolves to *target_docname*
    — the inverse of find_references, built by scanning every document's
    doctree once (confirmed by direct probe, 2026-07-22: ~2.6s across
    this Journal's full 1444 documents — fine for an on-demand --refs
    call, not something to run on every default invocation)."""
    incoming: list[ReferenceEntry] = []
    for docname in sorted(env.found_docs):
        if docname == target_docname:
            continue
        for entry in find_references(env, docname):
            if entry.resolved == target_docname:
                incoming.append(entry)
    return incoming


def check_multiple_toctree_parents(
    env: sphinx.environment.BuildEnvironment,
    files: list[pathlib.Path],
) -> list[Finding]:
    """Report selected documents implicated in repeated toctree inclusion.

    Sphinx records the authoritative resolved graph in
    ``env.toctree_includes`` but only logs its own concern at INFO level,
    anchored to the child document.  Deriving the finding from the graph
    keeps it independent of Sphinx's console wording and lets a selected
    parent surface a problem that Sphinx itself locates on an unselected
    child.  Repeating one child twice in the same parent and including it
    from two distinct parents are both represented by more than one parent
    occurrence and are intentionally treated alike.
    """
    parents_by_child: dict[str, list[str]] = {}
    for parent, children in getattr(env, "toctree_includes", {}).items():
        for child in children:
            parents_by_child.setdefault(child, []).append(parent)

    anomalies = {child: parents for child, parents in parents_by_child.items() if len(parents) > 1}
    findings: list[Finding] = []
    for path in files:
        docname = _docname_for(env, path)
        if docname is None:
            continue
        for child, parents in sorted(anomalies.items()):
            if docname != child and docname not in parents:
                continue
            lineno = 0
            if docname in parents:
                lineno = next(
                    (
                        entry.lineno
                        for entry in find_references(env, docname)
                        if entry.reftype == "toctree" and entry.resolved == child
                    ),
                    0,
                )
            counts = collections.Counter(parents)
            parent_list = ", ".join(
                f"{parent!r}" + (f" ({count} times)" if count > 1 else "") for parent, count in sorted(counts.items())
            )
            findings.append(
                Finding(
                    lineno,
                    Severity.WARNING,
                    f"document {child!r} is referenced by multiple toctree entries: {parent_list}",
                )
            )
    return findings


def _format_references(
    path: pathlib.Path,
    outgoing: list[ReferenceEntry],
    incoming: list[ReferenceEntry],
) -> str:
    lines = [f"References: {path}", "outgoing:"]
    if outgoing:
        for e in outgoing:
            status = e.resolved if e.resolved is not None else "BROKEN"
            lines.append(f"  {e.lineno}: {e.reftype} -> {e.target} ({status})")
    else:
        lines.append("  (none)")
    lines.append("incoming:")
    if incoming:
        lines.extend(f"  {e}" for e in incoming)
    else:
        lines.append("  (none)")
    return "\n".join(lines)


@dataclasses.dataclass(frozen=True, slots=True)
class ToctreeEntry:
    """A single ``.. toctree::`` directive, as reported by --outline
    (2026-07-26) — the container marker; the documents it points at
    appear immediately after it as OutlineEntry instances (docname
    set), each recursively expanded through ITS OWN toctrees in turn,
    via find_toctrees.

    maxdepth is the directive's own configured value (-1 when
    unspecified — Sphinx's own "unlimited" convention), shown as
    information about what the author configured for human HTML
    browsing.  find_toctrees' own recursion deliberately does NOT stop
    there: confirmed by direct probe against a real 2-level nested
    toctree project that Sphinx's own maxdepth-limited resolver
    (sphinx.environment.adapters.toctree.TocTree.get_toctree_for) would
    hide a real, reachable document one hop beyond the configured
    maxdepth — fine for a human clicking through an HTML sidebar one
    page at a time, wrong for an AI that wants to know the whole
    reachable project graph from one command.

    cycle is set instead of item_count/maxdepth when this entry
    represents a DETECTED CYCLE rather than a real toctree directive —
    find_toctrees stops descending into an already-visited docname on
    the current traversal path and leaves this marker in its place,
    visibly, rather than looping forever or failing silently (the same
    "never silent truncation" house rule as everywhere else in this
    tool).

    docname is set only when this directive belongs to a document pulled in
    from another file, matching OutlineEntry's provenance contract.  None
    therefore means local to the file being outlined; a non-empty value is
    public, self-identifying provenance in text, JSON, and --context.
    """

    lineno: int
    depth: int
    item_count: int = 0
    maxdepth: int = -1
    end: int = 0
    cycle: str | None = None
    docname: str | None = None

    def __str__(self) -> str:
        indent = "    " * (self.depth - 1)
        pos = f"{self.lineno}-{self.end}" if self.end > self.lineno else f"{self.lineno}"
        if self.docname:
            # A lone foreign container line must identify its source exactly
            # like a foreign OutlineEntry; local containers remain lean.
            pos = f"{self.docname}:{pos}"
        if self.cycle is not None:
            return (
                f"{indent}{pos}: toctree cycle — '{self.cycle}' is already an "
                "ancestor on this branch, not descending further"
            )
        maxdepth_label = "unlimited" if self.maxdepth < 0 else str(self.maxdepth)
        noun = "entry" if self.item_count == 1 else "entries"
        return f"{indent}{pos}: toctree ({self.item_count} {noun}, maxdepth={maxdepth_label})"

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return item in str(self)


def find_toctrees(
    env: sphinx.environment.BuildEnvironment,
    docname: str,
    doc: Document | None = None,
) -> list[list[ToctreeEntry | OutlineEntry]]:
    """Return one CLUSTER per top-level ``.. toctree::`` directive in
    *docname* — each cluster a self-contained ``[container, *pulled-in
    entries]`` list, recursively expanded across every document that
    directive points at, in turn (2026-07-26) — the first entry kind
    whose items can point outside the file being outlined.

    One cluster per ROOT-level directive, not one flat list, so a
    caller merging this into *docname*'s own local outline entries can
    splice each cluster in at its container's real position without
    re-sorting a cross-file entry by its (meaningless-here) foreign
    line number — see _merge_toctree_clusters.

    Verified mode only: toctree is invisible to bare docutils entirely
    (confirmed by direct probe — without a real Sphinx environment it
    is not even recognized as a directive, let alone resolved), so
    there is no heuristic-mode equivalent — the same constraint as
    --refs/check_bare_filenames.

    Depth continues seamlessly across the file boundary: a toctree
    container sits at _block_depth within its OWN document; each
    document it points at is entered at that container's own depth, so
    document's own LOCAL headings (already depth 1 for its own title,
    2 for its own subsections, from build_outline) land at
    container_depth + local_depth — confirmed by direct probe against
    a real 2-level nested project that this matches exactly how deep a
    heading reached by list nesting or section nesting alone would
    land, so --outline-depth needs no special case to bound it.

    Two things full, unbounded recursion needs, neither silent:

    * Lazy cycle detection — the current traversal PATH (the chain of
      docnames walked to reach this point) is tracked, not a
      precomputed whole-project graph.  The moment a toctree would
      recurse into a docname already on that path, that branch stops
      with a visible ToctreeEntry(cycle=...) marker naming it, and its
      siblings continue normally.
    * Diamond de-duplication — a docname already fully expanded via a
      DIFFERENT, non-cyclic path (a document reachable from more than
      one toctree is an entirely normal project shape, not an error)
      still gets its own heading entry the second time it is reached,
      but is not expanded again — avoiding duplicate, potentially large
      output for the same real subtree.
    """
    from sphinx.addnodes import toctree as toctree_node_cls

    document = _resolve_document(pathlib.Path(env.doc2path(docname)), doc)
    # env.get_doctree(), never document.doctree: a toctree node's
    # includefiles/maxdepth attributes are populated by Sphinx's own
    # toctree-directive processing during the environment read, which a
    # bare docutils parse of the same file never runs — confirmed by
    # direct probe (see find_toctrees' own docstring: toctree is
    # "invisible to bare docutils entirely").  This applies at EVERY
    # level of recursion, including the root docname itself, not only
    # the children — document.doctree is used only for .lines below.
    doctree = env.get_doctree(docname)
    seen = {docname}
    return [
        _expand_one_toctree(node, env, document, depth_offset=0, path=(docname,), seen=seen)
        for node in doctree.findall(toctree_node_cls)
    ]


def _expand_toctrees(
    env: sphinx.environment.BuildEnvironment,
    docname: str,
    document: Document,
    depth_offset: int,
    path: tuple[str, ...],
    seen: set[str],
) -> list[ToctreeEntry | OutlineEntry]:
    """Flatten every toctree directive found in *docname* (used only when
    recursing INTO a child document — its own toctree directives, if
    more than one, all nest inside the single cluster of the directive
    that brought us here, so no per-directive clustering is needed at
    this level; only find_toctrees' own root call needs clusters).

    env.get_doctree(docname), never document.doctree — see find_toctrees.
    """
    from sphinx.addnodes import toctree as toctree_node_cls

    doctree = env.get_doctree(docname)
    entries: list[ToctreeEntry | OutlineEntry] = []
    for node in doctree.findall(toctree_node_cls):
        entries.extend(_expand_one_toctree(node, env, document, depth_offset, path, seen))
    return entries


def _expand_one_toctree(
    node: docutils.nodes.Node,
    env: sphinx.environment.BuildEnvironment,
    document: Document,
    depth_offset: int,
    path: tuple[str, ...],
    seen: set[str],
) -> list[ToctreeEntry | OutlineEntry]:
    """Expand a single ``toctree`` doctree node: its own container entry,
    the headings of every document it includes, and — recursively —
    each of those documents' own toctrees, in turn."""
    lines = document.lines
    local_depth = _block_depth(node)
    toctree_depth = depth_offset + local_depth
    includefiles = list(node.get("includefiles", ()))
    maxdepth = node.get("maxdepth", -1)
    start = _node_line(node)
    end = _indented_extent(lines, start) if includefiles else start
    # path[0] is the document the caller asked to outline.  Provenance is
    # emitted only after crossing that file boundary: stamping the root too
    # would make local and foreign containers indistinguishable again.
    source_docname = path[-1] if len(path) > 1 else None
    entries: list[ToctreeEntry | OutlineEntry] = [
        ToctreeEntry(
            start,
            toctree_depth,
            len(includefiles),
            maxdepth,
            end,
            docname=source_docname,
        )
    ]

    for child_docname in includefiles:
        if child_docname in path:
            entries.append(
                ToctreeEntry(
                    start,
                    toctree_depth + 1,
                    cycle=child_docname,
                    docname=source_docname,
                )
            )
            continue

        child_path = pathlib.Path(env.doc2path(child_docname))
        child_doctree = env.get_doctree(child_docname)
        child_headings = build_outline(child_path, doctree=child_doctree)
        for h in child_headings:
            entries.append(
                dataclasses.replace(
                    h,
                    depth=toctree_depth + h.depth,
                    docname=child_docname,
                )
            )

        if child_docname in seen:
            # Diamond: already expanded via a different, non-cyclic path
            # — its headings are shown again (real content, reachable
            # from here too) but not recursed into again.
            continue
        seen.add(child_docname)
        child_document = Document(child_path)
        entries.extend(
            _expand_toctrees(
                env,
                child_docname,
                child_document,
                depth_offset=toctree_depth,
                path=(*path, child_docname),
                seen=seen,
            )
        )
    return entries


def _merge_toctree_clusters(
    local_entries: list[
        OutlineEntry | CodeBlockEntry | BlockQuoteEntry | TableEntry | AdmonitionEntry | CommentEntry | ListEntry
    ],
    clusters: list[list[ToctreeEntry | OutlineEntry]],
) -> list[
    OutlineEntry
    | CodeBlockEntry
    | BlockQuoteEntry
    | TableEntry
    | AdmonitionEntry
    | CommentEntry
    | ListEntry
    | ToctreeEntry
]:
    """Splice each toctree cluster from find_toctrees into *local_entries*
    (already sorted by lineno) at its own container's position, WITHOUT
    re-sorting the cluster's own contents by their raw line number — a
    cross-file heading's .lineno is a position in ANOTHER file, not
    comparable to this file's own line numbers, so the cluster (already
    in correct document/recursion order from find_toctrees) is spliced
    in as one contiguous, internally-unsorted block.
    """
    merged: list[
        OutlineEntry
        | CodeBlockEntry
        | BlockQuoteEntry
        | TableEntry
        | AdmonitionEntry
        | CommentEntry
        | ListEntry
        | ToctreeEntry
    ] = []
    idx = 0
    for cluster in clusters:
        if not cluster:
            continue
        anchor = cluster[0].lineno
        while idx < len(local_entries) and local_entries[idx].lineno < anchor:
            merged.append(local_entries[idx])
            idx += 1
        merged.extend(cluster)
    merged.extend(local_entries[idx:])
    return merged


# A bare filename mention: 'guide.rst', 'coding-standards.rst' — matched by
# basename only, since prose almost never spells out the full
# project-relative path a docname carries.
_BARE_FILENAME_RE = re.compile(r"\b([\w-]+)\.rst\b")

# Real evidence, this Journal's own corpus: 1072 files are named
# 'Notes.rst' — a bare mention of that basename is not a specific,
# actionable reference candidate, so a basename shared by more files than
# this must stay silent rather than dump an unusable wall of candidates.
_MAX_BARE_FILENAME_CANDIDATES = 5


def check_bare_filenames(
    env: sphinx.environment.BuildEnvironment,
    docname: str,
    doc: Document,
) -> list[Finding]:
    """Flag a bare '<name>.rst' filename mentioned as plain prose text
    where a real :doc:/:ref: cross-reference belongs (Max, 2026-07-23,
    evidence from a downstream project: several 'coding-standards.rst' prose mentions in
    that project's own docs are plain text, not links) — the mirror image
    of "did you mean": here a reference is MISSING where one should
    exist, not broken.

    Matched by basename against every known docname's own last path
    segment (env.found_docs).  Silent when the mentioned name matches no
    known doc at all (nothing confident to suggest), matches only THIS
    document's own docname (mentioning your own filename is not a
    missing cross-reference), or matches more than
    _MAX_BARE_FILENAME_CANDIDATES docs (too common a basename to be a
    specific suggestion — confirmed by real evidence, see above).
    Otherwise lists every remaining candidate, never guesses a single one.

    Scans the same author-facing prose Text nodes as check_homoglyphs
    (_NON_PROSE_NODE_TYPES) — deliberately including inline literal spans
    (unlike a literal_block): the real evidence is a filename wrapped in
    double backticks as the author's own emphasis, not captured code
    output.  WARNING, not ERROR: converting to a real cross-reference is a
    content decision (which role, which target syntax), never
    auto-fixable.
    """
    by_basename: dict[str, list[str]] = {}
    for d in env.found_docs:
        by_basename.setdefault(d.rsplit("/", 1)[-1], []).append(d)

    from sphinx.addnodes import pending_xref

    findings: list[Finding] = []
    # Production uses Sphinx's doctree so genuine pending_xref/reference
    # nodes remain distinguishable from prose.  The fallback keeps this
    # checker usable with the deliberately minimal environment doubles in
    # unit tests and by direct library callers.
    get_doctree = getattr(env, "get_doctree", None)
    sphinx_doctree = get_doctree(docname) if callable(get_doctree) else doc.doctree
    for text_node in sphinx_doctree.findall(docutils.nodes.Text):
        node: docutils.nodes.Node | None = text_node.parent
        skipped = False
        while node is not None:
            if isinstance(
                node,
                (*_NON_PROSE_NODE_TYPES, docutils.nodes.reference, pending_xref),
            ):
                skipped = True
                break
            node = node.parent
        if skipped:
            continue
        s = str(text_node)
        base_line = _node_line(text_node)
        for m in _BARE_FILENAME_RE.finditer(s):
            name = m.group(1)
            candidates = sorted(c for c in by_basename.get(name, ()) if c != docname)
            if not candidates or len(candidates) > _MAX_BARE_FILENAME_CANDIDATES:
                continue
            lineno = base_line + s[: m.start()].count("\n")
            targets = ", ".join(repr(c) for c in candidates)
            findings.append(
                Finding(
                    lineno,
                    Severity.WARNING,
                    f"{name}.rst mentioned as plain text — did you mean a "
                    f":doc:/:ref: cross-reference? possible target(s): {targets}",
                )
            )
    return findings


def find_code_blocks(
    env: sphinx.environment.BuildEnvironment,
    docname: str,
    lines: list[str] | None = None,
) -> list[CodeBlockEntry]:
    """Return every real code-block in document *docname*, in document order.

    Requires a genuine Sphinx environment (see _build_sphinx_env). Under
    Sphinx's own CodeBlock directive, every recognized code-block carries a
    "language" attribute — set to the explicit argument, or to the
    project's highlight_language when none is given — which is what this
    keys on. A plain "::" literal block or ".. parsed-literal::" never gets
    this attribute, and a ".. code-block::" merely quoted as example text
    inside another literal block never produces its own node at all
    (Sphinx never re-parses literal content), so both are correctly
    excluded without any text-based heuristic.

    lineno is the directive's own line, which Sphinx sets explicitly via
    set_source_info() during parsing — reliable and stable, unlike bare
    docutils' fuzzy (and sometimes None) .line for the same node kind.
    """
    doc = env.get_doctree(docname)
    entries: list[CodeBlockEntry] = []
    for node in doc.findall(docutils.nodes.literal_block):
        lang = node.get("language")
        if lang is None:
            continue
        depth = _block_depth(node)
        lineno = node.line if isinstance(node.line, int) else 0
        end = _indented_extent(lines, lineno) if lines and lineno else 0
        preview = _outline_preview(node.astext())
        entries.append(CodeBlockEntry(lineno, depth, lang, preview, end))
    return entries


# ---------------------------------------------------------------------------
# Phase 2 fallback — heuristic code-blocks with no --sphinx-src (best-effort)
# ---------------------------------------------------------------------------

# Sphinx treats "code-block", "code", and "sourcecode" as identical aliases
# for the same CodeBlock directive (confirmed by direct testing: all three
# produce the same "language" node attribute under a real Sphinx env) — a
# downstream project's docs use ".. code::" exclusively, never
# ".. code-block::", so matching only the long form missed 100% of its 75
# real code-blocks.
_CODE_BLOCK_MARKER_RE = re.compile(r"^[ \t]*\.\. (?:code-block|code|sourcecode)::[ \t]*(\S*)[ \t]*$")

# literalinclude's own argument is a file path, not a language — its
# language (if any) comes from a ":language: X" option line immediately
# following the directive, found separately via _find_directive_option.
_LITERALINCLUDE_MARKER_RE = re.compile(r"^[ \t]*\.\. literalinclude::")

_OPTION_LINE_RE = re.compile(r"^[ \t]+:([\w-]+):[ \t]*(.*?)[ \t]*$")


def _find_directive_option(lines: list[str], start: int, name: str) -> str | None:
    """Return the value of option *name* in the directive-option block
    starting at 0-based *start*, or None if absent.

    Directive options are consecutive indented ":name: value" lines
    immediately after the directive marker, ending at the first blank or
    non-option-shaped line.
    """
    for line in lines[start:]:
        if not line.strip():
            break
        m = _OPTION_LINE_RE.match(line)
        if not m:
            break
        if m.group(1) == name:
            return m.group(2) or None
    return None


def find_code_blocks_heuristic(path: pathlib.Path, doc: Document | None = None) -> list[CodeBlockEntry]:
    """Return every code-block-like marker line found by pure text search.

    Matches all three Sphinx code-block aliases ("code-block", "code",
    "sourcecode") plus ".. literalinclude::" — a real corpus differential
    test (calendar/2026/05/2026-05-04/Notes.rst) found the real Sphinx-based
    find_code_blocks also counts literalinclude, since it counts ANY
    literal_block with a "language" attribute regardless of which directive
    produced it.

    Used only when --sphinx-src is not given — the real find_code_blocks
    requires a Sphinx environment. No docutils/Sphinx parsing is involved at
    all, which is exactly what restores full recall for Sphinx-only options
    (:caption:/:linenos:/etc.) that break bare docutils parsing entirely
    (confirmed: those code-blocks silently vanish from the real Phase 1
    doctree, not just lose precise line info). For code-block/code/
    sourcecode, language is the explicit directive argument if given, else
    None (CodeBlock.run() always resolves SOME language, falling back to the
    project's highlight_language — unknown here, but the entry still exists).

    literalinclude is different: read directly from sphinx.directives.code.
    LiteralInclude.run(), it has NO such fallback — ':diff:' forces language
    'udiff', ':language:' sets it exactly, and otherwise the 'language'
    attribute is never set on the node at all. So a bare literalinclude (no
    :language:, no :diff:) is EXCLUDED here entirely, matching the real
    detector's "if lang is None: continue" for that same, genuinely
    unhighlighted node — found by a real corpus differential test
    (calendar/2026/05/2026-05-10/Notes.rst and others) that first showed the
    opposite mistake: including it with language=None produced 6 entries the
    real detector didn't have at all, not just a language mismatch.

    KNOWN, ACCEPTED limitation #1: unlike find_code_blocks, there is no AST
    here to guard against a marker merely quoted as example text inside
    another real code-block — it IS double-counted. This is the deliberate
    cost of dropping the AST cross-check to restore recall; see
    find_code_blocks for the version that avoids it (requires --sphinx-src).

    KNOWN, ACCEPTED limitation #2: "code", "code-block", and "sourcecode"
    are NOT fully equivalent aliases, confirmed by reading docutils'
    registry directly: "code" maps to sphinx.directives.patches.Code (option
    set: class/force/name/number-lines only — no caption, no linenos), while
    "code-block"/"sourcecode" map to the full sphinx.directives.code.
    CodeBlock (caption/linenos/emphasize-lines/dedent/etc.). This heuristic
    does not validate which options are legal for which alias — doing so
    would mean hardcoding a slice of Sphinx's own directive-class registry,
    the same cost/complexity already declined for :doc:/:ref:/toctree. A
    real corpus differential test (a "Sphinx essentials" cheatsheet, using
    ".. code:: rst" with ":caption:" — invalid for that alias, and a genuine
    pre-existing content bug independent of check_rst: Sphinx itself drops
    those blocks from the build) found 12 heuristic entries the real
    detector didn't have, all traceable to this cause.

    depth comes from build_outline's already-reliable section headings
    (unaffected by code-block option parsing issues): one level deeper than
    the nearest preceding heading, or 1 if none precede it at all.

    KNOWN, ACCEPTED limitation #3 (2026-07-26): unlike every OTHER block
    finder (find_admonitions/find_block_quotes/find_comments/find_tables/
    find_code_blocks), this one never touches the doctree at all, so it
    cannot use _block_depth — there is no node to walk ancestors of. A
    code-block nested inside a list item therefore gets the SAME depth
    it would have directly under the enclosing heading, one level
    shallower than the AST-aware finders would report for the identical
    shape. Consistent with limitations #1/#2 above: the deliberate cost
    of dropping the AST cross-check to restore recall when no
    --sphinx-src is given.
    """
    document = _resolve_document(path, doc)
    lines = document.lines
    headings = document.outline
    entries: list[CodeBlockEntry] = []
    for i, line in enumerate(lines):
        m = _CODE_BLOCK_MARKER_RE.match(line)
        if m:
            lang = m.group(1) or None
        elif _LITERALINCLUDE_MARKER_RE.match(line):
            # Unlike code-block, LiteralInclude.run() has no config/env
            # fallback: :diff: forces 'udiff', :language: sets it exactly,
            # and otherwise the attribute is never set at all — so a bare
            # literalinclude is excluded here too, matching the real
            # detector's "if lang is None: continue" for the same node.
            if _find_directive_option(lines, i + 1, "diff") is not None:
                lang = "udiff"
            else:
                lang = _find_directive_option(lines, i + 1, "language")
                if lang is None:
                    continue
        else:
            continue

        lineno = i + 1
        depth = 1
        for heading in headings:
            if heading.lineno <= lineno:
                depth = heading.depth + 1
            else:
                break
        end = _indented_extent(lines, lineno)
        # Preview skips the directive's own ':option:' lines and the blank
        # separator before the actual content starts — the same shape
        # _find_directive_option already scans, just walked to its end
        # instead of stopping at one named option.
        content_start = lineno  # 0-based index of the line right after the marker
        while content_start < end and _OPTION_LINE_RE.match(lines[content_start]):
            content_start += 1
        while content_start < end and not lines[content_start].strip():
            content_start += 1
        preview = _outline_preview("\n".join(lines[content_start:end]))
        entries.append(CodeBlockEntry(lineno, depth, lang, preview, end))
    return entries


# ---------------------------------------------------------------------------
# Phase 3 — Sphinx build integrity check
# ---------------------------------------------------------------------------


def _findings_from_sphinx_output(
    raw_output: str,
    files: list[pathlib.Path],
    project_root: pathlib.Path | None = None,
) -> list[Finding]:
    """Parse sphinx-build-style 'path:line: LEVEL: msg' console lines into
    Findings, filtered to *files*.

    Shared by run_sphinx (Phase 3's separate sphinx-build subprocess) and
    _build_sphinx_env's caller (Phase 2's in-process build) — same console-
    output shape either way, and Phase 2's own warnings need the identical
    treatment: found by direct reproduction (2026-07-20) that Phase 2's
    build captured its warnings into an io.StringIO() nothing read, and
    since it shares --build-dir with Phase 3, the doctree it wrote was
    already fresh by the time Phase 3's separate sphinx-build ran — Sphinx's
    own incremental logic skipped re-parsing, so a real structural ERROR
    (confirmed: 'Inconsistent title style: skip from level 2 to 4') was
    lost between the two phases, never surfacing in either one.
    """
    root = PROJECT_ROOT if project_root is None else project_root
    explicit = {f.resolve() for f in files}
    findings: list[Finding] = []
    for raw in _ANSI_ESCAPE_RE.sub("", raw_output).splitlines():
        m = _WARNING_RE.match(raw)
        if m:
            p = pathlib.Path(m.group("path")).resolve()
            if p in explicit:
                try:
                    rel = p.relative_to(root)
                except ValueError:
                    rel = p
                line = m.group("line")
                findings.append(
                    Finding(
                        lineno=int(line) if line is not None else 0,
                        severity=Severity(m.group("level")),
                        text=f"{rel}: {m.group('msg')}",
                    )
                )
    return findings


def _is_sphinx_fixable_duplicate(
    finding: Finding,
    suppressed_paths: set[pathlib.Path],
    project_root: pathlib.Path,
) -> bool:
    """Return whether Sphinx merely restated a suppressed fixable defect."""
    if not any(message in finding.text for message in _FIXABLE_SPHINX_MESSAGES):
        return False
    root = project_root.resolve()
    for path in suppressed_paths:
        resolved = path.resolve()
        try:
            displayed = resolved.relative_to(root)
        except ValueError:
            displayed = resolved
        if finding.text.startswith(f"{displayed}: "):
            return True
    return False


# Matches Sphinx's own two broken-:doc:-target message shapes — note
# "unknown document:" has a colon before the quote, "nonexisting document"
# does not (confirmed by direct probe, 2026-07-22: `sphinx-build` on a typo'd
# `:doc:` role emits "unknown document: 'x' [ref.doc]"; a typo'd toctree
# entry emits "toctree contains reference to nonexisting document 'x'
# [toc.not_readable]" — same target, differently worded).
_BROKEN_DOC_REF_RE = re.compile(r"(?:unknown document: |nonexisting document )'([^']+)'")
_BROKEN_LABEL_REF_RE = re.compile(r"undefined label: '([^']+)'")


def _did_you_mean(target: str, candidates: Iterable[str]) -> str | None:
    """Return a ' — did you mean: ...?' suffix for the closest candidates
    to *target*, or None if nothing is close enough to be worth suggesting."""
    matches = difflib.get_close_matches(target, list(candidates), n=3, cutoff=0.6)
    if not matches:
        return None
    return f" — did you mean: {', '.join(repr(m) for m in matches)}?"


def _attach_did_you_mean(finding: Finding, env: sphinx.environment.BuildEnvironment) -> Finding:
    """Append a 'did you mean' suggestion to a broken-:doc:/:ref: finding,
    using the SAME live Sphinx environment Phase 2 already built for this
    run (env.found_docs, env.domaindata['std']['anonlabels']) — never
    objects.inv, which needs a completed HTML build and holds less than the
    env already in hand.  Findings that aren't a broken :doc:/:ref: (or
    whose target has no close candidate) pass through unchanged.  Closes
    the guess-and-wait loop the contract otherwise leaves to a human/AI on a
    broken cross-reference (Max, 2026-07-22, item 2 of the priority list).
    """
    m = _BROKEN_DOC_REF_RE.search(finding.text)
    if m:
        suggestion = _did_you_mean(m.group(1), env.found_docs)
        if suggestion:
            return dataclasses.replace(finding, text=finding.text + suggestion)
        return finding
    m = _BROKEN_LABEL_REF_RE.search(finding.text)
    if m:
        anonlabels = env.domaindata.get("std", {}).get("anonlabels", {})
        suggestion = _did_you_mean(m.group(1), anonlabels)
        if suggestion:
            return dataclasses.replace(finding, text=finding.text + suggestion)
        return finding
    return finding


def run_sphinx(
    files: list[pathlib.Path],
    build_dir: pathlib.Path,
    sphinx_src: pathlib.Path,
    project_root: pathlib.Path | None = None,
) -> list[Finding]:
    """Run sphinx-build; return ERROR/WARNING findings for the checked files."""
    CALL_COUNTS["run_sphinx"] += 1
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sphinx",
            "--builder",
            "html",
            str(sphinx_src),
            str(build_dir),
        ],
        capture_output=True,
        text=True,
    )
    findings = _findings_from_sphinx_output(result.stdout + result.stderr, files, project_root)
    if result.returncode != 0 and not any(finding.severity == Severity.ERROR for finding in findings):
        findings.append(
            Finding(
                lineno=0,
                severity=Severity.ERROR,
                text=(
                    f"sphinx-build exited {result.returncode} "
                    "(failure may be outside the checked files — run without file filter)"
                ),
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Document facade — stage 1 of the document model
# ---------------------------------------------------------------------------


class Document:
    """Read-only facade over one .rst file — stage 1 of the document model.

    Everything the checkers and reporters need, computed at most once and
    shared: the Phase 0-normalized text, its lines, the hygiene findings,
    the docutils doctree, the outline, code-block and blockquote entries,
    and the git diff ranges.  Lazy (cached_property), so a consumer pays
    only for what it touches; CALL_COUNTS assertions pin the one-read/
    one-parse contract in the tests.

    Deliberately read-only: fixers keep working on their own mutating line
    buffer and write to disk; after a fixer writes, construct a NEW
    Document.  Invalidation is explicit in the object lifetime — which is
    exactly what makes the caching safe (a path-keyed cache would serve
    stale text after --fix writes).
    """

    def __init__(
        self,
        path: pathlib.Path,
        project_root: pathlib.Path | None = None,
    ) -> None:
        self.path = path
        self.project_root = PROJECT_ROOT if project_root is None else project_root

    @functools.cached_property
    def source(self) -> str:
        return _read_source(self.path)

    @functools.cached_property
    def _normalized(self) -> tuple[str, list[Finding]]:
        return _normalize_source(self.source)

    @property
    def text(self) -> str:
        return self._normalized[0]

    @property
    def hygiene(self) -> list[Finding]:
        return self._normalized[1]

    @functools.cached_property
    def lines(self) -> list[str]:
        return self.text.splitlines()

    @functools.cached_property
    def ranges(self) -> list[tuple[int, int]] | None:
        return _changed_line_ranges(self.path, self.project_root)

    @functools.cached_property
    def doctree(self) -> docutils.nodes.document:
        return _parse_rst(self.path, text=self.text)

    @functools.cached_property
    def nested_inline_by_node(self) -> dict[int, tuple[docutils.nodes.Node, ...]]:
        """Successful explicit inline constructs found inside each outer span.

        Both the dedicated warning and check_directives' misdiagnosis guard
        consume this map in one CLI run.  Cache the expensive grammar probes on
        the same read-only Document lifetime so each outer node is re-parsed
        exactly once, not once per consumer.
        """
        result: dict[int, tuple[docutils.nodes.Node, ...]] = {}
        for outer in _findall_node_types(self.doctree, _INLINE_CONTAINER_TYPES):
            nested = _nested_inline_nodes(outer, self.doctree)
            if nested:
                result[id(outer)] = nested
        return result

    @functools.cached_property
    def prose_text(self) -> str:
        """The document's prose: text the author wrote as text.

        Doctree Text nodes, skipping literal blocks (code is not prose),
        comments, raw passthrough, and generated topics (a
        ``.. contents::`` directive's title is apparatus, not content —
        it was rank 2 in the first raw-frequency probe).  Bare docutils:
        no Sphinx build or configuration involved.

        The parser's own voice is not the author's prose either: under
        bare docutils every :doc: role and Sphinx-only directive produces
        a system_message whose text ("unknown directive type", "no role
        entry") leaked into the word statistics — on the reference note
        (2025-06-25) the "top prose words" were doc/directive/role/
        unknown: docutils' error vocabulary, not Max's.  Found by the
        semantic-vs-deterministic comparison the test method prescribes:
        the AI reads the repetitions, the tool counts, disagreement is a
        bug on one side or the other.  _NON_PROSE_NODE_TYPES (shared with
        check_homoglyphs) is exactly this skip-list.
        """
        parts: list[str] = []
        for text_node in self.doctree.findall(docutils.nodes.Text):
            node: docutils.nodes.Node | None = text_node.parent
            skipped = False
            while node is not None:
                if isinstance(node, _NON_PROSE_NODE_TYPES):
                    skipped = True
                    break
                node = node.parent
            if not skipped:
                parts.append(str(text_node))
        return "\n".join(parts)

    @functools.cached_property
    def outline(self) -> list[OutlineEntry]:
        return build_outline(self.path, doc=self)

    @functools.cached_property
    def block_quotes(self) -> list[BlockQuoteEntry]:
        return find_block_quotes(self.path, doc=self)

    @functools.cached_property
    def admonitions(self) -> list[AdmonitionEntry]:
        return find_admonitions(self.path, doc=self)

    @functools.cached_property
    def comments(self) -> list[CommentEntry]:
        return find_comments(self.path, doc=self)

    @functools.cached_property
    def lists(self) -> list[ListEntry]:
        return find_lists(self.path, doc=self)

    @functools.cached_property
    def code_blocks_heuristic(self) -> list[CodeBlockEntry]:
        return find_code_blocks_heuristic(self.path, doc=self)

    @functools.cached_property
    def tables(self) -> list[TableEntry]:
        return find_tables(self.path, doc=self)


def _resolve_document(path: pathlib.Path, doc: Document | None) -> Document:
    """Return *doc* if the caller already has one, else construct a fresh
    Document for *path* — the one-liner every checker/reporter used to
    duplicate inline (14 call sites, found by code review): a caller
    chaining off another Document (e.g. via Document.tables/.outline)
    passes it through and never re-reads or re-parses the file; a caller
    with none still gets one lazily, on first touch."""
    return doc if doc is not None else Document(path)


# ---------------------------------------------------------------------------
# Per-repo configuration — an explicit, versioned declaration of project
# facts, NOT auto-detection: nothing is guessed, someone committed these
# values.  Honesty conditions (see docs/guide.rst):
# automatic discovery at the working directory only (no parent-walking),
# explicit --config from anywhere, applied values echoed in the output, CLI
# flags always override, unknown keys fail loudly (a typo'd key silently
# ignored would be worse than none).
# ---------------------------------------------------------------------------

_CONFIG_KEYS = frozenset({"sphinx-src", "build-dir"})


@dataclasses.dataclass(frozen=True, slots=True)
class LoadedConfig:
    """A validated config together with the directory its paths use."""

    source: str
    root: pathlib.Path
    values: dict[str, str]


def _config_error(source: str, message: str, *, explicit: bool = True) -> NoReturn:
    label = f"--config {source}" if explicit else source
    print(f"check_rst: {label}: {message}")
    raise SystemExit(1)


def _config_table(
    path: pathlib.Path,
    source: str,
    *,
    explicit: bool,
) -> dict[str, str] | None:
    """Read and validate one supported TOML config file."""
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        _config_error(source, f"invalid TOML: {exc}", explicit=explicit)
    except OSError as exc:
        _config_error(source, str(exc), explicit=explicit)

    if path.name == "pyproject.toml":
        tool = data.get("tool", {})
        table = tool.get("check_rst", {}) if isinstance(tool, dict) else {}
    else:
        table = data
    if not table:
        if explicit:
            _config_error(source, "does not declare check_rst settings", explicit=True)
        return None
    if not isinstance(table, dict):
        _config_error(
            source,
            "check_rst settings must be a TOML table",
            explicit=explicit,
        )

    unknown = set(table) - _CONFIG_KEYS
    if unknown:
        print(
            f"check_rst: unknown key(s) in {source}: "
            f"{', '.join(sorted(unknown))} — known keys: "
            f"{', '.join(sorted(_CONFIG_KEYS))}"
        )
        raise SystemExit(1)
    for key, value in table.items():
        if not isinstance(value, str):
            print(f"check_rst: {source}: {key} must be a string, got {type(value).__name__}")
            raise SystemExit(1)
    return table


def _load_config(explicit_path: pathlib.Path | None = None) -> LoadedConfig:
    """Load an explicit config or discover one in the working directory.

    Looks for `.check_rst.toml` (whole file is the table) first, then
    `pyproject.toml` `[tool.check_rst]` — the dedicated file wins when
    both exist.  An explicit path disables that cwd discovery.  Relative
    settings are resolved later against the returned root.
    """
    CALL_COUNTS["_load_config"] += 1
    if explicit_path is not None:
        path = explicit_path.expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path = path.resolve()
        source = str(path)
        if not path.exists():
            _config_error(source, "file not found")
        if not path.is_file():
            _config_error(source, "not a regular file")
        table = _config_table(path, source, explicit=True)
        assert table is not None
        return LoadedConfig(source, path.parent, table)

    for name in (".check_rst.toml", "pyproject.toml"):
        path = PROJECT_ROOT / name
        if not path.is_file():
            continue
        table = _config_table(path, name, explicit=False)
        if table is None:
            continue
        return LoadedConfig(name, PROJECT_ROOT.resolve(), table)
    return LoadedConfig("", PROJECT_ROOT.resolve(), {})


def _runtime_metadata(verified: bool, word_samples: bool) -> dict[str, Any]:
    """Return versions of the runtime components that affect results."""
    sphinx_runtime: dict[str, str | None] | None = None
    if verified or word_samples:
        try:
            sphinx_version = importlib.metadata.version("Sphinx")
        except importlib.metadata.PackageNotFoundError:
            sphinx_version = None
        sphinx_runtime = {"version": sphinx_version}

    stemmer_runtime: dict[str, str | None] | None = None
    if word_samples:
        try:
            stemmer_version = importlib.metadata.version("snowballstemmer")
        except importlib.metadata.PackageNotFoundError:
            stemmer_version = None
        stemmer_runtime = {"version": stemmer_version}

    return {
        "check_rst": {"version": __version__},
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
        },
        "docutils": {"version": getattr(docutils, "__version__", None)},
        "sphinx": sphinx_runtime,
        "snowballstemmer": stemmer_runtime,
    }


def _format_runtime(metadata: dict[str, Any]) -> str:
    """Render _runtime_metadata as one concise human-readable line."""
    parts = [f"check_rst {metadata['check_rst']['version']}", f"Python {metadata['python']['version']}"]
    if metadata["sphinx"] is not None:
        parts.append(f"Sphinx {metadata['sphinx']['version'] or 'unknown'}")
    parts.append(f"docutils {metadata['docutils']['version'] or 'unknown'}")
    if metadata["snowballstemmer"] is not None:
        parts.append(f"snowballstemmer {metadata['snowballstemmer']['version'] or 'unavailable'}")
    return "runtime: " + ", ".join(parts)


# ---------------------------------------------------------------------------
# Top prose words — the meaningful-frequency statistic, from existing
# dependencies only: sphinx.search stopword lists (package import — no
# Sphinx build or conf.py involved) and snowballstemmer (a hard dependency
# of Sphinx, so present wherever Sphinx is).  Both semi-internal, so both
# defensively imported: when unavailable the statistic is OMITTED, never
# degraded to stopword noise (an unfiltered "most frequent word" is '-',
# 'de', '|', 'в' — measured on the June 2026 corpus).
# ---------------------------------------------------------------------------

_WORD_TOKEN_RE = re.compile(r"\w+")
_CYRILLIC_RE = re.compile("[\u0430-\u044f\u0451]")  # lowercase Cyrillic incl. io


class WordStatsUnavailable(RuntimeError):
    """A required provider for meaningful prose-word statistics is absent."""


class StopwordsUnavailable(WordStatsUnavailable):
    """Raised when sphinx.search's per-language stopword data can't be
    located under any attribute name this project has ever seen it use.
    Callers surface this as an explicit, counted WARNING — never a
    silently omitted statistic (the exact bug this exception replaces:
    confirmed on two dev hosts running different Sphinx versions, each
    using a DIFFERENT attribute casing for the same data — 8.2.3 defines
    lowercase ``english_stopwords`` directly on the module, 9.1.0
    re-exports uppercase ``ENGLISH_STOPWORDS`` from a private
    ``sphinx.search._stopwords`` package — so this has already changed
    at least twice and will likely change again)."""


def _find_stopwords(mod: object, names: tuple[str, ...]) -> frozenset[str]:
    """Return the stopword set exposed on *mod* under any of *names*.

    Raises StopwordsUnavailable, never a placeholder, when none resolve
    to a non-empty set — a stat silently omitted here is a stat nobody
    notices went missing."""
    for name in names:
        found = getattr(mod, name, None)
        if found:
            return frozenset(found)
    tried = " or ".join(names)
    mod_name = getattr(mod, "__name__", repr(mod))
    raise StopwordsUnavailable(f"{mod_name} has neither {tried}")


@functools.cache
def _stopword_sets() -> dict[str, frozenset[str]]:
    """The en/ru/fr stopword lists this trilingual journal needs, from
    sphinx.search.  Kept per-language: besides filtering, the en/fr
    lists double as a deterministic language detector — whichever list
    a document's tokens hit more often is the document's Latin
    language, and picks the Latin stemmer (Max, on a downstream project's French
    page: "wrong language taken as a base for another language").

    Raises StopwordsUnavailable — never returns None — when sphinx.search
    isn't importable or its internals have moved again; see
    _find_stopwords."""
    try:
        import sphinx.search.en
        import sphinx.search.fr
        import sphinx.search.ru
    except ImportError as exc:
        raise StopwordsUnavailable(f"sphinx.search not importable: {exc}") from exc
    return {
        "en": _find_stopwords(sphinx.search.en, ("ENGLISH_STOPWORDS", "english_stopwords")),
        "ru": _find_stopwords(sphinx.search.ru, ("RUSSIAN_STOPWORDS", "russian_stopwords")),
        "fr": _find_stopwords(sphinx.search.fr, ("FRENCH_STOPWORDS", "french_stopwords")),
    }


@functools.cache
def _prose_stemmers() -> tuple[object, object, object]:
    """(cyrillic, latin, extra-french) stemmers.  The first two GROUP
    inflections — the displayed word is always a real surface form, never
    a stem; Latin routes to the English stemmer (French words group
    slightly imperfectly — a cosmetic approximation of grouping, never of
    display).  The French stemmer is the extra suppressor for the
    rare-words sibling annotation: probed on a real downstream document, the
    naive annotation was ~80% French inflections; any stemmer agreeing
    the two words are one suppresses the pair."""
    try:
        import snowballstemmer
    except ImportError as exc:
        raise WordStatsUnavailable(f"snowballstemmer not importable: {exc}") from exc
    return (
        snowballstemmer.stemmer("russian"),
        snowballstemmer.stemmer("english"),
        snowballstemmer.stemmer("french"),
    )


def _prose_word_groups(
    prose_texts: list[str],
) -> dict[str, collections.Counter[str]]:
    """Stem-grouped word counts over *prose_texts*.

    Two passes: the first counts en/fr stopword hits — the stopword lists
    doubling as a deterministic language detector — so the second can
    route Latin tokens to the RIGHT stemmer (French inflections like
    vérifie/vérifier/vérifiée group only under the French stemmer; the
    old always-English routing mis-based French documents).  Cyrillic
    always routes to Russian.  Tokens containing digits are identifier
    debris (git hashes, timestamps), excluded from all word statistics.

    Raises WordStatsUnavailable when either the stopword tables or the
    required stemmers are unavailable.
    """
    sets = _stopword_sets()
    stop = frozenset().union(*sets.values())
    kept: list[str] = []
    en_hits = 0
    fr_hits = 0
    for text in prose_texts:
        for word in _WORD_TOKEN_RE.findall(text.lower()):
            if word in sets["en"]:
                en_hits += 1
            if word in sets["fr"]:
                fr_hits += 1
            if len(word) <= 2 or word in stop or any(ch.isdigit() for ch in word):
                continue
            kept.append(word)
    stemmers = _prose_stemmers()
    groups: dict[str, collections.Counter[str]] = {}
    for word in kept:
        cyr, lat_en, lat_fr = stemmers
        lat = lat_fr if fr_hits > en_hits else lat_en
        key = (cyr if _CYRILLIC_RE.search(word) else lat).stemWord(word)  # type: ignore[attr-defined]
        groups.setdefault(key, collections.Counter())[word] += 1
    return groups


def _top_prose_words(prose_texts: list[str], n: int) -> tuple[list[tuple[str, int]], int]:
    """Return (n most frequent meaningful words, count of suppressed word
    groups beyond n) — bounded output, never silent truncation.

    Raises WordStatsUnavailable when either the stopword tables or the
    required stemmers are unavailable."""
    groups = _prose_word_groups(prose_texts)
    ranked = sorted(
        ((sum(forms.values()), forms) for forms in groups.values()),
        key=lambda item: (-item[0], item[1].most_common(1)[0][0]),
    )
    top = [(forms.most_common(1)[0][0], total) for total, forms in ranked[:n]]
    return top, max(0, len(ranked) - n)


def _one_edit_apart(a: str, b: str) -> bool:
    """True when *a* and *b* differ by exactly one edit: a substitution,
    an insertion/deletion, or an adjacent transposition — the classical
    shape of a typo.  Chosen over a similarity-ratio cutoff after the
    ratio missed a real, confessed, journal-attested mistake by 0.013:
    ratio(померял, померил) = 0.857 < the 0.87 cutoff, while the word
    occurs once against 146 correct occurrences."""
    la, lb = len(a), len(b)
    if abs(la - lb) > 1 or a == b:
        return False
    if la == lb:
        diffs = [i for i in range(la) if a[i] != b[i]]
        if len(diffs) == 1:
            return True
        return (
            len(diffs) == 2 and diffs[1] == diffs[0] + 1 and a[diffs[0]] == b[diffs[1]] and a[diffs[1]] == b[diffs[0]]
        )
    if la > lb:
        a, b = b, a  # a is the shorter
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1 :]


def _rare_prose_words(prose_texts: list[str], n: int) -> tuple[list[tuple[str, str | None, int]], int]:
    """The other extreme (Max, 2026-07-19), in its honest form: once-only
    prose words as (word, closest frequent sibling or None, sibling count)
    — the tool states the deterministic facts, the human judges typo vs
    morphology vs legitimate word.

    A MUTUAL pair — two once-words one edit apart, the small-page typo
    signature — is one symmetric fact and is reported once, as
    ``a ↔ b``, never as two reciprocal annotations (the "loop" display
    Max flagged).  Pairs sort first, then one-directional annotations
    (a rare word with a more frequent sibling one edit away —
    substitution, insertion/deletion, or adjacent transposition: the
    classical typo shape) — on a single page they are the spell-scan candidates —
    then plain once-words alphabetically.  Suppressions keep precision
    honest: identifier debris (mixed alphanumerics: git hashes,
    timestamps) is excluded, and a sibling pair unified by ANY stemmer
    (ru/en/fr) is a mere inflection, not a candidate (probed on the real
    downstream document: without this, ~80% of annotations were French
    morphology).

    Raises WordStatsUnavailable when either the stopword tables or the
    required stemmers are unavailable.
    """
    groups = _prose_word_groups(prose_texts)
    once: list[str] = []
    surfaces: dict[str, int] = {}
    for forms in groups.values():
        total = sum(forms.values())
        surface = forms.most_common(1)[0][0]
        surfaces[surface] = total
        if total == 1:  # debris already excluded at the groups level
            once.append(surface)
    stemmers = _prose_stemmers()
    annotated: list[tuple[str, str | None, int]] = []
    plain: list[tuple[str, str | None, int]] = []
    # Any other word can be the sibling — a small page's typo pair is two
    # once-words one edit apart (fameworks/frameworks, found by Max on a
    # real note); a frequency threshold on the sibling blinded exactly
    # that primary use-case.  Most frequent sibling preferred.
    by_frequency = sorted(surfaces, key=lambda w: (-surfaces[w], w))
    siblings: dict[str, str | None] = {}
    for word in sorted(once):
        sibling = next(
            (f for f in by_frequency if f != word and _one_edit_apart(word, f)),
            None,
        )
        if sibling is not None and any(
            st.stemWord(word) == st.stemWord(sibling)  # type: ignore[attr-defined]
            for st in stemmers
        ):
            sibling = None  # inflection, not a candidate
        siblings[word] = sibling
    pairs: list[tuple[str, str | None, int]] = []
    for word in sorted(once):
        sibling = siblings[word]
        if sibling is None:
            plain.append((word, None, 0))
        elif siblings.get(sibling) == word:
            if word < sibling:  # report the symmetric fact once
                pairs.append((word, sibling, surfaces[sibling]))
        else:
            annotated.append((word, sibling, surfaces[sibling]))
    ordered = pairs + annotated + plain
    return ordered[:n], max(0, len(ordered) - n)


def _docname_id(path: pathlib.Path, project_root: pathlib.Path | None = None) -> str:
    """Stable document name for section ids: path relative to the project
    root, without extension — the autosectionlabel prefix convention."""
    root = PROJECT_ROOT if project_root is None else project_root
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return path.stem
    return str(rel.with_suffix(""))


def _json_file_model(
    document: Document,
    code_blocks: list[CodeBlockEntry],
    word_samples: int,
    outline_entries: list[OutlineEntry] | None = None,
    toctree_entries: list[ToctreeEntry] | None = None,
    project_root: pathlib.Path | None = None,
) -> dict[str, Any]:
    """The per-file document model for --json: outline with stable ids,
    code-blocks, blockquote previews, statistics.

    word_samples == 0 (default outside --verbose/--word-samples, Max,
    2026-07-20) skips top_words/rare_words entirely — null, no error —
    same "pay for what you don't use" contract as the text footer: the
    stopword/stemmer machinery is never touched unless requested.

    toctree_entries (2026-07-26): the toctree CONTAINER markers found by
    find_toctrees, reported separately under "toctrees" — the headings
    they pull in from other documents are real sections, so they are
    merged straight into "outline" instead.  Both entry kinds expose a
    nullable docname: None for this file, the source docname after crossing
    a toctree boundary."""
    docname = _docname_id(document.path, project_root)
    outline = []
    outline_id_counts: collections.Counter[str] = collections.Counter()
    for entry in outline_entries if outline_entries is not None else document.outline:
        d = dataclasses.asdict(entry)
        # A cross-file heading's own Sphinx docname (entry.docname) IS its
        # stable identifier already — never re-derived from this file's
        # own `docname`, which would collide every cross-file entry onto
        # this document's id.
        base_id = f"{entry.docname or docname}:{entry.title}"
        outline_id_counts[base_id] += 1
        occurrence = outline_id_counts[base_id]
        d["id"] = base_id if occurrence == 1 else f"{base_id}#{occurrence}"
        outline.append(d)
    toctrees = []
    for toctree_entry in toctree_entries or []:
        toctrees.append(dataclasses.asdict(toctree_entry))
    # top_words/rare_words null + word_stats_error set is an explicit,
    # typed failure signal (never a bare null with no reason) — see
    # StopwordsUnavailable.  null with word_stats_error also null means
    # "not requested", distinguishable from "requested but unavailable".
    top_words: tuple[list[tuple[str, int]], int] | None
    rare_words: tuple[list[tuple[str, str | None, int]], int] | None
    word_stats_error: str | None
    if word_samples:
        try:
            top_words = _top_prose_words([document.prose_text], word_samples)
            rare_words = _rare_prose_words([document.prose_text], word_samples)
            word_stats_error = None
        except WordStatsUnavailable as exc:
            top_words = rare_words = None
            word_stats_error = str(exc)
    else:
        top_words = rare_words = None
        word_stats_error = None
    return {
        "outline": outline,
        "toctrees": toctrees,
        "code_blocks": [dataclasses.asdict(e) for e in code_blocks],
        "block_quotes": [dataclasses.asdict(e) for e in document.block_quotes],
        "tables": [dataclasses.asdict(e) for e in document.tables],
        "admonitions": [dataclasses.asdict(e) for e in document.admonitions],
        "comments": [dataclasses.asdict(e) for e in document.comments],
        "lists": [dataclasses.asdict(e) for e in document.lists],
        "stats": {
            "lines": len(document.lines),
            "empty_lines": sum(1 for line in document.lines if not line.strip()),
            "chars": len(document.text),
            "bytes": len(document.text.encode("utf-8")),
            "spaces": document.text.count(" "),
            "chars_distinct": len(set(document.text)),
            "chars_once": [
                f"U+{ord(c):04X}" for c in sorted(ch for ch, n in collections.Counter(document.text).items() if n == 1)
            ],
            "words": len(document.text.split()),
            "words_distinct": len(set(document.text.split())),
            # (top-10 list, suppressed-count) — same no-silent-truncation
            # contract as the footer.
            "top_words": top_words,
            # ([word, sibling|null, sibling-count], suppressed) — the other
            # extreme: once-only words with the closest-frequent-sibling
            # FACT; typo-vs-morphology judgment stays human.
            "rare_words": rare_words,
            "word_stats_error": word_stats_error,
        },
    }


# ---------------------------------------------------------------------------
# Targeted entry context (--context)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class ContextMatch:
    """One addressable member of the heterogeneous outline entry stream.

    ``selector`` is the preferred user-facing identity.  Sections retain
    their stable autosectionlabel-shaped id; every entry also has a generated
    ``kind@line`` alias, which makes anonymous and future entry kinds
    addressable without teaching the resolver about each class.
    """

    index: int
    entry: object
    selector: str
    universal_selector: str
    kind: str
    source_docname: str
    match_texts: tuple[str, ...]


def _generic_entry_kind(entry: object) -> str:
    """Human-readable kind derived from a class name, with useful refinements.

    The fallback is deliberately generic: adding a new ``SomethingEntry`` to
    the outline stream automatically makes it resolvable by --context.
    """
    if isinstance(entry, OutlineEntry):
        return "section"
    if isinstance(entry, ListEntry):
        if entry.item_count is not None:
            return f"{entry.kind} list"
        return f"{entry.kind} item"
    if isinstance(entry, CodeBlockEntry):
        return "code block"
    if isinstance(entry, BlockQuoteEntry):
        return "blockquote"
    if isinstance(entry, AdmonitionEntry):
        return f"{entry.kind} admonition"
    if isinstance(entry, ToctreeEntry):
        return "toctree cycle" if entry.cycle is not None else "toctree"
    name = type(entry).__name__
    if name.endswith("Entry"):
        name = name[:-5]
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).lower()
    return words or "entry"


def _entry_slug(kind: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", kind.lower()).strip("-") or "entry"


def _entry_lineno(entry: object) -> int:
    value = getattr(entry, "lineno", 0)
    return value if isinstance(value, int) else 0


def _entry_end(entry: object) -> int:
    start = _entry_lineno(entry)
    value = getattr(entry, "end", start)
    return value if isinstance(value, int) and value >= start else start


def _entry_depth(entry: object) -> int:
    value = getattr(entry, "depth", 1)
    return value if isinstance(value, int) and value >= 1 else 1


def _entry_string_values(entry: object) -> tuple[str, ...]:
    """All non-empty string fields, generically, as semantic exact matches."""
    values: list[str] = []
    if dataclasses.is_dataclass(entry):
        for field in dataclasses.fields(entry):
            value = getattr(entry, field.name)
            if isinstance(value, str) and value:
                values.append(value)
    else:
        for value in vars(entry).values() if hasattr(entry, "__dict__") else ():
            if isinstance(value, str) and value:
                values.append(value)
    return tuple(dict.fromkeys(values))


def _context_candidates(entries: list[object], local_docname: str) -> list[ContextMatch]:
    universal_counts: collections.Counter[str] = collections.Counter()
    section_counts: collections.Counter[str] = collections.Counter()
    candidates: list[ContextMatch] = []
    for index, entry in enumerate(entries):
        explicit_docname = getattr(entry, "docname", None)
        source_docname = explicit_docname if isinstance(explicit_docname, str) and explicit_docname else local_docname
        kind = _generic_entry_kind(entry)
        universal_base = f"{source_docname}:{_entry_slug(kind)}@{_entry_lineno(entry)}"
        universal_counts[universal_base] += 1
        universal_occurrence = universal_counts[universal_base]
        universal_selector = universal_base if universal_occurrence == 1 else f"{universal_base}#{universal_occurrence}"

        selector = universal_selector
        if isinstance(entry, OutlineEntry):
            section_base = f"{source_docname}:{entry.title}"
            section_counts[section_base] += 1
            occurrence = section_counts[section_base]
            selector = section_base if occurrence == 1 else f"{section_base}#{occurrence}"

        candidates.append(
            ContextMatch(
                index=index,
                entry=entry,
                selector=selector,
                universal_selector=universal_selector,
                kind=kind,
                source_docname=source_docname,
                match_texts=_entry_string_values(entry),
            )
        )
    return candidates


def _resolve_context_matches(entries: list[object], query: str, local_docname: str) -> list[ContextMatch]:
    """Resolve an exact selector first, then exact semantic field text.

    Selector precedence matters for duplicate titles: ``doc:Title`` is the
    stable identity of the first section, while bare ``Title`` deliberately
    remains ambiguous.  No substring/fuzzy fallback may silently choose a
    structurally different entry.
    """
    candidates = _context_candidates(entries, local_docname)
    by_selector = [candidate for candidate in candidates if query in (candidate.selector, candidate.universal_selector)]
    if by_selector:
        return by_selector
    return [candidate for candidate in candidates if query in candidate.match_texts]


def _context_relationships(
    candidates: list[ContextMatch], selected: ContextMatch
) -> tuple[
    ContextMatch | None,
    ContextMatch | None,
    ContextMatch | None,
    list[ContextMatch],
    list[ContextMatch],
]:
    """Return parent, previous/next sibling, direct children, and full path."""
    parents: dict[int, int | None] = {}
    children: dict[int | None, list[int]] = collections.defaultdict(list)
    stack: list[int] = []
    for candidate in candidates:
        depth = _entry_depth(candidate.entry)
        while stack and _entry_depth(candidates[stack[-1]].entry) >= depth:
            stack.pop()
        parent_index = stack[-1] if stack else None
        parents[candidate.index] = parent_index
        children[parent_index].append(candidate.index)
        stack.append(candidate.index)

    parent_index = parents[selected.index]
    parent = candidates[parent_index] if parent_index is not None else None
    sibling_indices = children[parent_index]
    position = sibling_indices.index(selected.index)
    previous = candidates[sibling_indices[position - 1]] if position else None
    following = candidates[sibling_indices[position + 1]] if position + 1 < len(sibling_indices) else None
    direct_children = [candidates[index] for index in children[selected.index]]

    path: list[ContextMatch] = []
    cursor: int | None = selected.index
    while cursor is not None:
        path.append(candidates[cursor])
        cursor = parents[cursor]
    path.reverse()
    return parent, previous, following, direct_children, path


def _context_entry_label(candidate: ContextMatch) -> str:
    entry = candidate.entry
    if isinstance(entry, OutlineEntry):
        return f'section "{entry.title}"'
    if isinstance(entry, ListEntry):
        if entry.item_count is not None:
            plural = "s" if entry.item_count != 1 else ""
            return f"{entry.kind} list ({entry.marker!r}, {entry.item_count} item{plural})"
        text = entry.marker if entry.kind == "definition" else entry.preview
        return f'{candidate.kind} "{text}"'
    if isinstance(entry, CodeBlockEntry):
        language = entry.language or "no language"
        suffix = f': "{entry.preview}"' if entry.preview else ""
        return f"code block ({language}){suffix}"
    if isinstance(entry, BlockQuoteEntry):
        return f'blockquote "{entry.preview}"'
    if isinstance(entry, TableEntry):
        title = entry.caption or entry.preview
        return f'table "{title}"' if title else "table"
    if isinstance(entry, AdmonitionEntry):
        title = entry.title or entry.preview
        return f'{candidate.kind} "{title}"' if title else candidate.kind
    if isinstance(entry, CommentEntry):
        return f'comment "{entry.preview}"'
    if isinstance(entry, ToctreeEntry):
        return str(entry).strip().split(": ", 1)[-1]
    values = _entry_string_values(entry)
    return f'{candidate.kind} "{values[0]}"' if values else candidate.kind


def _context_candidate_line(candidate: ContextMatch) -> str:
    start = _entry_lineno(candidate.entry)
    end = _entry_end(candidate.entry)
    extent = f"{start}-{end}" if end > start else str(start)
    return f"{candidate.selector} — {_context_entry_label(candidate)} — {extent}"


def _context_findings(document: Document) -> list[Finding]:
    """Phase 0/1 findings available without turning the query into a build."""
    findings = list(document.hygiene)
    findings.extend(check_adornments(document.path, True, doc=document))
    findings.extend(check_hierarchy(document.path, doc=document))
    findings.extend(check_single_top_level(document.path, doc=document))
    findings.extend(check_nested_inline_markup(document.path, True, doc=document))
    findings.extend(check_directives(document.path, True, True, doc=document))
    findings.extend(check_homoglyphs(document.path, doc=document))
    return list(dict.fromkeys(findings))


def _bounded_context_lines(lines: list[str], limit: int = 20) -> list[str]:
    shown = lines[:limit]
    hidden = len(lines) - len(shown)
    if hidden:
        shown.append(f"({hidden} more suppressed)")
    return shown


def _format_context(
    source_path: pathlib.Path,
    query: str,
    candidates: list[ContextMatch],
    selected: ContextMatch,
    findings: list[Finding],
    outgoing: list[ReferenceEntry] | None,
    incoming: list[ReferenceEntry] | None,
) -> str:
    parent, previous, following, children, path = _context_relationships(candidates, selected)
    start = _entry_lineno(selected.entry)
    end = _entry_end(selected.entry)
    extent = f"{start}-{end}" if end > start else str(start)
    applicable = [f for f in findings if f.lineno == 0 or start <= f.lineno <= end]

    lines = [
        f"Context: {source_path}",
        f"query: {query!r}",
        "entry:",
        f"  selector: {selected.selector}",
        f"  kind: {selected.kind}",
        f"  range: {extent}",
        f"  depth: {_entry_depth(selected.entry)}",
        f"  summary: {_context_entry_label(selected)}",
        "path:",
    ]
    lines.extend(f"  {_context_candidate_line(item)}" for item in path)
    lines.append(f"parent: {_context_candidate_line(parent)}" if parent is not None else "parent: (none)")
    lines.append("siblings:")
    lines.append(f"  previous: {_context_candidate_line(previous)}" if previous is not None else "  previous: (none)")
    lines.append(f"  next: {_context_candidate_line(following)}" if following is not None else "  next: (none)")
    lines.append("children:")
    if children:
        child_lines = [_context_candidate_line(child) for child in children]
        lines.extend(f"  {line}" for line in _bounded_context_lines(child_lines))
    else:
        lines.append("  (none)")

    lines.append("findings:")
    if applicable:
        lines.extend(f"  {finding.lineno}: {finding.severity}: {finding.text}" for finding in applicable)
    else:
        lines.append("  (none in selected range)")

    lines.append("references:")
    if outgoing is None or incoming is None:
        lines.append("  unavailable — verified Sphinx mode required")
    else:
        scoped_outgoing = [e for e in outgoing if start <= e.lineno <= end]
        lines.append("  outgoing (selected range):")
        if scoped_outgoing:
            formatted = [
                f"{e.lineno}: {e.reftype} -> {e.target} ({e.resolved if e.resolved is not None else 'BROKEN'})"
                for e in scoped_outgoing
            ]
            lines.extend(f"    {line}" for line in _bounded_context_lines(formatted))
        else:
            lines.append("    (none)")
        lines.append("  incoming (document-level):")
        if incoming:
            lines.extend(f"    {line}" for line in _bounded_context_lines([str(entry) for entry in incoming]))
        else:
            lines.append("    (none)")
    return "\n".join(lines)


def _format_context_candidates(
    path: pathlib.Path,
    query: str,
    candidates: list[ContextMatch],
    matches: list[ContextMatch],
) -> str:
    lines = [
        f"check_rst: {path}: --context {query!r} is ambiguous: {len(matches)} exact matches",
        "candidates:",
    ]
    candidate_limit = 20
    for match in matches[:candidate_limit]:
        _parent, _previous, _following, _children, entry_path = _context_relationships(candidates, match)
        path_text = " > ".join(item.selector for item in entry_path)
        lines.append(f"  {_context_candidate_line(match)} — path: {path_text}")
    hidden = len(matches) - candidate_limit
    if hidden > 0:
        lines.append(f"  ({hidden} more candidates suppressed)")
    return "\n".join(lines)


def _run_context_query(
    query: str,
    path: pathlib.Path,
    project_root: pathlib.Path,
    sphinx_src: pathlib.Path | None,
    build_dir: pathlib.Path | None,
    no_toctree: bool,
) -> int:
    """Run the self-contained, read-only --context query."""
    try:
        document = Document(path, project_root)
        _ = document.doctree
    except UnicodeDecodeError as exc:
        line = exc.object.count(b"\n", 0, exc.start) + 1
        print(f"check_rst: {path}:{line}: not valid UTF-8 ({exc.reason})")
        return 1

    env: sphinx.environment.BuildEnvironment | None = None
    sphinx_findings: list[Finding] = []
    keep_build = build_dir is not None
    actual_build_dir = (
        build_dir if build_dir is not None else pathlib.Path(tempfile.mkdtemp(prefix="check_rst_context_"))
    )
    try:
        if sphinx_src is None:
            local_docname = _docname_id(path, project_root)
            code_blocks = document.code_blocks_heuristic
            outline = document.outline
            clusters: list[list[ToctreeEntry | OutlineEntry]] = []
        else:
            env, warning_text = _build_sphinx_env_checked(sphinx_src, actual_build_dir, files=[path])
            local = _docname_for(env, path)
            if local is None:
                print(f"check_rst: {path}: not part of the --sphinx-src project")
                return 1
            local_docname = local
            code_blocks = find_code_blocks(env, local_docname, document.lines)
            outline = build_outline(path, doc=document, doctree=env.get_doctree(local_docname))
            clusters = [] if no_toctree else find_toctrees(env, local_docname, document)
            sphinx_findings.extend(_findings_from_sphinx_output(warning_text, [path], project_root))
            sphinx_findings.extend(check_bare_filenames(env, local_docname, document))
            sphinx_findings.extend(check_multiple_toctree_parents(env, [path]))

        local_entries: list[
            OutlineEntry | CodeBlockEntry | BlockQuoteEntry | TableEntry | AdmonitionEntry | CommentEntry | ListEntry
        ] = sorted(
            [
                *outline,
                *code_blocks,
                *document.block_quotes,
                *document.tables,
                *document.admonitions,
                *document.comments,
                *document.lists,
            ],
            key=_entry_lineno,
        )
        entries: list[object] = []
        if clusters:
            entries.extend(_merge_toctree_clusters(local_entries, clusters))
        else:
            entries.extend(local_entries)
        candidates = _context_candidates(entries, local_docname)
        matches = _resolve_context_matches(entries, query, local_docname)
        if not matches:
            print(f"check_rst: {path}: no exact entry match for {query!r}\nhint: inspect selectors with outline {path}")
            return 1
        if len(matches) > 1:
            print(_format_context_candidates(path, query, candidates, matches))
            return 1

        selected = matches[0]
        source_path = path
        selected_document = document
        if env is not None and selected.source_docname != local_docname:
            source_path = pathlib.Path(env.doc2path(selected.source_docname))
            selected_document = Document(source_path, project_root)
            sphinx_findings = _findings_from_sphinx_output(warning_text, [source_path], project_root)
            sphinx_findings.extend(check_bare_filenames(env, selected.source_docname, selected_document))
            sphinx_findings.extend(check_multiple_toctree_parents(env, [source_path]))

        findings = _context_findings(selected_document) + sphinx_findings
        outgoing = find_references(env, selected.source_docname) if env is not None else None
        incoming = find_incoming_references(env, selected.source_docname) if env is not None else None
        print(
            _format_context(
                source_path,
                query,
                candidates,
                selected,
                list(dict.fromkeys(findings)),
                outgoing,
                incoming,
            )
        )
        return 0
    finally:
        if not keep_build:
            shutil.rmtree(actual_build_dir, ignore_errors=True)


def _load_json_dump(path: pathlib.Path) -> dict[str, Any]:
    """Load and validate one check_rst ``--json`` dump for ``--diff-json``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"check_rst: {path}: {exc.strerror}")
        raise SystemExit(1) from exc
    except UnicodeError as exc:
        print(f"check_rst: {path}: not valid UTF-8: {exc}")
        raise SystemExit(1) from exc
    except json.JSONDecodeError as exc:
        print(f"check_rst: {path}: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")
        raise SystemExit(1) from exc

    if not isinstance(data, dict):
        print(f"check_rst: {path}: top level must be an object")
        raise SystemExit(1)
    for key in ("files", "summary"):
        if key not in data:
            print(f"check_rst: {path}: missing required key {key!r}")
            raise SystemExit(1)
    if not isinstance(data["files"], list):
        print(f"check_rst: {path}: 'files' must be an array")
        raise SystemExit(1)
    if not isinstance(data["summary"], dict):
        print(f"check_rst: {path}: 'summary' must be an object")
        raise SystemExit(1)

    summary = data["summary"]
    for key in ("files_checked", "errors", "warnings"):
        if key not in summary:
            print(f"check_rst: {path}: summary missing {key!r}")
            raise SystemExit(1)
        if not isinstance(summary[key], int) or isinstance(summary[key], bool):
            print(f"check_rst: {path}: summary {key!r} must be an integer")
            raise SystemExit(1)

    for i, file_record in enumerate(data["files"]):
        if not isinstance(file_record, dict):
            print(f"check_rst: {path}: files[{i}] must be an object")
            raise SystemExit(1)
        for key in ("path", "outline", "findings"):
            if key not in file_record:
                print(f"check_rst: {path}: files[{i}] missing {key!r}")
                raise SystemExit(1)
        if not isinstance(file_record["path"], str):
            print(f"check_rst: {path}: files[{i}].path must be a string")
            raise SystemExit(1)
        if not isinstance(file_record["outline"], list):
            print(f"check_rst: {path}: files[{i}].outline must be an array")
            raise SystemExit(1)
        if not isinstance(file_record["findings"], list):
            print(f"check_rst: {path}: files[{i}].findings must be an array")
            raise SystemExit(1)

    return data


def _diff_json_dumps(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Structured semantic diff between two --json dumps (--diff-json).

    Logged 2026-07-18, independently re-confirmed 2026-07-21 by a real
    downstream-project session: "several times this session I rewrote a whole file...
    and had to manually eyeball 'same warning count, same categories as
    before' rather than get a machine answer."

    Matches files by path, outline entries by their stable
    'docname:title' id (built for exactly this — see _json_file_model),
    findings by (severity, text).  Deliberately NOT by line number: an
    unrelated earlier edit shifts every line after it, which would
    otherwise show every surviving finding as both resolved and added.
    """
    provenance_keys = ("schema_version", "mode", "runtime")
    provenance_changed = [key for key in provenance_keys if old.get(key) != new.get(key)]

    old_files = {f["path"]: f for f in old.get("files", [])}
    new_files = {f["path"]: f for f in new.get("files", [])}

    def summary_delta(key: str) -> dict[str, int]:
        o = old.get("summary", {}).get(key, 0)
        n = new.get("summary", {}).get(key, 0)
        return {"old": o, "new": n, "delta": n - o}

    summary = {k: summary_delta(k) for k in ("files_checked", "errors", "warnings")}

    files_diff: dict[str, Any] = {}
    for path in sorted(set(old_files) | set(new_files)):
        if path not in new_files:
            files_diff[path] = {"status": "removed"}
            continue
        if path not in old_files:
            files_diff[path] = {"status": "added"}
            continue
        o, n = old_files[path], new_files[path]
        old_outline = {e["id"]: e for e in o.get("outline", [])}
        new_outline = {e["id"]: e for e in n.get("outline", [])}
        added_ids = sorted(set(new_outline) - set(old_outline))
        removed_ids = sorted(set(old_outline) - set(new_outline))
        changed_ids = sorted(
            oid
            for oid in (set(old_outline) & set(new_outline))
            if (old_outline[oid]["depth"], old_outline[oid]["char"])
            != (new_outline[oid]["depth"], new_outline[oid]["char"])
        )

        def finding_key(f: dict[str, Any]) -> tuple[str, str]:
            return (f["severity"], f["text"])

        old_findings = collections.Counter(finding_key(f) for f in o.get("findings", []))
        new_findings = collections.Counter(finding_key(f) for f in n.get("findings", []))
        added_findings = list((new_findings - old_findings).elements())
        resolved_findings = list((old_findings - new_findings).elements())

        changed = bool(added_ids or removed_ids or changed_ids or added_findings or resolved_findings)
        files_diff[path] = {
            "status": "changed" if changed else "unchanged",
            "outline": {
                "added": added_ids,
                "removed": removed_ids,
                "hierarchy_changed": changed_ids,
            },
            "findings": {
                "added": [{"severity": s, "text": t} for s, t in added_findings],
                "resolved": [{"severity": s, "text": t} for s, t in resolved_findings],
            },
        }

    def sphinx_finding_key(finding: dict[str, Any]) -> tuple[str, str]:
        return (finding["severity"], finding["text"])

    old_sphinx = collections.Counter(sphinx_finding_key(finding) for finding in old.get("sphinx_findings", []))
    new_sphinx = collections.Counter(sphinx_finding_key(finding) for finding in new.get("sphinx_findings", []))
    added_sphinx = list((new_sphinx - old_sphinx).elements())
    resolved_sphinx = list((old_sphinx - new_sphinx).elements())
    return {
        "provenance": {
            "changed": provenance_changed,
            "old": {key: old.get(key) for key in provenance_keys},
            "new": {key: new.get(key) for key in provenance_keys},
        },
        "summary": summary,
        "files": files_diff,
        "sphinx_findings": {
            "added": [{"severity": severity, "text": text} for severity, text in added_sphinx],
            "resolved": [{"severity": severity, "text": text} for severity, text in resolved_sphinx],
        },
    }


def _format_json_diff(diff: dict[str, Any]) -> str:
    """Render _diff_json_dumps' structured result as a --diff-json report."""
    lines = ["Summary:"]
    provenance = diff.get("provenance", {})
    if provenance.get("changed"):
        lines.append("  WARNING: comparison provenance differs: " + ", ".join(provenance["changed"]))
    for key, d in diff["summary"].items():
        sign = "+" if d["delta"] > 0 else ""
        lines.append(f"  {key}: {d['old']} -> {d['new']} ({sign}{d['delta']})")

    sphinx_findings = diff.get("sphinx_findings", {})
    added_sphinx = sphinx_findings.get("added", [])
    resolved_sphinx = sphinx_findings.get("resolved", [])
    if added_sphinx or resolved_sphinx:
        lines.append(f"Sphinx findings: +{len(added_sphinx)} added, -{len(resolved_sphinx)} resolved")
        lines.extend(f"  + {finding['severity']}: {finding['text']}" for finding in added_sphinx)
        lines.extend(f"  - {finding['severity']}: {finding['text']}" for finding in resolved_sphinx)

    for path, fd in diff["files"].items():
        status = fd["status"]
        if status in ("added", "removed", "unchanged"):
            lines.append(f"\n{path}: {status}")
            continue

        lines.append(f"\n{path}: changed")
        outline = fd["outline"]
        if outline["added"] or outline["removed"] or outline["hierarchy_changed"]:
            parts = []
            if outline["added"]:
                parts.append(f"+{len(outline['added'])} section(s)")
            if outline["removed"]:
                parts.append(f"-{len(outline['removed'])} section(s)")
            parts.append(
                f"hierarchy changed: {', '.join(outline['hierarchy_changed'])}"
                if outline["hierarchy_changed"]
                else "hierarchy unchanged"
            )
            lines.append(f"  outline: {', '.join(parts)}")
            for oid in outline["added"]:
                lines.append(f"    + {oid}")
            for oid in outline["removed"]:
                lines.append(f"    - {oid}")

        findings = fd["findings"]
        if findings["added"] or findings["resolved"]:
            lines.append(f"  findings: +{len(findings['added'])} added, -{len(findings['resolved'])} resolved")
            for f in findings["added"]:
                lines.append(f"    + {f['severity']}: {f['text']}")
            for f in findings["resolved"]:
                lines.append(f"    - {f['severity']}: {f['text']}")
    return "\n".join(lines)


def _print_outline_entries(
    entries: list[
        OutlineEntry
        | CodeBlockEntry
        | BlockQuoteEntry
        | TableEntry
        | AdmonitionEntry
        | CommentEntry
        | ListEntry
        | ToctreeEntry
    ],
    depth_limit: int | None,
    verbose: bool,
    sections_only: bool = False,
) -> None:
    """Print outline entries, honoring --outline-depth and --sections-only.

    Bounded output is never silent truncation (house rule): when a depth
    limit and/or --sections-only hides entries, a trailing note says how
    many and why.

    sections_only (2026-07-26) filters by KIND, not depth: every leaf
    entry (code-block/blockquote/table/admonition/comment/list) is
    suppressed regardless of how shallow it sits, unlike --outline-depth
    which bounds by depth regardless of kind — the two compose rather
    than overlap.  The levels:/blocks: legend and every heading's own
    bracketed counts are computed against the FULL entries list either
    way, never `shown` — a display filter trims display, never
    information, the same contract --outline-depth already established.

    verbose gates only the 'blocks:' whole-document summary line (Max,
    2026-07-20: verbosity-level inventory — the 'levels:' legend stays
    unconditional whenever --outline runs at all, matching its existing,
    unchanged behavior; 'blocks:' is the one promoted to --verbose-only).
    """
    shown = [
        e
        for e in entries
        if (depth_limit is None or e.depth <= depth_limit) and (not sections_only or isinstance(e, OutlineEntry))
    ]

    # Legend: the depth→char mapping with per-level section counts, plus the
    # document's total section/code-block/blockquote counts (Max,
    # 2026-07-20) — stated once and always for the WHOLE document, under a
    # depth limit it reveals what exists below the cut (the limit trims
    # entries, never information; two legend lines are not heavy).  In a
    # valid document each depth has one char; a malformed one lists all
    # observed chars for the depth, '/'-joined.
    level_chars: dict[int, list[str]] = {}
    level_counts: dict[int, int] = {}
    n_code = 0
    n_quotes = 0
    n_tables = 0
    n_admonitions = 0
    n_comments = 0
    n_lists = 0
    n_toctrees = 0
    n_cycles = 0
    for entry in entries:
        if isinstance(entry, OutlineEntry):
            # Cross-file headings (entry.docname set) are excluded from
            # THIS file's own levels: legend — they carry another
            # document's own adornment convention, which would pollute
            # what this legend promises: what chars/depths this file
            # itself uses (Max, 2026-07-26, implicit in the toctree
            # design: the legend answers "what do I pick for a new
            # sibling heading HERE", a question cross-file entries can't
            # answer for this file).
            if entry.docname is None:
                chars = level_chars.setdefault(entry.depth, [])
                if entry.char not in chars:
                    chars.append(entry.char)
                level_counts[entry.depth] = level_counts.get(entry.depth, 0) + 1
        elif isinstance(entry, ToctreeEntry):
            if entry.cycle is not None:
                n_cycles += 1
            else:
                n_toctrees += 1
        elif isinstance(entry, CodeBlockEntry):
            n_code += 1
        elif isinstance(entry, BlockQuoteEntry):
            n_quotes += 1
        elif isinstance(entry, TableEntry):
            n_tables += 1
        elif isinstance(entry, AdmonitionEntry):
            n_admonitions += 1
        elif isinstance(entry, CommentEntry):
            n_comments += 1
        elif isinstance(entry, ListEntry) and (entry.item_count is not None or entry.kind == "definition"):
            # Count the list as one unit (container, or a standalone
            # definition item) — never its individual bullet/enumerated
            # items, the same convention as a table counting once, not
            # once per row.
            n_lists += 1
    if level_chars:
        total_sections = sum(level_counts.values())
        legend = ", ".join(
            f"{depth} " + "/".join(repr(c) for c in chars) + f" ({level_counts[depth]})"
            for depth, chars in sorted(level_chars.items())
        )
        plural = "s" if total_sections != 1 else ""
        print(f"  levels: {legend}, {total_sections} section{plural} total")
    if verbose and (n_code or n_quotes or n_tables or n_admonitions or n_comments or n_lists or n_toctrees or n_cycles):
        block_parts = []
        if n_code:
            block_parts.append(f"{n_code} code block{'s' if n_code != 1 else ''}")
        if n_quotes:
            block_parts.append(f"{n_quotes} blockquote{'s' if n_quotes != 1 else ''}")
        if n_tables:
            block_parts.append(f"{n_tables} table{'s' if n_tables != 1 else ''}")
        if n_admonitions:
            block_parts.append(f"{n_admonitions} admonition{'s' if n_admonitions != 1 else ''}")
        if n_comments:
            block_parts.append(f"{n_comments} comment{'s' if n_comments != 1 else ''}")
        if n_lists:
            block_parts.append(f"{n_lists} list{'s' if n_lists != 1 else ''}")
        if n_toctrees:
            block_parts.append(f"{n_toctrees} toctree{'s' if n_toctrees != 1 else ''}")
        if n_cycles:
            block_parts.append(f"{n_cycles} toctree cycle{'s' if n_cycles != 1 else ''}")
        print(f"  blocks: {', '.join(block_parts)}")

    for entry in shown:
        if isinstance(entry, OutlineEntry):
            # Cumulative — everything anywhere in this section's line range,
            # including its subsections' own content (Max, 2026-07-20: asked
            # for whole-subtree totals, not direct-children-only, since
            # that's the simpler and more useful "how much is under this
            # heading" answer).  Computed against the FULL entries list,
            # never `shown` — a depth limit trims display, not information.
            #
            # entry.docname is not None (2026-07-26): a cross-file heading
            # pulled in via toctree recursion.  Its .lineno/.end live in
            # ANOTHER file's coordinate space — comparing them against
            # `entries`, which is this file's own local code/table/etc.
            # entries, would be a meaningless numeric coincidence, not a
            # real containment check (this listing never pulls a child
            # document's own code-blocks/tables/etc. in, only its headings
            # and toctrees), so nested counts are skipped entirely rather
            # than computed wrong.
            extra: list[str] = []
            if entry.docname is None:
                section_end = max(entry.end, entry.lineno)
                nested_code = sum(
                    1 for e in entries if isinstance(e, CodeBlockEntry) and entry.lineno <= e.lineno <= section_end
                )
                nested_quotes = sum(
                    1 for e in entries if isinstance(e, BlockQuoteEntry) and entry.lineno <= e.lineno <= section_end
                )
                nested_tables = sum(
                    1 for e in entries if isinstance(e, TableEntry) and entry.lineno <= e.lineno <= section_end
                )
                nested_admonitions = sum(
                    1 for e in entries if isinstance(e, AdmonitionEntry) and entry.lineno <= e.lineno <= section_end
                )
                nested_comments = sum(
                    1 for e in entries if isinstance(e, CommentEntry) and entry.lineno <= e.lineno <= section_end
                )
                nested_lists = sum(
                    1
                    for e in entries
                    if isinstance(e, ListEntry)
                    and (e.item_count is not None or e.kind == "definition")
                    and entry.lineno <= e.lineno <= section_end
                )
                nested_toctrees = sum(
                    1 for e in entries if isinstance(e, ToctreeEntry) and entry.lineno <= e.lineno <= section_end
                )
            else:
                nested_code = nested_quotes = nested_tables = 0
                nested_admonitions = nested_comments = nested_lists = nested_toctrees = 0
            if nested_code:
                extra.append(f"{nested_code} code block{'s' if nested_code != 1 else ''}")
            if nested_quotes:
                extra.append(f"{nested_quotes} blockquote{'s' if nested_quotes != 1 else ''}")
            if nested_tables:
                extra.append(f"{nested_tables} table{'s' if nested_tables != 1 else ''}")
            if nested_admonitions:
                extra.append(f"{nested_admonitions} admonition{'s' if nested_admonitions != 1 else ''}")
            if nested_comments:
                extra.append(f"{nested_comments} comment{'s' if nested_comments != 1 else ''}")
            if nested_toctrees:
                extra.append(f"{nested_toctrees} toctree{'s' if nested_toctrees != 1 else ''}")
            if nested_lists:
                extra.append(f"{nested_lists} list{'s' if nested_lists != 1 else ''}")
            print(f"  {entry.formatted(extra)}")
        else:
            print(f"  {entry}")
    hidden = len(entries) - len(shown)
    if hidden:
        reasons = []
        if depth_limit is not None:
            reasons.append(f"--outline-depth {depth_limit}")
        if sections_only:
            reasons.append("--sections-only")
        plural = "y" if hidden == 1 else "ies"
        # "deeper" is only accurate when depth is the sole possible cause
        # (sections_only unset) — preserves the exact pre-existing wording
        # for that case; a kind-filtered entry isn't necessarily deeper.
        label = "entr" if sections_only else "deeper entr"
        print(f"  ({hidden} {label}{plural} hidden — {', '.join(reasons)})")
    if not entries:
        print("  (no sections)")


# Long, static rationale for a repeated finding pattern, printed once per
# run rather than on every matching line (Max, 2026-07-20: "it repeats...
# long. Can we inform this as a separate line only once?" — the same
# "state shared context once, not per entry" principle as the outline's
# levels: legend).  Keyed by the finding text's distinguishing prefix;
# _hints_shown tracks which have already printed and is reset at the top
# of main() — once per RUN, not once per file.
_FINDING_HINTS: tuple[tuple[str, str], ...] = (
    (
        "nested inline markup ",
        "reStructuredText renders only the outer inline role; choose which one should survive",
    ),
    (
        "bold paragraph opener ",
        "AI documents often use this pattern as an informal heading; consider a proper section title",
    ),
    ("standalone bold line ", "verify it is not substituting a section title (bold is for inline emphasis only)"),
)
_hints_shown: set[str] = set()


def _print_findings(
    findings: list[Finding],
    prefix: str,
    no_warnings: bool,
    suppress: bool = False,
) -> tuple[int, int]:
    """Print findings; return (error count, visible-warning count).

    Counts, not booleans, so main() can feed the final summary line —
    truthiness-compatible with the old (has_errors, has_warnings) shape.
    suppress=True counts without printing (--outline-only): a display
    filter under the "trims display, never information" contract — the
    footer and the exit code stay honest.
    """
    n_errors = 0
    n_warnings = 0
    for f in findings:
        if f.severity == Severity.WARNING:
            if no_warnings:
                continue
            n_warnings += 1
            if not suppress:
                for key, hint in _FINDING_HINTS:
                    if f.text.startswith(key) and key not in _hints_shown:
                        _hints_shown.add(key)
                        print(f"  ({key.strip()}: {hint})")
                # No leading glyph (Max, 2026-07-20: "we break de-facto
                # compiler alike output... those prefixes are optional, we've
                # got the text warning or error" — added to the contract, see
                # docs/guide.rst, "De-facto compiler output").
                # Bare "{prefix}:{f}" already reads as "path:line: WARNING:
                # message" via Finding.__str__ — the shape generic tooling
                # (IDE problem matchers, editor jump-to-error) parses.
                with _report_kind("WARNING"):
                    print(f"{prefix}:{f}")
        else:
            n_errors += 1
            if not suppress:
                with _report_kind("ERROR"):
                    print(f"{prefix}:{f}")
    return n_errors, n_warnings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_fix_only_status(processed: int, errors: int, fixed: int) -> None:
    """Print the mandatory final status line for ``fix --fast`` (was ``--fix-only``)."""
    _emit_final_status(f"check_rst: {processed} file(s) processed, {errors} error(s), {fixed} file(s) fixed [fast]")


def _run_fix_only(
    files: list[pathlib.Path],
    whole_file: bool,
    *,
    include_structure: bool,
    project_root: pathlib.Path | None,
    scope: str,
    quiet: bool,
    verbose: bool,
) -> NoReturn:
    """Plan every selected mutation, then write and report structured results."""
    if not quiet:
        print(f"check_rst: fast scope — {scope}")

    plans: list[FixPlan] = []
    errors = 0
    for path in files:
        try:
            plans.append(
                _plan_fix(
                    path,
                    whole_file,
                    include_structure=include_structure,
                    project_root=project_root,
                )
            )
        except UnicodeDecodeError as exc:
            err_line = exc.object.count(b"\n", 0, exc.start) + 1
            _emit_report_line(
                f"{path}:{err_line}: ERROR: not valid UTF-8 ({exc.reason} at byte offset {exc.start})",
                "ERROR",
            )
            errors += 1
        except OSError as exc:
            _emit_report_line(f"check_rst: {path}: ERROR: cannot read input: {exc}", "ERROR")
            errors += 1
        except RuntimeError as exc:
            _emit_report_line(f"check_rst: {path}: ERROR: {exc}", "ERROR")
            errors += 1

    if errors:
        _print_fix_only_status(len(files), errors, 0)
        raise SystemExit(1)

    results: list[FixResult] = []
    for plan in plans:
        try:
            result = _apply_fix_plan(plan)
        except OSError as exc:
            _emit_report_line(
                f"check_rst: {plan.path}: ERROR: cannot write fix: {exc}",
                "ERROR",
            )
            errors += 1
            break
        results.append(result)
        if not quiet and result.changed:
            print(f"{result.path}: fixed — {result.counts.describe()}")
        elif not quiet and verbose:
            print(f"{result.path}: no fixable changes")

    fixed = sum(result.changed for result in results)
    _print_fix_only_status(len(files), errors, fixed)
    raise SystemExit(1 if errors else 0)


def _run_list_table(
    files: list[pathlib.Path], *, only: list[int], skip: list[int], apply: bool, quiet: bool
) -> NoReturn:
    """Plan every selected file's table conversions, print each file's
    refusals (never silent) and diff or write outcome, then exit —
    dry-run by default (1 when anything would change, matching diff's
    own convention), 0 on a successful --apply or a clean run either
    way. A file whose selection is unresolvable (unknown ordinal) or
    whose converted result fails whole-file semantic validation is
    reported and left untouched; it does not stop the other files."""
    would_change = 0
    fatal_files = 0
    converted_files = 0
    for path in files:
        result = _plan_list_table_file(path, only, skip)
        if result.fatal is not None:
            print(f"check_rst: {path}: {result.fatal}")
            fatal_files += 1
            continue
        for ordinal, reason in result.refusals:
            print(f"check_rst: {path}: table {ordinal}: {reason}")
        if not result.changed:
            if not quiet:
                print(f"check_rst: {path}: no eligible tables to convert")
            continue
        would_change += 1
        if apply:
            path.write_bytes(result.candidate.encode("utf-8"))
            converted_files += 1
            if not quiet:
                converted = ", ".join(str(ordinal) for ordinal in result.converted)
                print(f"check_rst: {path}: converted table(s) {converted}")
        else:
            print(
                "".join(
                    difflib.unified_diff(
                        [line + "\n" for line in result.original.splitlines()],
                        [line + "\n" for line in result.candidate.splitlines()],
                        fromfile=str(path),
                        tofile=str(path),
                    )
                ),
                end="",
            )
    if not quiet:
        if apply:
            _emit_final_status(
                f"check_rst: {len(files)} file(s) checked, {fatal_files} error(s), {converted_files} file(s) converted"
            )
        else:
            _emit_final_status(
                f"check_rst: {len(files)} file(s) checked, {fatal_files} error(s), {would_change} file(s) would change"
            )
    raise SystemExit(1 if fatal_files or (not apply and would_change) else 0)


# ---------------------------------------------------------------------------
# Subcommand CLI redesign (docs/roadmap.rst, "Subcommands: flag-soup
# incompatibilities become verbs") — replaces the old flat-flag parser and
# its hand-written _validate_cli_args incompatibility matrix, now deleted.
# Wired into _main() below via _build_cli_parser()/_backfill_post_parse();
# see tests/test_cli_subcommands.py for direct, isolated parser exercise.
#
# _CLI_ATTR_DEFAULTS is the complete cross-pipeline attribute contract: every
# name _main()'s ~960-line dispatch/pipeline body reads via `args.<name>`,
# across every verb combined. Every subparser gets this whole dict via
# set_defaults() so the untouched pipeline body never hits an AttributeError
# regardless of which verb reached it — parser-level defaults always win over
# an omitted flag, and are always overridden by a flag the verb's own parser
# actually defines and the user passed.
#
# build_dir/config/no_config/sphinx_src are deliberately ABSENT from this
# dict, unlike every other name the pipeline reads — they are the global
# options (_add_project_flags, defined once on the main parser, before the
# verb). argparse's _SubParsersAction.__call__ parses each subparser into a
# *fresh* Namespace, then unconditionally copies every one of its keys back
# onto the parent (`for key, value in vars(subnamespace).items():
# setattr(namespace, key, value)` — no hasattr guard at that step, unlike
# the single-parser default-fill loop). If these four names stayed in
# _CLI_ATTR_DEFAULTS, every subparser's own set_defaults() call would
# silently reset them to None/False on the shared namespace, clobbering
# whatever the user passed before the verb — confirmed by direct
# reproduction: --no-config check file.rst measured args.no_config as
# False. Keep this dict's four project-flag names removed, not "safe to
# re-add" — the clobber is a property of the merge step, not of any
# ordering trick played here.
# ---------------------------------------------------------------------------

_CLI_ATTR_DEFAULTS: dict[str, object] = {
    "collapse_title_spaces": False,
    "context": None,
    "diff": False,
    "diff_json": None,
    "diff_only": False,
    "exclude": [],
    "files": [],
    "fix": False,
    "fix_only": False,
    "git_scope": False,
    "json": False,
    "max_output_lines": None,
    "no_adornments": False,
    "no_directives": False,
    "no_toctree": False,
    "no_warnings": False,
    "normalize_blank_lines": False,
    "outline": False,
    "outline_depth": None,
    "outline_only": False,
    "quiet": False,
    "recursive": False,
    "refs": None,
    "sections_only": False,
    "single_space_prose": False,
    "skip_fixable": False,
    "verbose": False,
    "word_samples": None,
}


def _add_project_flags(parser: argparse.ArgumentParser) -> None:
    """--config/--no-config/--sphinx-src/--build-dir — global options
    identifying which project/repo to operate on, added once to the main
    parser (before the verb, git-style: ``check_rst --sphinx-src DIR check
    file.rst``, not ``check_rst check --sphinx-src DIR file.rst``). Every
    verb except diff-json can read them; diff-json is fully self-contained
    and rejects them explicitly (see _validate_diff_json_args)."""
    parser.add_argument(
        "--config",
        type=pathlib.Path,
        default=None,
        metavar="FILE",
        help=(
            "load check_rst settings from FILE instead of discovering "
            ".check_rst.toml or pyproject.toml in cwd. Relative sphinx-src "
            "and build-dir values, and bare Git file discovery, are rooted "
            "at FILE's directory; positional CLI paths remain cwd-relative"
        ),
    )
    parser.add_argument(
        "--no-config",
        action="store_true",
        help=(
            "skip .check_rst.toml/pyproject.toml auto-discovery entirely — run "
            "with CLI-only defaults, as if the working directory declared no "
            "project facts. A malformed or unknown-key config would otherwise "
            "fail loudly on discovery alone, before CLI flags get a say; this "
            "opts fully out instead of requiring the file to be valid first. "
            "Incompatible with --config, which explicitly requests a config"
        ),
    )
    parser.add_argument(
        "--sphinx-src",
        type=pathlib.Path,
        default=None,
        metavar="DIR",
        help=(
            "Sphinx source directory. Enables the verified versions of Phase 2 "
            "(Python Sphinx rules: a real in-process Sphinx env) and Phase 3 "
            "(Sphinx build integrity check) against it. Never auto-detected, "
            "even when a conf.py is sitting right there in cwd or an ancestor "
            "directory — this is deliberate, not a missing feature: pass it "
            "explicitly whenever you want verified results. Default: omit this "
            "option and Phase 2 falls back to a heuristic, text-search-only "
            "code-block detector (clearly labeled as such, with known false-"
            "positive edge cases) and Phase 3 is skipped entirely — there is no "
            "implicit directory ever guessed at. DIR must contain conf.py or "
            "this errors immediately; e.g. --sphinx-src . for a repo whose "
            "conf.py is at the root, or --sphinx-src docs/ when the source is "
            "a subdir"
        ),
    )
    parser.add_argument(
        "--build-dir",
        type=pathlib.Path,
        default=None,
        metavar="DIR",
        help=(
            "Sphinx output directory; if omitted a unique temp dir is created "
            "and removed after the run. Requires verified mode from "
            "--sphinx-src or project configuration"
        ),
    )


def _add_no_toctree_flag(parser: argparse.ArgumentParser) -> None:
    """--no-toctree — shared by every verb whose structure/model can recurse toctrees."""
    parser.add_argument(
        "--no-toctree",
        action="store_true",
        help=(
            "don't recurse into .. toctree:: directives when building this "
            "entry's structure (verified mode only — requires --sphinx-src); "
            "default recurses fully, pulling in every reachable document's "
            "own headings, bounded only by --outline-depth, never by each "
            "toctree's own maxdepth"
        ),
    )


def _add_scope_flags(parser: argparse.ArgumentParser) -> None:
    """--recursive/--git-scope/--exclude — shared by check/fix/diff/outline."""
    parser.add_argument(
        "--recursive",
        action="store_true",
        help=(
            "treat each positional argument as a directory and recursively "
            "discover *.rst files under it (pathlib.Path.rglob) instead of "
            "checking the arguments themselves as files; use --exclude to "
            "skip specific files. No shell involved, so filenames containing "
            "spaces are handled correctly. Implies whole-file checking, same "
            "as naming individual files"
        ),
    )
    parser.add_argument(
        "--git-scope",
        action="store_true",
        help=(
            "treat positional files as an allowlist intersected with Git's "
            "changed/untracked RST set, preserving bare-mode diff scoping "
            "instead of explicit files' normal whole-file scope; requires "
            "at least one file and is incompatible with --recursive"
        ),
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "with --recursive, skip any discovered file whose path matches "
            "PATTERN (pathlib.PurePath.match() semantics: a bare filename "
            "matches that name at any depth); repeatable"
        ),
    )


def _add_quiet_verbose_words(parser: argparse.ArgumentParser) -> None:
    """--quiet/--verbose/--word-samples — shared by check/fix/diff/outline."""
    parser.add_argument(
        "--verbose",
        action="store_true",
        help=(
            "show extra detail on bold/rubric WARNING findings: the actual bold/rubric "
            "text, a preview of the paragraph text after a bold opener, and the "
            "enclosing section title. No effect on adornment/hierarchy ERRORs or "
            "Phase 2 — those findings are already maximally detailed (adornments) or "
            "have no extra native detail to surface (Phase 2). Combine with "
            "outline --with-findings to see structure and findings together, or use "
            "either alone. Also raises "
            "the footer/outline detail level: the --outline 'blocks:' summary and the "
            "footer's 'lines:'/'words:'/top-and-rare-prose-words lines are hidden by "
            "default (and under --quiet) and shown only here — see --word-samples to "
            "promote just the prose-word lines without the rest"
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help=(
            "suppress progress output — phase banners, per-file OK lines, "
            "per-file fix notices. Findings (path:line: WARNING:/ERROR: "
            "lines), each repeated finding kind's once-per-run rationale, "
            "requested reports (--outline, --diff) and the final summary "
            "line still print. Born from session-transcript "
            "evidence (2026-07-18): five AI sessions independently piped "
            "output through grep to recover exactly this view"
        ),
    )
    parser.add_argument(
        "--word-samples",
        type=int,
        default=None,
        metavar="N",
        help=(
            "number of entries in the footer's top/rare prose words lines "
            "(and the JSON model's top_words/rare_words per file). Omit to "
            "default to 10 under --verbose, or to omit the lines entirely "
            "(and skip computing them — no stopword/stemmer cost paid) "
            "otherwise. Passing this explicitly promotes the lines at any "
            "verbosity level, --quiet included; 0 disables them even under "
            "--verbose"
        ),
    )


def _add_max_output_lines(parser: argparse.ArgumentParser) -> None:
    """--max-output-lines — kept as its own helper (not folded into the
    quiet/verbose/words group) because diff's parser deliberately never
    defines it: cli.py's _validate_cli_args already rejects it alongside
    ordinary --diff, not only --diff-only."""
    parser.add_argument(
        "--max-output-lines",
        type=int,
        default=None,
        metavar="N",
        help=(
            "cap the complete text report at N lines without stopping checks "
            "or masking their exit status; N must be >= 2. The first N-2 "
            "ordinary lines are followed by an output-limit statistics line "
            "and the authoritative final status. Applied after semantic "
            "filters such as --quiet/--sections-only/--outline-depth. "
            "Supported on check, fix, and outline; not defined on diff, refs, "
            "context, or diff-json, which must remain complete"
        ),
    )


def _add_report_filters(parser: argparse.ArgumentParser) -> None:
    """--no-warnings/--skip-fixable/--no-adornments/--no-directives — shared
    by check/fix/diff/outline."""
    parser.add_argument(
        "--no-warnings",
        action="store_true",
        help="suppress WARNING-level findings; only show and count ERROR-level ones",
    )
    parser.add_argument(
        "--skip-fixable",
        action="store_true",
        help=(
            "suppress ERROR-level findings that fix resolves automatically "
            "(byte hygiene: BOM/line endings/trailing whitespace; wrong "
            "adornment length, underline-only titles, hierarchy char order); "
            "human-review WARNINGs remain visible; unrelated non-fixable input, "
            "UTF-8, or Sphinx ERRORs still fail the run. Use on the pre-fix pass "
            "to focus on what needs human attention before running fix"
        ),
    )
    parser.add_argument(
        "--no-adornments",
        action="store_true",
        help=(
            "skip adornment and hierarchy lint and, with fix/diff, their "
            "structural changes; Phase 0 byte hygiene remains enabled"
        ),
    )
    parser.add_argument(
        "--no-directives",
        action="store_true",
        help="skip directive warnings (rubric, bold patterns)",
    )


def _build_full_parent() -> argparse.ArgumentParser:
    """Shared parent for the four verbs built on the roadmap's 'full' shape:
    check, fix, diff, outline."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "files",
        nargs="*",
        type=pathlib.Path,
        help=(
            "files to check, normally checked in full; --git-scope instead "
            "treats them as a changed-file allowlist. Omit to auto-detect "
            "changed/untracked *.rst files from git status in the selected "
            "project instead (cwd normally, FILE's directory with --config) "
            "— those are scoped to lines changed since HEAD (untracked "
            "files are still checked in full, having no HEAD state to diff "
            "against). Any selected file with an unresolved Git index entry "
            "aborts the complete check/fix before a phase or write starts"
        ),
    )
    _add_scope_flags(parent)
    _add_quiet_verbose_words(parent)
    _add_report_filters(parent)
    return parent


def _build_list_table_parent() -> argparse.ArgumentParser:
    """Parent for list-table: files + scope flags (--recursive/--git-
    scope/--exclude) + --quiet, but none of check/fix/diff/outline's
    report-filter or --word-samples flags — this verb runs no Phase 1
    lint pass of its own, only the table conversion itself."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "files",
        nargs="*",
        type=pathlib.Path,
        help=(
            "files to convert tables in, normally checked in full; --git-scope "
            "instead treats them as a changed-file allowlist. Omit to "
            "auto-detect changed/untracked *.rst files from git status in the "
            "selected project instead (cwd normally, FILE's directory with "
            "--config)"
        ),
    )
    _add_scope_flags(parent)
    parent.add_argument(
        "--quiet",
        action="store_true",
        help="suppress progress output — per-file OK lines and refusal notices; the final summary line still prints",
    )
    parent.add_argument(
        "--apply",
        action="store_true",
        help=(
            "write the converted file(s); the default previews a unified diff "
            "without modifying anything, same as diff's own convention. A "
            "table that fails semantic validation leaves its file untouched "
            "even when other tables in the same file convert successfully"
        ),
    )
    parent.add_argument(
        "--only",
        type=int,
        action="append",
        default=[],
        metavar="N",
        help=(
            "convert only the Nth table (1-based, document order) per selected "
            "file; repeatable. Default: every mechanically-eligible table. "
            "Combines with --skip by narrowing to --only's ordinals first, "
            "then removing any --skip ordinals from that set"
        ),
    )
    parent.add_argument(
        "--skip",
        type=int,
        action="append",
        default=[],
        metavar="N",
        help="exclude the Nth table (1-based, document order) per selected file from conversion; repeatable",
    )
    return parent


def _build_mutating_parent() -> argparse.ArgumentParser:
    """Shared parent for fix/diff only: --fast plus the three editorial
    fixers that require full parsing (and are therefore rejected by --fast,
    same as they're absent from check/outline entirely)."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--fast",
        action="store_true",
        help=(
            "fast, parser-free counterpart (was --fix-only/--diff-only): plan "
            "every selected file before writing, apply only Phase 0 byte "
            "hygiene and Phase 1 adornment/hierarchy corrections (fix) or "
            "preview them (diff), then stop without lint, statistics, "
            "docutils parsing, or either Sphinx phase. Config still roots Git "
            "selection, but configured Sphinx settings are reported inactive; "
            "explicit --sphinx-src/--build-dir and the editorial fixers below "
            "are incompatible. Run ordinary check_rst check afterwards for "
            "full validation"
        ),
    )
    parent.add_argument(
        "--normalize-blank-lines",
        action="store_true",
        help=(
            "remove leading blank lines and collapse repeated separator/EOF "
            "blank lines only when the complete docutils tree is unchanged; "
            "opt-in because blank lines inside literal-like blocks are "
            "content. Rejected under --fast, which skips the parser"
        ),
    )
    parent.add_argument(
        "--collapse-title-spaces",
        action="store_true",
        help=(
            "collapse internal ASCII-space runs in visible section-title "
            "text while preserving inline literals and requiring unchanged "
            "structure, attributes, targets, and ids; editorial and opt-in, "
            "rejected under --fast"
        ),
    )
    parent.add_argument(
        "--single-space-prose",
        action="store_true",
        help=(
            "apply an explicit single-ASCII-space policy to eligible "
            "paragraph text under a permitted-delta tree check; protects "
            "literal/raw/code/math payloads and RST syntax; editorial and "
            "opt-in, rejected under --fast"
        ),
    )
    return parent


# Attribute names a --fast allowlist scan must never flag regardless of
# `allowed`: mode identity is structural (implied by which verb/flag was
# used), not a value the allowlist check is meant to police.
_MODE_IDENTITY_ATTRS = frozenset({"command", "fix", "diff", "fix_only", "diff_only", "fast"})

# Preserves today's exact asymmetry between --fix-only's and --diff-only's
# allowlists in the now-deleted _validate_cli_args (cli.py, pre-redesign):
# fix's allows verbose/max_output_lines, diff's does not.
_FAST_ALLOWLIST: dict[str, frozenset[str]] = {
    "fix": frozenset(
        {
            "files",
            "config",
            "no_config",
            "git_scope",
            "no_adornments",
            "recursive",
            "exclude",
            "quiet",
            "verbose",
            "max_output_lines",
        }
    ),
    "diff": frozenset({"files", "config", "no_config", "git_scope", "no_adornments", "recursive", "exclude", "quiet"}),
}


def _cli_fail(message: str) -> NoReturn:
    """Report one CLI validation failure and exit 1 — the shared shape
    every per-verb validator below used to hand-roll inline (found by
    code review: ~12 duplicated print(f\"check_rst: ...\"); raise
    SystemExit(1) pairs). Distinct from _config_error: that one labels
    failures by config source (--config path or discovered file); this
    one is for argparse-level argument validation, with no such label."""
    print(f"check_rst: {message}")
    raise SystemExit(1)


def _validate_fast_allowlist(args: argparse.Namespace, verb: str) -> None:
    """--fast is self-contained, same as today's --fix-only/--diff-only:
    reject anything not on that verb's own allowlist (_FAST_ALLOWLIST)."""
    allowed = _FAST_ALLOWLIST[verb]
    values = vars(args)
    incompatible = [
        name
        for name, value in values.items()
        if name not in allowed and name not in _MODE_IDENTITY_ATTRS and _argument_is_set(value)
    ]
    if incompatible:
        _cli_fail(
            f"{verb} --fast is self-contained — incompatible "
            f"argument(s): {', '.join('--' + name.replace('_', '-') for name in incompatible)}"
        )


def _validate_config_flags(args: argparse.Namespace) -> None:
    """--no-config and --config are mutually exclusive — asking to both
    explicitly load a config file and skip config loading is a
    contradiction, not a request either flag alone could satisfy."""
    if args.no_config and args.config is not None:
        _cli_fail("--no-config is incompatible with --config")


def _validate_full_scope_args(args: argparse.Namespace) -> None:
    """--exclude/--git-scope/--recursive peer-flag rules shared by every verb
    built on _build_full_parent (check/fix/diff/outline) — legitimate peers
    on one parser, not expressible in argparse itself. Preserves the exact
    checks and messages from the now-deleted _validate_cli_args."""
    if args.exclude and not args.recursive:
        _cli_fail("--exclude requires --recursive")
    if args.git_scope:
        if args.recursive:
            _cli_fail("--git-scope is incompatible with --recursive")
        if not args.files:
            _cli_fail("--git-scope requires at least one file")


def _build_cli_parser() -> argparse.ArgumentParser:
    """Build the subcommand argparse parser.

    Every subparser is backfilled with _CLI_ATTR_DEFAULTS so the untouched
    _main() pipeline body can read any args.<name> regardless of verb.
    """
    hierarchy_lines = "\n".join(
        f"    {i:2d}. {c!r}" + ("  (preferred)" if c in PREFERRED_HIERARCHY else "") for i, c in enumerate(HIERARCHY, 1)
    )
    hierarchy_help = f"""
Adornment character hierarchy, by rank (check_hierarchy's ERROR-level
skipped-level/wrong-order checks, and fix's remap, both use this order;
a character past rank 6 also gets a WARNING, never an ERROR). Ranks 1-6
are the tool's opinionated default convention; ranks 7-32 are
every other character docutils itself recognizes as a valid RST adornment
(VALID_ADORNMENT_CHARS, derived directly from docutils, not hardcoded),
appended in docutils' own order — there's no practical meaning to the
order past rank 6 (no document realistically nests this deep), only a
defined, deterministic rank so no valid character is invisible to these
checks entirely:

{hierarchy_lines}
"""
    parser = argparse.ArgumentParser(
        prog="check_rst",
        description=(__doc__ or "") + hierarchy_help,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    _add_project_flags(parser)
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    full = _build_full_parent()
    mutating = _build_mutating_parent()

    check_p = sub.add_parser(
        "check",
        parents=[full],
        help="check .rst files against project formatting rules (default verb)",
        description=(
            "Check .rst files against project RST formatting rules "
            "(Phase 0: byte hygiene — Unix LF, no BOM; Phase 1: Python lint; "
            "Phase 2: Python Sphinx rules; Phase 3: Sphinx build)."
        ),
    )
    check_p.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help=(
            "text (default): ordinary findings and summary. json: emit the "
            "document model as one JSON object on stdout and nothing else — "
            "per-file findings, outline (with stable docname:title ids in "
            "the autosectionlabel convention), code-blocks, blockquote "
            "previews, statistics, and runtime/schema metadata plus the run "
            "summary. Exit code semantics unchanged either way"
        ),
    )
    _add_no_toctree_flag(check_p)
    _add_max_output_lines(check_p)
    check_p.set_defaults(**_CLI_ATTR_DEFAULTS)

    fix_p = sub.add_parser(
        "fix",
        parents=[full, mutating],
        help="apply auto-fixable corrections in-place",
        description=(
            "Apply auto-fixable corrections in-place before checking; "
            "the complete selected set is rejected before any write when "
            "Git reports an unresolved merge entry; "
            "fixable: byte hygiene (BOM removal, CRLF/CR and exotic line "
            "separators to LF, trailing whitespace on every source line), "
            "wrong adornment length, mismatched chars, title spaces, "
            "missing blank lines, underline-only titles (adornment line must "
            f"be >= {MIN_UNDERLINE_ONLY_LEN} chars to be recognized as one, "
            "regardless of the title's length), hierarchy char order. "
            "--fast skips lint/statistics/Sphinx for a fast mutation-only pass"
        ),
    )
    _add_max_output_lines(fix_p)
    fix_p.set_defaults(**_CLI_ATTR_DEFAULTS)
    fix_p.set_defaults(fix=True)

    diff_p = sub.add_parser(
        "diff",
        parents=[full, mutating],
        help="print unified diff of what fix would change",
        description=(
            "Print unified diff of what fix would change without modifying "
            "files. --fast stops after Phase 1 for a fast, read-only "
            "formatting preview (exits 1 when changes would be made, 0 when "
            "clean)"
        ),
    )
    diff_p.set_defaults(**_CLI_ATTR_DEFAULTS)
    diff_p.set_defaults(diff=True)

    outline_p = sub.add_parser(
        "outline",
        parents=[full],
        help="print each file's section structure (structure-only by default)",
        description=(
            "Print each file's section structure: a 'levels:' legend mapping "
            "each depth to its adornment char (once — the mapping is "
            'constant within a document), then "{start}-{end}: {title}" per '
            "heading (the range is the section's full extent — feed it "
            "straight to sed/Read), indented 4 spaces per level, with a "
            "'[N subsections]' count on parents, plus code-block, "
            "blockquote, table, admonition, comment, list, and verified "
            "toctree entries (previews are bounded). depth is this "
            "document's own nesting order (1 = top-level), independent of "
            "check_hierarchy's own HIERARCHY ranking — the same character "
            "can report a different depth in a different file; char is "
            "shown alongside so the HIERARCHY rank stays inferable. Always "
            "whole-document, never diff-scoped. Purely informational — "
            "never affects the exit code. Structure-only by default (no "
            "finding lines) — pass --with-findings to layer bold/rubric "
            "WARNING findings on top of the structure view. Always prints once, during "
            "Phase 2, never Phase 1: with --sphinx-src, headings + "
            "code-blocks from a real Sphinx env, verified; without it, the "
            "same shape from a heuristic text-search code-block detector "
            "instead, clearly labeled as such (see --sphinx-src)"
        ),
    )
    outline_p.add_argument(
        "--with-findings",
        action="store_true",
        help=(
            "layer bold/rubric WARNING findings on top of the structure "
            "view — today's plain --outline behavior, before this verb's "
            "default inverted to structure-only. A display choice, not a "
            "different check: findings are always counted in the summary "
            "footer and the exit code stays honest either way"
        ),
    )
    outline_p.add_argument(
        "--outline-depth",
        type=int,
        default=None,
        metavar="N",
        help=(
            "show only entries of every kind at nesting depth <= N; a "
            "trailing note reports how many deeper entries were hidden — "
            "bounded output, never silent truncation. Default: unlimited"
        ),
    )
    outline_p.add_argument(
        "--sections-only",
        action="store_true",
        help=(
            "show only headings — every leaf entry kind (code-block, "
            "blockquote, table, admonition, comment, list) suppressed "
            "regardless of depth, unlike --outline-depth which bounds by "
            "depth, not by kind. A display filter: the levels:/blocks: "
            "legend and every heading's own bracketed counts still reflect "
            "the whole document, and a trailing note reports how many "
            "entries were hidden — bounded output, never silent truncation. "
            "Composes with --outline-depth"
        ),
    )
    _add_no_toctree_flag(outline_p)
    _add_max_output_lines(outline_p)
    outline_p.set_defaults(**_CLI_ATTR_DEFAULTS)
    outline_p.set_defaults(outline=True)

    diff_json_p = sub.add_parser(
        "diff-json",
        help="semantic diff between two --format=json dumps",
        description=(
            "Semantic diff between two check_rst check --format=json dumps "
            "(e.g. before/after a large edit): which outline sections were "
            "added/removed, whether any surviving section's depth/char "
            "changed, which findings are new vs resolved — matched by "
            "(severity, text), never by line number, which drifts with any "
            "unrelated edit. Self-contained: no other flags apply, and no "
            "RST is read or checked."
        ),
    )
    diff_json_p.add_argument("old", metavar="OLD.json")
    diff_json_p.add_argument("new", metavar="NEW.json")
    diff_json_p.set_defaults(**_CLI_ATTR_DEFAULTS)

    refs_p = sub.add_parser(
        "refs",
        help="per-file :doc:/:ref: reference report",
        description=(
            "Per-file :doc:/:ref: reference report: this file's own OUTGOING "
            "targets, and every other file's INCOMING reference to it, "
            "derived from the live Sphinx environment (never objects.inv). "
            "Requires --sphinx-src (directly or via .check_rst.toml or "
            "--config)."
        ),
    )
    refs_p.add_argument("file", type=pathlib.Path, metavar="FILE")
    refs_p.set_defaults(**_CLI_ATTR_DEFAULTS)

    context_p = sub.add_parser(
        "context",
        help="targeted pre-edit briefing for one entry",
        description=(
            "Targeted pre-edit briefing for one exact entry in the same "
            "heterogeneous model as outline. ENTRY may be a stable section "
            "id, a generated selector shown by this mode's ambiguity output, "
            "or an exact title/term/preview. Reports range, kind, enclosing "
            "path, parent, adjacent siblings, direct children, applicable "
            "findings, and references (when verified Sphinx mode is "
            "available). Never guesses between multiple exact matches."
        ),
    )
    context_p.add_argument("entry", metavar="ENTRY")
    context_p.add_argument("file", type=pathlib.Path, metavar="FILE")
    _add_no_toctree_flag(context_p)
    context_p.set_defaults(**_CLI_ATTR_DEFAULTS)

    list_table_p = sub.add_parser(
        "list-table",
        parents=[_build_list_table_parent()],
        help="convert eligible grid/simple tables to list-table syntax",
        description=(
            "Convert eligible grid/simple tables (bare, or `.. table::`-wrapped "
            "with an optional caption — :name:/:class:/:align: are not yet "
            "supported and refused explicitly) to `.. list-table::` syntax. "
            "Every cell's own source is preserved verbatim; :widths: carries "
            "the original column geometry through unchanged. A table "
            "containing a merged row or column is refused, never flattened "
            "or guessed at. Every candidate is re-validated by parsing the "
            "whole resulting file and requiring its doctree to match the "
            "original exactly (aside from the one expected 'colwidths-given' "
            "class list-table's own syntax adds) before it may be written. "
            "Dry-run by default; --apply writes."
        ),
    )
    list_table_p.set_defaults(**_CLI_ATTR_DEFAULTS)

    return parser


def _backfill_post_parse(args: argparse.Namespace) -> None:
    """Fill in the handful of attributes that depend on another just-parsed
    value and so can't be a static set_defaults() — see _build_cli_parser().
    """
    if args.command == "check":
        args.json = args.format == "json"
    elif args.command == "fix":
        args.fix_only = args.fast
    elif args.command == "diff":
        args.diff_only = args.fast
    elif args.command == "outline":
        args.outline_only = not args.with_findings
    elif args.command == "diff-json":
        args.diff_json = [args.old, args.new]
    elif args.command == "refs":
        args.refs = args.file
    elif args.command == "context":
        args.context, args.files = args.entry, [args.file]
        args.quiet = True  # forced, same as today's --context behavior


def _validate_context_args(args: argparse.Namespace) -> None:
    """The two value-level checks that survive from today's --context
    self-contained allowlist (cli.py's now-deleted _validate_cli_args):
    everything else in that allowlist is structural once `context` only
    accepts ENTRY and FILE on its own parser.
    """
    if not args.context.strip():
        _cli_fail("--context ENTRY must not be empty")
    if args.files[0].suffix != ".rst":
        _cli_fail("--context requires exactly one positional .rst file")


def _validate_outline_args(args: argparse.Namespace) -> None:
    """The one value-level check that survives from today's --outline-depth
    rule (cli.py's now-deleted _validate_cli_args): the ">= 1" range. The
    "requires --outline/--outline-only" half is now structural — the flag
    only exists on outline's own parser."""
    if args.outline_depth is not None and args.outline_depth < 1:
        _cli_fail("--outline-depth must be >= 1")


def _validate_check_args(args: argparse.Namespace) -> None:
    """The two value-level checks that survive on check's own parser from
    today's now-deleted _validate_cli_args: --no-toctree's "requires one of
    --outline/--outline-only/--json/--context" half narrows to "requires
    --format=json" now that check has neither --outline nor --context; and
    --max-output-lines' incompatibility with --json is the only surviving
    case of that rule now that diff/diff-only/diff-json/refs/context never
    carry --max-output-lines at all."""
    if args.no_toctree and not args.json:
        _cli_fail("--no-toctree requires --format=json")
    if args.max_output_lines is not None and args.json:
        _cli_fail(
            "--max-output-lines is incompatible with --format=json — structured or copyable output must remain complete"
        )


def _validate_diff_json_args(args: argparse.Namespace) -> None:
    """diff-json is fully self-contained — no RST project is ever read, so
    the global project-identity options (--config/--sphinx-src/--build-dir,
    _add_project_flags) never apply to it. Reject rather than silently
    ignore, the same fail-loudly precedent as every other verb-incompatible
    combination (_validate_fast_allowlist, _validate_check_args)."""
    active = [
        flag
        for flag, value in (
            ("--config", args.config),
            ("--sphinx-src", args.sphinx_src),
            ("--build-dir", args.build_dir),
        )
        if value is not None
    ]
    if active:
        _cli_fail(f"diff-json is self-contained — incompatible argument(s): {', '.join(active)}")


def _validate_list_table_args(args: argparse.Namespace) -> None:
    """list-table never consults Sphinx — its own conversion and
    validation are bare-docutils only (same as find_tables itself, "no
    verified/heuristic split") — so --sphinx-src/--build-dir are
    incompatible, the same fail-loudly precedent as diff-json rejecting
    the whole project-flag family. --config stays valid: it still roots
    project/Git-scope discovery for this verb's own --recursive/
    --git-scope, unrelated to Sphinx verification."""
    active = [
        flag
        for flag, value in (("--sphinx-src", args.sphinx_src), ("--build-dir", args.build_dir))
        if value is not None
    ]
    if active:
        _cli_fail(f"list-table does not use Sphinx — incompatible argument(s): {', '.join(active)}")


def _argument_is_set(value: object) -> bool:
    """Return whether an argparse value represents an explicitly active option."""
    if value is None or value is False:
        return False
    if isinstance(value, list):
        return bool(value)
    return True


def _main() -> None:
    parser = _build_cli_parser()
    args = parser.parse_args()
    _backfill_post_parse(args)
    explicit_build_dir = args.build_dir is not None
    _hints_shown.clear()  # once per RUN, not carried over between main() calls
    _validate_config_flags(args)
    if args.max_output_lines is not None and args.max_output_lines < 2:
        print("check_rst: --max-output-lines must be >= 2")
        raise SystemExit(1)
    # Per-verb validation replacing the old flat-CLI's hand-written
    # incompatibility matrix (docs/roadmap.rst, "Subcommands: flag-soup
    # incompatibilities become verbs") — _validate_full_scope_args is safe
    # unconditionally: --recursive/--git-scope/--exclude default to
    # False/False/[] on every verb that doesn't define them, so it no-ops
    # there. The rest are scoped to the one verb whose parser can actually
    # make them non-default.
    _validate_full_scope_args(args)
    if args.command == "check":
        _validate_check_args(args)
    elif args.command in ("fix", "diff") and args.fast:
        _validate_fast_allowlist(args, args.command)
    elif args.command == "outline":
        _validate_outline_args(args)
    elif args.command == "context":
        _validate_context_args(args)
    elif args.command == "diff-json":
        _validate_diff_json_args(args)
    elif args.command == "list-table":
        _validate_list_table_args(args)

    if args.diff_json is not None:
        old_path, new_path = (pathlib.Path(p) for p in args.diff_json)
        old_data = _load_json_dump(old_path)
        new_data = _load_json_dump(new_path)
        print(_format_json_diff(_diff_json_dumps(old_data, new_data)))
        sys.exit(0)

    if args.word_samples is not None and args.word_samples < 0:
        print("check_rst: --word-samples must be >= 0")
        sys.exit(1)
    # Resolved sample count for top/rare prose words, footer and JSON alike
    # (Max, 2026-07-20): explicit --word-samples always wins and promotes
    # the lines at any verbosity level; otherwise --verbose defaults to 10;
    # otherwise 0 — meaning the stopword/stemmer computation is skipped
    # entirely, not merely hidden.
    word_samples = args.word_samples if args.word_samples is not None else (10 if args.verbose else 0)

    if args.outline_only:
        args.outline = True
        args.quiet = True

    if args.json:
        args.quiet = True

    if args.context is not None:
        args.quiet = True

    suppress_findings = args.outline_only or args.json

    # Per-repo config fills only what the CLI left unset — CLI always wins.
    # The TOML and schema are always validated; an overridden path value is
    # never applied or checked for conf.py/directory existence. --no-config
    # skips discovery entirely — even a malformed committed file never gets
    # read, let alone validated, when the run explicitly opts out.
    loaded_config = LoadedConfig("", PROJECT_ROOT.resolve(), {}) if args.no_config else _load_config(args.config)
    config_source = loaded_config.source
    config = loaded_config.values
    project_root = loaded_config.root if args.config is not None else PROJECT_ROOT
    config_applied: list[str] = []
    config_inactive: list[str] = []
    # list-table never consults Sphinx (_validate_list_table_args already
    # rejects --sphinx-src/--build-dir as *explicit* flags for this verb,
    # same rationale as --fast) — found by code review: this branch only
    # checked --fast (fix_only/diff_only), so a configured sphinx-src/
    # build-dir was silently APPLIED for list-table too, which then made
    # the later foreign-files/conf.py checks (Sphinx-mode-only) reject an
    # otherwise-valid list-table run. --config itself stays active either
    # way — it still roots project/Git-scope discovery for this verb.
    sphinx_inactive = args.fix_only or args.diff_only or args.command == "list-table"
    if args.sphinx_src is None and "sphinx-src" in config:
        if sphinx_inactive:
            reason = "--fast" if (args.fix_only or args.diff_only) else "list-table"
            config_inactive.append(f"sphinx-src={config['sphinx-src']} inactive ({reason})")
        else:
            configured = pathlib.Path(config["sphinx-src"]).expanduser()
            args.sphinx_src = configured if configured.is_absolute() else (loaded_config.root / configured).resolve()
            config_applied.append(f"sphinx-src={config['sphinx-src']}")
    if args.build_dir is None and "build-dir" in config:
        if sphinx_inactive:
            reason = "--fast" if (args.fix_only or args.diff_only) else "list-table"
            config_inactive.append(f"build-dir={config['build-dir']} inactive ({reason})")
        elif args.sphinx_src is None:
            config_inactive.append(f"build-dir={config['build-dir']} inactive (no sphinx-src)")
        else:
            configured = pathlib.Path(config["build-dir"]).expanduser()
            args.build_dir = configured if configured.is_absolute() else (loaded_config.root / configured).resolve()
            config_applied.append(f"build-dir={config['build-dir']}")
    if config_source and not args.quiet:
        config_details = [*config_applied, *config_inactive]
        print(
            f"config: {config_source} — "
            + (", ".join(config_details) if config_details else "no Sphinx settings applied")
        )

    runtime_metadata = _runtime_metadata(
        verified=args.sphinx_src is not None,
        word_samples=bool(word_samples),
    )

    def require_verified_sphinx(option: str) -> NoReturn:
        print(
            f"check_rst: {option} requires verified Sphinx mode — "
            "pass --sphinx-src DIR or --config FILE whose check_rst "
            "settings declare sphinx-src"
        )
        raise SystemExit(1)

    if explicit_build_dir and args.sphinx_src is None and not args.diff_only:
        require_verified_sphinx("--build-dir")

    if args.no_toctree and args.sphinx_src is None:
        require_verified_sphinx("--no-toctree")
    # The old "--no-toctree requires one of outline/outline-only/json/
    # context" half is now structurally impossible: --no-toctree only
    # exists on check/outline/context's own parsers, and each of those
    # already guarantees the condition on its own (check via
    # _validate_check_args requiring --format=json; outline's own
    # set_defaults(outline=True); context's own args.context backfill) —
    # see docs/roadmap.rst, "Subcommands: flag-soup incompatibilities
    # become verbs".

    # --sphinx-src is a deliberate opt-in to Phase 2; a path given without a
    # conf.py in it is a mistake worth failing on immediately, not silently
    # skipping (see module docstring, "Phase 2 — Sphinx build integrity check").
    if not args.diff_only and args.sphinx_src is not None and not (args.sphinx_src / "conf.py").is_file():
        print(f"check_rst: no conf.py found in --sphinx-src {args.sphinx_src}")
        sys.exit(1)

    if not args.diff_only and args.build_dir is not None:
        existing = args.build_dir
        while not existing.exists() and existing.parent != existing:
            existing = existing.parent
        if not existing.is_dir():
            print(f"check_rst: --build-dir {args.build_dir}: {existing} is not a directory")
            sys.exit(1)

    if args.refs is not None:
        if args.sphinx_src is None:
            require_verified_sphinx("--refs")
        if not args.refs.is_file():
            problem = "No such file or directory" if not args.refs.exists() else "not a regular file"
            print(f"check_rst: {args.refs}: {problem}")
            sys.exit(1)
        if not args.refs.resolve().is_relative_to(args.sphinx_src.resolve()):
            print(f"check_rst: {args.refs}: not part of --sphinx-src {args.sphinx_src}")
            sys.exit(1)
        print(_format_runtime(runtime_metadata))
        keep_build = args.build_dir is not None
        build_dir = args.build_dir if keep_build else pathlib.Path(tempfile.mkdtemp(prefix="check_rst_"))
        try:
            env, _warning_text = _build_sphinx_env_checked(args.sphinx_src, build_dir, files=[args.refs])
            docname = _docname_for(env, args.refs)
            if docname is None:
                print(f"check_rst: {args.refs}: not part of the --sphinx-src project")
                sys.exit(1)
            outgoing = find_references(env, docname)
            incoming = find_incoming_references(env, docname)
            print(_format_references(args.refs, outgoing, incoming))
        finally:
            if not keep_build:
                shutil.rmtree(build_dir, ignore_errors=True)
        sys.exit(0)

    if args.recursive:
        # A directory scope is just as deliberate as naming files — always
        # checked in full. Validate every directory up front (fail loudly on
        # a typo, same precedent as --sphinx-src) before discovering anything.
        if not args.files:
            print("check_rst: --recursive requires at least one directory")
            if args.fix_only:
                _print_fix_only_status(0, 1, 0)
            sys.exit(1)
        for d in args.files:
            if not d.is_dir():
                print(f"check_rst: --recursive argument is not a directory: {d}")
                if args.fix_only:
                    _print_fix_only_status(0, 1, 0)
                sys.exit(1)

        discovered: set[pathlib.Path] = set()
        for d in args.files:
            discovered.update(d.rglob("*.rst"))
        for pattern in args.exclude:
            discovered = {f for f in discovered if not f.match(pattern)}
        files = sorted(discovered)
        whole_file = True

        if not files:
            print("check_rst: no .rst files found under the given directories — nothing to do")
            if args.fix_only:
                _print_fix_only_status(0, 0, 0)
            sys.exit(0)
    else:
        # Resolve the file list; silently drop non-.rst entries so that passing
        # the raw output of "git diff --name-only HEAD" is safe.
        raw_files: list[pathlib.Path] = args.files or _changed_rst_files(project_root)
        files = [f for f in raw_files if f.suffix == ".rst"]
        if not files:
            msg = "no .rst files in the list" if args.files else "no changed .rst files"
            print(f"check_rst: {msg} — nothing to do")
            if args.fix_only:
                _print_fix_only_status(0, 0, 0)
            sys.exit(0)

        if args.git_scope:
            # Validate the allowlist before intersecting it with status: an
            # outside/missing sibling must abort atomically, never disappear
            # merely because Git could not have reported it as changed.
            invalid_files = [path for path in files if not path.is_file()]
            if invalid_files:
                for path in invalid_files:
                    problem = "file not found" if not path.exists() else "not a regular file"
                    print(f"check_rst: {path}: {problem}")
                if args.fix_only:
                    _print_fix_only_status(len(files), len(invalid_files), 0)
                sys.exit(1)
            worktree_root = _git_worktree_root(project_root).resolve()
            outside = [path for path in files if not path.resolve().is_relative_to(worktree_root)]
            if outside:
                for path in outside:
                    print(f"check_rst: {path}: outside the selected Git worktree {worktree_root}")
                if args.fix_only:
                    _print_fix_only_status(len(files), len(outside), 0)
                sys.exit(1)
            changed = {path.resolve() for path in _changed_rst_files(project_root)}
            files = [path for path in files if path.resolve() in changed]
            if not files:
                print("check_rst: no selected changed .rst files — nothing to do")
                if args.fix_only:
                    _print_fix_only_status(0, 0, 0)
                sys.exit(0)
            whole_file = False
        else:
            # Naming files explicitly is a deliberate "check this"
            # instruction, so they're checked in full. Auto-detected files
            # stay scoped to lines changed since HEAD.
            whole_file = bool(args.files)

    # The same file may be named through relative/absolute aliases or through
    # overlapping selection inputs.  One invocation checks each physical path
    # once, preserving the first spelling for user-facing output.
    unique_files: dict[pathlib.Path, pathlib.Path] = {}
    for path in files:
        unique_files.setdefault(path.resolve(), path)
    files = list(unique_files.values())

    # Validate the complete input set before starting any check or fixer.
    # Positional files are one requested operation: a typo must not allow
    # partial lint/build output, or (under --fix) mutate the valid siblings
    # before eventually reporting that another input never existed.
    invalid_files = [path for path in files if not path.is_file()]
    if invalid_files:
        for path in invalid_files:
            problem = "file not found" if not path.exists() else "not a regular file"
            print(f"check_rst: {path}: {problem}")
        if args.fix_only:
            _print_fix_only_status(len(files), len(invalid_files), 0)
        sys.exit(1)

    if not args.diff_only and args.sphinx_src is not None:
        sphinx_root = args.sphinx_src.resolve()
        foreign_files = [path for path in files if not path.resolve().is_relative_to(sphinx_root)]
        if foreign_files:
            for path in foreign_files:
                print(f"check_rst: {path}: not part of --sphinx-src {args.sphinx_src}")
            sys.exit(1)

    unmerged_files = _unmerged_files(files, project_root)
    if unmerged_files:
        for path in unmerged_files:
            print(f"check_rst: {path}: unresolved Git merge conflict — resolve before checking or fixing")
        if args.fix_only:
            _print_fix_only_status(len(files), len(unmerged_files), 0)
        sys.exit(1)

    if args.command == "list-table":
        _run_list_table(files, only=args.only, skip=args.skip, apply=args.apply, quiet=args.quiet)

    if args.fix_only:
        if whole_file:
            selection = "recursive" if args.recursive else "explicit"
            scope = f"{selection}/whole-file; hygiene and hierarchy are whole-file"
        else:
            scope = "Git-selected/diff-scoped adornment geometry; hygiene and hierarchy are whole-file"
        _run_fix_only(
            files,
            whole_file,
            include_structure=not args.no_adornments,
            project_root=project_root,
            scope=scope,
            quiet=args.quiet,
            verbose=args.verbose,
        )

    if args.context is not None:
        sys.exit(
            _run_context_query(
                args.context,
                files[0],
                project_root,
                args.sphinx_src,
                args.build_dir,
                args.no_toctree,
            )
        )

    if args.diff_only:
        preview_changes = 0
        errors = 0
        for path in files:
            try:
                preview = diff_fixes(
                    path,
                    whole_file,
                    include_structure=not args.no_adornments,
                    include_blank_lines=False,
                    collapse_title_spaces=False,
                    single_space_prose=False,
                    project_root=project_root,
                )
            except UnicodeDecodeError as exc:
                err_line = exc.object.count(b"\n", 0, exc.start) + 1
                _emit_report_line(
                    f"{path}:{err_line}: ERROR: not valid UTF-8 ({exc.reason} at byte offset {exc.start})",
                    "ERROR",
                )
                errors += 1
                continue
            if preview:
                print(preview, end="")
                preview_changes += 1
        _emit_final_status(
            f"check_rst: {len(files)} file(s) checked, {errors} error(s), {preview_changes} file(s) would change"
        )
        sys.exit(1 if errors or preview_changes else 0)

    if not args.quiet:
        print(_format_runtime(runtime_metadata))

    total_errors = 0
    total_warnings = 0
    files_checked = 0
    documents: dict[pathlib.Path, Document] = {}
    json_records: dict[pathlib.Path, dict[str, Any]] = {}
    total_lines = 0
    empty_lines = 0
    total_chars = 0
    total_bytes = 0
    total_spaces = 0
    char_counter: collections.Counter[str] = collections.Counter()
    word_counter: collections.Counter[str] = collections.Counter()
    char_len_sum = 0
    char_len_min = 0
    char_len_max = 0
    byte_len_sum = 0
    byte_len_min = 0
    byte_len_max = 0
    fixed_files: set[str] = set()
    would_change: set[str] = set()
    suppressed_fixable: collections.Counter[pathlib.Path] = collections.Counter()

    # ------------------------------------------------------------------ Phase 1
    mode_tag = " [fix]" if args.fix else " [diff]" if args.diff else ""
    if not args.quiet:
        print(f"Phase 1: RST rules{mode_tag}")
        print("-" * 40)

    for path in files:
        if not path.exists():
            if args.json:
                json_records[path] = {"path": str(path), "error": "file not found", "findings": []}
            else:
                _emit_report_line(f"{path}: ERROR: file not found", "ERROR")
            total_errors += 1
            continue

        pstr = str(path)
        files_checked += 1

        # Phase 0 — byte hygiene, before anything parses the file.  Always
        # whole-file (a line-ending policy can't be diff-scoped), independent
        # of --no-adornments, and every finding is --fix-able, so
        # --skip-fixable suppresses them all.  In --fix mode this write MUST
        # come first: the other fixers re-read the file from disk.
        # Phase 0 is also where a non-UTF-8 file surfaces: a clean per-file
        # ERROR, never a UnicodeDecodeError traceback (found by probe,
        # 2026-07-18 — same traceback-instead-of-diagnostic class as the
        # not-a-git-repo case).
        document = Document(path, project_root)
        if args.json:
            json_records[path] = {"path": pstr, "findings": []}
        try:
            hygiene_v = document.hygiene
        except UnicodeDecodeError as exc:
            # Detection is deterministic (UTF-8 validity is a hard fact);
            # repair is not — the source encoding is knowledge only the
            # human has (0xE9 is 'é' in Latin-1, 'й' in CP1251, 'И' in
            # KOI8-R, and Latin-1 "successfully" decodes anything, so
            # detection can't even fail loudly).  So: never fixable, the
            # ERROR survives --skip-fixable, and the diagnostic hands the
            # human the remedy shape with the one fact left blank.
            err_line = exc.object.count(b"\n", 0, exc.start) + 1
            msg = (
                f"not valid UTF-8 ({exc.reason} at byte offset {exc.start}, "
                f"line {err_line}) — file skipped; if you know the source "
                "encoding: iconv -f <encoding> -t utf-8"
            )
            if args.json:
                json_records[path]["error"] = msg
            else:
                _emit_report_line(f"{pstr}:{err_line}: ERROR: {msg}", "ERROR")
            total_errors += 1
            continue
        if args.fix:
            if fix_hygiene(path):
                fixed_files.add(pstr)
                if not args.quiet:
                    print(f"✓ {pstr}: hygiene fix applied (line endings / BOM / trailing whitespace)")
        elif hygiene_v:
            if args.skip_fixable:
                suppressed_fixable[path] += len(hygiene_v)
            else:
                if args.diff:
                    would_change.add(pstr)  # fix_hygiene would rewrite this file
                if args.json:
                    json_records[path]["findings"].extend(hygiene_v)
                e, w = _print_findings(hygiene_v, pstr, args.no_warnings, suppress_findings)
                total_errors += e
                total_warnings += w

        if args.fix and (args.collapse_title_spaces or args.single_space_prose):
            text_space_counts = fix_text_spaces(
                path,
                collapse_titles=args.collapse_title_spaces,
                single_space_prose=args.single_space_prose,
            )
            if text_space_counts.total:
                fixed_files.add(pstr)
                if not args.quiet:
                    print(f"✓ {pstr}: {text_space_counts.describe()}")

        if args.diff:
            ds = diff_fixes(
                path,
                whole_file,
                include_structure=not args.no_adornments,
                include_blank_lines=args.normalize_blank_lines,
                collapse_title_spaces=args.collapse_title_spaces,
                single_space_prose=args.single_space_prose,
                project_root=project_root,
            )
            if ds:
                would_change.add(pstr)
                print(ds, end="")
            elif not args.quiet:
                print(f"  {pstr}: no hygiene/adornment/hierarchy fixes needed")
        elif not args.no_adornments and args.fix:
            if fix_structure(path, whole_file, project_root=project_root):
                fixed_files.add(pstr)
                if not args.quiet:
                    print(f"✓ {pstr}: adornment/hierarchy fix applied")

        if args.fix and args.normalize_blank_lines:
            removed_blank_lines = fix_blank_lines(path)
            if removed_blank_lines:
                fixed_files.add(pstr)
                if not args.quiet:
                    noun = "line" if removed_blank_lines == 1 else "lines"
                    print(f"✓ {pstr}: {removed_blank_lines} redundant blank {noun} removed")

        if args.fix:
            # Fixers wrote to disk — the facade's explicit lifecycle:
            # construct a fresh Document for the post-fix checks and stats.
            document = Document(path, project_root)

        if not args.no_adornments:
            adornment_v = check_adornments(path, whole_file, doc=document)
            hierarchy_v = check_hierarchy(path, doc=document)
            single_top_v = check_single_top_level(path, doc=document)
            all_v = adornment_v + hierarchy_v + single_top_v
            if args.skip_fixable:
                # All ERROR-level findings here are resolved by --fix; suppress
                # them from output and exit code. The non-preferred-adornment-
                # char WARNING (check_hierarchy) and the single-top-level-title
                # WARNING (check_single_top_level) need human judgment same as
                # bold/rubric warnings, so unlike ERRORs they still show through.
                errors_v = [f for f in all_v if f.severity == Severity.ERROR]
                warnings_v = [f for f in all_v if f.severity == Severity.WARNING]
                suppressed_fixable[path] += len(errors_v)
                if args.json:
                    json_records[path]["findings"].extend(warnings_v)
                _, w = _print_findings(warnings_v, pstr, args.no_warnings, suppress_findings)
                total_warnings += w
                if not all_v and not args.diff and not args.quiet:
                    print(f"✓ {pstr}: adornments + hierarchy OK")
            else:
                if args.json:
                    json_records[path]["findings"].extend(all_v)
                e, w = _print_findings(all_v, pstr, args.no_warnings, suppress_findings)
                if not all_v and not args.diff and not args.quiet:
                    print(f"✓ {pstr}: adornments + hierarchy OK")
                total_errors += e
                total_warnings += w

        nested_inline_v = check_nested_inline_markup(path, whole_file, doc=document)
        if args.json:
            json_records[path]["findings"].extend(nested_inline_v)
        _, w = _print_findings(nested_inline_v, pstr, args.no_warnings, suppress_findings)
        total_warnings += w  # WARNING-only: choosing one of two roles is semantic.

        if not args.no_directives:
            directive_v = check_directives(path, whole_file, args.verbose, doc=document)
            if args.json:
                json_records[path]["findings"].extend(directive_v)
            e, w = _print_findings(directive_v, pstr, args.no_warnings, suppress_findings)
            if not e and not w and not args.quiet:
                print(f"✓ {pstr}: directives OK")
            total_errors += e  # directive findings are warnings; e stays 0
            total_warnings += w

        homoglyph_v = check_homoglyphs(path, doc=document)
        if args.json:
            json_records[path]["findings"].extend(homoglyph_v)
        _, w = _print_findings(homoglyph_v, pstr, args.no_warnings, suppress_findings)
        total_warnings += w  # WARNING-only, never affects total_errors

        if args.skip_fixable and suppressed_fixable[path] and not args.quiet:
            print(f"↷ {pstr}: {suppressed_fixable[path]} auto-fixable finding(s) suppressed")

        # Footer statistics, from the same normalized read Phase 0 defines —
        # in --fix mode this is the file's final, post-fix state.  Empty
        # lines are RST's block delimiter, so the empty/total ratio is a
        # quick structure signal.
        documents[path] = document
        stat_text = document.text
        stat_lines = document.lines
        total_lines += len(stat_lines)
        empty_lines += sum(1 for line in stat_lines if not line.strip())
        total_chars += len(stat_text)
        total_bytes += len(stat_text.encode("utf-8"))
        total_spaces += stat_text.count(" ")
        # Frequency counters (Max, 2026-07-19): words at Phase 0 level are
        # whitespace-separated tokens of the raw normalized text — markup
        # included ('#######' is a token); deliberately not a prose count.
        # For chars the once-only set is tiny and is an oddity scan (a stray
        # variation selector, a lone Vietnamese letter); for words it would
        # be degenerate (~73% of any prose vocabulary occurs once), so words
        # get counts only.
        char_counter.update(stat_text)
        word_counter.update(stat_text.split())
        # Line-length spread over NON-empty lines (min over all lines would
        # trivially be 0); max is the over-long-line signal.  Two measures,
        # chars (code points) and bytes, shown collapsed when they coincide
        # — same rule as the character totals.
        for line in stat_lines:
            if line.strip():
                n = len(line)
                char_len_sum += n
                char_len_min = n if char_len_min == 0 else min(char_len_min, n)
                char_len_max = max(char_len_max, n)
                b = len(line.encode("utf-8"))
                byte_len_sum += b
                byte_len_min = b if byte_len_min == 0 else min(byte_len_min, b)
                byte_len_max = max(byte_len_max, b)

    # A Sphinx application loads project extensions into this Python process.
    # docutils_namespace() restores Sphinx's directive/role/node registrations,
    # but arbitrary extensions may mutate other process-global state.  When a
    # later report will need the bare-docutils tree and Phase 1 did not already
    # force it (notably --no-directives), materialize that cached tree BEFORE
    # constructing Sphinx.  Derived outline/block/prose properties can then be
    # evaluated later without running a parser in the extension-mutated process.
    if args.sphinx_src is not None and (args.outline or args.json or word_samples):
        for document_model in documents.values():
            _ = document_model.doctree

    # ------------------------------------------------------------ Phase 2 & 3
    sphinx_findings_json: list[dict[str, Any]] | None = None
    if not args.quiet:
        print()
    if args.sphinx_src is None:
        if not args.quiet:
            print(
                "Phase 2: Python Sphinx rules (heuristic — no --sphinx-src given: "
                "code-block detection is best-effort text search, not a real Sphinx "
                "parse; pass --sphinx-src for verified results)"
            )
            print("-" * 40)

        if args.outline or args.json:
            for path in files:
                # phase2_doc, not document: a fresh, independently-typed
                # local (Document | None, narrowed below) — reusing
                # "document" here shadows Phase 1's Document-typed local
                # of the same name and mypy infers one function-scope type
                # from its first assignment (Max, 2026-07-20: pre-existing
                # mypy debt closed).
                phase2_doc = documents.get(path)
                if phase2_doc is None:
                    continue
                code_blocks = phase2_doc.code_blocks_heuristic
                if args.json:
                    json_records[path].update(
                        _json_file_model(
                            phase2_doc,
                            code_blocks,
                            word_samples,
                            project_root=project_root,
                        )
                    )
                    if json_records[path]["stats"]["word_stats_error"] and not args.no_warnings:
                        total_warnings += 1
                if args.outline and not args.json:
                    heuristic_combined: list[
                        OutlineEntry
                        | CodeBlockEntry
                        | BlockQuoteEntry
                        | TableEntry
                        | AdmonitionEntry
                        | CommentEntry
                        | ListEntry
                        | ToctreeEntry
                    ] = sorted(
                        [
                            *phase2_doc.outline,
                            *code_blocks,
                            *phase2_doc.block_quotes,
                            *phase2_doc.tables,
                            *phase2_doc.admonitions,
                            *phase2_doc.comments,
                            *phase2_doc.lists,
                        ],
                        key=lambda e: e.lineno,
                    )
                    with _report_kind("outline"):
                        print(f"Outline: {path}")
                        _print_outline_entries(
                            heuristic_combined,
                            args.outline_depth,
                            args.verbose,
                            args.sections_only,
                        )
        elif not args.quiet:
            print("  (nothing to check — pass --outline to see the resolved structure)")

        if not args.quiet:
            print()
            print("Phase 3: Sphinx build — skipped (no --sphinx-src given)")
    else:
        keep_build = args.build_dir is not None
        build_dir = args.build_dir if keep_build else pathlib.Path(tempfile.mkdtemp(prefix="check_rst_"))

        try:
            if not args.quiet:
                print(f"Phase 2: Python Sphinx rules ({build_dir})")
                print("-" * 40)

            env, phase2_warning_text = _build_sphinx_env_checked(args.sphinx_src, build_dir, files=files)
            unavailable = [path for path in files if _docname_for(env, path) is None]
            if unavailable:
                for path in unavailable:
                    print(f"check_rst: {path}: not part of the --sphinx-src environment")
                raise SystemExit(1)
            # Phase 2's OWN build warnings — see _build_sphinx_env's
            # docstring for why these would otherwise vanish between here
            # and Phase 3.  Merged into sphinx_v below and reported
            # together: same console-output shape, same "sphinx" prefix,
            # one combined print/count site.
            phase2_v = _findings_from_sphinx_output(phase2_warning_text, files, project_root)
            for path in files:
                bare_filename_doc = documents.get(path)
                if bare_filename_doc is None:
                    continue
                bare_filename_docname = _docname_for(env, path)
                if bare_filename_docname is None:
                    continue
                bare_filename_v = check_bare_filenames(env, bare_filename_docname, bare_filename_doc)
                multiple_toctree_v = check_multiple_toctree_parents(env, [path])
                if args.json:
                    json_records[path]["findings"].extend(bare_filename_v)
                    json_records[path]["findings"].extend(multiple_toctree_v)
                _, w = _print_findings(bare_filename_v, str(path), args.no_warnings, suppress_findings)
                total_warnings += w  # WARNING-only, never affects total_errors
                _, w = _print_findings(
                    multiple_toctree_v,
                    str(path),
                    args.no_warnings,
                    suppress_findings,
                )
                total_warnings += w  # WARNING-only, never affects total_errors
            if args.outline or args.json:
                for path in files:
                    # phase2_doc: see the sibling heuristic loop above for
                    # why this isn't named "document".
                    phase2_doc = documents.get(path)
                    if phase2_doc is None:
                        continue
                    pstr = str(path)
                    docname = _docname_for(env, path)
                    code_blocks = find_code_blocks(env, docname, phase2_doc.lines) if docname is not None else []
                    verified_outline = (
                        build_outline(
                            path,
                            doc=phase2_doc,
                            doctree=env.get_doctree(docname),
                        )
                        if docname is not None
                        else phase2_doc.outline
                    )
                    toctree_clusters = (
                        find_toctrees(env, docname, phase2_doc) if docname is not None and not args.no_toctree else []
                    )
                    cross_file_headings = [
                        e for cluster in toctree_clusters for e in cluster if isinstance(e, OutlineEntry)
                    ]
                    toctree_containers = [
                        e for cluster in toctree_clusters for e in cluster if isinstance(e, ToctreeEntry)
                    ]
                    if args.json:
                        json_records[path].update(
                            _json_file_model(
                                phase2_doc,
                                code_blocks,
                                word_samples,
                                outline_entries=[*verified_outline, *cross_file_headings],
                                toctree_entries=toctree_containers,
                                project_root=project_root,
                            )
                        )
                        if json_records[path]["stats"]["word_stats_error"] and not args.no_warnings:
                            total_warnings += 1
                        if docname is None:
                            json_records[path]["unreachable"] = (
                                "not part of the --sphinx-src project — code-blocks unavailable"
                            )
                    if args.outline and not args.json:
                        local_entries: list[
                            OutlineEntry
                            | CodeBlockEntry
                            | BlockQuoteEntry
                            | TableEntry
                            | AdmonitionEntry
                            | CommentEntry
                            | ListEntry
                        ] = sorted(
                            [
                                *verified_outline,
                                *code_blocks,
                                *phase2_doc.block_quotes,
                                *phase2_doc.tables,
                                *phase2_doc.admonitions,
                                *phase2_doc.comments,
                                *phase2_doc.lists,
                            ],
                            key=lambda e: e.lineno,
                        )
                        combined = _merge_toctree_clusters(local_entries, toctree_clusters)
                        with _report_kind("outline"):
                            if docname is None:
                                print(f"Outline: {pstr} (not part of --sphinx-src project — code-blocks unavailable)")
                            else:
                                print(f"Outline: {pstr}")
                            _print_outline_entries(
                                combined,
                                args.outline_depth,
                                args.verbose,
                                args.sections_only,
                            )
            elif not args.quiet:
                print("  (nothing to check — pass --outline to see the resolved structure)")

            if not args.quiet:
                print()
                print(f"Phase 3: Sphinx build integrity ({build_dir})")
                print("-" * 40)

            sphinx_v = phase2_v + run_sphinx(
                [f for f in files if f.exists()],
                build_dir,
                args.sphinx_src,
                project_root,
            )
            sphinx_v = [_attach_did_you_mean(f, env) for f in sphinx_v]
            # Phase 2 and Phase 3 intentionally inspect the same checked
            # documents.  A diagnostic can therefore appear in both streams;
            # Findings are frozen/hashable, so preserve first-seen order while
            # counting and printing an identical finding only once.
            sphinx_v = list(dict.fromkeys(sphinx_v))
            if args.skip_fixable and suppressed_fixable:
                suppressed_paths = set(suppressed_fixable)
                sphinx_v = [
                    finding
                    for finding in sphinx_v
                    if not _is_sphinx_fixable_duplicate(finding, suppressed_paths, project_root)
                ]
            if args.json:
                sphinx_findings_json = [
                    dataclasses.asdict(f) for f in sphinx_v if not args.no_warnings or f.severity != Severity.WARNING
                ]
            e, w = _print_findings(sphinx_v, "sphinx", args.no_warnings, suppress_findings)
            if not e and not w and not args.quiet:
                print("✓ no warnings or errors in the checked files")
            total_errors += e
            total_warnings += w
        finally:
            if not keep_build:
                shutil.rmtree(build_dir, ignore_errors=True)

    # --json: the whole model as one JSON object on stdout — nothing else
    # was printed (quiet implied, findings suppressed and captured).
    if args.json:
        for rec in json_records.values():
            rec["findings"] = [
                dataclasses.asdict(f)
                for f in rec.get("findings", [])
                if not args.no_warnings or f.severity != Severity.WARNING
            ]
        data: dict[str, Any] = {
            "schema_version": _JSON_SCHEMA_VERSION,
            "mode": "verified" if args.sphinx_src is not None else "heuristic",
            "runtime": runtime_metadata,
            # The config-visibility honesty condition holds in JSON too:
            # when a per-repo config supplied values, say which and what.
            "config": (
                {
                    "source": config_source,
                    "applied": config_applied,
                    "inactive": config_inactive,
                }
                if config_source
                else None
            ),
            "files": [json_records[f] for f in files if f in json_records],
            "summary": {
                "files_checked": files_checked,
                "errors": total_errors,
                "warnings": total_warnings,
                "lines": total_lines,
                "empty_lines": empty_lines,
                "chars": total_chars,
                "bytes": total_bytes,
            },
        }
        if sphinx_findings_json is not None:
            data["sphinx_findings"] = sphinx_findings_json
        print(json.dumps(data, ensure_ascii=False, indent=2))
        sys.exit(1 if total_errors else 0)

    # Word-frequency stats — computed ahead of Line 1 so a WordStatsUnavailable
    # warning is counted in THIS run's total_warnings, not just noted after
    # the count already printed (Max, 2026-07-20: "no silent fails anymore;
    # fails must be explicit").  word_samples == 0 (outside --verbose/
    # --word-samples) skips this entirely — the stopword/stemmer machinery
    # is never touched for output nobody asked to see (Max, 2026-07-20:
    # "we shouldn't pay for what we don't use").
    top_result: tuple[list[tuple[str, int]], int] | None = None
    rare_result: tuple[list[tuple[str, str | None, int]], int] | None = None
    word_stats_error: str | None = None
    if word_samples and word_counter.total():
        prose_texts = [d.prose_text for d in documents.values()]
        try:
            top_result = _top_prose_words(prose_texts, word_samples)
            rare_result = _rare_prose_words(prose_texts, word_samples)
        except WordStatsUnavailable as exc:
            word_stats_error = str(exc)
            if not args.no_warnings:
                total_warnings += 1

    # Summary — always, one machine-parseable line (kills the grep -c and
    # exit-code-probe post-processing observed across five AI sessions).
    if not args.quiet:
        print()

    # Line 1 — run facts and character totals.  Symbols (code points) vs
    # bytes: two numbers when they differ (non-ASCII content), one with a
    # note when they coincide.
    parts = [
        f"check_rst: {files_checked} file(s) checked",
        f"{total_errors} error(s)",
        f"{total_warnings} warning(s)",
    ]
    if args.fix:
        parts.append(f"{len(fixed_files)} file(s) fixed")
    if args.diff:
        parts.append(f"{len(would_change)} file(s) would change")
    if total_lines:
        distinct_chars = len(char_counter)
        once_chars = sum(1 for n in char_counter.values() if n == 1)
        char_detail = f"{distinct_chars} distinct, {once_chars} once"
        if total_bytes != total_chars:
            parts.append(f"{total_chars} char(s) ({char_detail}), {total_bytes} byte(s)")
        else:
            parts.append(f"{total_chars} char(s) (= bytes, {char_detail})")
        pct_spaces = round(100 * total_spaces / total_chars) if total_chars else 0
        parts.append(f"{total_spaces} space(s) ({pct_spaces}%)")
    _emit_final_status(", ".join(parts))
    del parts

    # Line 2 — everything about lines, no mixture with the totals above.
    # --verbose only (Max, 2026-07-20: verbosity-level inventory — cheap to
    # compute, but detailed enough that the default/--quiet loop stays to
    # the one-line summary above; this is exactly the gap independently
    # reported the same day from real usage: "--quiet doesn't quiet the
    # prose-statistics tail").
    if total_lines and args.verbose:
        pct = round(100 * empty_lines / total_lines)
        line2 = f"lines: {total_lines} total ({empty_lines} empty, {pct}%)"
        nonempty = total_lines - empty_lines
        if nonempty:
            char_avg = round(char_len_sum / nonempty)
            char_triple = f"{char_len_min}/{char_avg}/{char_len_max}"
            byte_avg = round(byte_len_sum / nonempty)
            byte_triple = f"{byte_len_min}/{byte_avg}/{byte_len_max}"
            if byte_triple != char_triple:
                spread = f"{char_triple} chars / {byte_triple} bytes"
            else:
                spread = f"{char_triple} chars (= bytes)"
            line2 += f", length min/avg/max {spread}"
        print(line2)

    # Line 4 is printed after line 3 below: top prose words — a doctree-level
    # measure (stopword-filtered, stem-grouped), unlike the raw lines above.
    # Line 3 — everything about words (raw-text tokens), same shape as
    # lines.  --verbose only, same reasoning as Line 2 above.
    total_words = word_counter.total()
    if total_words and args.verbose:
        distinct_words = len(word_counter)
        once_words = sum(1 for n in word_counter.values() if n == 1)
        word_len_sum = sum(len(w) * n for w, n in word_counter.items())
        word_avg = round(word_len_sum / total_words)
        word_len_min = min(len(w) for w in word_counter)
        word_len_max = max(len(w) for w in word_counter)
        print(
            f"words: {total_words} total, {distinct_words} distinct "
            f"({once_words} once), length min/avg/max "
            f"{word_len_min}/{word_avg}/{word_len_max}"
        )

    # Line 4 — top/rare prose words.  Gated on word_samples, independently
    # of args.verbose above: --word-samples N promotes this line at any
    # level (--quiet included), the one line-3/4 split where promotion
    # applies (Max, 2026-07-20).
    if total_words and word_samples:
        # First-match locations (Max, 2026-07-19): where to jump.  Found
        # in the RAW file (case-insensitive word match), so the number is
        # openable in an editor even when the word's counted occurrence
        # is a prose node deep in a paragraph.  "@line" for a single
        # file, "@docname:line" across several.
        multi_file = len(documents) > 1

        def _first_match(word: str) -> str:
            pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
            for doc_path, d in documents.items():
                for i, line in enumerate(d.lines, 1):
                    if pattern.search(line):
                        return f"@{_docname_id(doc_path)}:{i}" if multi_file else f"@{i}"
            return ""

        if word_stats_error is not None:
            # Explicit and counted (in total_warnings above) — never the
            # silent line-omission this replaced (Max, 2026-07-20: "I
            # don't see word frequency at the end of the output. Why?" —
            # because it just vanished).
            if not args.no_warnings and not suppress_findings:
                _emit_report_line(
                    f"WARNING: top/rare prose words unavailable — {word_stats_error}",
                    "WARNING",
                )
        else:
            assert top_result is not None
            assert rare_result is not None
            if top_result[0]:
                tops, suppressed = top_result
                listing = ", ".join(f"{word} ({count} {_first_match(word)})" for word, count in tops)
                note = f" (yet {suppressed} suppressed)" if suppressed else ""
                print(f"top prose words: {listing}{note}")
            if rare_result[0]:
                rare, suppressed = rare_result
                listing = ", ".join(
                    (
                        f"{w} {_first_match(w)} ↔ {sib} {_first_match(sib)}"
                        if cnt == 1
                        else f"{w} {_first_match(w)} (~{sib} {cnt}x)"
                    )
                    if sib
                    else f"{w} {_first_match(w)}"
                    for w, sib, cnt in rare
                )
                note = f" (yet {suppressed} suppressed)" if suppressed else ""
                print(f"rare prose words: {listing}{note}")

    sys.exit(1 if total_errors else 0)


def _requested_output_limit(argv: list[str]) -> int | None:
    """Return a valid bootstrap limit without replacing argparse validation."""
    if "-h" in argv or "--help" in argv:
        return None
    requested: int | None = None
    for index, token in enumerate(argv):
        if token == "--":
            break
        raw: str | None = None
        if token == "--max-output-lines" and index + 1 < len(argv):
            raw = argv[index + 1]
        elif token.startswith("--max-output-lines="):
            raw = token.partition("=")[2]
        if raw is not None:
            try:
                limit = int(raw)
            except ValueError:
                return None
            requested = limit
    return requested if requested is not None and requested >= 2 else None


def main() -> None:
    """Run the CLI, installing the whole-report sink when requested."""
    limit = _requested_output_limit(sys.argv[1:])
    if limit is None:
        _main()
        return

    global _ACTIVE_OUTPUT_BUDGET
    target = sys.stdout
    sink = OutputBudgetSink(limit, target)
    previous = _ACTIVE_OUTPUT_BUDGET
    _ACTIVE_OUTPUT_BUDGET = sink
    caught: SystemExit | None = None
    exit_code = 0
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            try:
                _main()
            except SystemExit as exc:
                caught = exc
                exit_code = exc.code if isinstance(exc.code, int) else 1
    finally:
        _ACTIVE_OUTPUT_BUDGET = previous
    sink.finish(exit_code)
    if caught is not None:
        raise caught


if __name__ == "__main__":
    main()
