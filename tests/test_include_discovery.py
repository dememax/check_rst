# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Discovery roots, scan population and the reverse include graph (CR-43) — check_rst project
"""CR-43 judges a file meant for ``.. include::`` in the context of its
includers.  That needs, first, the files that may include it: a reverse,
transitive include graph over a defined discovery universe (D9d).

These tests pin the lexical foundation only.  A lexical scan cannot tell an
include directive from include-looking text in a comment or a literal block,
so every site it finds is *possible*; confirming a site with the parse, and
every user-visible behaviour, belong to later CR-43 pairs.

The module is imported inside a fixture so that this file collects under
plain pytest before the module exists (the 0.7.1 lesson: RED commits must
collect).
"""

from __future__ import annotations

import importlib
import os
from typing import TYPE_CHECKING

import docutils.core
import docutils.nodes
import pytest

if TYPE_CHECKING:
    import types
    from pathlib import Path


@pytest.fixture
def inc() -> types.ModuleType:
    return importlib.import_module("check_rst.cli._includes")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Discovery roots (D9d)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_an_active_configuration_directory_is_the_discovery_root(inc: types.ModuleType, tmp_path: Path) -> None:
    doc = _write(tmp_path / "project" / "docs" / "a.rst", "Text.\n")

    roots, uncovered = inc.discovery_roots([doc], config_root=tmp_path / "project", sphinx_src=None, cwd=tmp_path)

    assert roots == ((tmp_path / "project").resolve(),)
    assert uncovered == ()


@pytest.mark.integration
def test_a_sphinx_source_outside_the_configuration_root_is_added_never_narrowing(
    inc: types.ModuleType, tmp_path: Path
) -> None:
    config_root = tmp_path / "project"
    inside = config_root / "docs"
    outside = tmp_path / "elsewhere" / "src"
    inside.mkdir(parents=True)
    outside.mkdir(parents=True)

    narrow, _ = inc.discovery_roots([], config_root=config_root, sphinx_src=inside, cwd=tmp_path)
    wide, _ = inc.discovery_roots([], config_root=config_root, sphinx_src=outside, cwd=tmp_path)

    assert narrow == (config_root.resolve(),)
    assert wide == (config_root.resolve(), outside.resolve())


@pytest.mark.integration
def test_without_configuration_each_file_uses_its_git_worktree(
    inc: types.ModuleType, tmp_git_repo: Path, tmp_path: Path
) -> None:
    doc = _write(tmp_git_repo / "sub" / "a.rst", "Text.\n")

    roots, uncovered = inc.discovery_roots([doc], config_root=None, sphinx_src=None, cwd=tmp_path)

    assert roots == (tmp_git_repo.resolve(),)
    assert uncovered == ()


@pytest.mark.integration
def test_outside_git_the_working_directory_covers_only_files_beneath_it(inc: types.ModuleType, tmp_path: Path) -> None:
    cwd = tmp_path / "work"
    inside = _write(cwd / "a.rst", "Text.\n")
    outside = _write(tmp_path / "other" / "b.rst", "Text.\n")

    roots, uncovered = inc.discovery_roots([inside, outside], config_root=None, sphinx_src=None, cwd=cwd)

    assert roots == (cwd.resolve(),)
    assert uncovered == (outside.resolve(),)


@pytest.mark.integration
def test_a_file_outside_the_configuration_root_is_uncovered(inc: types.ModuleType, tmp_path: Path) -> None:
    config_root = tmp_path / "project"
    config_root.mkdir()
    stray = _write(tmp_path / "stray.rst", "Text.\n")

    roots, uncovered = inc.discovery_roots([stray], config_root=config_root, sphinx_src=None, cwd=tmp_path)

    assert roots == (config_root.resolve(),)
    assert uncovered == (stray.resolve(),)


# ---------------------------------------------------------------------------
# The automatic includer scan population
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_the_scan_population_skips_git_metadata_ignored_files_and_directory_symlinks(
    inc: types.ModuleType, tmp_git_repo: Path
) -> None:
    kept = _write(tmp_git_repo / "docs" / "kept.rst", "Text.\n")
    _write(tmp_git_repo / "docs" / "notes.txt", "Not a source suffix.\n")
    _write(tmp_git_repo / "build" / "generated.rst", "Ignored.\n")
    _write(tmp_git_repo / ".gitignore", "build/\n")
    _write(tmp_git_repo / ".git" / "fake.rst", "Git metadata.\n")
    (tmp_git_repo / "loop").symlink_to(tmp_git_repo, target_is_directory=True)

    population = inc.scan_population((tmp_git_repo.resolve(),))

    assert population == (kept.resolve(),)


@pytest.mark.integration
def test_the_scan_population_adds_configured_source_suffixes(inc: types.ModuleType, tmp_path: Path) -> None:
    rst = _write(tmp_path / "a.rst", "Text.\n")
    txt = _write(tmp_path / "b.txt", "Text.\n")

    population = inc.scan_population((tmp_path.resolve(),), suffixes=(".rst", ".txt"))

    assert population == (rst.resolve(), txt.resolve())


