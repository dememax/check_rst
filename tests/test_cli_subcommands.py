# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Isolated argparse-subcommand builder tests — check_rst project
"""Tests for the subcommand CLI redesign's parser, built and exercised in
isolation from ``_main()`` — see docs/roadmap.rst, "Subcommands: flag-soup
incompatibilities become verbs".

Staged per the approved plan: each stage adds verbs to the same
``_build_cli_parser()``/``_backfill_post_parse()`` pair and tests them here,
fully unwired from ``_main()`` until the cutover stage. This file exercises
``Namespace`` shape and malformed-argv rejection directly against the parser
builder — it does not call ``cli.main()`` and does not touch the
existing flat-CLI test suite in test_check_rst.py.

Stage 1 covers Tier 2 (the three self-contained verbs: diff-json, refs,
context) — highest confidence, fully isolated from every open fork.
"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

import pytest

from check_rst import cli

if TYPE_CHECKING:
    import argparse

# The complete cross-pipeline attribute contract every subcommand's Namespace
# must satisfy after _backfill_post_parse — see cli.py's _main() body, which
# reads each of these at least once across check/fix/diff/outline/context/
# refs/diff-json combined.
_FULL_ATTR_CONTRACT = frozenset(
    {
        "build_dir",
        "collapse_title_spaces",
        "config",
        "context",
        "diff",
        "diff_json",
        "diff_only",
        "exclude",
        "files",
        "fix",
        "fix_only",
        "git_scope",
        "json",
        "max_output_lines",
        "no_adornments",
        "no_config",
        "no_directives",
        "no_toctree",
        "no_warnings",
        "normalize_blank_lines",
        "outline",
        "outline_depth",
        "outline_only",
        "quiet",
        "recursive",
        "refs",
        "sections_only",
        "single_space_prose",
        "skip_fixable",
        "sphinx_src",
        "verbose",
        "word_samples",
    }
)


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = cli._build_cli_parser()
    args = parser.parse_args(argv)
    cli._backfill_post_parse(args)
    return args


@pytest.mark.unit
def test_diff_json_verb_populates_full_attribute_contract() -> None:
    args = _parse(["diff-json", "old.json", "new.json"])
    assert args.command == "diff-json"
    assert vars(args).keys() >= _FULL_ATTR_CONTRACT
    assert args.diff_json == ["old.json", "new.json"]
    assert args.files == []


@pytest.mark.unit
def test_hierarchy_verb_is_self_contained() -> None:
    args = _parse(["hierarchy"])
    assert args.command == "hierarchy"
    assert vars(args).keys() >= _FULL_ATTR_CONTRACT
    assert args.files == []


@pytest.mark.unit
def test_hierarchy_allows_no_config() -> None:
    """Same reasoning as test_diff_json_allows_no_config: --no-config asks
    the tool NOT to do something hierarchy was never going to do anyway
    (read a project config) — a harmless no-op, not an incompatible
    combination worth rejecting. Was inconsistent with diff-json's own,
    already-tested conclusion until this fix."""
    args = _parse(["--no-config", "hierarchy"])
    cli._validate_hierarchy_args(args)  # must not raise


@pytest.mark.unit
def test_diff_json_verb_requires_exactly_two_positionals() -> None:
    parser = cli._build_cli_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["diff-json", "old.json"])
    assert exc.value.code == 2


@pytest.mark.unit
def test_refs_verb_populates_full_attribute_contract() -> None:
    args = _parse(["--sphinx-src", "docs", "refs", "file.rst"])
    assert args.command == "refs"
    assert vars(args).keys() >= _FULL_ATTR_CONTRACT
    assert args.refs == pathlib.Path("file.rst")
    assert args.sphinx_src == pathlib.Path("docs")
    assert args.files == []
    # refs never carried --quiet/--recursive/etc. even before this redesign —
    # confirm they're still absent from the parser, not silently accepted.
    with pytest.raises(SystemExit) as exc:
        cli._build_cli_parser().parse_args(["refs", "--quiet", "file.rst"])
    assert exc.value.code == 2


@pytest.mark.unit
def test_refs_verb_requires_exactly_one_positional() -> None:
    parser = cli._build_cli_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["refs"])
    assert exc.value.code == 2


@pytest.mark.unit
def test_context_verb_populates_full_attribute_contract() -> None:
    args = _parse(["context", "some-entry", "file.rst"])
    assert args.command == "context"
    assert vars(args).keys() >= _FULL_ATTR_CONTRACT
    assert args.context == "some-entry"
    assert args.files == [pathlib.Path("file.rst")]
    assert args.quiet is True  # forced, same as today's --context behavior


@pytest.mark.unit
def test_context_verb_requires_both_positionals() -> None:
    parser = cli._build_cli_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["context", "only-entry"])
    assert exc.value.code == 2


@pytest.mark.unit
def test_context_verb_rejects_empty_entry() -> None:
    args = _parse(["context", "  ", "file.rst"])
    with pytest.raises(SystemExit) as exc:
        cli._validate_context_args(args)
    assert exc.value.code == 1


@pytest.mark.unit
def test_context_verb_carries_no_toctree() -> None:
    args = _parse(["context", "entry", "--no-toctree", "file.rst"])
    assert args.no_toctree is True


# ---------------------------------------------------------------------------
# Stage 2 — Tier 1 mode verbs: check, fix, diff.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_check_verb_populates_full_attribute_contract() -> None:
    args = _parse(["check", "file.rst"])
    assert args.command == "check"
    assert vars(args).keys() >= _FULL_ATTR_CONTRACT
    assert args.files == [pathlib.Path("file.rst")]
    assert args.format == "text"
    assert args.json is False
    assert args.fix is False
    assert args.diff is False


@pytest.mark.unit
def test_check_verb_format_json_backfills_json_flag() -> None:
    args = _parse(["check", "--format", "json", "file.rst"])
    assert args.json is True


@pytest.mark.unit
def test_check_verb_carries_scope_and_budget_flags() -> None:
    args = _parse(
        [
            "check",
            "--recursive",
            "--exclude",
            "*.gen.rst",
            "--max-output-lines",
            "5",
            "docs",
        ],
    )
    assert args.recursive is True
    assert args.exclude == ["*.gen.rst"]
    assert args.max_output_lines == 5
    assert args.files == [pathlib.Path("docs")]


@pytest.mark.unit
def test_check_verb_has_no_mutating_flags() -> None:
    parser = cli._build_cli_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["check", "--normalize-blank-lines", "file.rst"])
    assert exc.value.code == 2


@pytest.mark.unit
def test_fix_verb_populates_full_attribute_contract() -> None:
    args = _parse(["fix", "file.rst"])
    assert args.command == "fix"
    assert vars(args).keys() >= _FULL_ATTR_CONTRACT
    assert args.fix is True
    assert args.fix_only is False
    assert args.diff is False


@pytest.mark.unit
def test_fix_fast_backfills_fix_only() -> None:
    args = _parse(["fix", "--fast"])
    assert args.fix is True
    assert args.fix_only is True


@pytest.mark.unit
def test_fix_fast_allows_verbose_and_max_output_lines() -> None:
    args = _parse(["fix", "--fast", "--verbose", "--max-output-lines", "5"])
    cli._validate_fast_allowlist(args, "fix")  # must not raise


@pytest.mark.unit
def test_fix_fast_rejects_sphinx_src() -> None:
    args = _parse(["--sphinx-src", "docs", "fix", "--fast"])
    with pytest.raises(SystemExit) as exc:
        cli._validate_fast_allowlist(args, "fix")
    assert exc.value.code == 1


@pytest.mark.unit
@pytest.mark.parametrize("verb", ["fix", "diff"])
def test_fast_allows_no_config(verb: str) -> None:
    """--no-config is --config's semantic sibling (same project-identity
    category, same rooting-of-Git-selection rationale) — allowed in the
    same allowlist --config is already in, not rejected as if it were an
    unrelated, Sphinx-mode-only flag."""
    args = _parse(["--no-config", verb, "--fast"])
    cli._validate_fast_allowlist(args, verb)  # must not raise


@pytest.mark.unit
def test_fix_fast_rejects_editorial_flags() -> None:
    """--normalize-blank-lines/--collapse-title-spaces/--single-space-prose
    all require full parsing, exactly like today's --fix-only rejection."""
    args = _parse(["fix", "--fast", "--normalize-blank-lines"])
    with pytest.raises(SystemExit) as exc:
        cli._validate_fast_allowlist(args, "fix")
    assert exc.value.code == 1


