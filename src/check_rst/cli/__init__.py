# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
"""Command-line implementation for check_rst."""

from __future__ import annotations

import argparse
import collections
import contextlib
import difflib
import pathlib
import shutil
import sys
import tempfile
from typing import TYPE_CHECKING, Any, NoReturn

from check_rst import DOCUMENTATION_URL, __version__

from . import _formatting, _helpers, _output
from ._config import LoadedConfig, _load_config
from ._formatting import _plan_fix, diff_fixes
from ._helpers import (
    HIERARCHY,
    PREFERRED_HIERARCHY,
    _git_worktree_root,
    _unmerged_files,
)
from ._list_table import _plan_list_table_file
from ._output import (
    OutputBudgetSink,
    _emit_final_status,
    _emit_report_line,
    _hints_shown,
    _print_fix_only_status,
)
from ._pipeline import _run_check_pipeline
from ._reports import (
    _diff_json_dumps,
    _format_json_diff,
    _format_references,
    _format_runtime,
    _load_json_dump,
    _run_context_query,
    _runtime_metadata,
)
from ._sphinx import (
    _build_sphinx_env_checked,
    _docname_for,
    find_incoming_references,
    find_references,
)

if TYPE_CHECKING:
    from ._types import FixPlan, FixResult, ListTableIssue


_TOP_LEVEL_HELP = f"""\
Check .rst files against reStructuredText and Sphinx project rules.

A required command selects one action: check and diff serve the
reviewer/auditor role; fix and list-table serve the modifier role;
outline, context, and refs serve the reader role. Phase 0 checks byte
hygiene, Phase 1 checks RST formatting and directives, Phase 2 resolves
Sphinx-aware structure, and Phase 3 runs a real Sphinx build.

Global options must precede the command. The working directory is the
project root unless --config selects another project; --no-config skips
configuration discovery; --sphinx-src enables verified Phase 2 and 3.

Exit status: 0 no ERROR; 1 one or more ERRORs. Preview commands diff and
list-table also return 1 when files would change. 2 command-line usage error.

Examples:
    check_rst check
    check_rst --sphinx-src . check
    check_rst check --skip-fixable
    check_rst fix --fast
    check_rst diff doc.rst
    check_rst check --recursive docs/
    check_rst outline doc.rst
    check_rst context 'doc:Section' doc.rst
    check_rst refs doc.rst
    check_rst list-table doc.rst
    check_rst diff-json before.json after.json

Documentation: {DOCUMENTATION_URL}
Run check_rst COMMAND --help for command options.
"""


_DOCUMENTATION_EPILOG = f"Documentation: {DOCUMENTATION_URL}"


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
            result = _formatting._apply_fix_plan(plan)
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
    files: list[pathlib.Path],
    *,
    only: list[int],
    skip: list[int],
    apply: bool,
    quiet: bool,
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
    converted_tables = 0
    refused_tables = 0
    error_tables = 0
    refusal_categories: collections.Counter[str] = collections.Counter()

    def print_issue(path: pathlib.Path, issue: ListTableIssue, *, fatal: bool) -> None:
        is_error = fatal or issue.category in {"source-model", "semantic-proof"}
        label = "ERROR" if is_error else "UNCHANGED" if issue.category == "unchanged" else "REFUSED"
        line = issue.entry.lineno if issue.entry is not None else 1
        print(f"check_rst: {path}:{line}: {label} [{issue.code}]")
        if issue.entry is not None and issue.ordinal is not None:
            rows, cols = issue.entry.dims
            caption = f', "{issue.entry.caption}"' if issue.entry.caption else ""
            print(f"  table {issue.ordinal} ({issue.entry.kind}, {rows}x{cols}{caption}): {issue.reason}")
        else:
            print(f"  {issue.reason}")
        print(f"  Impact: {issue.impact}")
        print(f"  Action: {issue.action}")

    for path in files:
        result = _plan_list_table_file(path, only, skip)
        if result.fatal is not None:
            print_issue(path, result.fatal, fatal=True)
            fatal_files += 1
            continue
        file_has_error = False
        for issue in result.refusals:
            print_issue(path, issue, fatal=False)
            if issue.category in {"source-model", "semantic-proof"}:
                error_tables += 1
                file_has_error = True
            elif issue.category != "unchanged":
                refused_tables += 1
                refusal_categories[issue.category] += 1
        if file_has_error:
            fatal_files += 1
        if not result.changed:
            if not quiet and not result.refusals:
                print(f"check_rst: {path}: no eligible tables to convert")
            continue
        would_change += 1
        converted_tables += len(result.converted)
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
    refusal_detail = ""
    if refusal_categories:
        categories = ", ".join(f"{name}: {count}" for name, count in sorted(refusal_categories.items()))
        refusal_detail = f" ({categories})"
    table_status = (
        f", {converted_tables} table(s) converted, {refused_tables} table(s) refused{refusal_detail}, "
        f"{error_tables} table error(s)"
    )
    if apply:
        _emit_final_status(
            f"check_rst: {len(files)} file(s) checked, {fatal_files} error(s), "
            f"{converted_files} file(s) converted{table_status}"
        )
    else:
        _emit_final_status(
            f"check_rst: {len(files)} file(s) checked, {fatal_files} error(s), "
            f"{would_change} file(s) would change{table_status}"
        )
    raise SystemExit(1 if fatal_files or (not apply and would_change) else 0)


