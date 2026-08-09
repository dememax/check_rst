# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Registry-driven Sphinx manual builder and installer — check_rst project
"""Build and install every manual page registered by ``docs/conf.py``."""

from __future__ import annotations

import argparse
import dataclasses
import os
import pathlib
import runpy
import shutil
import subprocess
import sys
import tempfile
from typing import Any

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS_DIR = PROJECT_ROOT / "docs"
DEFAULT_BUILD_DIR = DOCS_DIR / "_build" / "man"


class InstallError(RuntimeError):
    """A cleanly reportable build, registry, or installation failure."""


@dataclasses.dataclass(frozen=True, slots=True)
class ManualPage:
    """The installation-relevant fields of one Sphinx man_pages entry."""

    source: str
    target: str
    section: int

    @property
    def filename(self) -> str:
        return f"{self.target}.{self.section}"


def _load_registry() -> list[ManualPage]:
    """Load and validate the canonical Sphinx manual-page registry."""
    config: dict[str, Any] = runpy.run_path(str(DOCS_DIR / "conf.py"))
    raw_pages = config.get("man_pages")
    if not isinstance(raw_pages, list):
        raise InstallError("docs/conf.py: man_pages must be a list")

    pages: list[ManualPage] = []
    filenames: set[str] = set()
    for index, raw_page in enumerate(raw_pages, 1):
        if not isinstance(raw_page, tuple) or len(raw_page) != 5:
            raise InstallError(f"docs/conf.py: man_pages entry {index} must be a 5-item tuple")
        source, target, description, authors, section = raw_page
        if not isinstance(source, str) or not isinstance(target, str):
            raise InstallError(f"docs/conf.py: man_pages entry {index} source and target must be strings")
        if (
            not isinstance(description, str)
            or not isinstance(authors, list)
            or not all(isinstance(author, str) for author in authors)
        ):
            raise InstallError(f"docs/conf.py: man_pages entry {index} has invalid description or authors")
        if not isinstance(section, int) or isinstance(section, bool) or section < 1:
            raise InstallError(f"docs/conf.py: man_pages entry {index} section must be a positive integer")
        if pathlib.PurePath(target).name != target:
            raise InstallError(f"docs/conf.py: man_pages entry {index} target must be a basename")
        if not (DOCS_DIR / f"{source}.rst").is_file():
            raise InstallError(f"docs/conf.py: manual source does not exist: {source}.rst")

        page = ManualPage(source=source, target=target, section=section)
        if page.filename in filenames:
            raise InstallError(f"docs/conf.py: duplicate generated manual name: {page.filename}")
        filenames.add(page.filename)
        pages.append(page)

    if not pages:
        raise InstallError("docs/conf.py: man_pages is empty")
    return pages


def _absolute_path(path: pathlib.Path, option: str) -> pathlib.Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        raise InstallError(f"{option} must be an absolute path: {path}")
    return expanded


def _installation_prefix(prefix: pathlib.Path, destdir: pathlib.Path | None) -> pathlib.Path:
    """Apply packaging-style DESTDIR without discarding the absolute prefix."""
    prefix = _absolute_path(prefix, "--prefix")
    if destdir is None:
        return prefix
    destination_root = _absolute_path(destdir, "--destdir")
    return destination_root.joinpath(*prefix.parts[1:])


def _build_pages(build_dir: pathlib.Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sphinx",
            "-W",
            "--keep-going",
            "-b",
            "man",
            str(DOCS_DIR),
            str(build_dir),
        ],
        cwd=PROJECT_ROOT,
        check=False,
    )
    if result.returncode:
        raise InstallError(f"Sphinx man build failed with status {result.returncode}")


def _install_atomically(source: pathlib.Path, destination: pathlib.Path) -> None:
    """Replace one generated page without exposing a partially copied file."""
    destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_stream:
            shutil.copyfileobj(input_stream, output)
        temporary.chmod(0o644)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _install_pages(
    pages: list[ManualPage],
    build_dir: pathlib.Path,
    man_root: pathlib.Path,
) -> None:
    generated_pages = [(page, build_dir / page.filename) for page in pages]
    for _page, generated in generated_pages:
        if not generated.is_file():
            raise InstallError(f"generated manual page is missing: {generated}")

    for page, generated in generated_pages:
        destination = man_root / f"man{page.section}" / page.filename
        _install_atomically(generated, destination)
        print(f"installed {page.filename} -> {destination}")


def _update_index(man_root: pathlib.Path) -> None:
    makewhatis = shutil.which("makewhatis")
    if makewhatis is not None:
        command = [makewhatis, str(man_root)]
    else:
        mandb = shutil.which("mandb")
        if mandb is None:
            print("install_man_pages: no makewhatis or mandb found; manual index not updated", file=sys.stderr)
            return
        command = [mandb, "-q", str(man_root)]

    result = subprocess.run(command, check=False)
    if result.returncode:
        raise InstallError(f"manual index command failed with status {result.returncode}: {command[0]}")
    print(f"updated manual index: {man_root}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and install the manual pages registered in docs/conf.py.",
    )
    parser.add_argument(
        "--prefix",
        type=pathlib.Path,
        default=pathlib.Path("/usr/local"),
        help="installation prefix; default /usr/local (use ~/opt for a private installation)",
    )
    parser.add_argument(
        "--destdir",
        type=pathlib.Path,
        help="stage below DESTDIR while retaining PREFIX, for distribution packaging",
    )
    parser.add_argument(
        "--build-dir",
        type=pathlib.Path,
        default=DEFAULT_BUILD_DIR,
        help=f"Sphinx man output directory; default {DEFAULT_BUILD_DIR}",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="install already-generated pages from --build-dir",
    )
    parser.add_argument(
        "--no-index",
        action="store_true",
        help="do not run makewhatis or mandb after a live installation",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        pages = _load_registry()
        build_dir = args.build_dir.expanduser().resolve()
        if not args.skip_build:
            _build_pages(build_dir)

        install_prefix = _installation_prefix(args.prefix, args.destdir)
        man_root = install_prefix / "share" / "man"
        _install_pages(pages, build_dir, man_root)
        staged = f" (staged under {_absolute_path(args.destdir, '--destdir')})" if args.destdir is not None else ""
        print(f"installed {len(pages)} manual page(s) under {man_root}{staged}")

        if args.destdir is not None:
            print("manual index skipped for DESTDIR staging")
        elif args.no_index:
            print("manual index skipped by --no-index")
        else:
            _update_index(man_root)
    except (InstallError, OSError) as exc:
        print(f"install_man_pages: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