@pytest.mark.unit
def test_diff_verb_populates_full_attribute_contract() -> None:
    args = _parse(["diff", "file.rst"])
    assert args.command == "diff"
    assert vars(args).keys() >= _FULL_ATTR_CONTRACT
    assert args.diff is True
    assert args.diff_only is False
    assert args.fix is False


@pytest.mark.unit
def test_diff_fast_backfills_diff_only() -> None:
    args = _parse(["diff", "--fast"])
    assert args.diff is True
    assert args.diff_only is True


@pytest.mark.unit
def test_diff_fast_rejects_verbose_unlike_fix_fast() -> None:
    """Preserves today's exact asymmetry: --diff-only's allowlist excludes
    verbose/max-output-lines, --fix-only's includes them."""
    args = _parse(["diff", "--fast", "--verbose"])
    with pytest.raises(SystemExit) as exc:
        cli._validate_fast_allowlist(args, "diff")
    assert exc.value.code == 1


@pytest.mark.unit
def test_diff_verb_has_no_max_output_lines() -> None:
    """--max-output-lines is incompatible with ordinary --diff too, not only
    --diff-only (cli.py's _validate_cli_args, args.diff is in the
    incompatible-mode tuple) — so diff's parser never defines the flag."""
    parser = cli._build_cli_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["diff", "--max-output-lines", "5", "file.rst"])
    assert exc.value.code == 2


