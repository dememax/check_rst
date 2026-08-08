# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
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

# The pre-split cli.py bound these at its own top level too (each submodule
# below imports them for its own use, but never re-exposes the module/typing
# object itself) -- kept here, explicitly re-exported, so check_rst.cli.X
# for one of these stays available exactly as before the split (confirmed by
# a dir()-parity check against the pre-split module). Plain (non-aliased)
# form for the two dotted ones: "import a.b as a" binds a.b itself, not the
# top package -- confirmed by direct probe (getattr(docutils, "__version__",
# None) silently returned None instead of the real version string) -- so
# these two need a noqa instead of the "as X" self-import ruff otherwise
# recognizes as an explicit re-export.
import enum as enum
import functools as functools
import importlib.metadata  # noqa: F401
import json
import pathlib
import platform as platform
import re
import shutil
import subprocess as subprocess
import sys
import tempfile
import tomllib as tomllib
import unicodedata as unicodedata
from typing import TYPE_CHECKING as TYPE_CHECKING
from typing import Any, NoReturn
from typing import cast as cast

import docutils.nodes  # noqa: F401

from check_rst import __version__

from . import _checks, _helpers, _output, _reports, _sphinx
from ._checks import (
    _BOLD_PREVIEW_LEN as _BOLD_PREVIEW_LEN,
)
from ._checks import (
    _CODE_BLOCK_MARKER_RE as _CODE_BLOCK_MARKER_RE,
)
from ._checks import (
    _CONFUSABLE_CHARS as _CONFUSABLE_CHARS,
)
from ._checks import (
    _CYRILLIC_LATIN_CONFUSABLES as _CYRILLIC_LATIN_CONFUSABLES,
)
from ._checks import (
    _GRID_TABLE_BORDER_RE as _GRID_TABLE_BORDER_RE,
)
from ._checks import (
    _INTERNAL_ASCII_SPACES_RE as _INTERNAL_ASCII_SPACES_RE,
)
from ._checks import (
    _KNOWN_DIRECTIVE_NAMES as _KNOWN_DIRECTIVE_NAMES,
)
from ._checks import (
    _LIST_TABLE_BODY_INDENT as _LIST_TABLE_BODY_INDENT,
)
from ._checks import (
    _LIST_TABLE_ELIGIBLE_KINDS as _LIST_TABLE_ELIGIBLE_KINDS,
)
from ._checks import (
    _LIST_TABLE_FIRST_MARKER as _LIST_TABLE_FIRST_MARKER,
)
from ._checks import (
    _LIST_TABLE_OTHER_MARKER as _LIST_TABLE_OTHER_MARKER,
)
from ._checks import (
    _LITERALINCLUDE_MARKER_RE as _LITERALINCLUDE_MARKER_RE,
)
from ._checks import (
    _MISTYPED_DIRECTIVE_RE as _MISTYPED_DIRECTIVE_RE,
)
from ._checks import (
    _OPTION_LINE_RE as _OPTION_LINE_RE,
)
from ._checks import (
    _OUTLINE_PREVIEW_LEN as _OUTLINE_PREVIEW_LEN,
)
from ._checks import (
    _SIMPLE_TABLE_RULE_RE as _SIMPLE_TABLE_RULE_RE,
)
from ._checks import (
    _SPHINX_DIRECTIVE_NAMES as _SPHINX_DIRECTIVE_NAMES,
)
from ._checks import (
    _TABLE_DIRECTIVE_KIND as _TABLE_DIRECTIVE_KIND,
)
from ._checks import (
    _TABLE_DIRECTIVE_RE as _TABLE_DIRECTIVE_RE,
)
from ._checks import (
    _TABLE_OPTION_RE as _TABLE_OPTION_RE,
)
from ._checks import (
    _TEXT_NODE_SPACES_RE as _TEXT_NODE_SPACES_RE,
)
from ._checks import (
    _WORD_RE as _WORD_RE,
)
from ._checks import (
    _apply_fix_plan as _apply_fix_plan,
)
from ._checks import (
    _apply_permitted_text_space_edits as _apply_permitted_text_space_edits,
)
from ._checks import (
    _apply_structure_to_text as _apply_structure_to_text,
)
from ._checks import (
    _apply_text_space_edits as _apply_text_space_edits,
)
from ._checks import (
    _blank_line_candidate as _blank_line_candidate,
)
from ._checks import (
    _canonical_doctree_model as _canonical_doctree_model,
)
from ._checks import (
    _changed_line_count as _changed_line_count,
)
from ._checks import (
    _char_script as _char_script,
)
from ._checks import (
    _compute_adornment_fixes as _compute_adornment_fixes,
)
from ._checks import (
    _compute_hierarchy_remap as _compute_hierarchy_remap,
)
from ._checks import (
    _compute_structure_fixes as _compute_structure_fixes,
)
from ._checks import (
    _doctree_fingerprint as _doctree_fingerprint,
)
from ._checks import (
    _editable_text_scope as _editable_text_scope,
)
from ._checks import (
    _evaluate_list_table_candidate as _evaluate_list_table_candidate,
)
from ._checks import (
    _expected_text_space_counts as _expected_text_space_counts,
)
from ._checks import (
    _find_directive_option as _find_directive_option,
)
from ._checks import (
    _first_appearance_adornments as _first_appearance_adornments,
)
from ._checks import (
    _freeze_node_attribute as _freeze_node_attribute,
)
from ._checks import (
    _homoglyph_words_in as _homoglyph_words_in,
)
from ._checks import (
    _inline_kind as _inline_kind,
)
from ._checks import (
    _is_implicit_reference as _is_implicit_reference,
)
from ._checks import (
    _is_permitted_text_space_delta as _is_permitted_text_space_delta,
)
from ._checks import (
    _list_table_conversion_preserves_semantics as _list_table_conversion_preserves_semantics,
)
from ._checks import (
    _nested_inline_nodes as _nested_inline_nodes,
)
from ._checks import (
    _normalize_blank_lines as _normalize_blank_lines,
)
from ._checks import (
    _normalize_text_spaces as _normalize_text_spaces,
)
from ._checks import (
    _outline_preview as _outline_preview,
)
from ._checks import (
    _parse_aligned_table as _parse_aligned_table,
)
from ._checks import (
    _plan_fix as _plan_fix,
)
from ._checks import (
    _plan_list_table_file as _plan_list_table_file,
)
from ._checks import (
    _render_list_table as _render_list_table,
)
from ._checks import (
    _render_list_table_row as _render_list_table_row,
)
from ._checks import (
    _resolve_list_table_selection as _resolve_list_table_selection,
)
from ._checks import (
    _table_end as _table_end,
)
from ._checks import (
    _table_has_span as _table_has_span,
)
from ._checks import (
    _table_kind_and_start as _table_kind_and_start,
)
from ._checks import (
    _table_kind_eligible as _table_kind_eligible,
)
from ._checks import (
    _text_space_edits as _text_space_edits,
)
from ._checks import (
    _text_space_evidence as _text_space_evidence,
)
from ._checks import (
    _title_char_events as _title_char_events,
)
from ._checks import (
    _title_line_indexes as _title_line_indexes,
)
from ._checks import (
    build_outline as build_outline,
)
from ._checks import (
    check_adornments as check_adornments,
)
from ._checks import (
    check_directives as check_directives,
)
from ._checks import (
    check_hierarchy as check_hierarchy,
)
from ._checks import (
    check_homoglyphs as check_homoglyphs,
)
from ._checks import (
    check_hygiene as check_hygiene,
)
from ._checks import (
    check_nested_inline_markup as check_nested_inline_markup,
)
from ._checks import (
    check_single_top_level as check_single_top_level,
)
from ._checks import (
    diff_fixes as diff_fixes,
)
from ._checks import (
    diff_structure as diff_structure,
)
from ._checks import (
    find_admonitions as find_admonitions,
)
from ._checks import (
    find_block_quotes as find_block_quotes,
)
from ._checks import (
    find_code_blocks_heuristic as find_code_blocks_heuristic,
)
from ._checks import (
    find_comments as find_comments,
)
from ._checks import (
    find_lists as find_lists,
)
from ._checks import (
    find_tables as find_tables,
)
from ._checks import (
    fix_blank_lines as fix_blank_lines,
)
from ._checks import (
    fix_hygiene as fix_hygiene,
)
from ._checks import (
    fix_structure as fix_structure,
)
from ._checks import (
    fix_text_spaces as fix_text_spaces,
)
from ._config import (
    _CONFIG_KEYS as _CONFIG_KEYS,
)
from ._config import (
    LoadedConfig as LoadedConfig,
)
from ._config import (
    _config_error as _config_error,
)
from ._config import (
    _config_table as _config_table,
)
from ._config import (
    _load_config as _load_config,
)
from ._document import (
    Document as Document,
)
from ._document import (
    _DocumentCore as _DocumentCore,
)
from ._document import (
    _DocumentInlineMixin as _DocumentInlineMixin,
)
from ._document import (
    _DocumentOutlineMixin as _DocumentOutlineMixin,
)
from ._document import (
    _DocumentProseMixin as _DocumentProseMixin,
)
from ._document import (
    _resolve_document as _resolve_document,
)
from ._helpers import (
    _DOCUTILS_MIN_ADORNMENT_LEN as _DOCUTILS_MIN_ADORNMENT_LEN,
)
from ._helpers import (
    _JSON_SCHEMA_VERSION as _JSON_SCHEMA_VERSION,
)
from ._helpers import (
    _NONALPHANUM_7BIT_PATTERN as _NONALPHANUM_7BIT_PATTERN,
)
from ._helpers import (
    _ROMAN_TABLE as _ROMAN_TABLE,
)
from ._helpers import (
    _SEPARATORS_TO_LF as _SEPARATORS_TO_LF,
)
from ._helpers import (
    _SEPARATORS_TO_SPACE as _SEPARATORS_TO_SPACE,
)
from ._helpers import (
    CALL_COUNTS as CALL_COUNTS,
)
from ._helpers import (
    HIERARCHY as HIERARCHY,
)
from ._helpers import (
    MIN_UNDERLINE_ONLY_LEN as MIN_UNDERLINE_ONLY_LEN,
)
from ._helpers import (
    PREFERRED_HIERARCHY as PREFERRED_HIERARCHY,
)
from ._helpers import (
    PROJECT_ROOT as PROJECT_ROOT,
)
from ._helpers import (
    VALID_ADORNMENT_CHARS as VALID_ADORNMENT_CHARS,
)
from ._helpers import (
    _block_depth as _block_depth,
)
from ._helpers import (
    _canonical_title as _canonical_title,
)
from ._helpers import (
    _changed_line_ranges as _changed_line_ranges,
)
from ._helpers import (
    _changed_rst_files as _changed_rst_files,
)
from ._helpers import (
    _char_label as _char_label,
)
from ._helpers import (
    _enclosing_section_title as _enclosing_section_title,
)
from ._helpers import (
    _enum_marker as _enum_marker,
)
from ._helpers import (
    _findall_node_types as _findall_node_types,
)
from ._helpers import (
    _git as _git,
)
from ._helpers import (
    _git_at as _git_at,
)
from ._helpers import (
    _git_failure as _git_failure,
)
from ._helpers import (
    _git_for_root as _git_for_root,
)
from ._helpers import (
    _git_worktree_root as _git_worktree_root,
)
from ._helpers import (
    _in_scope as _in_scope,
)
from ._helpers import (
    _indented_extent as _indented_extent,
)
from ._helpers import (
    _inline_node_line as _inline_node_line,
)
from ._helpers import (
    _int_to_alpha as _int_to_alpha,
)
from ._helpers import (
    _int_to_roman as _int_to_roman,
)
from ._helpers import (
    _is_adornment as _is_adornment,
)
from ._helpers import (
    _node_line as _node_line,
)
from ._helpers import (
    _normalize_source as _normalize_source,
)
from ._helpers import (
    _normalize_source_detailed as _normalize_source_detailed,
)
from ._helpers import (
    _parse_rst as _parse_rst,
)
from ._helpers import (
    _read_normalized as _read_normalized,
)
from ._helpers import (
    _read_source as _read_source,
)
from ._helpers import (
    _unmerged_files as _unmerged_files,
)
from ._helpers import (
    analyze_block as analyze_block,
)
from ._helpers import (
    iter_title_blocks as iter_title_blocks,
)
from ._helpers import (
    iter_underline_only as iter_underline_only,
)
from ._output import (
    _ACTIVE_OUTPUT_BUDGET as _ACTIVE_OUTPUT_BUDGET,
)
from ._output import (
    _FINDING_HINTS as _FINDING_HINTS,
)
from ._output import (
    _OUTPUT_KIND as _OUTPUT_KIND,
)
from ._output import (
    OutputBudgetSink as OutputBudgetSink,
)
from ._output import (
    _emit_final_status as _emit_final_status,
)
from ._output import (
    _emit_report_line as _emit_report_line,
)
from ._output import (
    _hints_shown as _hints_shown,
)
from ._output import (
    _print_findings as _print_findings,
)
from ._output import (
    _print_fix_only_status as _print_fix_only_status,
)
from ._output import (
    _print_outline_entries as _print_outline_entries,
)
from ._output import (
    _report_kind as _report_kind,
)
from ._reports import (
    _CYRILLIC_RE as _CYRILLIC_RE,
)
from ._reports import (
    _WORD_TOKEN_RE as _WORD_TOKEN_RE,
)
from ._reports import (
    _bounded_context_lines as _bounded_context_lines,
)
from ._reports import (
    _context_candidate_line as _context_candidate_line,
)
from ._reports import (
    _context_candidates as _context_candidates,
)
from ._reports import (
    _context_entry_label as _context_entry_label,
)
from ._reports import (
    _context_findings as _context_findings,
)
from ._reports import (
    _context_relationships as _context_relationships,
)
from ._reports import (
    _diff_json_dumps as _diff_json_dumps,
)
from ._reports import (
    _docname_id as _docname_id,
)
from ._reports import (
    _entry_depth as _entry_depth,
)
from ._reports import (
    _entry_end as _entry_end,
)
from ._reports import (
    _entry_lineno as _entry_lineno,
)
from ._reports import (
    _entry_slug as _entry_slug,
)
from ._reports import (
    _entry_string_values as _entry_string_values,
)
from ._reports import (
    _find_stopwords as _find_stopwords,
)
from ._reports import (
    _format_context as _format_context,
)
from ._reports import (
    _format_context_candidates as _format_context_candidates,
)
from ._reports import (
    _format_json_diff as _format_json_diff,
)
from ._reports import (
    _format_references as _format_references,
)
from ._reports import (
    _format_runtime as _format_runtime,
)
from ._reports import (
    _generic_entry_kind as _generic_entry_kind,
)
from ._reports import (
    _json_file_model as _json_file_model,
)
from ._reports import (
    _load_json_dump as _load_json_dump,
)
from ._reports import (
    _one_edit_apart as _one_edit_apart,
)
from ._reports import (
    _prose_stemmers as _prose_stemmers,
)
from ._reports import (
    _prose_word_groups as _prose_word_groups,
)
from ._reports import (
    _rare_prose_words as _rare_prose_words,
)
from ._reports import (
    _resolve_context_matches as _resolve_context_matches,
)
from ._reports import (
    _run_context_query as _run_context_query,
)
from ._reports import (
    _runtime_metadata as _runtime_metadata,
)
from ._reports import (
    _stopword_sets as _stopword_sets,
)
from ._reports import (
    _top_prose_words as _top_prose_words,
)
from ._sphinx import (
    _ANSI_ESCAPE_RE as _ANSI_ESCAPE_RE,
)
from ._sphinx import (
    _BARE_FILENAME_RE as _BARE_FILENAME_RE,
)
from ._sphinx import (
    _BROKEN_DOC_REF_RE as _BROKEN_DOC_REF_RE,
)
from ._sphinx import (
    _BROKEN_LABEL_REF_RE as _BROKEN_LABEL_REF_RE,
)
from ._sphinx import (
    _FIXABLE_SPHINX_MESSAGES as _FIXABLE_SPHINX_MESSAGES,
)
from ._sphinx import (
    _MAX_BARE_FILENAME_CANDIDATES as _MAX_BARE_FILENAME_CANDIDATES,
)
from ._sphinx import (
    _WARNING_RE as _WARNING_RE,
)
from ._sphinx import (
    _attach_did_you_mean as _attach_did_you_mean,
)
from ._sphinx import (
    _build_sphinx_env as _build_sphinx_env,
)
from ._sphinx import (
    _build_sphinx_env_checked as _build_sphinx_env_checked,
)
from ._sphinx import (
    _did_you_mean as _did_you_mean,
)
from ._sphinx import (
    _docname_for as _docname_for,
)
from ._sphinx import (
    _expand_one_toctree as _expand_one_toctree,
)
from ._sphinx import (
    _expand_toctrees as _expand_toctrees,
)
from ._sphinx import (
    _findings_from_sphinx_output as _findings_from_sphinx_output,
)
from ._sphinx import (
    _is_sphinx_fixable_duplicate as _is_sphinx_fixable_duplicate,
)
from ._sphinx import (
    _merge_toctree_clusters as _merge_toctree_clusters,
)
from ._sphinx import (
    _resolve_xref_target as _resolve_xref_target,
)
from ._sphinx import (
    _toctree_anomalies as _toctree_anomalies,
)
from ._sphinx import (
    check_bare_filenames as check_bare_filenames,
)
from ._sphinx import (
    check_multiple_toctree_parents as check_multiple_toctree_parents,
)
from ._sphinx import (
    find_code_blocks as find_code_blocks,
)
from ._sphinx import (
    find_incoming_references as find_incoming_references,
)
from ._sphinx import (
    find_references as find_references,
)
from ._sphinx import (
    find_toctrees as find_toctrees,
)
from ._sphinx import (
    run_sphinx as run_sphinx,
)

