# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Shared check/fix/diff execution pipeline — check_rst project

from __future__ import annotations

import collections
import dataclasses
import json
import pathlib
import re
import shutil
import sys
import tempfile
from typing import TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    import argparse

from . import _reports, _sphinx
from ._composition import CompositionIndex
from ._document import Document, build_outline
from ._formatting import (
    _apply_fix_plan,
    _plan_fix,
    check_adornments,
    check_hierarchy,
    check_single_top_level,
    diff_fixes,
)
from ._helpers import _JSON_SCHEMA_VERSION
from ._lint import check_directives, check_homoglyphs, check_nested_inline_markup
from ._output import (
    _emit_final_status,
    _emit_report_line,
    _print_findings,
    _print_outline_entries,
    _report_kind,
)
from ._reports import _docname_id, _format_runtime, _json_file_model
from ._sphinx import (
    _attach_did_you_mean,
    _build_sphinx_env_checked,
    _docname_for,
    _findings_from_sphinx_output,
    _is_sphinx_fixable_duplicate,
    _merge_toctree_clusters,
    _source_was_transformed,
    _toctree_anomalies,
    check_bare_filenames,
    check_multiple_toctree_parents,
    find_code_blocks,
    find_conditionals,
    find_includes,
    find_toctrees,
    nest_composed_clusters,
    partition_composed_entries,
)
from ._types import (
    Finding,
    FixPlan,
    LocalEntry,
    MergedEntry,
    OutlineEntry,
    Severity,
    ToctreeEntry,
    WordStatsUnavailable,
    _plural,
)


@dataclasses.dataclass(slots=True)
class _PipelineState:
    """Mutable facts accumulated once across the selected document set.

    The CLI phases share these facts, but no longer share a long register of
    loosely related local variables.  Keeping the state explicit makes each
    phase helper's inputs and mutations inspectable and type-checked.
    """

    total_errors: int = 0
    total_warnings: int = 0
    files_checked: int = 0
    documents: dict[pathlib.Path, Document] = dataclasses.field(default_factory=dict)
    json_records: dict[pathlib.Path, dict[str, Any]] = dataclasses.field(default_factory=dict)
    total_lines: int = 0
    empty_lines: int = 0
    total_chars: int = 0
    total_bytes: int = 0
    total_spaces: int = 0
    char_counter: collections.Counter[str] = dataclasses.field(default_factory=collections.Counter)
    word_counter: collections.Counter[str] = dataclasses.field(default_factory=collections.Counter)
    char_len_sum: int = 0
    char_len_min: int = 0
    char_len_max: int = 0
    byte_len_sum: int = 0
    byte_len_min: int = 0
    byte_len_max: int = 0
    fixed_files: set[str] = dataclasses.field(default_factory=set)
    would_change: set[str] = dataclasses.field(default_factory=set)
    suppressed_fixable: collections.Counter[pathlib.Path] = dataclasses.field(default_factory=collections.Counter)
    sphinx_findings_json: list[dict[str, Any]] | None = None
    fix_plans: dict[pathlib.Path, FixPlan] = dataclasses.field(default_factory=dict)


def _plan_normal_fixes(
    args: argparse.Namespace,
    files: list[pathlib.Path],
    whole_file: bool,
    project_root: pathlib.Path,
    state: _PipelineState,
) -> None:
    """Plan the complete full-pipeline fix selection before any write."""
    for path in files:
        try:
            state.fix_plans[path] = _plan_fix(
                path,
                whole_file,
                include_structure=not args.no_adornments,
                include_blank_lines=args.normalize_blank_lines,
                collapse_title_spaces=args.collapse_title_spaces,
                single_space_prose=args.single_space_prose,
                project_root=project_root,
            )
        except UnicodeDecodeError as exc:
            err_line = exc.object.count(b"\n", 0, exc.start) + 1
            _emit_report_line(
                f"{path}:{err_line}: ERROR: not valid UTF-8 ({exc.reason} at byte offset {exc.start})",
                "ERROR",
            )
            state.total_errors += 1
        except OSError as exc:
            _emit_report_line(f"check_rst: {path}: ERROR: cannot read input: {exc}", "ERROR")
            state.total_errors += 1
        except RuntimeError as exc:
            _emit_report_line(f"check_rst: {path}: ERROR: {exc}", "ERROR")
            state.total_errors += 1

    if state.total_errors:
        _emit_final_status(
            f"check_rst: {len(files)} file(s) selected, {state.total_errors} input error(s), 0 file(s) fixed"
        )
        raise SystemExit(1)


