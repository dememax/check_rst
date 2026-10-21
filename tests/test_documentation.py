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
    "check_rst-entitle": 1,
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
def test_sphinx_config_reads_version_from_a_clean_source_checkout() -> None:
    """The docs build must not depend on check_rst already being installed.

    ``-I -S`` removes the working directory, PYTHONPATH, and site packages
    from module discovery.  What remains is exactly the source checkout that
    ``docs/conf.py`` can locate relative to itself.
    """
    script = "import runpy, sys; print(runpy.run_path(sys.argv[1])['release'])"
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", script, str(DOCS_DIR / "conf.py")],
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    metadata = runpy.run_path(str(PROJECT_ROOT / "src" / "check_rst" / "__init__.py"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == metadata["__version__"]


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


@pytest.mark.unit
def test_packaging_metadata_requires_the_supported_docutils_minor() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as stream:
        dependencies = tomllib.load(stream)["project"]["dependencies"]

    assert "docutils>=0.23,<0.24" in dependencies
    assert "Sphinx>=9.1,<10" in dependencies


@pytest.mark.unit
def test_release_docs_require_a_concrete_clean_export_build() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    releasing = (DOCS_DIR / "releasing.rst").read_text(encoding="utf-8")

    assert "git archive --prefix=check_rst/" in readme
    assert "pip wheel --wheel-dir dist ." not in readme
    assert "release_tree=$(mktemp -d)" in releasing
    assert 'git archive <release-commit> | tar -x -C "$release_tree"' in releasing


@pytest.mark.unit
def test_contract_version_and_next_minor_scope_are_documented() -> None:
    command_manual = (DOCS_DIR / "man" / "check_rst.rst").read_text(encoding="utf-8")
    roadmap = (DOCS_DIR / "roadmap.rst").read_text(encoding="utf-8")

    assert (
        "Increment it when a wrapper-visible command-line or JSON runtime contract becomes incompatible"
        in command_manual
    )
    for item in (
        "cross-path snapshot pairing",
        "JSON output for further commands",
        "list-table reflow",
        "byte-safe JSON path",
    ):
        assert item in roadmap


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
    assert contains(Path("tools/install_man_pages.py"))
    assert contains(Path("docs/man/check_rst-formats.rst"))
    assert contains(Path("tests/fixtures/combined_sphinx/.check_rst.toml"))
    assert contains(Path("tests/fixtures/combined_sphinx/guide.rst"))


def _quoted_hints(text: str, label: str) -> list[tuple[str, str]]:
    """Return (preceding line, joined hint text) for each "(label: ...)" quote."""
    lines = text.splitlines()
    quotes: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        if not line.strip().startswith(f"({label}: "):
            continue
        parts = [line.strip()]
        cursor = index
        while not parts[-1].endswith(")") and cursor + 1 < len(lines):
            cursor += 1
            parts.append(lines[cursor].strip())
        quotes.append((lines[index - 1].strip() if index else "", " ".join(parts)))
    return quotes


@pytest.mark.unit
def test_documented_finding_hints_match_real_output() -> None:
    """A finding's shared explanation is quoted in the docs as real output.

    It must be today's text, and it must follow a finding it explains,
    because the CLI prints it after the first such finding (CR-31).
    """
    from check_rst.cli._output import _FINDING_HINTS

    checked = 0
    for page in sorted(DOCS_DIR.rglob("*.rst")):
        text = page.read_text(encoding="utf-8")
        for label, hint in _FINDING_HINTS.values():
            for preceding, quote in _quoted_hints(text, label):
                checked += 1
                assert quote == f"({label}: {hint})", (page.name, quote)
                assert f": {label}" in preceding, (page.name, preceding)
    assert checked


@pytest.mark.unit
def test_guide_quotes_the_unseparated_title_remedy() -> None:
    """CR-46: the guide's two remedies stay identical to the compact text
    carried by parser-free and parser-backed findings."""
    from check_rst.cli._formatting import _UNSEPARATED_TITLE_REMEDY

    guide = _normalized_text(DOCS_DIR / "guide.rst")

    assert _UNSEPARATED_TITLE_REMEDY in guide
    assert "directly after a non-blank line that is not a bullet item" in guide
    assert "an enumerated item followed by an unindented line is ordinary text to Docutils" in guide


def _normalized_text(path: Path) -> str:
    """Return a document's text with line breaks folded into single spaces."""
    return " ".join(path.read_text(encoding="utf-8").split())


@pytest.mark.unit
def test_guide_defines_the_title_placeholder_as_check_rst_terminology() -> None:
    """CR-47: "placeholder" is check_rst's authoring convention, never a term of
    reStructuredText, Docutils or Sphinx.  Its first normative definition says
    so, and names what it declares and what fix computes."""
    guide = _normalized_text(DOCS_DIR / "guide.rst")

    assert "check_rst title placeholder" in guide
    assert "an authoring convention of check_rst, not a reStructuredText, Docutils or Sphinx term" in guide
    assert "declares the title's intended style while ``fix`` computes its geometry" in guide


@pytest.mark.unit
def test_guide_explains_title_styles_from_primary_sources() -> None:
    """The style rule is anchored to the specification, the primer and the
    Docutils parser pinned to both supported lanes, not to a moving branch."""
    guide = _normalized_text(DOCS_DIR / "guide.rst")

    for source in (
        "https://docutils.sourceforge.io/docs/ref/rst/restructuredtext.html#sections",
        "https://docutils.sourceforge.io/docs/user/rst/quickstart.html#document-title-subtitle",
        "https://sourceforge.net/p/docutils/code/10276/tree/tags/docutils-0.22.4/docutils/parsers/rst/states.py",
        "https://sourceforge.net/p/docutils/code/10339/tree/tags/docutils-0.23/docutils/parsers/rst/states.py",
    ):
        assert source in guide
    assert "Inconsistent title style: skip from level" in guide
    assert "DocTitle" in guide


@pytest.mark.unit
def test_outline_manual_documents_the_style_token() -> None:
    manual = _normalized_text(DOCS_DIR / "man" / "check_rst-outline.rst")

    for token in ("``*o``", "``*u``", "``n``", "``?n``"):
        assert token in manual
    assert "each depth with its title styles" in manual
    assert "the hint is ``unknown``" in manual


@pytest.mark.unit
def test_json_manual_documents_the_form_member() -> None:
    manual = _normalized_text(DOCS_DIR / "man" / "check_rst-json.rst")

    assert "``form``" in manual
    assert '``"o"``, ``"u"`` or ``"n"``' in manual
    assert "an absent ``form`` means the snapshot never recorded it" in manual


@pytest.mark.unit
def test_include_context_contract_is_documented_for_each_command() -> None:
    """CR-43 P7: every affected interface names its contextual contract.

    The guide carries the full rationale, but a reader who starts from a
    command manual must still learn whether the command discovers, refuses,
    composes or reports include contexts.
    """
    pages = {
        name: _normalized_text(DOCS_DIR / "man" / name)
        for name in (
            "check_rst.rst",
            "check_rst-check.rst",
            "check_rst-config.rst",
            "check_rst-diff.rst",
            "check_rst-entitle.rst",
            "check_rst-fix.rst",
            "check_rst-json.rst",
            "check_rst-outline.rst",
            "check_rst-reports.rst",
        )
    }

    assert "``--standalone PATTERN``" in pages["check_rst.rst"]
    assert "``--fragment PATTERN``" in pages["check_rst.rst"]
    assert '``standalone = ["PATTERN", ...]``' in pages["check_rst-config.rst"]
    assert '``fragments = ["PATTERN", ...]``' in pages["check_rst-config.rst"]
    assert "joined read-only and whole-file" in pages["check_rst-check.rst"]
    assert "conservative fast refusal" in pages["check_rst-fix.rst"]
    assert "every available include context" in pages["check_rst-fix.rst"]
    assert "includers that both modes discover" in pages["check_rst-fix.rst"]
    assert "non-``.rst`` includer" in pages["check_rst-fix.rst"]
    assert "``fragments`` or ``--fragment``" in pages["check_rst-fix.rst"]
    assert "never apply conflicting structural edits" not in pages["check_rst-fix.rst"]
    assert "same contextual plan as ``fix``" in pages["check_rst-diff.rst"]
    assert "``config.roles``" in pages["check_rst-json.rst"]
    assert "contexts disagree or one is unavailable" in pages["check_rst-outline.rst"]
    assert "contexts disagree or one is unavailable" in pages["check_rst-reports.rst"]
    assert "outside every discovery root" in pages["check_rst-outline.rst"]
    assert "outside every discovery root" in pages["check_rst-reports.rst"]
    assert "discovery-only" in pages["check_rst-entitle.rst"]


@pytest.mark.unit
def test_guide_and_roadmap_record_cr43_boundaries_and_compatibility() -> None:
    """The normative guide and release record name CR-43's limitations and
    visible compatibility signatures, including the reader-side N1 change,
    conservative title-free-include refusal, and fast Sphinx-source check."""
    guide = _normalized_text(DOCS_DIR / "guide.rst")
    roadmap = _normalized_text(DOCS_DIR / "roadmap.rst")

    for phrase in (
        "Include contexts and discovery roots",
        "``include.context-conflict``",
        "``include.context-unavailable``",
        "non-``.rst`` includer",
        "ignored includer",
        "outside every discovery root",
    ):
        assert phrase in guide

    assert "0.7.3 (2026-10-21)" in roadmap
    assert "contextual ownership for ``.. include::`` fragments" in roadmap
    assert "Readers now return status 1 instead of a standalone answer" in roadmap
    assert "contract version 2 covers both" in roadmap
    assert "title-free menu bar" in roadmap
    assert "run full ``fix``" in roadmap
    assert "without ``conf.py`` now exits 1" in roadmap
    assert "instead of being ignored by fast mode" in roadmap
    assert "P6 projects" not in roadmap


@pytest.mark.unit
def test_roadmap_records_cr45_title_candidate_boundary() -> None:
    """The 0.7.3 record names the parser-free model's corrected boundary."""
    roadmap = _normalized_text(DOCS_DIR / "roadmap.rst")

    assert "proven Docutils body constructs" in roadmap
    assert "Docutils falls back to ordinary text" in roadmap
