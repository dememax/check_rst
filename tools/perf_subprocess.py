# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Isolated CLI runner that exports structural call counts — check_rst project
"""Invoke the worktree CLI and persist its in-process ``CALL_COUNTS``."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

from check_rst.cli import _helpers
from check_rst.cli import main as check_rst_main


def _write_counts(path: pathlib.Path) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(sorted(_helpers.CALL_COUNTS.items())), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run check_rst and export CALL_COUNTS.")
    parser.add_argument("--counts-file", required=True, type=pathlib.Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(arguments)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a check_rst command is required after --")

    _helpers.CALL_COUNTS.clear()
    previous_argv = sys.argv
    sys.argv = ["check_rst", *command]
    exit_status = 0
    try:
        try:
            check_rst_main()
        except SystemExit as exc:
            exit_status = exc.code if isinstance(exc.code, int) else 1
    finally:
        sys.argv = previous_argv
        _write_counts(args.counts_file)
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main())