def _run_phase1(
    args: argparse.Namespace,
    files: list[pathlib.Path],
    whole_file: bool,
    project_root: pathlib.Path,
    word_samples: int,
    suppress_findings: bool,
    state: _PipelineState,
) -> None:
    """Run byte/RST checks and accumulate one normalized document per file."""
    # ------------------------------------------------------------------ Phase 1
    mode_tag = " [fix]" if args.fix else " [diff]" if args.diff else ""
    if not args.quiet:
        print(f"Phase 1: RST rules{mode_tag}")
        print("-" * 40)

    for path in files:
        if not path.exists():
            if args.json:
                state.json_records[path] = {
                    "path": str(path),
                    "error": "file not found",
                    "outline": [],
                    "findings": [],
                }
            else:
                _emit_report_line(f"{path}: ERROR: file not found", "ERROR")
            state.total_errors += 1
            continue

        pstr = str(path)
        state.files_checked += 1

        # Phase 0 — byte hygiene, before anything parses the file.  Always
        # whole-file (a line-ending policy can't be diff-scoped), independent
        # of --no-adornments, and every finding is --fix-able, so
        # --skip-fixable suppresses them all.  In --fix mode the complete
        # selection was already planned without writes; this original-state
        # Document supplies the hygiene progress category before the composed
        # candidate is installed atomically below.
        # Phase 0 is also where a non-UTF-8 file surfaces: a clean per-file
        # ERROR, never a UnicodeDecodeError traceback (found by probe,
        # 2026-07-18 — same traceback-instead-of-diagnostic class as the
        # not-a-git-repo case).
        document = Document(path, project_root)
        if args.json:
            state.json_records[path] = {"path": pstr, "outline": [], "findings": []}
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
                state.json_records[path]["error"] = msg
            else:
                _emit_report_line(f"{pstr}:{err_line}: ERROR: {msg}", "ERROR")
            state.total_errors += 1
            continue
        if args.fix:
            plan = state.fix_plans[path]
            try:
                _apply_fix_plan(plan)
            except (OSError, RuntimeError) as exc:
                _emit_report_line(f"check_rst: {path}: ERROR: cannot write fix: {exc}", "ERROR")
                state.total_errors += 1
                continue
            if plan.changed:
                state.fixed_files.add(pstr)
            if not args.quiet and hygiene_v:
                print(f"✓ {pstr}: hygiene fix applied (line endings / BOM / trailing whitespace)")
            if not args.quiet and plan.text_space_counts.total:
                print(f"✓ {pstr}: {plan.text_space_counts.describe()}")
            if not args.quiet and plan.counts.structural_lines:
                print(f"✓ {pstr}: adornment/hierarchy fix applied")
            if not args.quiet and plan.blank_lines_removed:
                noun = _plural(plan.blank_lines_removed, "line")
                print(f"✓ {pstr}: {plan.blank_lines_removed} redundant blank {noun} removed")
        elif hygiene_v:
            if args.skip_fixable:
                state.suppressed_fixable[path] += len(hygiene_v)
            else:
                if args.diff:
                    state.would_change.add(pstr)  # fix_hygiene would rewrite this file
                if args.json:
                    state.json_records[path]["findings"].extend(hygiene_v)
                e, w = _print_findings(hygiene_v, pstr, args.no_warnings, suppress_findings)
                state.total_errors += e
                state.total_warnings += w

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
                state.would_change.add(pstr)
                print(ds, end="")
            elif not args.quiet:
                print(f"  {pstr}: no hygiene/adornment/hierarchy fixes needed")
        if args.fix:
            # The composed fix plan wrote to disk — the facade's explicit lifecycle:
            # construct a fresh Document for the post-fix checks and stats.
            document = Document(path, project_root)

        if not args.no_adornments:
            adornment_v = check_adornments(path, whole_file, doc=document)
            hierarchy_v = check_hierarchy(path, doc=document)
            # Verified mode must use Sphinx's effective parse (extensions,
            # source mutation, includes, and HTML-resolved conditions), so its
            # single-title check runs in Phase 2 after the environment exists.
            single_top_v = check_single_top_level(path, doc=document) if args.sphinx_src is None else []
            all_v = adornment_v + hierarchy_v + single_top_v
            if args.skip_fixable:
                # Severity and repairability are independent.  Suppress only
                # findings explicitly owned by the deterministic fixer; a
                # non-fixable structural ERROR still affects the exit status.
                fixable_v = [finding for finding in all_v if finding.fixable]
                visible_v = [finding for finding in all_v if not finding.fixable]
                state.suppressed_fixable[path] += len(fixable_v)
                if args.json:
                    state.json_records[path]["findings"].extend(visible_v)
                e, w = _print_findings(visible_v, pstr, args.no_warnings, suppress_findings)
                state.total_errors += e
                state.total_warnings += w
                if not all_v and not args.diff and not args.quiet:
                    print(f"✓ {pstr}: adornments + hierarchy OK")
            else:
                if args.json:
                    state.json_records[path]["findings"].extend(all_v)
                e, w = _print_findings(all_v, pstr, args.no_warnings, suppress_findings)
                if not all_v and not args.diff and not args.quiet:
                    print(f"✓ {pstr}: adornments + hierarchy OK")
                state.total_errors += e
                state.total_warnings += w

        nested_inline_v = check_nested_inline_markup(path, whole_file, doc=document)
        if args.json:
            state.json_records[path]["findings"].extend(nested_inline_v)
        _, w = _print_findings(nested_inline_v, pstr, args.no_warnings, suppress_findings)
        state.total_warnings += w  # WARNING-only: choosing one of two roles is semantic.

        if not args.no_directives:
            directive_v = check_directives(path, whole_file, args.verbose, doc=document)
            if args.json:
                state.json_records[path]["findings"].extend(directive_v)
            e, w = _print_findings(directive_v, pstr, args.no_warnings, suppress_findings)
            if not e and not w and not args.quiet:
                print(f"✓ {pstr}: directives OK")
            state.total_errors += e  # directive findings are warnings; e stays 0
            state.total_warnings += w

        homoglyph_v = check_homoglyphs(path, doc=document)
        if args.json:
            state.json_records[path]["findings"].extend(homoglyph_v)
        _, w = _print_findings(homoglyph_v, pstr, args.no_warnings, suppress_findings)
        state.total_warnings += w  # WARNING-only, never affects state.total_errors

        if args.skip_fixable and state.suppressed_fixable[path] and not args.quiet:
            print(f"↷ {pstr}: {state.suppressed_fixable[path]} auto-fixable finding(s) suppressed")

        # Footer statistics, from the same normalized read Phase 0 defines —
        # in --fix mode this is the file's final, post-fix state.  Empty
        # lines are RST's block delimiter, so the empty/total ratio is a
        # quick structure signal.
        state.documents[path] = document
        stat_text = document.text
        stat_lines = document.lines
        state.total_lines += len(stat_lines)
        state.empty_lines += sum(1 for line in stat_lines if not line.strip())
        state.total_chars += len(stat_text)
        state.total_bytes += len(stat_text.encode("utf-8"))
        state.total_spaces += stat_text.count(" ")
        # Frequency counters (Max, 2026-07-19): words at Phase 0 level are
        # whitespace-separated tokens of the raw normalized text — markup
        # included ('#######' is a token); deliberately not a prose count.
        # For chars the once-only set is tiny and is an oddity scan (a stray
        # variation selector, a lone Vietnamese letter); for words it would
        # be degenerate (~73% of any prose vocabulary occurs once), so words
        # get counts only.
        state.char_counter.update(stat_text)
        state.word_counter.update(stat_text.split())
        # Line-length spread over NON-empty lines (min over all lines would
        # trivially be 0); max is the over-long-line signal.  Two measures,
        # chars (code points) and bytes, shown collapsed when they coincide
        # — same rule as the character totals.
        for line in stat_lines:
            if line.strip():
                n = len(line)
                state.char_len_sum += n
                state.char_len_min = n if state.char_len_min == 0 else min(state.char_len_min, n)
                state.char_len_max = max(state.char_len_max, n)
                b = len(line.encode("utf-8"))
                state.byte_len_sum += b
                state.byte_len_min = b if state.byte_len_min == 0 else min(state.byte_len_min, b)
                state.byte_len_max = max(state.byte_len_max, b)

    # A Sphinx application loads project extensions into this Python process.
    # docutils_namespace() restores Sphinx's directive/role/node registrations,
    # but arbitrary extensions may mutate other process-global state.  When a
    # later report will need the bare-docutils tree and Phase 1 did not already
    # force it (notably --no-directives), materialize that cached tree BEFORE
    # constructing Sphinx.  Derived outline/block/prose properties can then be
    # evaluated later without running a parser in the extension-mutated process.
    if args.sphinx_src is not None and (args.outline or args.json or word_samples):
        for document_model in state.documents.values():
            _ = document_model.doctree