# Re-export every name from every submodule below: this package replaces
# a single cli.py module, and check_rst.cli.<name> must keep resolving
# for every name that module used to expose, private-by-convention names
# included (the test suite and dogfooding scripts reach many of them
# directly) -- confirmed by a dir()-parity check against the pre-split
# module before this package replaced it.
from ._types import (
    _INLINE_CONTAINER_TYPES as _INLINE_CONTAINER_TYPES,
)
from ._types import (
    _NON_PROSE_NODE_TYPES as _NON_PROSE_NODE_TYPES,
)
from ._types import (
    AdmonitionEntry as AdmonitionEntry,
)
from ._types import (
    BlockCorrection as BlockCorrection,
)
from ._types import (
    BlockQuoteEntry as BlockQuoteEntry,
)
from ._types import (
    CodeBlockEntry as CodeBlockEntry,
)
from ._types import (
    CommentEntry as CommentEntry,
)
from ._types import (
    ContextMatch as ContextMatch,
)
from ._types import (
    Finding as Finding,
)
from ._types import (
    FixCounts as FixCounts,
)
from ._types import (
    FixPlan as FixPlan,
)
from ._types import (
    FixResult as FixResult,
)
from ._types import (
    ListEntry as ListEntry,
)
from ._types import (
    ListTableCandidate as ListTableCandidate,
)
from ._types import (
    ListTableFileResult as ListTableFileResult,
)
from ._types import (
    OutlineEntry as OutlineEntry,
)
from ._types import (
    ParsedTable as ParsedTable,
)
from ._types import (
    ReferenceEntry as ReferenceEntry,
)
from ._types import (
    Severity as Severity,
)
from ._types import (
    StopwordsUnavailable as StopwordsUnavailable,
)
from ._types import (
    TableEntry as TableEntry,
)
from ._types import (
    TextSpaceCounts as TextSpaceCounts,
)
from ._types import (
    TitleBlock as TitleBlock,
)
from ._types import (
    ToctreeEntry as ToctreeEntry,
)
from ._types import (
    UnderlineOnlyCandidate as UnderlineOnlyCandidate,
)
from ._types import (
    WordStatsUnavailable as WordStatsUnavailable,
)
from ._types import (
    _TextSpaceEdit as _TextSpaceEdit,
)
from ._types import (
    _TextSpaceEvidence as _TextSpaceEvidence,
)


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
            result = _checks._apply_fix_plan(plan)
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


