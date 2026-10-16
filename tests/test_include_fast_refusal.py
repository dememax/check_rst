# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# The conservative fast refusal for files that may be included (CR-43, rule 7) — check_rst project
"""fix --fast and diff --fast never parse RST, so they cannot judge a file in
its includers' context.  When a selected file may be included, is a declared
fragment, lies outside every discovery root, or the include graph is
incomplete, a structural change that would alter the file's title model is
refused (include.context-unavailable).  The refusal is conditional: a change
that leaves the file's titles and their styles as they are, such as pure
adornment geometry, still applies, and byte hygiene always applies.

The remedy is the command's own: full fix for fix --fast, full diff for
diff --fast.  entitle shares fast mode's discovery and safety boundary
(D9c), but it always changes the title model and has no full mode: it
refuses any file that may be included and names no other command.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from check_rst import cli

if TYPE_CHECKING:
    from pathlib import Path

_MAIN = "######\nMain\n######\n\n*********\nSubtitle\n*********\n\n=======\nIntro\n=======\n\nText.\n\n.. include:: part.rst\n"
# Standalone, part.rst's "=" title is a page title, which fix would remap to
# "#": a change of title style, so it depends on the includer's context.
_PART = "========\nShared\n========\n\nBody.\n"


def _commit(repo: Path, *names: str) -> None:
    subprocess.run(["git", "-C", str(repo), "add", *names], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)


def _run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *argv: str, no_config: bool = True
) -> tuple[int, str]:
    monkeypatch.setattr("sys.argv", ["check_rst.py", *(["--no-config"] if no_config else []), *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    code = exc.value.code
    return (code if isinstance(code, int) else 1), capsys.readouterr().out


@pytest.fixture
def project(rst_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (rst_repo / "main.rst").write_text(_MAIN, encoding="utf-8")
    (rst_repo / "part.rst").write_text(_PART, encoding="utf-8")
    _commit(rst_repo, "main.rst", "part.rst")
    monkeypatch.chdir(rst_repo)
    return rst_repo


@pytest.mark.integration
def test_fix_fast_refuses_a_style_change_in_a_file_that_may_be_included(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CR-43 reproduction: fix --fast used to remap part.rst's "=" to "#"
    and break main.rst, while the documented loop stayed green."""
    part = project / "part.rst"
    part.write_text(_PART.replace("Body.", "Body.   "), encoding="utf-8")

    code, out = _run(monkeypatch, capsys, "fix", "--fast", "part.rst")

    assert code == 1, out
    assert (
        "part.rst:2: ERROR: fix refused — this file may be included by main.rst:15, so its title levels "
        "depend on that document, which fast mode cannot judge — run full fix to judge it in context"
    ) in out
    assert part.read_text(encoding="utf-8") == _PART, "titles kept, trailing whitespace still removed"


@pytest.mark.integration
def test_diff_fast_names_full_diff_as_its_remedy(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run(monkeypatch, capsys, "diff", "--fast", "part.rst")

    assert code == 1, out
    assert "which fast mode cannot judge — run full diff to judge it in context" in out
    assert "@@" not in out


@pytest.mark.integration
def test_pure_geometry_still_applies_to_a_file_that_may_be_included(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A length-only correction keeps every title and its style, so nothing
    depends on the includer and nothing is refused."""
    part = project / "part.rst"
    part.write_text("############\nShared\n############\n\nBody.\n", encoding="utf-8")

    code, out = _run(monkeypatch, capsys, "fix", "--fast", "part.rst")

    assert code == 0, out
    assert "fix refused" not in out
    assert part.read_text(encoding="utf-8") == "########\nShared\n########\n\nBody.\n"


@pytest.mark.integration
def test_fix_fast_refuses_a_declared_fragment_without_a_visible_includer(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    part = rst_repo / "contact.rst"
    part.write_text(_PART, encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "--fragment", "contact.rst", "fix", "--fast", "contact.rst")

    assert code == 1, out
    assert (
        "fix refused — this file is declared a fragment (--fragment 'contact.rst'), so its title levels "
        "depend on an includer check_rst cannot see — edit its titles by hand, or remove the declaration "
        "if it is not a fragment"
    ) in out
    assert part.read_text(encoding="utf-8") == _PART


@pytest.mark.integration
def test_fix_fast_refuses_a_file_outside_every_discovery_root(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Outside Git and outside the working directory, no root covers the
    file, so its includers cannot be searched (D9d step 5)."""
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    part = elsewhere / "part.rst"
    part.write_text(_PART, encoding="utf-8")
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))

    code, out = _run(monkeypatch, capsys, "fix", "--fast", str(part))

    assert code == 1, out
    assert "fix refused — this file lies outside every discovery root (" in out
    assert "so check_rst cannot search for its includers — run from the project root or pass --config" in out
    assert part.read_text(encoding="utf-8") == _PART