@pytest.mark.unit
@pytest.mark.parametrize("verb", ["check", "fix", "diff"])
def test_full_scope_rejects_exclude_without_recursive(verb: str) -> None:
    args = _parse([verb, "--exclude", "*.gen.rst", "file.rst"])
    with pytest.raises(SystemExit) as exc:
        cli._validate_full_scope_args(args)
    assert exc.value.code == 1


@pytest.mark.unit
def test_full_scope_rejects_git_scope_with_recursive() -> None:
    args = _parse(["check", "--git-scope", "--recursive", "docs"])
    with pytest.raises(SystemExit) as exc:
        cli._validate_full_scope_args(args)
    assert exc.value.code == 1


@pytest.mark.unit
def test_full_scope_rejects_git_scope_without_files() -> None:
    args = _parse(["check", "--git-scope"])
    with pytest.raises(SystemExit) as exc:
        cli._validate_full_scope_args(args)
    assert exc.value.code == 1


@pytest.mark.unit
def test_full_scope_allows_git_scope_with_files() -> None:
    args = _parse(["check", "--git-scope", "file.rst"])
    cli._validate_full_scope_args(args)  # must not raise


# ---------------------------------------------------------------------------
# Stage 3 — outline's inverted default, and check's --format/--no-toctree
# interaction.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_outline_verb_default_is_structure_only() -> None:
    """Decision 3: bare `outline FILE` inverts today's default — structure
    only, same as today's --outline-only, not today's combined --outline."""
    args = _parse(["outline", "file.rst"])
    assert args.command == "outline"
    assert vars(args).keys() >= _FULL_ATTR_CONTRACT
    assert args.outline is True
    assert args.outline_only is True
    assert args.files == [pathlib.Path("file.rst")]


@pytest.mark.unit
def test_outline_with_findings_opts_into_combined_view() -> None:
    args = _parse(["outline", "--with-findings", "file.rst"])
    assert args.outline is True
    assert args.outline_only is False


@pytest.mark.unit
def test_outline_verb_carries_depth_sections_toctree_and_budget_flags() -> None:
    args = _parse(
        [
            "outline",
            "--outline-depth",
            "3",
            "--sections-only",
            "--no-toctree",
            "--max-output-lines",
            "5",
            "file.rst",
        ],
    )
    assert args.outline_depth == 3
    assert args.sections_only is True
    assert args.no_toctree is True
    assert args.max_output_lines == 5


@pytest.mark.unit
@pytest.mark.parametrize("depth", [0, -1])
def test_outline_depth_rejects_below_one(depth: int) -> None:
    args = _parse(["outline", "--outline-depth", str(depth), "file.rst"])
    with pytest.raises(SystemExit) as exc:
        cli._validate_outline_args(args)
    assert exc.value.code == 1


