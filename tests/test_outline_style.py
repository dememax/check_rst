# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Complete title styles in outline, JSON and the CLI contract (CR-47) — check_rst project
"""A reStructuredText title style is its adornment character *and* its form:
underline-only or overline-and-underline.  The same character in the two
forms is two distinct styles (reStructuredText specification, "Sections";
Docutils keys an underline-only style by the character and an overlined one
by the ``(overline, underline)`` character pair).

outline used to report only the character, so it could not show the form
that the guide tells authors to copy for a new sibling title.  Every section
now carries a style token: the character followed by ``o`` (overline and
underline) or ``u`` (underline only), or a bare ``n`` when the physical
source does not prove the complete style.  Alphanumeric characters can never
be adornment characters, so the suffix is unambiguous; ``?`` is a valid
adornment character, so the unknown token is never ``?n``.

The default outline text format changes with it, which is an incompatible
change to a documented command-line contract: the CLI contract version is 2.
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import TYPE_CHECKING, Any

import docutils.nodes
import pytest
from _support import _rst

from check_rst import cli
from check_rst.cli import _comparison, _document, _reports, _sphinx, _types

if TYPE_CHECKING:
    from pathlib import Path


def _styles(path: Path) -> list[tuple[int, str, str]]:
    return [(entry.depth, entry.style, entry.title) for entry in _document.build_outline(path)]


# ---------------------------------------------------------------------------
# The style of each section
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_outline_reports_overline_and_underline_only_forms(tmp_path: Path) -> None:
    p = _rst(tmp_path, "#######\nTitle\n#######\n\n*******\nFirst\n*******\n\nSub\n===\n\nText.\n")

    assert _styles(p) == [(1, "#o", "Title"), (2, "*o", "First"), (3, "=u", "Sub")]


@pytest.mark.integration
def test_outline_gives_one_character_in_two_forms_two_tokens(tmp_path: Path) -> None:
    """The overlined page title and the underline-only sections below it are
    two distinct styles for Docutils, and outline shows them as two."""
    p = _rst(tmp_path, "=========\n Manual\n=========\n\nIntro.\n\nInstall\n=======\n\nText.\n")

    assert _styles(p) == [(1, "=o", "Manual"), (2, "=u", "Install")]


@pytest.mark.integration
def test_outline_reports_a_real_question_mark_adornment_with_its_form(tmp_path: Path) -> None:
    p = _rst(tmp_path, "?????\nTitle\n?????\n\nSub\n???\n\nText.\n")

    assert _styles(p) == [(1, "?o", "Title"), (2, "?u", "Sub")]


@pytest.mark.integration
def test_outline_reports_n_for_a_section_without_source_evidence(tmp_path: Path) -> None:
    """An extension may build a real section without a source line: its
    style is not proven, so the token is a bare n, never a guessed form."""
    p = _rst(tmp_path, "#######\nTitle\n#######\n")
    document = _document.Document(p, tmp_path)
    generated = docutils.nodes.section(ids=["generated"])
    generated += docutils.nodes.title("", "Generated")
    document.doctree += generated

    entry = next(e for e in _document.build_outline(p, doc=document) if e.title == "Generated")

    assert (entry.lineno, entry.form, entry.style) == (0, "n", "n")
    assert str(entry) == "0:n Generated"


@pytest.mark.integration
def test_outline_keeps_the_form_of_an_exactly_included_title(tmp_path: Path) -> None:
    (tmp_path / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    index = tmp_path / "index.rst"
    index.write_text(
        "#######\nIndex\n#######\n\n.. include:: fragment.rst\n\n.. include:: clipped.rst\n   :start-after: BEGIN\n",
        encoding="utf-8",
    )
    (tmp_path / "fragment.rst").write_text("**********\nIncluded\n**********\n\nBody.\n", encoding="utf-8")
    (tmp_path / "clipped.rst").write_text("discarded\nBEGIN\nClipped\n-------\n\nBody.\n", encoding="utf-8")

    env, _ = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    entries = _document.build_outline(index, doctree=env.get_doctree("index"), source_root=tmp_path)
    by_title = {entry.title: entry for entry in entries}

    assert by_title["Included"].provenance is not None
    assert by_title["Included"].provenance.exact is True
    assert by_title["Included"].style == "*o"
    assert by_title["Clipped"].provenance is not None
    assert by_title["Clipped"].provenance.exact is True
    assert by_title["Clipped"].style == "-u"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("conf", "index_text", "fragment", "title"),
    [
        (
            'project = "test"\n\ndef rewrite(app, docname, source):\n'
            '    source[0] = "Injected\\n========\\n\\n" + source[0]\n\n'
            'def setup(app):\n    app.connect("source-read", rewrite)\n',
            "Physical\n--------\n",
            None,
            "Injected",
        ),
        (
            'project = "test"\n\ndef rewrite(app, path, docname, source):\n'
            '    source[0] = source[0].replace("Included", "Generated")\n\n'
            'def setup(app):\n    app.connect("include-read", rewrite)\n',
            "#######\nIndex\n#######\n\n.. include:: fragment.rst\n",
            "**********\nIncluded\n**********\n",
            "Generated",
        ),
        (
            'project = "test"\nrst_prolog = "Prologue\\n========"\n',
            "Physical\n--------\n",
            None,
            "Prologue",
        ),
    ],
    ids=["source-read", "include-read", "rst-prolog"],
)
def test_outline_never_guesses_the_style_of_inexact_or_synthetic_source(
    tmp_path: Path, conf: str, index_text: str, fragment: str | None, title: str
) -> None:
    """Rewritten, mutated or injected source has no proven physical style."""
    (tmp_path / "conf.py").write_text(conf, encoding="utf-8")
    index = tmp_path / "index.rst"
    index.write_text(index_text, encoding="utf-8")
    if fragment is not None:
        (tmp_path / "fragment.rst").write_text(fragment, encoding="utf-8")

    env, _ = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    entries = _document.build_outline(
        index,
        doc=_document.Document(index, tmp_path),
        doctree=env.get_doctree("index"),
        source_root=tmp_path,
        root_transformed=_sphinx._source_was_transformed(env, "index"),
    )
    entry = next(e for e in entries if e.title == title)

    assert (entry.form, entry.style) == ("n", "n")


# ---------------------------------------------------------------------------
# Human outline output
# ---------------------------------------------------------------------------

_DOCUMENT = "#######\nTitle\n#######\n\n*******\nFirst\n*******\n\nSub\n===\n\nText.\n\n*******\nSecond\n*******\n"
_LEGEND = "levels: 1 '#o' (1), 2 '*o' (2), 3 '=u' (1), 4 sections total; next free section char: '-'"


def _outline(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--no-config", "outline", *argv])
    with pytest.raises(SystemExit):
        cli.main()
    return capsys.readouterr().out


@pytest.mark.integration
def test_cli_outline_lines_and_legend_carry_the_full_style(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Each line stays self-contained: it names the style to copy for a new
    sibling, so a reader never cross-references the legend."""
    p = rst_repo / "test.rst"
    p.write_text(_DOCUMENT, encoding="utf-8")

    out = _outline(monkeypatch, capsys, str(p))

    assert _LEGEND in out
    for line in (
        r"^  1-\d+:#o Title",
        r"^      5-\d+:\*o First",
        r"^          9-\d+:=u Sub",
        r"^      14-\d+:\*o Second",
    ):
        assert re.search(line, out, re.MULTILINE), (line, out)
    assert not re.search(r"^\s*\d+(-\d+)?:[#*=] ", out, re.MULTILINE), out