# ---------------------------------------------------------------------------
# Lexical include sites
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_a_lexical_include_site_records_its_line_target_indent_and_options(
    inc: types.ModuleType, tmp_path: Path
) -> None:
    main = _write(
        tmp_path / "docs" / "main.rst",
        "Title\n=====\n\n.. include:: parts/part.rst\n   :start-after: BEGIN\n   :end-line: 9\n\n"
        ".. note::\n\n   ..  INCLUDE::   ../shared.rst\n",
    )

    sites = inc.lexical_includes(main)

    assert [(s.line, s.argument, s.indent, s.options) for s in sites] == [
        (4, "parts/part.rst", 0, (("start-after", "BEGIN"), ("end-line", "9"))),
        (10, "../shared.rst", 3, ()),
    ]
    assert [s.target for s in sites] == [
        (tmp_path / "docs" / "parts" / "part.rst").resolve(),
        (tmp_path / "shared.rst").resolve(),
    ]


@pytest.mark.integration
def test_standard_and_literal_includes_are_not_structural_sites(inc: types.ModuleType, tmp_path: Path) -> None:
    main = _write(
        tmp_path / "main.rst",
        ".. include:: <isonum.txt>\n\n.. include:: code.py\n   :literal:\n\n"
        ".. include:: sample.rst\n   :code: rst\n\n.. include:: part.rst\n",
    )

    sites = inc.lexical_includes(main)

    assert [s.argument for s in sites] == ["code.py", "sample.rst", "part.rst"]
    assert [s.structural for s in sites] == [False, False, True]


@pytest.mark.integration
def test_include_looking_text_in_a_literal_block_is_still_a_possible_site(
    inc: types.ModuleType, tmp_path: Path
) -> None:
    """A lexical scan cannot prove a line is literal text; fast mode will
    refuse on it, and full mode confirms with the parse (a later pair)."""
    main = _write(tmp_path / "main.rst", "Example::\n\n    .. include:: part.rst\n")

    sites = inc.lexical_includes(main)

    assert [(s.line, s.argument, s.indent) for s in sites] == [(3, "part.rst", 4)]


@pytest.mark.integration
def test_a_sphinx_absolute_include_path_resolves_from_the_source_directory(
    inc: types.ModuleType, tmp_path: Path
) -> None:
    main = _write(tmp_path / "src" / "guide" / "main.rst", ".. include:: /shared/part.rst\n")

    sites = inc.lexical_includes(main, sphinx_src=tmp_path / "src")

    assert [s.target for s in sites] == [(tmp_path / "src" / "shared" / "part.rst").resolve()]


# ---------------------------------------------------------------------------
# The reverse, transitive include graph
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_the_graph_finds_direct_and_transitive_includers(inc: types.ModuleType, tmp_path: Path) -> None:
    root = _write(tmp_path / "root.rst", ".. include:: middle.rst\n")
    middle = _write(tmp_path / "middle.rst", ".. include:: parts/leaf.rst\n")
    leaf = _write(tmp_path / "parts" / "leaf.rst", "Leaf\n====\n")
    other = _write(tmp_path / "other.rst", ".. include:: parts/leaf.rst\n")

    graph = inc.IncludeGraph.build(inc.scan_population((tmp_path.resolve(),)))

    assert sorted(site.includer for site in graph.includers(leaf)) == sorted([middle.resolve(), other.resolve()])
    assert set(graph.transitive_includers(leaf)) == {middle.resolve(), other.resolve(), root.resolve()}
    assert graph.may_be_included(leaf)
    assert not graph.may_be_included(root)


@pytest.mark.integration
def test_the_graph_scans_an_include_target_whatever_its_suffix(inc: types.ModuleType, tmp_path: Path) -> None:
    """Every transitively reached include target belongs to the population,
    whatever its suffix: a .txt fragment can include a further fragment."""
    root = _write(tmp_path / "root.rst", ".. include:: chapter.txt\n")
    chapter = _write(tmp_path / "chapter.txt", ".. include:: leaf.rst\n")
    leaf = _write(tmp_path / "leaf.rst", "Leaf\n====\n")

    graph = inc.IncludeGraph.build(inc.scan_population((tmp_path.resolve(),)))

    assert set(graph.transitive_includers(leaf)) == {chapter.resolve(), root.resolve()}


@pytest.mark.integration
def test_the_graph_terminates_on_an_include_cycle(inc: types.ModuleType, tmp_path: Path) -> None:
    a = _write(tmp_path / "a.rst", ".. include:: b.rst\n")
    b = _write(tmp_path / "b.rst", ".. include:: a.rst\n")

    graph = inc.IncludeGraph.build(inc.scan_population((tmp_path.resolve(),)))

    assert set(graph.transitive_includers(a)) == {a.resolve(), b.resolve()}


