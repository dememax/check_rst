# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Sphinx build configuration for the documentation — check_rst project

from __future__ import annotations

import datetime
import pathlib
import sys

# A source checkout is itself a supported documentation-build input.  Prefer
# its package metadata even when another check_rst version is installed, and
# do not require an editable install merely to build the manuals.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import check_rst

project = "check_rst"
author = "Maxime P. DEMENTYEV"
current_year = datetime.date.today().year
copyright_years = "2026" if current_year == 2026 else f"2026-{current_year}"
copyright = f"{copyright_years}, {author}"
language = "en"
# Sphinx's man builder reads config.version for the .TH header's version
# field, never config.release (confirmed by reading
# sphinx.writers.manpage.ManualPageTranslator.visit_document) — release
# alone left every generated man page's version field blank.  This project
# never distinguishes a short "version series" from a full "release", so
# both share check_rst's own single version string rather than a second
# hardcoded literal that could drift from it.
version = release = check_rst.__version__

extensions = ["sphinx.ext.autosectionlabel"]
autosectionlabel_prefix_document = True
exclude_patterns = ["_build"]
source_suffix = {".rst": "restructuredtext"}
root_doc = "index"

html_theme = "alabaster"

man_pages = [
    ("man/check_rst", "check_rst", "check, fix, and query reStructuredText and Sphinx documentation", [author], 1),
    ("man/check_rst-check", "check_rst-check", "report reStructuredText and Sphinx findings", [author], 1),
    ("man/check_rst-fix", "check_rst-fix", "apply bounded reStructuredText corrections in place", [author], 1),
    ("man/check_rst-diff", "check_rst-diff", "preview check_rst fix output as a unified diff", [author], 1),
    ("man/check_rst-outline", "check_rst-outline", "print navigable document structure", [author], 1),
    (
        "man/check_rst-list-table",
        "check_rst-list-table",
        "convert eligible aligned tables to list-table syntax",
        [author],
        1,
    ),
    (
        "man/check_rst-entitle",
        "check_rst-entitle",
        "wrap a document under a new top-level title",
        [author],
        1,
    ),
    (
        "man/check_rst-hierarchy",
        "check_rst-hierarchy",
        "print the live adornment-character order",
        [author],
        1,
    ),
    (
        "man/check_rst-reports",
        "check_rst-reports",
        "query entry context, references, and semantic changes",
        [author],
        1,
    ),
    ("man/check_rst-config", "check_rst-config", "repository facts for check_rst", [author], 5),
    ("man/check_rst-json", "check_rst-json", "machine-readable check_rst report format", [author], 5),
    (
        "man/check_rst-formats",
        "check_rst-formats",
        "native and bridge source-format boundaries",
        [author],
        7,
    ),
    (
        "man/check_rst-workflow",
        "check_rst-workflow",
        "safe reading and edit-validation sequence",
        [author],
        7,
    ),
    (
        "man/check_rst-rules",
        "check_rst-rules",
        "deterministic checks and human decisions",
        [author],
        7,
    ),
]

rst_prolog = f"""\
.. |project| replace:: {project}
.. |author| replace:: {author}
.. |copyright| replace:: {copyright}
"""