@pytest.mark.integration
def test_an_unreadable_population_file_refuses_style_changes(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unreadable file may hold any include, so the include graph is
    incomplete and no file can be proven unincluded."""
    doc = rst_repo / "doc.rst"
    doc.write_text(_PART, encoding="utf-8")
    (rst_repo / "broken.rst").write_bytes(b"Title\n=====\n\n\xff\xfe not UTF-8\n")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "fix", "--fast", "doc.rst")

    assert code == 1, out
    assert (
        "fix refused — the include graph is incomplete: broken.rst cannot be read, so check_rst cannot rule "
        "out that it includes this file — make it readable or ignore it"
    ) in out
    assert doc.read_text(encoding="utf-8") == _PART


@pytest.mark.integration
def test_include_looking_text_in_a_literal_block_still_refuses_in_fast_mode(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fast mode cannot prove that the line is literal text: the conservative
    fast refusal (full mode may prove it safe, in a later pair)."""
    (rst_repo / "example.rst").write_text(
        "#######\nExample\n#######\n\nSee::\n\n    .. include:: part.rst\n", encoding="utf-8"
    )
    part = rst_repo / "part.rst"
    part.write_text(_PART, encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "fix", "--fast", "part.rst")

    assert code == 1, out
    assert "this file may be included by example.rst:7" in out


@pytest.mark.integration
def test_a_file_nothing_includes_is_fixed_as_before(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = rst_repo / "doc.rst"
    doc.write_text(_PART, encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "fix", "--fast", "doc.rst")

    assert code == 0, out
    assert doc.read_text(encoding="utf-8") == "########\nShared\n########\n\nBody.\n"


@pytest.mark.integration
@pytest.mark.parametrize(
    "argv",
    [("fix", "--fast", "docs/part.rst"), ("entitle", "Book", "docs/part.rst", "--apply")],
    ids=["fix", "entitle"],
)
def test_a_configured_sphinx_source_locates_a_rooted_include_in_fast_mode(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: tuple[str, ...]
) -> None:
    """Fast mode and entitle never run Sphinx, so the configured sphinx-src
    is inactive for them.  It still says where a leading "/" include points:
    ignoring it hid this includer, and fix --fast remapped part.rst's "="."""
    (rst_repo / ".check_rst.toml").write_text('sphinx-src = "docs"\n', encoding="utf-8")
    (rst_repo / "docs" / "sub").mkdir(parents=True)
    (rst_repo / "docs" / "conf.py").write_text('project = "p"\n', encoding="utf-8")
    (rst_repo / "docs" / "sub" / "index.rst").write_text(
        "######\nMain\n######\n\n*****\nSub\n*****\n\n.. include:: /part.rst\n", encoding="utf-8"
    )
    part = rst_repo / "docs" / "part.rst"
    part.write_text(_PART, encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, *argv, no_config=False)

    assert code == 1, out
    assert "this file may be included by docs/sub/index.rst:9, so its title levels depend on that document" in out
    assert part.read_text(encoding="utf-8") == _PART


# ---------------------------------------------------------------------------
# The includer side (Q1)
# ---------------------------------------------------------------------------

# An underline-only page title: fix would give it an overline (CR-42), a
# change of title style.
_INCLUDER = "Main\n####\n\nText.\n\n.. include:: {target}{options}\n"


def _includer(repo: Path, target: str, options: str = "") -> Path:
    path = repo / "main.rst"
    path.write_text(_INCLUDER.format(target=target, options=options), encoding="utf-8")
    return path


_INCLUDES_REFUSAL = (
    "so its hierarchy depends on what that file adds, which fast mode cannot judge — run full fix to judge it "
    "in context"
)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("options", "content"),
    [
        ("", "Shared\n******\n\nBody.\n"),
        ("", "Jane Doe\nphone: 0100\n"),
        ("\n   :parser: rst", "Jane Doe\nphone: 0100\n"),
    ],
    ids=["titled-fragment", "title-free-fragment", "parser-option"],
)
def test_fix_fast_refuses_an_includer_with_any_structural_include(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], options: str, content: str
) -> None:
    """Fast mode cannot prove what a structural include adds: a title-free
    source may still yield sections, through another :parser:, a Sphinx
    include-read or source-read handler, or an extension directive.
    Changing the includer's own styles could restructure the composed
    document, so only full mode may judge it."""
    main = _includer(rst_repo, "part.rst", options)
    (rst_repo / "part.rst").write_text(content, encoding="utf-8")
    before = main.read_text(encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "fix", "--fast", "main.rst")

    assert code == 1, out
    assert f"main.rst:1: ERROR: fix refused — this file includes part.rst at line 6, {_INCLUDES_REFUSAL}" in out
    assert main.read_text(encoding="utf-8") == before