@pytest.mark.unit
def test_outline_depth_one_is_allowed() -> None:
    args = _parse(["outline", "--outline-depth", "1", "file.rst"])
    cli._validate_outline_args(args)  # must not raise


@pytest.mark.unit
def test_check_no_toctree_requires_format_json() -> None:
    args = _parse(["check", "--no-toctree", "file.rst"])
    with pytest.raises(SystemExit) as exc:
        cli._validate_check_args(args)
    assert exc.value.code == 1


@pytest.mark.unit
def test_check_no_toctree_allowed_with_format_json() -> None:
    args = _parse(["check", "--format", "json", "--no-toctree", "file.rst"])
    cli._validate_check_args(args)  # must not raise


@pytest.mark.unit
def test_check_max_output_lines_incompatible_with_format_json() -> None:
    args = _parse(["check", "--format", "json", "--max-output-lines", "5", "file.rst"])
    with pytest.raises(SystemExit) as exc:
        cli._validate_check_args(args)
    assert exc.value.code == 1


@pytest.mark.unit
def test_check_max_output_lines_allowed_in_text_format() -> None:
    args = _parse(["check", "--max-output-lines", "5", "file.rst"])
    cli._validate_check_args(args)  # must not raise


# ---------------------------------------------------------------------------
# Global options: --config/--no-config/--sphinx-src/--build-dir moved to the
# main parser (git-style: before the verb), stage 6 of the approved plan —
# see docs/roadmap.rst, "Subcommands: flag-soup incompatibilities become
# verbs". RED motivation: argparse's _SubParsersAction.__call__ parses each
# subparser into a *fresh* Namespace, then unconditionally copies every one
# of its keys back onto the parent — no hasattr guard at that merge step.
# Leaving these four names in _CLI_ATTR_DEFAULTS (so every subparser's own
# set_defaults() call still defines them) silently resets them to their
# None/False defaults after the merge, clobbering whatever the main parser
# already parsed. These tests pin the fix: the four names must be absent
# from _CLI_ATTR_DEFAULTS, and a global flag's value must survive an
# arbitrary verb dispatch.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cli_attr_defaults_excludes_global_project_flags() -> None:
    """The clobber precondition: if any of these four reappear in
    _CLI_ATTR_DEFAULTS, every subparser's set_defaults() call defines them
    again, and _SubParsersAction's unconditional merge resets them after
    the main parser already parsed the user's global value."""
    assert not ({"config", "no_config", "sphinx_src", "build_dir"} & cli._CLI_ATTR_DEFAULTS.keys())


@pytest.mark.unit
@pytest.mark.parametrize("verb", ["check", "fix", "diff", "outline", "refs", "context"])
def test_global_sphinx_src_survives_verb_dispatch(verb: str) -> None:
    """Direct regression for the clobber bug: --sphinx-src, placed before
    the verb, must still be set after the subparser merge, for every verb
    that can read it."""
    tail = {
        "refs": ["file.rst"],
        "context": ["entry", "file.rst"],
    }.get(verb, ["file.rst"])
    args = _parse(["--sphinx-src", "docs", verb, *tail])
    assert args.sphinx_src == pathlib.Path("docs")


@pytest.mark.unit
def test_global_project_flags_rejected_after_verb() -> None:
    """--sphinx-src no longer has a home on any subparser — placed after
    the verb, argparse must reject it as unrecognized, not silently accept
    a now-orphaned flag."""
    parser = cli._build_cli_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["check", "--sphinx-src", "docs", "file.rst"])
    assert exc.value.code == 2


@pytest.mark.unit
def test_no_config_survives_verb_dispatch() -> None:
    args = _parse(["--no-config", "check", "file.rst"])
    assert args.no_config is True


@pytest.mark.unit
def test_no_config_rejects_explicit_config() -> None:
    args = _parse(["--no-config", "--config", "x.toml", "check", "file.rst"])
    with pytest.raises(SystemExit) as exc:
        cli._validate_config_flags(args)
    assert exc.value.code == 1


@pytest.mark.unit
def test_config_alone_passes_config_flags_validation() -> None:
    args = _parse(["--config", "x.toml", "check", "file.rst"])
    cli._validate_config_flags(args)  # must not raise


