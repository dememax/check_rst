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
builder — it does not call ``check_rst.main()`` and does not touch the
existing flat-CLI test suite in test_check_rst.py.

Stage 1 covers Tier 2 (the three self-contained verbs: diff-json, refs,
context) — highest confidence, fully isolated from every open fork.
"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    import argparse
    import types

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


@pytest.fixture(scope="session")
def check_rst() -> types.ModuleType:
    """Return the installed-layout implementation module once per session."""
    from check_rst import cli

    return cli


def _parse(check_rst: types.ModuleType, argv: list[str]) -> argparse.Namespace:
    parser = check_rst._build_cli_parser()
    args = parser.parse_args(argv)
    check_rst._backfill_post_parse(args)
    return cast("argparse.Namespace", args)


@pytest.mark.unit
def test_diff_json_verb_populates_full_attribute_contract(check_rst: types.ModuleType) -> None:
    args = _parse(check_rst, ["diff-json", "old.json", "new.json"])
    assert args.command == "diff-json"
    assert vars(args).keys() >= _FULL_ATTR_CONTRACT
    assert args.diff_json == ["old.json", "new.json"]
    assert args.files == []


@pytest.mark.unit
def test_diff_json_verb_requires_exactly_two_positionals(check_rst: types.ModuleType) -> None:
    parser = check_rst._build_cli_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["diff-json", "old.json"])
    assert exc.value.code == 2


@pytest.mark.unit
def test_refs_verb_populates_full_attribute_contract(check_rst: types.ModuleType) -> None:
    args = _parse(check_rst, ["refs", "--sphinx-src", "docs", "file.rst"])
    assert args.command == "refs"
    assert vars(args).keys() >= _FULL_ATTR_CONTRACT
    assert args.refs == pathlib.Path("file.rst")
    assert args.sphinx_src == pathlib.Path("docs")
    assert args.files == []
    # refs never carried --quiet/--recursive/etc. even before this redesign —
    # confirm they're still absent from the parser, not silently accepted.
    with pytest.raises(SystemExit) as exc:
        check_rst._build_cli_parser().parse_args(["refs", "--quiet", "file.rst"])
    assert exc.value.code == 2


@pytest.mark.unit
def test_refs_verb_requires_exactly_one_positional(check_rst: types.ModuleType) -> None:
    parser = check_rst._build_cli_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["refs"])
    assert exc.value.code == 2


@pytest.mark.unit
def test_context_verb_populates_full_attribute_contract(check_rst: types.ModuleType) -> None:
    args = _parse(check_rst, ["context", "some-entry", "file.rst"])
    assert args.command == "context"
    assert vars(args).keys() >= _FULL_ATTR_CONTRACT
    assert args.context == "some-entry"
    assert args.files == [pathlib.Path("file.rst")]
    assert args.quiet is True  # forced, same as today's --context behavior


@pytest.mark.unit
def test_context_verb_requires_both_positionals(check_rst: types.ModuleType) -> None:
    parser = check_rst._build_cli_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["context", "only-entry"])
    assert exc.value.code == 2


@pytest.mark.unit
def test_context_verb_rejects_empty_entry(check_rst: types.ModuleType) -> None:
    args = _parse(check_rst, ["context", "  ", "file.rst"])
    with pytest.raises(SystemExit) as exc:
        check_rst._validate_context_args(args)
    assert exc.value.code == 1


@pytest.mark.unit
def test_context_verb_carries_no_toctree(check_rst: types.ModuleType) -> None:
    args = _parse(check_rst, ["context", "entry", "--no-toctree", "file.rst"])
    assert args.no_toctree is True