def _run_sphinx_phases(
    args: argparse.Namespace,
    files: list[pathlib.Path],
    project_root: pathlib.Path,
    word_samples: int,
    suppress_findings: bool,
    state: _PipelineState,
) -> None:
    """Run heuristic or verified Sphinx structure and build checks."""
    # ------------------------------------------------------------ Phase 2 & 3
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
                phase2_doc = state.documents.get(path)
                if phase2_doc is None:
                    continue
                code_blocks = phase2_doc.code_blocks_heuristic
                include_entries = phase2_doc.includes
                if args.json:
                    state.json_records[path].update(
                        _json_file_model(
                            phase2_doc,
                            code_blocks,
                            word_samples,
                            include_entries=include_entries,
                            structure_stage="parser-effective",
                            project_root=project_root,
                        )
                    )
                    if state.json_records[path]["stats"]["word_stats_error"] and not args.no_warnings:
                        state.total_warnings += 1
                if args.outline and not args.json:
                    heuristic_entries: list[LocalEntry] = [
                        *phase2_doc.outline,
                        *include_entries,
                        *code_blocks,
                        *phase2_doc.block_quotes,
                        *phase2_doc.tables,
                        *phase2_doc.admonitions,
                        *phase2_doc.comments,
                        *phase2_doc.lists,
                    ]
                    heuristic_root, include_clusters = partition_composed_entries(heuristic_entries)
                    heuristic_combined: list[MergedEntry] = _merge_toctree_clusters(
                        heuristic_root,
                        include_clusters,
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
                bare_filename_doc = state.documents.get(path)
                if bare_filename_doc is None:
                    continue
                bare_filename_docname = _docname_for(env, path)
                if bare_filename_docname is None:
                    continue
                bare_filename_v = check_bare_filenames(env, bare_filename_docname, bare_filename_doc)
                multiple_toctree_v = check_multiple_toctree_parents(env, [path], anomalies=toctree_anomalies)
                single_top_v: list[Finding] = []
                if not args.no_adornments:
                    get_doctree = getattr(env, "get_doctree", None)
                    effective_doctree = (
                        _sphinx.resolve_html_structure(env, bare_filename_docname)
                        if callable(get_doctree)
                        else bare_filename_doc.doctree
                    )
                    single_top_v = check_single_top_level(
                        path,
                        doc=bare_filename_doc,
                        doctree=effective_doctree,
                        source_root=args.sphinx_src,
                        root_transformed=_source_was_transformed(env, bare_filename_docname),
                    )
                if args.json:
                    state.json_records[path]["findings"].extend(bare_filename_v)
                    state.json_records[path]["findings"].extend(multiple_toctree_v)
                    state.json_records[path]["findings"].extend(single_top_v)
                _, w = _print_findings(bare_filename_v, str(path), args.no_warnings, suppress_findings)
                state.total_warnings += w  # WARNING-only, never affects state.total_errors
                e, _ = _print_findings(single_top_v, str(path), args.no_warnings, suppress_findings)
                state.total_errors += e
                _, w = _print_findings(
                    multiple_toctree_v,
                    str(path),
                    args.no_warnings,
                    suppress_findings,
                )
                state.total_warnings += w  # WARNING-only, never affects state.total_errors
            if args.outline or args.json:
                for path in files:
                    # phase2_doc: see the sibling heuristic loop above for
                    # why this isn't named "document".
                    phase2_doc = state.documents.get(path)
                    if phase2_doc is None:
                        continue
                    pstr = str(path)
                    docname = _docname_for(env, path)
                    verified_tree = env.get_doctree(docname) if docname is not None else None
                    verified_composition = (
                        CompositionIndex(
                            verified_tree,
                            path,
                            args.sphinx_src,
                            root_transformed=_source_was_transformed(env, docname),
                        )
                        if docname is not None and verified_tree is not None
                        else None
                    )
                    code_blocks = (
                        find_code_blocks(
                            env,
                            docname,
                            phase2_doc.lines,
                            phase2_doc,
                            doctree=verified_tree,
                            composition=verified_composition,
                        )
                        if docname is not None
                        else []
                    )
                    verified_outline = (
                        build_outline(
                            path,
                            doc=phase2_doc,
                            doctree=verified_tree,
                            source_root=args.sphinx_src,
                            root_transformed=_source_was_transformed(env, docname),
                            composition=verified_composition,
                        )
                        if docname is not None
                        else phase2_doc.outline
                    )
                    toctree_clusters = (
                        find_toctrees(
                            env,
                            docname,
                            phase2_doc,
                            doctree=verified_tree,
                            composition=verified_composition,
                        )
                        if docname is not None and not args.no_toctree
                        else []
                    )
                    include_entries = (
                        find_includes(
                            env,
                            docname,
                            phase2_doc,
                            doctree=verified_tree,
                            composition=verified_composition,
                        )
                        if docname is not None
                        else phase2_doc.includes
                    )
                    conditional_entries = (
                        find_conditionals(
                            env,
                            docname,
                            phase2_doc,
                            doctree=verified_tree,
                            composition=verified_composition,
                        )
                        if docname is not None
                        else []
                    )
                    cross_file_headings = [
                        e for cluster in toctree_clusters for e in cluster if isinstance(e, OutlineEntry)
                    ]
                    toctree_containers = [
                        e for cluster in toctree_clusters for e in cluster if isinstance(e, ToctreeEntry)
                    ]
                    if args.json:
                        state.json_records[path].update(
                            _json_file_model(
                                phase2_doc,
                                code_blocks,
                                word_samples,
                                outline_entries=[
                                    *verified_outline,
                                    *cross_file_headings,
                                ],
                                toctree_entries=toctree_containers,
                                include_entries=include_entries,
                                conditional_entries=conditional_entries,
                                structure_stage="parser-effective",
                                project_root=project_root,
                            )
                        )
                        if state.json_records[path]["stats"]["word_stats_error"] and not args.no_warnings:
                            state.total_warnings += 1
                        if docname is None:
                            state.json_records[path]["unreachable"] = (
                                "not part of the --sphinx-src project — code-blocks unavailable"
                            )
                    if args.outline and not args.json:
                        composed_entries: list[LocalEntry] = [
                            *verified_outline,
                            *include_entries,
                            *conditional_entries,
                            *code_blocks,
                            *phase2_doc.block_quotes,
                            *phase2_doc.tables,
                            *phase2_doc.admonitions,
                            *phase2_doc.comments,
                            *phase2_doc.lists,
                        ]
                        local_entries, include_clusters = partition_composed_entries(composed_entries)
                        nested_includes, root_toctrees = nest_composed_clusters(include_clusters, toctree_clusters)
                        clusters = [*nested_includes, *root_toctrees]
                        clusters.sort(key=lambda cluster: cluster[0].lineno if cluster else 0)
                        combined = _merge_toctree_clusters(local_entries, clusters)
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
            # state.documents.  A diagnostic can therefore appear in both streams;
            # Findings are frozen/hashable, so preserve first-seen order while
            # counting and printing an identical finding only once.
            sphinx_v = list(dict.fromkeys(sphinx_v))
            if args.skip_fixable and state.suppressed_fixable:
                suppressed_paths = set(state.suppressed_fixable)
                sphinx_v = [
                    finding
                    for finding in sphinx_v
                    if not _is_sphinx_fixable_duplicate(finding, suppressed_paths, project_root)
                ]
            if args.json:
                state.sphinx_findings_json = [
                    dataclasses.asdict(f) for f in sphinx_v if not args.no_warnings or f.severity != Severity.WARNING
                ]
            e, w = _print_findings(sphinx_v, "sphinx", args.no_warnings, suppress_findings)
            if not e and not w and not args.quiet:
                print("✓ no warnings or errors in the checked files")
            state.total_errors += e
            state.total_warnings += w
        finally:
            if not keep_build:
                shutil.rmtree(build_dir, ignore_errors=True)


def _emit_json_result(
    args: argparse.Namespace,
    files: list[pathlib.Path],
    runtime_metadata: dict[str, Any],
    config_source: str,
    config_applied: list[str],
    config_inactive: list[str],
    state: _PipelineState,
) -> NoReturn:
    """Emit the complete JSON contract and exit with the accumulated status."""
    # --json: the whole model as one JSON object on stdout — nothing else
    # was printed (quiet implied, findings suppressed and captured).
    for rec in state.json_records.values():
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
        "files": [state.json_records[f] for f in files if f in state.json_records],
        "summary": {
            "files_checked": state.files_checked,
            "errors": state.total_errors,
            "warnings": state.total_warnings,
            "lines": state.total_lines,
            "empty_lines": state.empty_lines,
            "chars": state.total_chars,
            "bytes": state.total_bytes,
        },
    }
    if state.sphinx_findings_json is not None:
        data["sphinx_findings"] = state.sphinx_findings_json
    print(json.dumps(data, ensure_ascii=False, indent=2))
    sys.exit(1 if state.total_errors else 0)