@pytest.mark.integration
def test_fix_fast_refuses_an_includer_whose_titles_arrive_transitively(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    main = _includer(rst_repo, "middle.rst")
    (rst_repo / "middle.rst").write_text("Plain text.\n\n.. include:: leaf.rst\n", encoding="utf-8")
    (rst_repo / "leaf.rst").write_text("Leaf\n****\n", encoding="utf-8")
    before = main.read_text(encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "fix", "--fast", "main.rst")

    assert code == 1, out
    assert f"this file includes middle.rst at line 6, {_INCLUDES_REFUSAL}" in out
    assert main.read_text(encoding="utf-8") == before


@pytest.mark.integration
def test_fix_fast_refuses_an_includer_whose_target_cannot_be_read(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing target proves nothing about what it may add."""
    main = _includer(rst_repo, "missing.rst")
    before = main.read_text(encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "fix", "--fast", "main.rst")

    assert code == 1, out
    assert f"this file includes missing.rst at line 6, {_INCLUDES_REFUSAL}" in out
    assert main.read_text(encoding="utf-8") == before


@pytest.mark.integration
@pytest.mark.parametrize("option", [":literal:", ":code: python"], ids=["literal", "code"])
def test_fix_fast_still_fixes_an_includer_whose_includes_are_text(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], option: str
) -> None:
    """Only a literal or code include is lexically proven to add no
    structure, so the includer's hierarchy is its own."""
    target, content = "code.py", "print('#####')\n"
    main = _includer(rst_repo, target, f"\n   {option}")
    (rst_repo / target).write_text(content, encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "fix", "--fast", "main.rst")

    assert code == 0, out
    assert main.read_text(encoding="utf-8").startswith("######\nMain\n######\n")


# ---------------------------------------------------------------------------
# entitle (D9c): fast mode's boundary, without a full-mode remedy
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("apply", [False, True], ids=["preview", "apply"])
def test_entitle_refuses_a_file_that_may_be_included(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], apply: bool
) -> None:
    """entitle used to wrap part.rst alone and break main.rst's hierarchy.
    It has no full mode to suggest, and fix does not wrap."""
    code, out = _run(monkeypatch, capsys, "entitle", "Book", "part.rst", *(["--apply"] if apply else []))

    assert code == 1, out
    assert (
        "check_rst: part.rst: ERROR: entitle refused — this file may be included by main.rst:15, so its title "
        "levels depend on that document, and entitle judges one file alone"
    ) in out
    assert "run full" not in out
    assert "@@" not in out
    assert (project / "part.rst").read_text(encoding="utf-8") == _PART


@pytest.mark.integration
def test_entitle_refuses_an_includer_whose_fragment_contributes_titles(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    main = _includer(rst_repo, "part.rst")
    (rst_repo / "part.rst").write_text("Shared\n******\n\nBody.\n", encoding="utf-8")
    before = main.read_text(encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "entitle", "Book", "main.rst", "--apply")

    assert code == 1, out
    assert (
        "check_rst: main.rst: ERROR: entitle refused — this file includes part.rst at line 6, so its hierarchy "
        "depends on what that file adds, and entitle judges one file alone"
    ) in out
    assert main.read_text(encoding="utf-8") == before


@pytest.mark.integration
def test_entitle_reads_the_configuration_with_fast_mode_semantics(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The configured roles apply; the configured Sphinx settings stay
    inactive, as in fast mode."""
    (rst_repo / ".check_rst.toml").write_text('sphinx-src = "docs"\nfragments = ["contact.rst"]\n', encoding="utf-8")
    contact = rst_repo / "contact.rst"
    contact.write_text(_PART, encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "entitle", "Book", "contact.rst", no_config=False)

    assert code == 1, out
    assert "config: .check_rst.toml — fragments=contact.rst, sphinx-src=docs inactive (entitle)" in out
    assert (
        "check_rst: contact.rst: ERROR: entitle refused — this file is declared a fragment "
        "(.check_rst.toml 'contact.rst'), so its title levels depend on an includer check_rst cannot see — "
        "edit its titles by hand, or remove the declaration if it is not a fragment"
    ) in out
    assert contact.read_text(encoding="utf-8") == _PART


@pytest.mark.integration
def test_entitle_accepts_an_explicit_configuration_and_still_wraps(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = rst_repo / "doc.rst"
    doc.write_text(_PART, encoding="utf-8")
    config = rst_repo / "cfg.toml"
    config.write_text('standalone = ["doc.rst"]\n', encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "--config", str(config), "entitle", "Book", "doc.rst", no_config=False)

    assert code == 0, out
    assert f"config: {config} — standalone=doc.rst" in out
    assert "+Book" in out
    assert doc.read_text(encoding="utf-8") == _PART, "a preview writes nothing"


@pytest.mark.integration
def test_entitle_matches_the_command_line_role_patterns(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (rst_repo / "doc.rst").write_text(_PART, encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "--fragment", "typo/*.rst", "entitle", "Book", "doc.rst")

    assert code == 1, out
    assert "check_rst: --fragment: fragments pattern 'typo/*.rst' matches no file" in out


@pytest.mark.integration
def test_entitle_refuses_a_file_outside_every_discovery_root(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    part = elsewhere / "part.rst"
    part.write_text(_PART, encoding="utf-8")
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))

    code, out = _run(monkeypatch, capsys, "entitle", "Book", str(part), "--apply")

    assert code == 1, out
    assert "entitle refused — this file lies outside every discovery root (" in out
    assert "run from the project root or pass --config" in out
    assert part.read_text(encoding="utf-8") == _PART


@pytest.mark.integration
def test_entitle_still_wraps_a_file_nothing_includes(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = rst_repo / "doc.rst"
    doc.write_text(_PART, encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _run(monkeypatch, capsys, "entitle", "Book", "doc.rst", "--apply")

    assert code == 0, out
    assert doc.read_text(encoding="utf-8").startswith("######\nBook\n######\n")
