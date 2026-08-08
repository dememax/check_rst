# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Tests for check_rst.cli's _reports domain (word-stats, --context, --refs, diff-json) — check_rst project

from __future__ import annotations

import json
import re
import sys
import textwrap
import types
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from _support import _GOOD_BLOCK, _build_multi_file_env, _rst

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any


@pytest.mark.integration
def test_resolve_xref_target_doc_resolves_relative_target(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "index": "Title\n=====\n",
            "sub/page": "Sub Page\n========\n",
        },
    )
    assert check_rst._resolve_xref_target(env, "sub/page", "doc", "../index") == "index"


@pytest.mark.integration
def test_resolve_xref_target_doc_unresolvable_returns_none(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(check_rst, tmp_path, {"index": "Title\n=====\n"})
    assert check_rst._resolve_xref_target(env, "index", "doc", "no-such-page") is None


@pytest.mark.integration
def test_resolve_xref_target_ref_resolves_label(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "index": "Title\n=====\n\n.. _my-label:\n\nSection\n-------\n",
        },
    )
    assert check_rst._resolve_xref_target(env, "index", "ref", "my-label") == "index"


@pytest.mark.integration
def test_resolve_xref_target_unknown_reftype_returns_none(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(check_rst, tmp_path, {"index": "Title\n=====\n"})
    assert check_rst._resolve_xref_target(env, "index", "obj", "whatever") is None


@pytest.mark.integration
def test_find_references_outgoing_doc_and_ref_in_document_order(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "index": """\
            Title
            =====

            :doc:`other`

            See :ref:`other-label`.
            """,
            "other": "Other\n=====\n\n.. _other-label:\n\nSection\n-------\n",
        },
    )
    entries = check_rst.find_references(env, "index")
    assert [e.reftype for e in entries] == ["doc", "ref"]
    assert entries[0].target == "other"
    assert entries[0].resolved == "other"
    assert entries[1].target == "other-label"
    assert entries[1].resolved == "other"
    assert entries[0].lineno < entries[1].lineno


@pytest.mark.integration
def test_find_references_broken_target_resolved_is_none(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "index": "Title\n=====\n\n:doc:`nonexistent`\n",
        },
    )
    entries = check_rst.find_references(env, "index")
    assert len(entries) == 1
    assert entries[0].resolved is None


@pytest.mark.integration
def test_find_incoming_references_finds_pointing_docs(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "a": "A\n=\n\n:doc:`b`\n",
            "b": "B\n=\n\n.. _shared-label:\n\nSection\n-------\n",
            "c": "C\n=\n\nSee :ref:`shared-label`.\n",
        },
    )
    incoming = check_rst.find_incoming_references(env, "b")
    assert {e.docname for e in incoming} == {"a", "c"}


@pytest.mark.integration
def test_find_incoming_references_empty_when_nothing_points_at_it(check_rst: types.ModuleType, tmp_path: Path) -> None:
    env = _build_multi_file_env(
        check_rst,
        tmp_path,
        {
            "index": "Title\n=====\n",
            "lonely": "Lonely\n======\n",
        },
    )
    assert check_rst.find_incoming_references(env, "lonely") == []


