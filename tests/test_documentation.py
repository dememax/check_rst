# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Documentation build and source-distribution regression tests — check_rst project
"""Verify that installed-user documentation remains buildable and distributable."""

from __future__ import annotations

import runpy
import shutil
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = PROJECT_ROOT / "docs"
DOCUMENTATION_URL = "https://github.com/dememax/check_rst/blob/main/docs/guide.rst"
EXPECTED_MAN_PAGES = {
    "check_rst": 1,
    "check_rst-check": 1,
    "check_rst-diff": 1,
    "check_rst-fix": 1,
    "check_rst-hierarchy": 1,
    "check_rst-list-table": 1,
    "check_rst-outline": 1,
    "check_rst-reports": 1,
    "check_rst-config": 5,
    "check_rst-json": 5,
    "check_rst-formats": 7,
    "check_rst-rules": 7,
    "check_rst-workflow": 7,
}


@pytest.fixture(scope="module")
def built_man_pages(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("sphinx-man")
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
            str(output),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return output


@pytest.mark.integration
def test_man_page_registry_names_every_canonical_source() -> None:
    config: dict[str, Any] = runpy.run_path(str(DOCS_DIR / "conf.py"))
    registered = {target: section for _source, target, _description, _authors, section in config["man_pages"]}

    assert registered == EXPECTED_MAN_PAGES
    for source, target, _description, authors, section in config["man_pages"]:
        assert (DOCS_DIR / f"{source}.rst").is_file()
        assert authors == ["Maxime P. DEMENTYEV"]
        assert section == EXPECTED_MAN_PAGES[target]


@pytest.mark.integration
def test_sphinx_man_builder_produces_terminal_manuals(built_man_pages: Path) -> None:
    generated = {path.name for path in built_man_pages.iterdir() if path.is_file()}
    assert generated == {f"{name}.{section}" for name, section in EXPECTED_MAN_PAGES.items()}

    for name, section in EXPECTED_MAN_PAGES.items():
        roff = (built_man_pages / f"{name}.{section}").read_text(encoding="utf-8")
        assert '.TH "' in roff
        assert "Man page generated from reStructuredText" in roff
        assert ":doc:`" not in roff
        assert ".. code-block::" not in roff


@pytest.mark.unit
def test_packaging_metadata_exposes_the_canonical_guide() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]

    assert project["urls"]["Documentation"] == DOCUMENTATION_URL


@pytest.mark.integration
def test_source_distribution_contains_manual_sources(tmp_path: Path) -> None:
    source = tmp_path / "source"
    shutil.copytree(
        PROJECT_ROOT,
        source,
        ignore=shutil.ignore_patterns(".git", ".mypy_cache", ".pytest_cache", "__pycache__"),
    )
    dist = tmp_path / "dist"
    script = "import setuptools.build_meta as backend, sys; print(backend.build_sdist(sys.argv[1]))"
    result = subprocess.run(
        [sys.executable, "-c", script, str(dist)],
        cwd=source,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    archives = list(dist.glob("*.tar.gz"))
    assert len(archives) == 1
    with tarfile.open(archives[0], "r:gz") as archive:
        members = {Path(name) for name in archive.getnames()}

    def contains(suffix: Path) -> bool:
        return any(member.parts[1:] == suffix.parts for member in members)

    assert contains(Path("docs/conf.py"))
    assert contains(Path("docs/guide.rst"))
    assert contains(Path("docs/man/check_rst.rst"))
    assert contains(Path("docs/man/check_rst-formats.rst"))
    assert contains(Path("tests/fixtures/combined_sphinx/.check_rst.toml"))
    assert contains(Path("tests/fixtures/combined_sphinx/guide.rst"))