def _run_hierarchy() -> NoReturn:
    """Print the complete live adornment order for this Docutils runtime."""
    print("Adornment hierarchy for this Docutils runtime:")
    for index, character in enumerate(HIERARCHY, 1):
        preferred = " (preferred)" if character in PREFERRED_HIERARCHY else ""
        print(f"{index:2d}. {character!r}{preferred}")
    raise SystemExit(0)


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
        help="load settings from FILE instead of discovering .check_rst.toml/pyproject.toml in the working directory",
    )
    parser.add_argument(
        "--no-config",
        action="store_true",
        help="skip config discovery entirely, CLI-only defaults; incompatible with --config",
    )
    parser.add_argument(
        "--sphinx-src",
        type=pathlib.Path,
        default=None,
        metavar="DIR",
        help=(
            "Sphinx source tree; enables verified Phase 2/3 against it, never auto-detected. "
            "omit for heuristic Phase 2 and no Phase 3"
        ),
    )
    parser.add_argument(
        "--build-dir",
        type=pathlib.Path,
        default=None,
        metavar="DIR",
        help="Sphinx output directory; a temp dir is used and removed if omitted. Requires --sphinx-src",
    )


def _add_no_toctree_flag(parser: argparse.ArgumentParser) -> None:
    """--no-toctree — shared by every verb whose structure/model can recurse toctrees."""
    parser.add_argument(
        "--no-toctree",
        action="store_true",
        help="don't recurse .. toctree:: directives in verified mode; default recurses fully",
    )


def _add_scope_flags(parser: argparse.ArgumentParser, *, outline: bool = False) -> None:
    """--recursive/--git-scope/--exclude — shared by check/fix/diff/outline."""
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="treat each positional argument as a directory, discover *.rst under it; whole-file, like explicit files",
    )
    parser.add_argument(
        "--git-scope",
        action="store_true",
        help=(
            "select files through Git; show whole-document structure; findings use changed-line scope"
            if outline
            else "treat positional files as a Git allowlist; findings use changed-line scope"
        ),
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="with --recursive, skip discovered files matching PATTERN (pathlib.PurePath.match); repeatable",
    )


def _add_quiet_verbose_words(parser: argparse.ArgumentParser) -> None:
    """--quiet/--verbose/--word-samples — shared by check/fix/diff/outline."""
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="extra detail on bold/rubric WARNINGs, plus footer and outline statistics",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress progress output; findings and the final summary line still print",
    )
    parser.add_argument(
        "--word-samples",
        type=int,
        default=None,
        metavar="N",
        help="entries in the top/rare prose words lines; default 10 under --verbose, else omitted. 0 disables",
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
        help="cap the report at N lines (>= 2); exit status is unaffected and final status is always shown",
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
        help="suppress ERROR-level findings fix would resolve automatically; WARNINGs stay visible",
    )
    parser.add_argument(
        "--no-adornments",
        action="store_true",
        help="skip adornment/hierarchy lint and, with fix/diff, their fixes; Phase 0 byte hygiene remains enabled",
    )
    parser.add_argument(
        "--no-directives",
        action="store_true",
        help="skip directive warnings (rubric, bold patterns)",
    )