@pytest.mark.integration
def test_cli_refs_shows_outgoing_and_incoming(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\nroot_doc = "a"\n', encoding="utf-8")
    (rst_repo / "a.rst").write_text("A\n=\n\n:doc:`b`\n", encoding="utf-8")
    b = rst_repo / "b.rst"
    b.write_text("B\n=\n\n:doc:`a`\n", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "--sphinx-src", str(rst_repo), "refs", str(b)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "outgoing" in out
    assert "-> a" in out
    assert "incoming" in out
    assert "a:" in out


@pytest.mark.integration
def test_cli_refs_includes_parent_and_globbed_child_toctree_edges(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Toctrees are document references too, including glob-expanded entries."""
    (rst_repo / "conf.py").write_text(
        'project = "test"\nextensions = []\nroot_doc = "index"\n',
        encoding="utf-8",
    )
    (rst_repo / "index.rst").write_text(
        "Root\n====\n\n.. toctree::\n\n   organs/index\n",
        encoding="utf-8",
    )
    organs = rst_repo / "organs"
    (organs / "alpha").mkdir(parents=True)
    (organs / "beta").mkdir()
    target = organs / "index.rst"
    target.write_text(
        "Organizations\n=============\n\n.. toctree::\n   :glob:\n\n   */index\n",
        encoding="utf-8",
    )
    (organs / "alpha" / "index.rst").write_text("Alpha\n=====\n", encoding="utf-8")
    (organs / "beta" / "index.rst").write_text("Beta\n====\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "refs", str(target)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "toctree -> organs/alpha/index (organs/alpha/index)" in out
    assert "toctree -> organs/beta/index (organs/beta/index)" in out
    assert "index:4: toctree -> organs/index" in out


@pytest.mark.integration
def test_cli_refs_requires_sphinx_src(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "index.rst"
    p.write_text("Title\n=====\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "refs", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--sphinx-src DIR" in out
    assert "--config FILE" in out


@pytest.mark.integration
def test_cli_refs_file_not_part_of_project(
    check_rst: types.ModuleType,
    rst_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text("Title\n=====\n", encoding="utf-8")
    # rst_repo IS tmp_path (tmp_git_repo returns it directly) — a genuinely
    # unreachable file must live outside it, same precedent as
    # test_docname_for_unreachable_file_returns_none.
    outside = tmp_path.parent / "not_in_this_project.rst"
    outside.write_text("Title\n=====\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--sphinx-src", str(rst_repo), "refs", str(outside)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    assert "not part of" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_refs_missing_file_errors_cleanly(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    missing = rst_repo / "missing.rst"
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--sphinx-src", str(rst_repo), "refs", str(missing)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    assert "missing.rst" in capsys.readouterr().out


@pytest.mark.integration
def test_cli_json_valid_and_complete(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "Title\n=====\n\n**Bold Heading**\n\nHe wrote:\n\n    Quoted text.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1  # underline-only ERROR — exit semantics unchanged
    out = capsys.readouterr().out
    data = json.loads(out)  # pure JSON — nothing else on stdout
    assert data["schema_version"] == 1
    assert data["mode"] == "heuristic"
    assert data["runtime"]["python"]["executable"] == sys.executable
    assert data["runtime"]["docutils"]["version"]
    assert data["runtime"]["sphinx"] is None
    assert data["runtime"]["snowballstemmer"] is None
    assert data["config"] is None  # no per-repo config in this sandbox
    (f,) = data["files"]
    assert f["path"].endswith("test.rst")
    assert any(x["severity"] == "ERROR" for x in f["findings"])
    assert any(x["severity"] == "WARNING" for x in f["findings"])
    assert f["outline"][0]["title"] == "Title"
    assert f["block_quotes"][0]["preview"] == "Quoted text."
    assert f["stats"]["lines"] == 8
    assert data["summary"]["errors"] >= 1


@pytest.mark.integration
def test_cli_json_no_warnings_filters_records_and_summary(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    document.write_text("#######\nTitle\n#######\n\n**Heading-like text**\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", "--no-warnings", str(document)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["warnings"] == 0
    assert all(finding["severity"] != "WARNING" for finding in data["files"][0]["findings"])


@pytest.mark.integration
def test_cli_json_no_warnings_filters_sphinx_findings(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    document = rst_repo / "index.rst"
    document.write_text("#######\nTitle\n#######\n\nSee :doc:`missing`.\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "check", "--format=json", "--no-warnings", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["warnings"] == 0
    assert data.get("sphinx_findings", []) == []


@pytest.mark.integration
def test_cli_json_stable_section_ids(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Outline entries carry a stable id in the autosectionlabel convention
    (docname:title) — an AI can say 'insert after <id>' without line
    numbers."""
    sub = rst_repo / "docs"
    sub.mkdir()
    p = sub / "guide.rst"
    p.write_text("#######\nTitle\n#######\n\nText.\n", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    assert data["files"][0]["outline"][0]["id"] == "docs/guide:Title"


@pytest.mark.integration
def test_cli_json_section_ids_are_unique_for_duplicate_titles(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "doc.rst"
    document.write_text(
        textwrap.dedent("""\
            #######
            Title
            #######

            **********
            Repeated
            **********

            Text.

            **********
            Repeated
            **********
            """),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(document)])

    with pytest.raises(SystemExit):
        check_rst.main()

    data = json.loads(capsys.readouterr().out)
    ids = [entry["id"] for entry in data["files"][0]["outline"]]
    assert ids == ["doc:Title", "doc:Repeated", "doc:Repeated#2"]


@pytest.mark.integration
def test_outline_section_extents(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A section's extent runs from its title line to the last content line
    before the next same-or-shallower section's block (overline included),
    trailing blank separator lines trimmed; the last section runs to EOF."""
    p = _rst(
        tmp_path,
        """\
        Root
        ####

        Intro.

        Sub A
        =====

        Body A.

        Sub B
        =====

        Body B.
        """,
    )
    entries = check_rst.build_outline(p)
    assert [(e.title, e.lineno, e.end) for e in entries] == [
        ("Root", 1, 14),
        ("Sub A", 6, 9),  # blank line 10 before Sub B trimmed
        ("Sub B", 11, 14),
    ]


@pytest.mark.integration
def test_block_quote_multiline_extent(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A multi-paragraph quote reports its full range; a single-line quote
    keeps the single-number format."""
    p = _rst(
        tmp_path,
        "Intro:\n\n    First quoted line.\n\n    Second quoted paragraph.\n\nAfter.\n",
    )
    entries = check_rst.find_block_quotes(p)
    assert len(entries) == 1
    assert (entries[0].lineno, entries[0].end) == (3, 5)
    assert str(entries[0]).startswith('3-5: blockquote "')

    single = _rst(tmp_path / "sub" if False else tmp_path, "Intro:\n\n    One line.\n")
    entries = check_rst.find_block_quotes(single)
    assert str(entries[0]) == '3: blockquote "One line."'


@pytest.mark.integration
def test_heuristic_code_block_extent(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """A code-block's extent covers the directive line through the last
    indented content line."""
    p = _rst(
        tmp_path,
        "Title\n=====\n\n.. code-block:: python\n\n    x = 1\n    y = 2\n\nAfter.\n",
    )
    entries = check_rst.find_code_blocks_heuristic(p)
    assert len(entries) == 1
    assert (entries[0].lineno, entries[0].end) == (4, 7)
    assert str(entries[0]) == "    4-7: code-block (python): x = 1 y = 2"


@pytest.mark.integration
def test_cli_json_outline_carries_extent(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    entry = data["files"][0]["outline"][0]
    assert entry["lineno"] == 4
    assert entry["end"] == 7


@pytest.mark.integration
def test_document_prose_text_skips_code_comments_topics(check_rst: types.ModuleType, tmp_path: Path) -> None:
    """Prose is what the author wrote as text: titles and paragraphs —
    not code content, not comments, not generated topics (.. contents::)."""
    p = _rst(
        tmp_path,
        """\
        Title
        =====

        .. contents:: Contents

        Real prose here.

        .. code:: python

            SECRETTOKEN = 1

        .. a comment HIDDENWORD

        Final paragraph.
        """,
    )
    doc = check_rst.Document(p)
    assert "Real prose here." in doc.prose_text
    assert "Title" in doc.prose_text
    assert "Final paragraph." in doc.prose_text
    assert "SECRETTOKEN" not in doc.prose_text
    assert "HIDDENWORD" not in doc.prose_text
    assert "Contents" not in doc.prose_text


@pytest.mark.integration
def test_cli_footer_top_prose_words(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Footer line 4: stopwords filtered (en/ru/fr), counts case-insensitive,
    ordered by frequency."""
    p = rst_repo / "test.rst"
    p.write_text(
        "#########\nproduct\n#########\n\n"
        "The product and the server de la maison \u0438 \u0441\u0435\u0440\u0432\u0435\u0440.\n\n"
        "product server again.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "top prose words: product (3 @2), server (2 @5)" in out
    assert "the (" not in out  # stopwords never appear


@pytest.mark.unit
def test_stopword_sets_pins_known_words_all_three_languages(
    check_rst: types.ModuleType,
) -> None:
    """Regression guard, strengthened: the single existing membership check
    ("the" in English) said nothing about Russian or French ever
    resolving to real content — pin several common words per language."""
    sets = check_rst._stopword_sets()
    assert {"the", "and", "a", "over", "again"} <= sets["en"]
    assert {"и", "в", "на"} <= sets["ru"]
    assert {"le", "la", "de", "et"} <= sets["fr"]


@pytest.mark.integration
def test_cli_footer_top_prose_words_excludes_english_stopwords(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dedicated English fixture, several distinct stopwords at once —
    the existing test above only ever excludes "the"."""
    p = rst_repo / "test.rst"
    p.write_text(
        "#########\nproduct\n#########\n\n"
        "The product and the server over the network. product server "
        "communicate again. product server run again.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "product (4 @2), server (3 @5)" in out
    # Word-boundary match: a naive substring check falsely matches inside
    # a longer word ending in the same letters — confirmed live on the
    # Russian fixture below, where a bare-substring check on the "and"
    # stopword matched inside the unrelated "data" content word.
    for stopword in ("the", "and", "over", "again"):
        assert not re.search(rf"\b{stopword} \(", out), stopword


@pytest.mark.integration
def test_cli_footer_top_prose_words_excludes_russian_stopwords(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dedicated Russian fixture — no prior test asserted a Russian
    stopword's absence by name at all.  Cyrillic via \\uXXXX escapes
    (ruff RUF001/RUF003): "sensor"/"server" are the content words
    under test; "and"/"in"/"on" are the stopwords under test."""
    title = "\u0414\u0430\u0442\u0447\u0438\u043a"  # Sensor (capitalized, as title)
    sensor = "\u0434\u0430\u0442\u0447\u0438\u043a"  # sensor
    server = "\u0441\u0435\u0440\u0432\u0435\u0440"  # server
    room = "\u043a\u043e\u043c\u043d\u0430\u0442\u0435"  # room
    works = "\u0440\u0430\u0431\u043e\u0442\u0430\u0435\u0442"  # works
    exchange = "\u043e\u0431\u043c\u0435\u043d\u0438\u0432\u0430\u044e\u0442\u0441\u044f"  # exchange
    data = "\u0434\u0430\u043d\u043d\u044b\u043c\u0438"  # data
    network = "\u0441\u0435\u0442\u0438"  # network
    and_ = "\u0438"  # and
    in_ = "\u0432"  # in
    on_ = "\u043d\u0430"  # on
    p = rst_repo / "test.rst"
    p.write_text(
        f"########\n{title}\n########\n\n"
        f"{sensor} {and_} {server} "
        f"{in_} {room}. {sensor} "
        f"{works} {on_} {server}. "
        f"{sensor} {and_} {server} "
        f"{exchange} "
        f"{data} {in_} {network}.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    # Sensor/server: content words, high frequency.
    assert f"{sensor} (4 @2), {server} (3 @5)" in out
    # Word-boundary match: a naive substring check on the "and" stopword
    # falsely matches inside the "data" content word above (which ends
    # in the same letter) — confirmed live, this is exactly why the
    # check needs a boundary, not just the other two languages' luck at
    # avoiding it.
    for stopword in (and_, in_, on_):
        assert not re.search(rf"\b{stopword} \(", out), stopword


@pytest.mark.integration
def test_cli_footer_top_prose_words_excludes_french_stopwords(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dedicated French fixture — no prior test asserted a French
    stopword's absence by name at all."""
    p = rst_repo / "test.rst"
    p.write_text(
        "#########\nCapteur\n#########\n\n"
        "Le capteur et le serveur. Le capteur fonctionne sur le serveur. "
        "Le capteur et le serveur échangent des données.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "capteur (4 @2), serveur (3 @5)" in out
    for stopword in ("le", "et", "de", "sur"):
        assert not re.search(rf"\b{stopword} \(", out), stopword


@pytest.mark.integration
def test_cli_footer_top_words_stem_grouping_shows_surface_form(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Inflections group via stemming, but the displayed word is the most
    frequent REAL surface form — never a stem."""
    p = rst_repo / "test.rst"
    # Cyrillic via escapes (ruff RUF001): Заголовок / Проблемы и проблемы
    # дают проблема.
    p.write_text(
        "#########\n\u0417\u0430\u0433\u043e\u043b\u043e\u0432\u043e\u043a\n#########\n\n"
        "\u041f\u0440\u043e\u0431\u043b\u0435\u043c\u044b \u0438 \u043f\u0440\u043e\u0431\u043b\u0435\u043c\u044b \u0434\u0430\u044e\u0442 \u043f\u0440\u043e\u0431\u043b\u0435\u043c\u0430.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "\u043f\u0440\u043e\u0431\u043b\u0435\u043c\u044b (3 @5)" in out
    assert "\u043f\u0440\u043e\u0431\u043b\u0435\u043c (" not in out.replace(
        "\u043f\u0440\u043e\u0431\u043b\u0435\u043c\u044b (", ""
    )  # no bare stems


@pytest.mark.integration
def test_cli_json_top_words(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "#########\nproduct\n#########\n\nproduct server and server product.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", "--word-samples", "10", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    top, suppressed = data["files"][0]["stats"]["top_words"]
    assert top[0] == ["product", 3]
    assert top[1] == ["server", 2]
    assert suppressed == 0


@pytest.mark.integration
def test_cli_footer_top_words_bounded_with_suppression_note(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Top-10 shown (--word-samples default), the rest counted — bounded
    output, never silent truncation (Max: 'word 1, word 2, ... (yet N
    suppressed)')."""
    p = rst_repo / "test.rst"
    nato = [
        "bravo",
        "charlie",
        "delta",
        "echo",
        "foxtrot",
        "golf",
        "hotel",
        "india",
        "juliett",
        "kilo",
        "lima",
        "mike",
        "november",
        "oscar",
        "papa",
    ]
    words = " ".join(["alpha"] * 3 + nato)
    p.write_text(f"#######\nTitle\n#######\n\n{words}.\n", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--word-samples", "10", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "top prose words: alpha (3 @" in out
    # 17 groups total (15 nato words + alpha + title), 10 shown, 7 suppressed
    assert "(yet 7 suppressed)" in out


@pytest.mark.integration
def test_cli_footer_rare_words_with_sibling_annotation(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A once-word with a frequent close sibling is annotated with the
    fact — '(~sibling Nx)' — and sorts first; plain once-words follow;
    identifier debris (mixed alphanumerics) is excluded."""
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\n"
        "The server processes data; processes run; processes wait.\n\n"
        "One procesess appears here; zebra abc123def.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "rare prose words: procesess @7 (~processes 3x)" in out
    assert "zebra" in out
    assert "abc123def" not in out  # debris filter


@pytest.mark.integration
def test_cli_footer_rare_words_bounded(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    nato = [
        "bravo",
        "charlie",
        "delta",
        "echo",
        "foxtrot",
        "golf",
        "hotel",
        "india",
        "juliett",
        "kilo",
        "lima",
        "mike",
        "november",
        "oscar",
        "papa",
        "quebec",
    ]
    p = rst_repo / "test.rst"
    p.write_text("#######\nTitle\n#######\n\n" + " ".join(nato) + ".\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--word-samples", "10", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    # 17 once-groups (16 nato + title), 10 shown, 7 suppressed
    assert "rare prose words: " in out
    line = next(ln for ln in out.splitlines() if ln.startswith("rare prose words"))
    assert "(yet 7 suppressed)" in line


@pytest.mark.integration
def test_cli_json_rare_words(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\n"
        "The server processes data; processes run; processes wait.\n\n"
        "One procesess appears.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", "--word-samples", "10", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    rare, suppressed = data["files"][0]["stats"]["rare_words"]
    assert ["procesess", "processes", 3] in rare
    assert isinstance(suppressed, int)


@pytest.mark.integration
def test_prose_grouping_detects_french_documents(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The en/fr stopword lists double as a language detector: a French
    document routes Latin tokens to the FRENCH stemmer, so inflections
    (vérifie / vérifier / vérifiée — 1sg, infinitive, participle) form ONE
    group instead of three rare words with misleading annotations (Max, on
    a downstream project's page: 'wrong language taken as a base for another
    language').  Snowball reality check: the French stemmer unifies the
    infinitive and the participle (vérifier/vérifiée -> vérifi) but stems
    the 1sg differently (vérifie -> vérif) — so the grouping proof is
    'vérifier (2)', and vérifie appears rare WITH the one-edit
    annotation (~vérifier): the edit-distance fact catches exactly the
    inflection pair the stemmer misses, and the human (who named the
    pair: 1sg and infinitive) judges it instantly."""
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitre\n#######\n\nLe serveur vérifie la connexion; il faut vérifier; elle est vérifiée.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "vérifier (2 @" in out  # infinitive+participle: ONE group of two
    rare = next(ln for ln in out.splitlines() if ln.startswith("rare prose words"))
    assert "vérifie @5 (~vérifier 2x)" in rare  # the one-edit fact fills the stemmer's gap


@pytest.mark.integration
def test_cli_rare_words_catches_the_confessed_mistake(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The journal-attested case this feature exists for: Max's habitual
    Russian mistake (one substitution) against the frequent correct form
    — missed by the 0.87 similarity cutoff (0.857), caught by the
    one-edit-apart criterion.  Cyrillic via escapes (ruff RUF001):
    померил x3, померял x1."""
    ok = "померил"  # померил
    bad = "померял"  # померял
    dav = "давление"  # давление
    p = rst_repo / "test.rst"
    p.write_text(
        f"#########\nTitle\n#########\n\n{ok} {dav}. {ok} {dav}. {ok} {dav}. {bad} {dav}.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert f"rare prose words: {bad} @5 (~{ok} 3x)" in out


@pytest.mark.integration
def test_cli_rare_words_annotates_once_vs_once_pair(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A small page's typo signature is TWO once-words one edit apart —
    fameworks/frameworks on a real 2025 note (the typo even lives in the
    linked filename).  No frequency threshold on the sibling — and the
    symmetric fact is reported ONCE, as 'a ↔ b', never as two reciprocal
    annotations (the "loop" display Max flagged)."""
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\nDetect the JS frameworks today.\n\nSee the fameworks page again.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    rare = next(ln for ln in out.splitlines() if ln.startswith("rare prose words"))
    assert "fameworks @7 \u2194 frameworks @5" in rare  # one symmetric fact, with jump targets
    assert "(~fameworks" not in rare  # no reciprocal annotation
    assert "(~frameworks" not in rare


@pytest.mark.integration
def test_prose_statistics_on_realistic_journal_note(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Modeled on calendar/2025/06/2025-06-25/Notes.rst — the reference
    note for this feature (Max: the AI reads the content and sees the
    repetitions; the tool counts).  The fixture reproduces the note's
    phenomena: trilingual prose, a :doc: role bare docutils can't
    resolve, a Sphinx code-block with :caption: and French tool output
    inside, the auto-generated toctree apparatus, and the typo pair.

    Semantic expectations (the AI's half):
    - top words are the AUTHOR's repetitions — never docutils' own
      error vocabulary ('unknown directive type', 'no role entry')
      leaking through system_message nodes: the bug this test caught
      on the real note, where top-3 was doc/directive/role;
    - code-block content (including its French wget chatter) and the
      toctree entries are not prose;
    - the typo pair surfaces as one symmetric fact."""
    ok = "кондей"  # kondej — the repeated theme word
    got_up = "встал"  # vstal
    became = "стал"  # stal
    became2 = "стало"  # stalo — same lexeme as стал, stems together
    p = rst_repo / "test.rst"
    p.write_text(
        "#########\nWednesday\n#########\n\n"
        f"{ok} работает. {ok} гудит. Чинил {ok} снова.\n\n"
        f"{got_up} рано. {became} запускать сервер. Потом {became2} тихо.\n\n"
        "Detect the JS frameworks:\n"
        ":doc:`./16-15 HTML and JS fameworks of restserver`\n\n"
        ".. code-block:: shell\n"
        "   :caption: Скачка\n\n"
        "   wget https://cdn.example.net/van.js\n"
        "   Résolution de cdn.example.net... connecté.\n\n"
        ".. toctree::\n"
        "   :maxdepth: 1\n\n"
        "   16-15 HTML and JS fameworks of restserver\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    top = next(ln for ln in out.splitlines() if ln.startswith("top prose"))
    rare = next(ln for ln in out.splitlines() if ln.startswith("rare prose"))

    # The author's repetition leads — not the parser's error vocabulary.
    assert f"top prose words: {ok} (3 @5)" in top
    for parser_noise in ("directive", "unknown", "role", "caption", "canonical"):
        assert parser_noise not in top
        assert parser_noise not in rare
    # Code-block content is not prose (its French chatter neither).
    assert "wget" not in top + rare
    assert "résolution" not in (top + rare).lower()
    # The same-lexeme pair groups (стал+стало), and the annotation shows
    # the legit-pair fact for встал.
    assert f"{got_up} @7 (~{became} 2x)" in rare
    # The typo pair: one symmetric fact (role text vs title; toctree
    # apparatus does not inflate the counts).
    assert "fameworks @10 ↔ frameworks @9" in rare


@pytest.mark.unit
def test_find_stopwords_accepts_either_known_casing(check_rst: types.ModuleType) -> None:
    uppercase_mod = types.SimpleNamespace(ENGLISH_STOPWORDS={"the", "a"})  # sphinx 9.1.0 (gl63)
    lowercase_mod = types.SimpleNamespace(english_stopwords={"the", "a"})  # sphinx 8.2.3 (this host)

    names = ("ENGLISH_STOPWORDS", "english_stopwords")
    assert check_rst._find_stopwords(uppercase_mod, names) == frozenset({"the", "a"})
    assert check_rst._find_stopwords(lowercase_mod, names) == frozenset({"the", "a"})


@pytest.mark.unit
def test_find_stopwords_raises_when_neither_name_present(
    check_rst: types.ModuleType,
) -> None:
    """A third casing (sphinx renamed it again) must raise — never
    silently return an empty set mistaken for 'no stopwords'."""
    renamed_again_mod = types.SimpleNamespace(SOME_OTHER_NAME={"the", "a"})
    renamed_again_mod.__name__ = "renamed_again_mod"

    with pytest.raises(check_rst.StopwordsUnavailable, match="renamed_again_mod"):
        check_rst._find_stopwords(renamed_again_mod, ("ENGLISH_STOPWORDS", "english_stopwords"))


@pytest.mark.unit
def test_stopword_sets_returns_nonempty_sets_for_all_three_languages(
    check_rst: types.ModuleType,
) -> None:
    """Regression guard for the reported bug: against the REAL installed
    sphinx (whichever casing it uses), _stopword_sets() must resolve —
    not silently return None."""
    sets = check_rst._stopword_sets()
    assert set(sets) == {"en", "ru", "fr"}
    assert all(sets[lang] for lang in sets)
    assert "the" in sets["en"]


@pytest.mark.unit
def test_stopword_sets_raises_when_sphinx_search_not_importable(
    check_rst: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sphinx.search unimportable must raise, not silently return None."""
    check_rst._stopword_sets.cache_clear()
    monkeypatch.setitem(sys.modules, "sphinx.search.en", None)
    try:
        with pytest.raises(check_rst.StopwordsUnavailable):
            check_rst._stopword_sets()
    finally:
        check_rst._stopword_sets.cache_clear()


@pytest.mark.unit
def test_prose_stemmers_raise_instead_of_silently_degrading(
    check_rst: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_rst._prose_stemmers.cache_clear()
    monkeypatch.setitem(sys.modules, "snowballstemmer", None)
    try:
        with pytest.raises(check_rst.WordStatsUnavailable, match="snowballstemmer"):
            check_rst._prose_stemmers()
    finally:
        check_rst._prose_stemmers.cache_clear()


@pytest.mark.integration
def test_cli_footer_explicit_warning_when_stopwords_unavailable(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The footer must say so explicitly and count it as a warning — never
    silently omit the top/rare prose words lines with zero trace.  The
    warning must also land in Line 1's own count (computed ahead of that
    print), not just appear after it already printed 0."""
    p = rst_repo / "test.rst"
    p.write_text("#######\nTitle\n#######\n\nSome prose words here.\n", encoding="utf-8")

    def _boom() -> dict[str, set[str]]:
        raise check_rst.StopwordsUnavailable("sphinx.search.en has neither X nor Y")

    monkeypatch.setattr(check_rst._reports, "_stopword_sets", _boom)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", "--verbose", str(p)])
    with pytest.raises(SystemExit) as exc_info:
        check_rst.main()
    assert exc_info.value.code == 0  # a broken cosmetic stat must not fail the run
    out = capsys.readouterr().out
    assert "WARNING: top/rare prose words unavailable — sphinx.search.en has neither X nor Y" in out
    assert "top prose words:" not in out
    assert "rare prose words:" not in out
    summary = next(ln for ln in out.splitlines() if ln.startswith("check_rst:"))
    assert "1 warning(s)" in summary


@pytest.mark.integration
def test_cli_json_word_stats_error_when_stopwords_unavailable(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--json gets the same explicit, counted failure: null stats plus a
    named reason, never a bare null with no way to tell why."""
    p = rst_repo / "test.rst"
    p.write_text("#######\nTitle\n#######\n\nSome prose words here.\n", encoding="utf-8")

    def _boom() -> dict[str, set[str]]:
        raise check_rst.StopwordsUnavailable("sphinx.search.en has neither X nor Y")

    monkeypatch.setattr(check_rst._reports, "_stopword_sets", _boom)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", "--word-samples", "10", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    data = json.loads(capsys.readouterr().out)
    stats = data["files"][0]["stats"]
    assert stats["top_words"] is None
    assert stats["rare_words"] is None
    assert "sphinx.search.en has neither X nor Y" in stats["word_stats_error"]


@pytest.mark.integration
def test_cli_no_warnings_suppresses_word_stats_failure_warning(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = rst_repo / "test.rst"
    document.write_text(_GOOD_BLOCK + "\nSome prose words here.\n", encoding="utf-8")

    def _boom() -> dict[str, set[str]]:
        raise check_rst.StopwordsUnavailable("unavailable for test")

    monkeypatch.setattr(check_rst._reports, "_stopword_sets", _boom)
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "check", "--quiet", "--no-warnings", "--word-samples", "10", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "top/rare prose words unavailable" not in out
    assert "0 warning(s)" in out


def _json_dump(
    path: str = "doc.rst",
    outline: list[dict[str, Any]] | None = None,
    findings: list[dict[str, Any]] | None = None,
    files_checked: int = 1,
    errors: int = 0,
    warnings: int = 0,
    sphinx_findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a minimal --json-shaped dict for _diff_json_dumps tests —
    only the fields the diff actually reads."""
    data = {
        "files": [{"path": path, "outline": outline or [], "findings": findings or []}],
        "summary": {"files_checked": files_checked, "errors": errors, "warnings": warnings},
    }
    if sphinx_findings is not None:
        data["sphinx_findings"] = sphinx_findings
    return data


@pytest.mark.unit
def test_diff_json_dumps_summary_deltas(check_rst: types.ModuleType) -> None:
    old = _json_dump(warnings=74)
    new = _json_dump(warnings=95)
    diff = check_rst._diff_json_dumps(old, new)
    assert diff["summary"]["warnings"] == {"old": 74, "new": 95, "delta": 21}
    assert diff["summary"]["errors"] == {"old": 0, "new": 0, "delta": 0}


@pytest.mark.unit
def test_diff_json_dumps_outline_added_section_hierarchy_unchanged(
    check_rst: types.ModuleType,
) -> None:
    """The doc's own worked example: 'added subsection, hierarchy
    unchanged' — a new section id appears, but every surviving section
    keeps its (depth, char)."""
    old = _json_dump(
        outline=[
            {"id": "doc:Title", "depth": 1, "char": "#", "title": "Title"},
            {"id": "doc:Sub", "depth": 2, "char": "*", "title": "Sub"},
        ]
    )
    new = _json_dump(
        outline=[
            {"id": "doc:Title", "depth": 1, "char": "#", "title": "Title"},
            {"id": "doc:Sub", "depth": 2, "char": "*", "title": "Sub"},
            {"id": "doc:New", "depth": 2, "char": "*", "title": "New"},
        ]
    )
    diff = check_rst._diff_json_dumps(old, new)
    file_diff = diff["files"]["doc.rst"]
    assert file_diff["outline"]["added"] == ["doc:New"]
    assert file_diff["outline"]["removed"] == []
    assert file_diff["outline"]["hierarchy_changed"] == []
    assert file_diff["status"] == "changed"


@pytest.mark.unit
def test_diff_json_dumps_hierarchy_changed_flags_the_id(
    check_rst: types.ModuleType,
) -> None:
    """A surviving section that changed depth or char is named, not just
    flagged true/false — the reader needs to know WHICH one."""
    old = _json_dump(outline=[{"id": "doc:Sub", "depth": 2, "char": "*", "title": "Sub"}])
    new = _json_dump(outline=[{"id": "doc:Sub", "depth": 3, "char": "=", "title": "Sub"}])
    diff = check_rst._diff_json_dumps(old, new)
    assert diff["files"]["doc.rst"]["outline"]["hierarchy_changed"] == ["doc:Sub"]


@pytest.mark.unit
def test_diff_json_dumps_findings_added_and_resolved_matched_by_severity_and_text(
    check_rst: types.ModuleType,
) -> None:
    """Findings match on (severity, text), NOT line number — a finding
    that merely shifted lines because of an unrelated earlier edit must
    not appear as both resolved and added."""
    old = _json_dump(
        findings=[
            {"lineno": 10, "severity": "WARNING", "text": "bold paragraph opener 'Foo'"},
            {"lineno": 20, "severity": "WARNING", "text": "bold paragraph opener 'Gone'"},
        ]
    )
    new = _json_dump(
        findings=[
            {"lineno": 15, "severity": "WARNING", "text": "bold paragraph opener 'Foo'"},  # shifted, not new
            {"lineno": 30, "severity": "WARNING", "text": "bold paragraph opener 'New'"},
        ]
    )
    diff = check_rst._diff_json_dumps(old, new)
    findings = diff["files"]["doc.rst"]["findings"]
    assert findings["added"] == [{"severity": "WARNING", "text": "bold paragraph opener 'New'"}]
    assert findings["resolved"] == [{"severity": "WARNING", "text": "bold paragraph opener 'Gone'"}]


@pytest.mark.unit
def test_diff_json_dumps_compares_sphinx_findings_even_when_counts_cancel(
    check_rst: types.ModuleType,
) -> None:
    """One resolved and one added Sphinx warning must not look unchanged."""
    old = _json_dump(
        warnings=1,
        sphinx_findings=[{"lineno": 4, "severity": "WARNING", "text": "doc.rst: old warning"}],
    )
    new = _json_dump(
        warnings=1,
        sphinx_findings=[{"lineno": 8, "severity": "WARNING", "text": "doc.rst: new warning"}],
    )

    diff = check_rst._diff_json_dumps(old, new)

    assert diff["sphinx_findings"]["added"] == [{"severity": "WARNING", "text": "doc.rst: new warning"}]
    assert diff["sphinx_findings"]["resolved"] == [{"severity": "WARNING", "text": "doc.rst: old warning"}]
    assert "new warning" in check_rst._format_json_diff(diff)


@pytest.mark.unit
def test_diff_json_dumps_reports_runtime_provenance_change(
    check_rst: types.ModuleType,
) -> None:
    old = _json_dump()
    old.update(
        {
            "schema_version": 1,
            "mode": "verified",
            "runtime": {"sphinx": {"version": "8.2.3"}},
        }
    )
    new = _json_dump()
    new.update(
        {
            "schema_version": 1,
            "mode": "verified",
            "runtime": {"sphinx": {"version": "9.1.0"}},
        }
    )

    diff = check_rst._diff_json_dumps(old, new)

    assert "runtime" in diff["provenance"]["changed"]
    assert "provenance differs" in check_rst._format_json_diff(diff)


@pytest.mark.unit
def test_diff_json_dumps_unchanged_file_reports_unchanged_status(
    check_rst: types.ModuleType,
) -> None:
    same = _json_dump(outline=[{"id": "doc:T", "depth": 1, "char": "#", "title": "T"}])
    diff = check_rst._diff_json_dumps(same, same)
    assert diff["files"]["doc.rst"]["status"] == "unchanged"


@pytest.mark.unit
def test_diff_json_dumps_added_and_removed_files(check_rst: types.ModuleType) -> None:
    old = _json_dump(path="a.rst")
    new = _json_dump(path="b.rst")
    diff = check_rst._diff_json_dumps(old, new)
    assert diff["files"]["a.rst"] == {"status": "removed"}
    assert diff["files"]["b.rst"] == {"status": "added"}


@pytest.mark.integration
def test_cli_diff_json_end_to_end(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """End to end: two real --json dumps, one edit apart, compared via
    --diff-json — the report names the added finding and the summary
    delta, no manual eyeballing of two large JSON blobs required."""
    p = rst_repo / "test.rst"
    p.write_text("#######\nTitle\n#######\n\n**A point.**  Detail.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    old_json = capsys.readouterr().out
    (rst_repo / "old.json").write_text(old_json, encoding="utf-8")

    p.write_text(
        "#######\nTitle\n#######\n\n**A point.**  Detail.\n\n**Another point.**  More.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    new_json = capsys.readouterr().out
    (rst_repo / "new.json").write_text(new_json, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "diff-json", str(rst_repo / "old.json"), str(rst_repo / "new.json")],
    )
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "warnings" in out
    assert "1" in out
    assert "2" in out
    assert "Another point" in out


@pytest.mark.integration
def test_cli_diff_json_missing_file_errors_cleanly(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "diff-json", str(tmp_path / "missing1.json"), str(tmp_path / "missing2.json")],
    )
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "missing1.json" in out


@pytest.mark.integration
@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("not JSON", "invalid JSON"),
        ("[]", "top level must be an object"),
        ("{}", "missing required key"),
        ('{"files": [], "summary": {}}', "summary missing"),
    ],
)
def test_cli_diff_json_rejects_malformed_or_wrong_schema_cleanly(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    content: str,
    message: str,
) -> None:
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text(content, encoding="utf-8")
    new.write_text(json.dumps(_json_dump()), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "diff-json", str(old), str(new)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert message in out
    assert "Traceback" not in out


@pytest.mark.unit
def test_context_resolver_accepts_future_entry_kind_without_registration(
    check_rst: types.ModuleType,
) -> None:
    @dataclass(frozen=True)
    class FutureWidgetEntry:
        lineno: int
        depth: int
        label: str
        end: int

    entry = FutureWidgetEntry(12, 2, "Opaque widget", 15)

    matches = check_rst._resolve_context_matches([entry], "Opaque widget", "guide")

    assert len(matches) == 1
    assert matches[0].entry is entry
    assert matches[0].kind == "future widget"
    assert matches[0].selector == "guide:future-widget@12"


@pytest.mark.integration
def test_cli_context_list_item_reports_parent_path_and_adjacent_siblings(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\n* First item.\n* Target item.\n* Third item.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "context", "Target item.", str(p)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "kind: bullet item" in out
    assert "selector: test:bullet-item@6" in out
    assert "range: 6" in out
    assert "path:" in out
    assert 'section "Title"' in out
    assert "bullet list" in out
    assert "parent: test:bullet-list@5" in out
    assert "previous: test:bullet-item@5" in out
    assert "next: test:bullet-item@7" in out
    assert "children:\n  (none)" in out
    assert "references:\n  unavailable — verified Sphinx mode required" in out


@pytest.mark.integration
def test_cli_context_section_stable_id_and_applicable_finding(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\n********\nTarget\n********\n\n**Decision**\n\nDetails.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "context", "test:Target", str(p)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "kind: section" in out
    assert "selector: test:Target" in out
    assert "range: 6-11" in out
    assert "findings:" in out
    assert "standalone bold line 'Decision'" in out


@pytest.mark.integration
def test_cli_context_ambiguous_exact_match_lists_candidates_without_guessing(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\n* Repeat.\n* Repeat.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "context", "Repeat.", str(p)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "ambiguous: 2 exact matches" in out
    assert "candidates:" in out
    assert "test:bullet-item@5" in out
    assert "test:bullet-item@6" in out
    assert "Context:" not in out


@pytest.mark.integration
def test_cli_context_ambiguous_candidates_are_bounded_without_silent_truncation(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    items = "".join("* Repeat.\n" for _ in range(25))
    p.write_text(f"#######\nTitle\n#######\n\n{items}", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "context", "Repeat.", str(p)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "ambiguous: 25 exact matches" in out
    assert out.count(" — path:") == 20
    assert "(5 more candidates suppressed)" in out


@pytest.mark.integration
def test_cli_context_universal_selector_addresses_anonymous_container(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = rst_repo / "test.rst"
    p.write_text(
        "#######\nTitle\n#######\n\n* First.\n* Second.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_rst.py", "context", "test:bullet-list@5", str(p)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "kind: bullet list" in out
    assert "selector: test:bullet-list@5" in out
    assert "children:" in out
    assert "test:bullet-item@5" in out
    assert "test:bullet-item@6" in out


@pytest.mark.integration
def test_cli_context_requires_exactly_one_positional_file(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Under the subcommand redesign, context's parser defines exactly two
    positionals (ENTRY, FILE) — a third one is now an ordinary argparse
    "unrecognized arguments" (exit 2, message on stderr), not this
    project's own logic to pin down (that logic still checks the one
    surviving value rule — the file must end in .rst — see
    test_context_verb_rejects_empty_entry's sibling assertions in
    tests/test_cli_subcommands.py)."""
    one = rst_repo / "one.rst"
    two = rst_repo / "two.rst"
    one.write_text("Title\n=====\n", encoding="utf-8")
    two.write_text("Title\n=====\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "context", "Title", str(one), str(two)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


@pytest.mark.integration
def test_cli_context_verified_references_are_scoped_to_selected_entry(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    index = tmp_path / "index.rst"
    index.write_text(
        "Index\n=====\n\nSee :doc:`target`.\n",
        encoding="utf-8",
    )
    target = tmp_path / "target.rst"
    target.write_text(
        "Target\n======\n\nOutside\n-------\n\nSee :doc:`outside`.\n\nDetails\n-------\n\nSee :doc:`index`.\n",
        encoding="utf-8",
    )
    (tmp_path / "outside.rst").write_text("Outside\n=======\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(tmp_path), "context", "target:Details", str(target)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "outgoing (selected range):" in out
    assert "doc -> index (index)" in out
    assert "doc -> outside" not in out
    assert "incoming (document-level):" in out
    assert "index:" in out
    assert "doc -> target" in out


@pytest.mark.integration
def test_cli_context_resolves_nested_cross_file_toctree_in_its_source_document(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    index = tmp_path / "index.rst"
    child = tmp_path / "child.rst"
    grandchild = tmp_path / "grandchild.rst"
    index.write_text(
        "Index\n=====\n\n.. toctree::\n\n   child\n",
        encoding="utf-8",
    )
    child.write_text(
        "Child\n=====\n\n.. toctree::\n\n   grandchild\n",
        encoding="utf-8",
    )
    grandchild.write_text("Grandchild\n==========\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(tmp_path), "context", "child:toctree@4", str(index)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert f"Context: {child}" in out
    assert "selector: child:toctree@4" in out
    assert "index:toctree@4" in out
    assert 'child:Child — section "Child"' in out
    assert "parent: child:Child" in out