def _run_diff_only(
    files: list[pathlib.Path],
    whole_file: bool,
    project_root: pathlib.Path,
    *,
    no_adornments: bool,
) -> NoReturn:
    """diff's own non-fast, read-only preview: byte-hygiene + adornment/
    hierarchy diff only, no lint/statistics/Sphinx (that's Phase 1-3, the
    check/fix pipeline's own job). Split out of _main() alongside the
    other _run_* handlers — self-contained given files/whole_file/
    project_root, which _discover_and_validate_files already resolved."""
    preview_changes = 0
    errors = 0
    for path in files:
        try:
            preview = diff_fixes(
                path,
                whole_file,
                include_structure=not no_adornments,
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


def _run_diff_json(args: argparse.Namespace) -> NoReturn:
    """diff-json's own fully self-contained verb body — no RST project is
    ever read (_validate_diff_json_args already rejects every project-
    identity flag), so this needs nothing from _main() beyond args itself.
    Split out of _main() (found by code review: _main was a single
    ~1000-line function with no seams) as the first, easiest-to-isolate
    piece — every other branch below this one in _main needs project_root/
    config/runtime_metadata that diff-json never touches."""
    old_path, new_path = (pathlib.Path(p) for p in args.diff_json)
    old_data = _load_json_dump(old_path)
    new_data = _load_json_dump(new_path)
    print(_format_json_diff(_diff_json_dumps(old_data, new_data)))
    sys.exit(0)


def _run_refs(args: argparse.Namespace, runtime_metadata: dict[str, Any]) -> NoReturn:
    """--refs' own self-contained verb body: one file's outgoing/incoming
    cross-references, always exactly one document, always its own
    throwaway Sphinx build unless --build-dir asks to keep it. Split out
    of _main() alongside _run_diff_json — same rationale, a clean,
    already fully self-contained branch."""
    if args.sphinx_src is None:
        _require_verified_sphinx("--refs")
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


def _discover_and_validate_files(
    args: argparse.Namespace, project_root: pathlib.Path
) -> tuple[list[pathlib.Path], bool]:
    """Resolve which files this run operates on, then validate the complete
    selection before any check or fixer touches disk. Split out of _main()
    (found by code review: _main was a single ~1000-line function with no
    seams) — recursive/git-scope/explicit-file selection, then de-dup by
    resolved path, then the invalid-file/foreign-file(--sphinx-src)/
    unresolved-merge checks every verb past this point depends on having
    already passed. Returns (files, whole_file); every early-exit path
    here calls sys.exit itself — a typo or unresolved conflict must abort
    atomically, never report partial progress (--fix-only's own
    precedent, preserved via the _print_fix_only_status calls below)."""
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
        raw_files: list[pathlib.Path] = args.files or _helpers._changed_rst_files(project_root)
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
            changed = {path.resolve() for path in _helpers._changed_rst_files(project_root)}
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

    return files, whole_file


def _require_verified_sphinx(option: str) -> NoReturn:
    """Shared failure for any option that needs verified Sphinx mode but
    --sphinx-src (directly or via --config) was never supplied."""
    print(
        f"check_rst: {option} requires verified Sphinx mode — "
        "pass --sphinx-src DIR or --config FILE whose check_rst "
        "settings declare sphinx-src"
    )
    raise SystemExit(1)


def _run_check_pipeline(
    args: argparse.Namespace,
    files: list[pathlib.Path],
    whole_file: bool,
    project_root: pathlib.Path,
    runtime_metadata: dict[str, Any],
    word_samples: int,
    suppress_findings: bool,
    config_source: str,
    config_applied: list[str],
    config_inactive: list[str],
) -> NoReturn:
    """The check/fix/diff Phase 1-3 pipeline shared by all three verbs
    (they're one algorithm parameterized by args.fix/args.diff/args.json/
    args.outline, not three separate ones — check_single_top_level's own
    Phase 1 loop, Phase 2/3 Sphinx integration, JSON assembly, word-stats,
    and the final summary line, all sharing one pass over *files*).

    Split out of _main() (found by code review: _main was a single
    ~1000-line function with no seams) as the one piece left after the
    already-self-contained early verb branches (diff-json, --refs,
    list-table, --context, --fix-only, diff --fast/non-fast) are each
    their own function — this is _main()'s true remaining body, not a
    per-verb split, because check/fix/diff genuinely share this walk.
    Always exits: JSON output exits directly; every other path falls
    through to the final summary line's sys.exit.
    """
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
            # Computed once for the whole selection, not once per file below
            # (found by code review: check_multiple_toctree_parents used to
            # rebuild this same project-wide graph on every iteration of this
            # very loop, against the one shared env it never changes for).
            toctree_anomalies = _toctree_anomalies(env)
            for path in files:
                bare_filename_doc = documents.get(path)
                if bare_filename_doc is None:
                    continue
                bare_filename_docname = _docname_for(env, path)
                if bare_filename_docname is None:
                    continue
                bare_filename_v = check_bare_filenames(env, bare_filename_docname, bare_filename_doc)
                multiple_toctree_v = check_multiple_toctree_parents(env, [path], anomalies=toctree_anomalies)
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

            sphinx_v = phase2_v + _sphinx.run_sphinx(
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
            top_result = _reports._top_prose_words(prose_texts, word_samples)
            rare_result = _reports._rare_prose_words(prose_texts, word_samples)
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
        _run_diff_json(args)

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
    loaded_config = (
        LoadedConfig("", _helpers.PROJECT_ROOT.resolve(), {}) if args.no_config else _load_config(args.config)
    )
    config_source = loaded_config.source
    config = loaded_config.values
    project_root = loaded_config.root if args.config is not None else _helpers.PROJECT_ROOT
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

    if explicit_build_dir and args.sphinx_src is None and not args.diff_only:
        _require_verified_sphinx("--build-dir")

    if args.no_toctree and args.sphinx_src is None:
        _require_verified_sphinx("--no-toctree")
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
        _run_refs(args, runtime_metadata)

    files, whole_file = _discover_and_validate_files(args, project_root)

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
        _run_diff_only(files, whole_file, project_root, no_adornments=args.no_adornments)

    _run_check_pipeline(
        args,
        files,
        whole_file,
        project_root,
        runtime_metadata,
        word_samples,
        suppress_findings,
        config_source,
        config_applied,
        config_inactive,
    )


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

    # _ACTIVE_OUTPUT_BUDGET now lives in ._output, not in this module's own
    # globals -- a bare "global _ACTIVE_OUTPUT_BUDGET" here would rebind a
    # DIFFERENT (this module's own, never-read) name instead of the one
    # _emit_final_status actually reads, since Python's global statement
    # only ever affects the current module's namespace. Rebind through the
    # module object itself so the mutation lands where it's read from.
    target = sys.stdout
    sink = OutputBudgetSink(limit, target)
    previous = _output._ACTIVE_OUTPUT_BUDGET
    _output._ACTIVE_OUTPUT_BUDGET = sink
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
        _output._ACTIVE_OUTPUT_BUDGET = previous
    sink.finish(exit_code)
    if caught is not None:
        raise caught


if __name__ == "__main__":
    main()