@pytest.mark.integration
@pytest.mark.parametrize("option", [["--sections-only"], ["--max-output-lines", "6"], ["--outline-depth", "1"]])
def test_cli_outline_legend_keeps_full_styles_under_filters_and_limits(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    option: list[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(_DOCUMENT, encoding="utf-8")

    out = _outline(monkeypatch, capsys, *option, str(p))

    assert _LEGEND in out


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def _check_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, Any]:
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--no-config", "check", "--format=json", *argv])
    with pytest.raises(SystemExit):
        cli.main()
    data: dict[str, Any] = json.loads(capsys.readouterr().out)
    return data


@pytest.mark.integration
def test_json_outline_records_the_character_and_the_form(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """JSON keeps ``char`` for compatibility and adds ``form``.  The human
    token is derived from the two; no redundant style member exists."""
    p = rst_repo / "test.rst"
    p.write_text(_DOCUMENT, encoding="utf-8")

    data = _check_json(monkeypatch, capsys, str(p))
    outline = data["files"][0]["outline"]

    assert [(entry["char"], entry["form"]) for entry in outline] == [
        ("#", "o"),
        ("*", "o"),
        ("=", "u"),
        ("*", "o"),
    ]
    assert all("style" not in entry for entry in outline)


@pytest.mark.unit
def test_json_outline_keeps_the_legacy_character_beside_an_unknown_form() -> None:
    """``char: "?"`` with ``form: "n"`` is an unknown style; with ``o`` or
    ``u`` it is a real question-mark adornment.  Consumers never have to
    reconstruct an unknown style from the legacy character."""
    unknown = _types.OutlineEntry(0, 1, "?", "Generated")
    real = _types.OutlineEntry(2, 1, "?", "Title", form="o")

    assert (_reports._entry_asdict(unknown)["char"], _reports._entry_asdict(unknown)["form"]) == ("?", "n")
    assert (_reports._entry_asdict(real)["char"], _reports._entry_asdict(real)["form"]) == ("?", "o")
    assert (unknown.style, real.style) == ("n", "?o")


# ---------------------------------------------------------------------------
# CLI contract version 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_json_check_report_records_contract_version_2_as_an_integer(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(_DOCUMENT, encoding="utf-8")

    data = _check_json(monkeypatch, capsys, str(p))
    version = data["runtime"]["check_rst"]["contract_version"]

    assert type(version) is int
    assert version == 2


@pytest.mark.integration
def test_git_comparison_document_records_contract_version_2(tmp_git_repo: Path) -> None:
    """compare builds an internal JSON-shaped document per Git side; its
    runtime provenance names the same contract as every public report."""
    document = tmp_git_repo / "doc.rst"
    document.write_text("#######\nTitle\n#######\n\nOld.\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_git_repo), "add", "doc.rst"], check=True)
    subprocess.run(["git", "-C", str(tmp_git_repo), "commit", "-qm", "doc"], check=True)
    document.write_text("#######\nTitle\n#######\n\nNew.\n", encoding="utf-8")
    comparison = _comparison.compare_git_states(
        tmp_git_repo,
        _comparison.GitState.revision_state("HEAD"),
        _comparison.GitState.worktree(),
    )

    for old_side in (True, False):
        dump = cli._git_section_dump(comparison, tmp_git_repo, old_side=old_side)
        version = dump["runtime"]["check_rst"]["contract_version"]
        assert type(version) is int
        assert version == 2