def _emit_text_summary(
    args: argparse.Namespace,
    word_samples: int,
    suppress_findings: bool,
    state: _PipelineState,
) -> NoReturn:
    """Emit text statistics and the authoritative final status, then exit."""
    # Word-frequency stats — computed ahead of Line 1 so a WordStatsUnavailable
    # warning is counted in THIS run's state.total_warnings, not just noted after
    # the count already printed (Max, 2026-07-20: "no silent fails anymore;
    # fails must be explicit").  word_samples == 0 (outside --verbose/
    # --word-samples) skips this entirely — the stopword/stemmer machinery
    # is never touched for output nobody asked to see (Max, 2026-07-20:
    # "we shouldn't pay for what we don't use").
    top_result: tuple[list[tuple[str, int]], int] | None = None
    rare_result: tuple[list[tuple[str, str | None, int]], int] | None = None
    word_stats_error: str | None = None
    if word_samples and state.word_counter.total():
        prose_texts = [d.prose_text for d in state.documents.values()]
        try:
            top_result = _reports._top_prose_words(prose_texts, word_samples)
            rare_result = _reports._rare_prose_words(prose_texts, word_samples)
        except WordStatsUnavailable as exc:
            word_stats_error = str(exc)
            if not args.no_warnings:
                state.total_warnings += 1

    # Summary — always, one machine-parseable line (kills the grep -c and
    # exit-code-probe post-processing observed across five AI sessions).
    if not args.quiet:
        print()

    # Line 1 — run facts and character totals.  Symbols (code points) vs
    # bytes: two numbers when they differ (non-ASCII content), one with a
    # note when they coincide.
    parts = [
        f"check_rst: {state.files_checked} file(s) checked",
        f"{state.total_errors} error(s)",
        f"{state.total_warnings} warning(s)",
    ]
    if args.fix:
        parts.append(f"{len(state.fixed_files)} file(s) fixed")
    if args.diff:
        parts.append(f"{len(state.would_change)} file(s) would change")
    if state.total_lines:
        distinct_chars = len(state.char_counter)
        once_chars = sum(1 for n in state.char_counter.values() if n == 1)
        char_detail = f"{distinct_chars} distinct, {once_chars} once"
        if state.total_bytes != state.total_chars:
            parts.append(f"{state.total_chars} char(s) ({char_detail}), {state.total_bytes} byte(s)")
        else:
            parts.append(f"{state.total_chars} char(s) (= bytes, {char_detail})")
        pct_spaces = round(100 * state.total_spaces / state.total_chars) if state.total_chars else 0
        parts.append(f"{state.total_spaces} space(s) ({pct_spaces}%)")
    _emit_final_status(", ".join(parts))
    del parts

    # Line 2 — everything about lines, no mixture with the totals above.
    # --verbose only (Max, 2026-07-20: verbosity-level inventory — cheap to
    # compute, but detailed enough that the default/--quiet loop stays to
    # the one-line summary above; this is exactly the gap independently
    # reported the same day from real usage: "--quiet doesn't quiet the
    # prose-statistics tail").
    if state.total_lines and args.verbose:
        pct = round(100 * state.empty_lines / state.total_lines)
        line2 = f"lines: {state.total_lines} total ({state.empty_lines} empty, {pct}%)"
        nonempty = state.total_lines - state.empty_lines
        if nonempty:
            char_avg = round(state.char_len_sum / nonempty)
            char_triple = f"{state.char_len_min}/{char_avg}/{state.char_len_max}"
            byte_avg = round(state.byte_len_sum / nonempty)
            byte_triple = f"{state.byte_len_min}/{byte_avg}/{state.byte_len_max}"
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
    total_words = state.word_counter.total()
    if total_words and args.verbose:
        distinct_words = len(state.word_counter)
        once_words = sum(1 for n in state.word_counter.values() if n == 1)
        word_len_sum = sum(len(w) * n for w, n in state.word_counter.items())
        word_avg = round(word_len_sum / total_words)
        word_len_min = min(len(w) for w in state.word_counter)
        word_len_max = max(len(w) for w in state.word_counter)
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
        multi_file = len(state.documents) > 1

        def _first_match(word: str) -> str:
            pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
            for doc_path, d in state.documents.items():
                for i, line in enumerate(d.lines, 1):
                    if pattern.search(line):
                        return f"@{_docname_id(doc_path)}:{i}" if multi_file else f"@{i}"
            return ""

        if word_stats_error is not None:
            # Explicit and counted (in state.total_warnings above) — never the
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

    sys.exit(1 if state.total_errors else 0)


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

    state = _PipelineState()

    if args.fix:
        _plan_normal_fixes(args, files, whole_file, project_root, state)

    _run_phase1(args, files, whole_file, project_root, word_samples, suppress_findings, state)
    _run_sphinx_phases(args, files, project_root, word_samples, suppress_findings, state)
    if args.json:
        _emit_json_result(
            args,
            files,
            runtime_metadata,
            config_source,
            config_applied,
            config_inactive,
            state,
        )
    _emit_text_summary(args, word_samples, suppress_findings, state)