@pytest.mark.integration
def test_the_graph_matches_a_target_through_a_file_symlink_by_its_real_path(
    inc: types.ModuleType, tmp_path: Path
) -> None:
    """Role membership canonicalizes; a fragment reached through a symlinked
    file name is still the same file."""
    leaf = _write(tmp_path / "real" / "leaf.rst", "Leaf\n====\n")
    os.symlink(leaf, tmp_path / "alias.rst")
    _write(tmp_path / "root.rst", ".. include:: alias.rst\n")

    graph = inc.IncludeGraph.build(inc.scan_population((tmp_path.resolve(),)))

    assert graph.may_be_included(leaf)


# ---------------------------------------------------------------------------
# Checkpoint corrections (Codex, 2026-10-16)
# ---------------------------------------------------------------------------


def _docutils_text(path: Path) -> str:
    """The text Docutils itself produces for *path*, opened by that path."""
    tree = docutils.core.publish_doctree(
        path.read_text(encoding="utf-8"), source_path=str(path), settings_overrides={"report_level": 5}
    )
    text: str = tree.astext()
    return text


@pytest.mark.integration
def test_an_explicit_sphinx_source_is_a_root_without_configuration(
    inc: types.ModuleType, tmp_git_repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """D9d adds an active Sphinx source as a root on its own: it must not
    depend on a configuration root being present."""
    doc = _write(tmp_git_repo / "a.rst", "Text.\n")
    sphinx_src = tmp_path_factory.mktemp("elsewhere") / "src"
    sphinx_src.mkdir()

    roots, uncovered = inc.discovery_roots([doc], config_root=None, sphinx_src=sphinx_src, cwd=tmp_git_repo)

    assert roots == (tmp_git_repo.resolve(), sphinx_src.resolve())
    assert uncovered == ()


@pytest.mark.integration
def test_an_option_less_indented_than_the_directive_is_not_its_option(inc: types.ModuleType, tmp_path: Path) -> None:
    """Only lines inside the directive's indented block are its options.  A
    shallower ":literal:" belongs outside it, so the include stays
    structural; reading it as the include's option would let fast mode
    mutate the included file unchecked."""
    _write(tmp_path / "part.rst", "Hello *world*.\n")
    main = _write(tmp_path / "main.rst", "   .. include:: part.rst\n :literal:\n")

    sites = inc.lexical_includes(main)

    assert [(s.indent, s.options, s.structural) for s in sites] == [(3, (), True)]
    tree = docutils.core.publish_doctree(
        main.read_text(encoding="utf-8"), source_path=str(main), settings_overrides={"report_level": 5}
    )
    assert list(tree.findall(docutils.nodes.emphasis)), "Docutils includes part.rst as parsed RST"


@pytest.mark.integration
def test_a_symlinked_includer_resolves_its_includes_from_its_lexical_path(
    inc: types.ModuleType, tmp_path: Path
) -> None:
    """Docutils resolves a relative include from the path used to open the
    includer, not from its real path.  The alias and the real file are two
    includer contexts, and each must name the child Docutils reads."""
    _write(tmp_path / "alias" / "child.rst", "ALIAS CHILD\n")
    _write(tmp_path / "real" / "child.rst", "REAL CHILD\n")
    real_source = _write(tmp_path / "real" / "source.rst", ".. include:: child.rst\n")
    alias_source = tmp_path / "alias" / "source.rst"
    alias_source.symlink_to(os.path.relpath(real_source, alias_source.parent))
    root = tmp_path.resolve()

    sites = inc.lexical_includes(root / "alias" / "source.rst")
    graph = inc.IncludeGraph.build(inc.scan_population((root,)))

    assert _docutils_text(alias_source).strip() == "ALIAS CHILD"
    assert [s.target for s in sites] == [root / "alias" / "child.rst"]
    assert [s.includer for s in graph.includers(root / "alias" / "child.rst")] == [root / "alias" / "source.rst"]
    assert [s.includer for s in graph.includers(root / "real" / "child.rst")] == [root / "real" / "source.rst"]


@pytest.mark.integration
def test_a_non_utf8_file_name_is_scanned_rather_than_crashing_the_scan(
    inc: types.ModuleType, tmp_git_repo: Path
) -> None:
    """pygit2 can ask libgit2 about ignoredness only for a UTF-8-encodable
    path.  A surrogate-escaped file name cannot be proven ignored, so the
    conservative choice is to scan it, never to crash or to skip it."""
    root = tmp_git_repo.resolve()
    raw = os.fsencode(root) + b"/odd_\xff.rst"
    descriptor = os.open(raw, os.O_WRONLY | os.O_CREAT, 0o600)
    os.write(descriptor, b".. include:: part.rst\n")
    os.close(descriptor)
    _write(root / "part.rst", "Part\n====\n")

    population = inc.scan_population((root,))
    graph = inc.IncludeGraph.build(population)

    assert root / os.fsdecode(b"odd_\xff.rst") in population
    assert graph.may_be_included(root / "part.rst")