@pytest.mark.unit
@pytest.mark.parametrize("flag", ["--config", "--sphinx-src", "--build-dir"])
def test_diff_json_rejects_each_global_project_flag(flag: str) -> None:
    args = _parse([flag, "x", "diff-json", "old.json", "new.json"])
    with pytest.raises(SystemExit) as exc:
        cli._validate_diff_json_args(args)
    assert exc.value.code == 1


@pytest.mark.unit
def test_diff_json_allows_no_config() -> None:
    """--no-config asks the tool NOT to do something diff-json was never
    going to do anyway (read a project config) — a harmless no-op, not an
    incompatible combination worth rejecting."""
    args = _parse(["--no-config", "diff-json", "old.json", "new.json"])
    cli._validate_diff_json_args(args)  # must not raise


# ---------------------------------------------------------------------------
# list-table verb (docs/roadmap.rst, "Targeted aligned-table to list-table
# transformation") — narrower shape than check/fix/diff/outline: files +
# scope flags (--recursive/--git-scope/--exclude) + --quiet, plus its own
# --apply/--only/--skip. No report-filter or --word-samples flags — this
# verb runs no Phase 1 lint pass of its own. --sphinx-src/--build-dir are
# rejected (verified Sphinx mode is irrelevant to a bare-docutils source
# transformation, the same fail-loudly precedent as diff-json rejecting
# them); --config stays available since it still roots project/Git-scope
# discovery for this verb's own --recursive/--git-scope.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_table_verb_populates_full_attribute_contract() -> None:
    args = _parse(["list-table", "file.rst"])
    assert args.command == "list-table"
    assert vars(args).keys() >= _FULL_ATTR_CONTRACT
    assert args.files == [pathlib.Path("file.rst")]
    assert args.only == []
    assert args.skip == []
    assert args.apply is False


@pytest.mark.unit
def test_list_table_only_and_skip_repeatable() -> None:
    args = _parse(
        ["list-table", "--only", "1", "--only", "3", "--skip", "2", "file.rst"],
    )
    assert args.only == [1, 3]
    assert args.skip == [2]


@pytest.mark.unit
def test_list_table_carries_scope_flags() -> None:
    args = _parse(["list-table", "--recursive", "--exclude", "*.gen.rst", "docs"])
    assert args.recursive is True
    assert args.exclude == ["*.gen.rst"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "flag",
    [
        "--no-warnings",
        "--skip-fixable",
        "--no-adornments",
        "--no-directives",
        "--word-samples",
    ],
)
def test_list_table_has_no_report_filter_flags(flag: str) -> None:
    parser = cli._build_cli_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(
            ["list-table", flag, "1", "file.rst"] if flag == "--word-samples" else ["list-table", flag, "file.rst"]
        )
    assert exc.value.code == 2


@pytest.mark.unit
@pytest.mark.parametrize("flag", ["--sphinx-src", "--build-dir"])
def test_list_table_rejects_sphinx_mode_flags(flag: str) -> None:
    args = _parse([flag, "docs", "list-table", "file.rst"])
    with pytest.raises(SystemExit) as exc:
        cli._validate_list_table_args(args)
    assert exc.value.code == 1


@pytest.mark.unit
def test_list_table_allows_config() -> None:
    args = _parse(["--config", "x.toml", "list-table", "file.rst"])
    cli._validate_list_table_args(args)  # must not raise


@pytest.mark.unit
def test_list_table_quiet_help_matches_shared_wording() -> None:
    """list-table's --quiet used to be redeclared inline in
    _build_list_table_parent with independently-editable, already-drifted
    wording ("...summary line still prints" vs. the shared helper's
    "...summary line still print"). Both parsers must now source the exact
    same string, not two copies that can drift again."""
    shared_help = next(a for a in cli._build_full_parent()._actions if "--quiet" in a.option_strings).help
    list_table_help = next(a for a in cli._build_list_table_parent()._actions if "--quiet" in a.option_strings).help
    assert shared_help == list_table_help


@pytest.mark.unit
def test_top_level_help_mentions_report_length_limiting() -> None:
    """--max-output-lines lives only on check/fix/outline's own --help
    (docs/roadmap.rst's "full" shape minus diff) and was previously
    undiscoverable from bare `check_rst --help` — a one-line pointer on the
    top-level page is enough for a reader to know to look further."""
    assert "--max-output-lines" in cli._TOP_LEVEL_HELP
