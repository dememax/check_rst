# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Source hygiene, formatting checks, and deterministic fix planning — check_rst project

from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING

import docutils.nodes
import docutils.parsers.rst
import docutils.parsers.rst.languages
import docutils.parsers.rst.languages.en
import docutils.parsers.rst.states
import docutils.parsers.rst.tableparser
import docutils.statemachine
import docutils.utils

if TYPE_CHECKING:
    import pathlib


from . import _helpers
from ._document import (
    Document,
    _resolve_document,
)
from ._helpers import (
    _DOCUTILS_MIN_ADORNMENT_LEN,
    HIERARCHY,
    PREFERRED_HIERARCHY,
    _canonical_title,
    _changed_line_ranges,
    _in_scope,
    _is_adornment,
    _normalize_source,
    _normalize_source_detailed,
    _read_normalized,
    _read_source,
    analyze_block,
    iter_title_blocks,
    iter_underline_only,
)
from ._types import (
    Finding,
    FixPlan,
    FixResult,
    Severity,
    TextSpaceCounts,
    TitleBlock,
    _TextSpaceEdit,
    _TextSpaceEvidence,
)


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
                err(
                    lineno,
                    f"overline char '{block.over[0]}' differs from underline char '{block.under[0]}'",
                )
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
    return str(_helpers._parse_rst(path, text=text).pformat())


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
    document = _helpers._parse_rst(path, text=text)
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
            attributes = _helpers._freeze_node_attribute(node.attributes)
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