def _build_full_parent(*, outline: bool = False) -> argparse.ArgumentParser:
    """Shared parent for the four verbs built on the roadmap's 'full' shape:
    check, fix, diff, outline."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "files",
        nargs="*",
        type=pathlib.Path,
        help="RST files to process in full; omit to auto-detect changed/untracked *.rst files",
    )
    _add_scope_flags(parent, outline=outline)
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
        help="files to convert tables in, checked in full; omit to auto-detect changed/untracked *.rst",
    )
    _add_scope_flags(parent)
    parent.add_argument(
        "--quiet",
        action="store_true",
        help="suppress progress output; the final summary line still prints",
    )
    parent.add_argument(
        "--apply",
        action="store_true",
        help="write converted files; default previews a diff",
    )
    parent.add_argument(
        "--only",
        type=int,
        action="append",
        default=[],
        metavar="N",
        help="convert only the Nth table shown by outline (1-based); repeatable, default considers every table",
    )
    parent.add_argument(
        "--skip",
        type=int,
        action="append",
        default=[],
        metavar="N",
        help="exclude the Nth table shown by outline (1-based) from conversion; repeatable",
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
        help="parser-free Phase 0 hygiene and Phase 1 adornment/hierarchy only; no lint, statistics, or Sphinx",
    )
    parent.add_argument(
        "--normalize-blank-lines",
        action="store_true",
        help="collapse leading/repeated separator blank lines, tree-verified; opt-in, rejected under --fast",
    )
    parent.add_argument(
        "--collapse-title-spaces",
        action="store_true",
        help="collapse internal space runs in section-title text, tree-verified; opt-in, rejected under --fast",
    )
    parent.add_argument(
        "--single-space-prose",
        action="store_true",
        help="single-ASCII-space policy for eligible prose, tree-verified; opt-in, rejected under --fast",
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
    "diff": frozenset(
        {
            "files",
            "config",
            "no_config",
            "git_scope",
            "no_adornments",
            "recursive",
            "exclude",
            "quiet",
        }
    ),
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
    parser = argparse.ArgumentParser(
        prog="check_rst",
        description=_TOP_LEVEL_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    _add_project_flags(parser)
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    full = _build_full_parent()
    outline_full = _build_full_parent(outline=True)
    mutating = _build_mutating_parent()

    check_p = sub.add_parser(
        "check",
        parents=[full],
        help="check .rst files against project formatting rules",
        description="Reviewer/auditor role: Phase 0 hygiene, Phase 1 lint, Phase 2 Sphinx structure, Phase 3 build.",
        epilog=_DOCUMENTATION_EPILOG,
    )
    check_p.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="text (default) or json: complete document model as one object, nothing else on stdout",
    )
    _add_no_toctree_flag(check_p)
    _add_max_output_lines(check_p)
    check_p.set_defaults(**_CLI_ATTR_DEFAULTS)

    fix_p = sub.add_parser(
        "fix",
        parents=[full, mutating],
        help="apply auto-fixable corrections in-place",
        description=(
            "Modifier role: byte hygiene and adornment/hierarchy geometry, in-place. "
            "Rejects the whole selection before writing on any unresolved Git merge entry. "
            "--fast skips lint, statistics, and Sphinx."
        ),
        epilog=_DOCUMENTATION_EPILOG,
    )
    _add_max_output_lines(fix_p)
    fix_p.set_defaults(**_CLI_ATTR_DEFAULTS)
    fix_p.set_defaults(fix=True)

    diff_p = sub.add_parser(
        "diff",
        parents=[full, mutating],
        help="print unified diff of what fix would change",
        description="Reviewer/auditor role, read-only: preview what fix would change. --fast stops after Phase 1.",
        epilog=_DOCUMENTATION_EPILOG,
    )
    diff_p.set_defaults(**_CLI_ATTR_DEFAULTS)
    diff_p.set_defaults(diff=True)

    outline_p = sub.add_parser(
        "outline",
        parents=[outline_full],
        help="print each file's section structure (structure-only by default)",
        description=(
            "Reader role: this file's section tree, navigable without a linear read. "
            "Structure-only by default; --with-findings layers bold/rubric WARNINGs on top. "
            "Structure is always whole-document and never affects the exit code."
        ),
        epilog=_DOCUMENTATION_EPILOG,
    )
    outline_p.add_argument(
        "--with-findings",
        action="store_true",
        help="layer bold/rubric WARNING findings on the structure view; a display choice, always counted either way",
    )
    outline_p.add_argument(
        "--outline-depth",
        type=int,
        default=None,
        metavar="N",
        help="show only entries at nesting depth <= N; hidden entries are counted, never silently dropped",
    )
    outline_p.add_argument(
        "--sections-only",
        action="store_true",
        help="show only headings, every leaf kind hidden regardless of depth; composes with --outline-depth",
    )
    _add_no_toctree_flag(outline_p)
    _add_max_output_lines(outline_p)
    outline_p.set_defaults(**_CLI_ATTR_DEFAULTS)
    outline_p.set_defaults(outline=True)

    diff_json_p = sub.add_parser(
        "diff-json",
        help="semantic diff between two --format=json dumps",
        description=(
            "Semantic diff between two check --format=json dumps, matched by (severity, text), "
            "never by line number. Self-contained: no RST read, no other flags apply."
        ),
        epilog=_DOCUMENTATION_EPILOG,
    )
    diff_json_p.add_argument("old", metavar="OLD.json")
    diff_json_p.add_argument("new", metavar="NEW.json")
    diff_json_p.set_defaults(**_CLI_ATTR_DEFAULTS)

    refs_p = sub.add_parser(
        "refs",
        help="per-file :doc:/:ref: reference report",
        description=(
            "Reader role: this file's outgoing targets and every other file's incoming reference "
            "to it, from the live Sphinx environment, never objects.inv. Requires --sphinx-src."
        ),
        epilog=_DOCUMENTATION_EPILOG,
    )
    refs_p.add_argument("file", type=pathlib.Path, metavar="FILE")
    refs_p.set_defaults(**_CLI_ATTR_DEFAULTS)

    context_p = sub.add_parser(
        "context",
        help="targeted pre-edit briefing for one entry",
        description=(
            "Reader role: a pre-edit briefing for one exact entry — a stable id, a generated "
            "selector, or an exact title/term/preview. Never guesses among multiple exact matches."
        ),
        epilog=_DOCUMENTATION_EPILOG,
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
            "Modifier role: convert eligible grid/simple tables to .. list-table:: syntax. "
            "Default bulk conversion resolves nested tables ancestor-first; merged cells remain "
            "unchanged. Every candidate and combined write is gated by whole-file tree equality. "
            "Runs in bare Docutils mode; Sphinx mode is not used. N counts every table shown by "
            "outline. Dry-run returns 1 when files would change; --apply returns 1 only on errors."
        ),
        epilog=_DOCUMENTATION_EPILOG,
    )
    list_table_p.set_defaults(**_CLI_ATTR_DEFAULTS)

    hierarchy_p = sub.add_parser(
        "hierarchy",
        help="print the live adornment-character hierarchy",
        description="Print the complete adornment ranking used by checks and fixes for this Docutils runtime.",
        epilog=_DOCUMENTATION_EPILOG,
    )
    hierarchy_p.set_defaults(**_CLI_ATTR_DEFAULTS)

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


def _validate_hierarchy_args(args: argparse.Namespace) -> None:
    """hierarchy reports runtime constants and never selects a project."""
    active = [
        flag
        for flag, value in (
            ("--config", args.config),
            ("--no-config", args.no_config),
            ("--sphinx-src", args.sphinx_src),
            ("--build-dir", args.build_dir),
        )
        if value is not None and value is not False
    ]
    if active:
        _cli_fail(f"hierarchy is self-contained — incompatible argument(s): {', '.join(active)}")


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
        for flag, value in (
            ("--sphinx-src", args.sphinx_src),
            ("--build-dir", args.build_dir),
        )
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
    elif args.command == "hierarchy":
        _validate_hierarchy_args(args)
    elif args.command == "list-table":
        _validate_list_table_args(args)

    if args.diff_json is not None:
        _run_diff_json(args)
    if args.command == "hierarchy":
        _run_hierarchy()

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
