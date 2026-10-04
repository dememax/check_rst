# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Verify that a wheel contains exactly the package Python sources — check_rst project

from __future__ import annotations

import argparse
import pathlib
import zipfile


def _python_sources(root: pathlib.Path) -> set[str]:
    return {f"{root.name}/{path.relative_to(root).as_posix()}" for path in root.rglob("*.py")}


def verify(wheel: pathlib.Path, source: pathlib.Path) -> list[str]:
    """Return mismatches between package sources and wheel Python modules."""
    expected = _python_sources(source)
    with zipfile.ZipFile(wheel) as archive:
        prefix = f"{source.name}/"
        actual = {name for name in archive.namelist() if name.startswith(prefix) and name.endswith(".py")}
    problems = [f"unexpected wheel module: {name}" for name in sorted(actual - expected)]
    problems.extend(f"missing wheel module: {name}" for name in sorted(expected - actual))
    return problems


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=pathlib.Path)
    parser.add_argument("--source", type=pathlib.Path, default=pathlib.Path("src/check_rst"))
    args = parser.parse_args()
    problems = verify(args.wheel, args.source)
    if problems:
        parser.exit(1, "\n".join(problems) + "\n")
    print(f"wheel contents match {args.source}")


if __name__ == "__main__":
    main()
