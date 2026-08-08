# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Phase 0/1 checkers and fixers, plus list-table conversion — check_rst project

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import TYPE_CHECKING, cast

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
    from collections.abc import Iterator
    from typing import TypeGuard


from . import _helpers
from ._document import (
    Document,
    _resolve_document,
)
from ._helpers import (
    _DOCUTILS_MIN_ADORNMENT_LEN,
    CALL_COUNTS,
    HIERARCHY,
    PREFERRED_HIERARCHY,
    _block_depth,
    _canonical_title,
    _changed_line_ranges,
    _enclosing_section_title,
    _enum_marker,
    _findall_node_types,
    _in_scope,
    _indented_extent,
    _inline_node_line,
    _is_adornment,
    _node_line,
    _normalize_source,
    _normalize_source_detailed,
    _read_normalized,
    _read_source,
    analyze_block,
    iter_title_blocks,
    iter_underline_only,
)
from ._types import (
    _INLINE_CONTAINER_TYPES,
    _NON_PROSE_NODE_TYPES,
    AdmonitionEntry,
    BlockQuoteEntry,
    CodeBlockEntry,
    CommentEntry,
    Finding,
    FixPlan,
    FixResult,
    ListEntry,
    ListTableCandidate,
    ListTableFileResult,
    OutlineEntry,
    ParsedTable,
    Severity,
    TableEntry,
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
    original_model = _canonical_doctree_model(_helpers._parse_rst(path, text=original_text))
    candidate_model = _canonical_doctree_model(_helpers._parse_rst(path, text=candidate_text))
    return original_model == candidate_model


def _canonical_model_label(model: object) -> str:
    """Short, readable name for one _canonical_doctree_model() node —
    'Text' for a text node, its docutils tag name otherwise."""
    if isinstance(model, tuple) and len(model) == 2 and model[0] == "Text":
        return "Text"
    if isinstance(model, tuple) and len(model) == 4:
        return str(model[1])
    return "?"


def _is_text_model(model: object) -> TypeGuard[tuple[str, str]]:
    """True for a _canonical_doctree_model() Text-node tuple specifically
    — distinguished from an Element tuple by length alone (2 vs 4), the
    same shape _canonical_doctree_model itself constructs."""
    return isinstance(model, tuple) and len(model) == 2 and model[0] == "Text"


def _describe_doctree_divergence(original: object, candidate: object, path: tuple[str, ...] = ()) -> str:
    """Human-readable description of the FIRST structural difference
    between two _canonical_doctree_model() trees, walked in parallel,
    depth-first — found live: 'converted result failed semantic
    validation' named that the trees differed but never where or how,
    forcing a manual bisection of the whole file to isolate the actual
    cause. First divergence wins deliberately, not exhaustively: a
    dropped or retyped node cascades into every attribute/child-count/
    text comparison below it too, and those are consequences, not the
    cause — reporting all of them would bury the one fact that matters
    in noise the size of the whole subtree."""
    if original == candidate:
        return ""
    where = "/".join(path) if path else "document root"
    if _is_text_model(original) or _is_text_model(candidate):
        if _is_text_model(original) and _is_text_model(candidate):
            return f"{where}: text changed from {original[1]!r} to {candidate[1]!r}"
        return f"{where}: was {_canonical_model_label(original)!r}, became {_canonical_model_label(candidate)!r}"
    o_mod, o_name, o_attrs, o_children = cast("tuple[str, str, object, tuple[object, ...]]", original)
    c_mod, c_name, c_attrs, c_children = cast("tuple[str, str, object, tuple[object, ...]]", candidate)
    if (o_mod, o_name) != (c_mod, c_name):
        return f"{where}: node type changed from {o_name!r} to {c_name!r}"
    if o_attrs != c_attrs:
        return f"{where} <{o_name}>: attributes changed from {o_attrs!r} to {c_attrs!r}"
    if len(o_children) != len(c_children):
        return f"{where} <{o_name}>: child count changed from {len(o_children)} to {len(c_children)}"
    for index, (o_child, c_child) in enumerate(zip(o_children, c_children, strict=True)):
        sub = _describe_doctree_divergence(o_child, c_child, (*path, f"{o_name}[{index}]"))
        if sub:
            return sub
    return ""  # unreachable given the caller's own inequality check above


def _list_table_divergence_reason(path: pathlib.Path, original_text: str, candidate_text: str) -> str:
    """The diagnostic counterpart to _list_table_conversion_preserves_
    semantics' plain bool: re-parses both variants and names the first
    structural difference between them. Paid for only once validation
    has already failed — the common, passing-validation path never
    re-parses or walks the trees a second time for this."""
    original_model = _canonical_doctree_model(_helpers._parse_rst(path, text=original_text))
    candidate_model = _canonical_doctree_model(_helpers._parse_rst(path, text=candidate_text))
    return _describe_doctree_divergence(original_model, candidate_model)


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
        reason = _list_table_divergence_reason(path, original, candidate_text)
        detail = f" ({reason})" if reason else ""
        return ListTableFileResult(
            path,
            original,
            original,
            [],
            [],
            [],
            f"converted result failed semantic validation — file left untouched{detail}",
        )
    return ListTableFileResult(path, original, candidate_text, converted, refusals, [], None)


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
