# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Tests for check_rst.cli's _sphinx domain (Phase 2/3 Sphinx integration) — check_rst project

from __future__ import annotations

import collections
import json
import subprocess
import sys
import textwrap
import types
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from _support import _GOOD_BLOCK, BuildSphinxEnv, _build_multi_file_env
from docutils.parsers.rst import directives as docutils_directives
from docutils.parsers.rst.directives.misc import Include as DocutilsInclude

from check_rst import cli
from check_rst.cli import _composition, _document, _formatting, _helpers, _reports, _sphinx, _types

if TYPE_CHECKING:
    import docutils.nodes


@pytest.mark.unit
def test_tracking_include_uses_docutils_version_native_clip_identity(tmp_path: Path) -> None:
    """Cycle pre-detection preserves the active Docutils clip semantics."""
    source = tmp_path / "index.rst"
    option_spec = DocutilsInclude.option_spec
    assert option_spec is not None
    text_default = "" if option_spec["start-after"] is docutils_directives.unchanged_required else None
    clip = _composition._docutils_include_clip((None, None, None, None))
    assert clip == (None, None, text_default, text_default)
    assert _composition._active_include_cycle(
        str(source),
        clip,
        [(str(source), clip)],
    ) == str(source)


@pytest.mark.integration
def test_clip_span_unknown_encoding_hits_unparenthesized_except(tmp_path: Path) -> None:
    """Regression coverage for _clip_span's PEP 758 unparenthesized
    multi-except (Python 3.14 syntax, not a Python-2 typo — see the
    comment at its definition): an unknown codec name must raise
    LookupError from path.read_text, land in that except clause, and
    fall back to the inexact/no-span result rather than propagating."""
    target = tmp_path / "fragment.rst"
    target.write_text("Body.\n", encoding="utf-8")

    result = _composition._clip_span(target, {"encoding": "totally-bogus-codec-xyz"})

    assert result == (0, None, False)


@pytest.mark.integration
def test_composition_source_lines_unknown_encoding_hits_unparenthesized_except(tmp_path: Path) -> None:
    """Same PEP 758 except clause, the second of this module's two sites
    (CompositionIndex.source_lines) — an include whose declared encoding
    doesn't exist must fall back to an empty line list, not crash or
    silently propagate LookupError."""
    root = tmp_path / "index.rst"
    (tmp_path / "fragment.rst").write_text("Body.\n", encoding="utf-8")
    doctree = _helpers._parse_rst(root, "Index\n=====\n")
    composition = _composition.CompositionIndex(doctree, root, tmp_path)
    provenance = _types.SourceProvenance(
        source="fragment.rst",
        origin=_types.SourceOrigin.INCLUDE,
        include_chain=(
            _types.IncludeSite(
                source="index.rst",
                lineno=1,
                target="fragment.rst",
                mode="parsed",
                options=(("encoding", "totally-bogus-codec-xyz"),),
            ),
        ),
        exact=True,
    )

    lines = composition.source_lines(provenance, root, ["Index", "====="])

    assert lines == []


@pytest.mark.integration
def test_docname_for_unreachable_file_returns_none(tmp_path: Path) -> None:
    """A file outside the Sphinx project's source tree resolves to None,
    not a crash — Phase 2 must be able to skip it gracefully."""
    (tmp_path / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (tmp_path / "index.rst").write_text("Title\n=====\n", encoding="utf-8")
    env, _ = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    outside = tmp_path.parent / "not_in_this_project.rst"
    assert _sphinx._docname_for(env, outside) is None


@pytest.mark.integration
def test_verified_structure_finders_share_prefetched_doctree_and_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    root = tmp_path / "index.rst"
    root.write_text(
        "Index\n=====\n\n.. include:: fragment.rst\n\n.. code-block:: python\n\n   pass\n",
        encoding="utf-8",
    )
    (tmp_path / "fragment.rst").write_text("Included\n--------\n", encoding="utf-8")
    env, _warnings = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    document = _document.Document(root, tmp_path)
    tree = env.get_doctree("index")
    composition = _composition.CompositionIndex(tree, root, tmp_path)

    def reject_refetch(_docname: str) -> None:
        raise AssertionError("duplicate env.get_doctree call")

    monkeypatch.setattr(env, "get_doctree", reject_refetch)

    assert _sphinx.find_code_blocks(
        env,
        "index",
        document.lines,
        document,
        doctree=tree,
        composition=composition,
    )
    assert _document.build_outline(
        root,
        doc=document,
        doctree=tree,
        source_root=tmp_path,
        composition=composition,
    )
    assert (
        _sphinx.find_toctrees(
            env,
            "index",
            document,
            doctree=tree,
            composition=composition,
        )
        == []
    )
    assert _sphinx.find_includes(
        env,
        "index",
        document,
        doctree=tree,
        composition=composition,
    )
    assert (
        _sphinx.find_conditionals(
            env,
            "index",
            document,
            doctree=tree,
            composition=composition,
        )
        == []
    )


@pytest.mark.integration
def test_cli_verified_mode_accepts_orphan_inside_sphinx_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Toctree reachability is not Sphinx membership: orphans are still parsed."""
    (tmp_path / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    (tmp_path / "index.rst").write_text("Index\n=====\n", encoding="utf-8")
    orphan = tmp_path / "orphan.rst"
    orphan.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(tmp_path),
            "check",
            "--quiet",
            str(orphan),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert "not part of" not in capsys.readouterr().out


@pytest.mark.integration
def test_html_title_enforcement_resolves_standard_conditionals(tmp_path: Path) -> None:
    """Only the branch active for check_rst's HTML integrity build is structural."""
    (tmp_path / "conf.py").write_text(
        'project = "test"\nextensions = ["sphinx.ext.ifconfig"]\nshow_extra = False\n',
        encoding="utf-8",
    )
    document_path = tmp_path / "index.rst"
    document_path.write_text(
        textwrap.dedent("""\
            #####
            Index
            #####

            .. only:: html

               ##########
               HTML title
               ##########

            .. only:: latex

               ###########
               LaTeX title
               ###########

            .. ifconfig:: show_extra

               ############
               Hidden title
               ############
            """),
        encoding="utf-8",
    )
    env, _warnings = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    doctree = _sphinx.resolve_html_structure(env, "index")

    findings = _formatting.check_single_top_level(
        document_path,
        doc=_document.Document(document_path, tmp_path),
        doctree=doctree,
        source_root=tmp_path,
    )

    assert len(findings) == 1
    assert findings[0].severity == "ERROR"
    assert "HTML title" in findings[0].text
    assert "LaTeX title" not in findings[0].text
    assert "Hidden title" not in findings[0].text


@pytest.mark.integration
def test_html_title_enforcement_preserves_conf_py_custom_tags(tmp_path: Path) -> None:
    (tmp_path / "conf.py").write_text(
        'project = "test"\ntags.add("edition")\n',
        encoding="utf-8",
    )
    document_path = tmp_path / "index.rst"
    document_path.write_text(
        textwrap.dedent("""\
            #######
            Index
            #######

            .. only:: edition

               ##########
               Tagged title
               ##########
            """),
        encoding="utf-8",
    )
    env, _warnings = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")

    findings = _formatting.check_single_top_level(
        document_path,
        doc=_document.Document(document_path, tmp_path),
        doctree=_sphinx.resolve_html_structure(env, "index"),
        source_root=tmp_path,
    )

    assert len(findings) == 1
    assert "Tagged title" in findings[0].text


@pytest.mark.integration
def test_verified_cli_checks_source_read_effective_titles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verified mode must not reuse Phase 1's pre-extension title answer."""
    (tmp_path / "conf.py").write_text(
        textwrap.dedent("""\
            project = "test"

            def add_title(app, docname, source):
                if docname == "index":
                    source[0] += "\\n##########\\nInjected\\n##########\\n"

            def setup(app):
                app.connect("source-read", add_title)
            """),
        encoding="utf-8",
    )
    document = tmp_path / "index.rst"
    document.write_text("#######\nIndex\n#######\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst",
            "--sphinx-src",
            str(tmp_path),
            "check",
            "--skip-fixable",
            str(document),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "index.rst:0: ERROR: second effective top-level title 'Injected'" in output


@pytest.mark.integration
def test_title_enforcement_keeps_rst_epilogue_provenance(tmp_path: Path) -> None:
    """Synthetic Sphinx content remains visible without a fake physical line."""
    (tmp_path / "conf.py").write_text(
        'project = "test"\nrst_epilog = "\\n########\\nEpilogue\\n########\\n"\n',
        encoding="utf-8",
    )
    document_path = tmp_path / "index.rst"
    document_path.write_text("#######\nIndex\n#######\n", encoding="utf-8")
    env, _warnings = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")

    findings = _formatting.check_single_top_level(
        document_path,
        doc=_document.Document(document_path, tmp_path),
        doctree=_sphinx.resolve_html_structure(env, "index"),
        source_root=tmp_path,
    )

    assert len(findings) == 1
    assert findings[0].source == "<rst_epilogue>"
    assert findings[0].lineno == 0
    assert "Epilogue" in findings[0].text


@pytest.mark.integration
def test_cli_verified_mode_rejects_file_excluded_by_sphinx_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Inside srcdir is insufficient when Sphinx itself excluded the source."""
    (tmp_path / "conf.py").write_text(
        'project = "test"\nexclude_patterns = ["excluded.rst"]\n',
        encoding="utf-8",
    )
    (tmp_path / "index.rst").write_text("Index\n=====\n", encoding="utf-8")
    excluded = tmp_path / "excluded.rst"
    excluded.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(tmp_path),
            "check",
            "--quiet",
            str(excluded),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "not part of the --sphinx-src environment" in out
    assert "no warnings or errors in the checked files" not in out


# '-' is fixed at level 4 by "L4 under 3" (nested #->*->=->-); "L reused
# wrongly" then reuses '-' directly under a level-2 parent ("L2 B"),
# skipping the already-established level 3 ('=') — a real docutils ERROR,
# confirmed by direct probe: "Inconsistent title style: skip from level 2
# to 4."
_INCONSISTENT_TITLE_STYLE_RST = textwrap.dedent("""\
    Title
    #####

    L2 A
    ****

    L3 under A
    ==========

    L4 under 3
    ----------

    L2 B
    ****

    L reused wrongly
    ----------------
    """)


@pytest.mark.unit
def test_find_findings_from_sphinx_output_parses_console_lines() -> None:
    """_findings_from_sphinx_output (shared by run_sphinx's subprocess
    parsing and Phase 2's captured-warning parsing) turns a raw
    'path:line: LEVEL: msg' console line into a Finding, filtered to the
    given files."""
    raw = "/some/repo/index.rst:16: ERROR: Inconsistent title style: skip from level 2 to 4.\n"
    findings = _sphinx._findings_from_sphinx_output(raw, [Path("/some/repo/index.rst")])
    assert len(findings) == 1
    assert findings[0].severity == "ERROR"
    assert "Inconsistent title style" in findings[0].text


@pytest.mark.unit
def test_findings_from_sphinx_output_accepts_warning_without_line_number() -> None:
    """Sphinx emits some file-scoped diagnostics without ``:line:``.

    ``toc.not_included`` is a common example.  It still references the
    checked file and must not disappear merely because Sphinx has no more
    precise source anchor to report.
    """
    raw = "/some/repo/orphan.rst: WARNING: document isn't included in any toctree [toc.not_included]\n"

    findings = _sphinx._findings_from_sphinx_output(raw, [Path("/some/repo/orphan.rst")])

    assert len(findings) == 1
    assert findings[0].lineno == 0
    assert findings[0].severity == "WARNING"
    assert "toc.not_included" in findings[0].text


@pytest.mark.unit
def test_findings_from_sphinx_output_strips_ansi_color_codes() -> None:
    """The actual root cause, pinned directly: Sphinx's in-process build
    colorizes its console stream even into an io.StringIO() with no real
    isatty() — confirmed live — and the leading '\\x1b[31m' broke
    _WARNING_RE's '^' anchor, silently dropping every match."""
    raw = "\x1b[31m/some/repo/index.rst:16: ERROR: Inconsistent title style: skip from level 2 to 4.\x1b[39;49;00m\n"
    findings = _sphinx._findings_from_sphinx_output(raw, [Path("/some/repo/index.rst")])
    assert len(findings) == 1
    assert findings[0].severity == "ERROR"
    assert "Inconsistent title style" in findings[0].text
    assert "\x1b" not in findings[0].text


@pytest.mark.unit
def test_run_sphinx_nonzero_with_only_warning_adds_failure_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A matching warning must not mask sphinx-build's failed exit status."""
    document = tmp_path / "index.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    warning = f"{document}:4: WARNING: warning emitted before fatal failure\n"

    command: list[str] = []

    def failed_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        command.extend(args)
        return subprocess.CompletedProcess(args=["sphinx-build"], returncode=2, stdout=warning, stderr="fatal\n")

    monkeypatch.setattr("check_rst.cli._sphinx.subprocess.run", failed_run)
    findings = _sphinx.run_sphinx([document], tmp_path / "_build", tmp_path, tmp_path)

    assert any(f.severity == "WARNING" for f in findings)
    assert any(f.severity == "ERROR" and "exited 2" in f.text for f in findings)
    assert command[:3] == [sys.executable, "-m", "sphinx"]


@pytest.mark.unit
def test_runtime_metadata_names_behavior_affecting_dependencies() -> None:
    runtime = _reports._runtime_metadata(verified=True, word_samples=True)

    assert runtime["check_rst"]["version"] == "0.4.0"
    assert runtime["python"]["version"]
    assert runtime["python"]["executable"] == sys.executable
    assert runtime["docutils"]["version"]
    assert runtime["sphinx"]["version"]
    assert runtime["snowballstemmer"]["version"]


@pytest.mark.integration
def test_cli_version_reports_release_identity(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["check_rst", "--version"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert capsys.readouterr().out == (
        "check_rst 0.4.0\nCopyright (C) 2026 Maxime P. DEMENTYEV\nLicense: GPL-3.0-only\n"
    )


@pytest.mark.integration
def test_build_sphinx_env_returns_its_own_warning_text(tmp_path: Path) -> None:
    """_build_sphinx_env must return its captured warning stream, not
    just the env — the whole point of the fix: the caller MUST see it."""
    (tmp_path / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    (tmp_path / "index.rst").write_text(_INCONSISTENT_TITLE_STYLE_RST, encoding="utf-8")
    _env, warning_text = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    assert "Inconsistent title style" in warning_text


@pytest.mark.integration
def test_build_sphinx_env_reemits_persistent_warning_with_cached_build_dir(
    tmp_path: Path,
) -> None:
    """Re-read checked documents without discarding the incremental cache.

    The documented edit/fix/recheck loop deliberately reuses its Sphinx
    build directory for speed.  A checked document must reproduce its
    persistent diagnostic, while an unrelated unchanged document must stay
    cached and avoid a second ``source-read`` event.
    """
    read_log = tmp_path / "source-read.log"
    (tmp_path / "conf.py").write_text(
        textwrap.dedent(f"""\
            from pathlib import Path

            project = "t"
            extensions = []

            def record_source_read(app, docname, source):
                with Path({str(read_log)!r}).open("a", encoding="utf-8") as fh:
                    fh.write(docname + "\\n")

            def setup(app):
                app.connect("source-read", record_source_read)
            """),
        encoding="utf-8",
    )
    checked = tmp_path / "index.rst"
    checked.write_text(_INCONSISTENT_TITLE_STYLE_RST, encoding="utf-8")
    (tmp_path / "other.rst").write_text(_GOOD_BLOCK, encoding="utf-8")
    build_dir = tmp_path / "_build"

    _env, first_warning_text = _sphinx._build_sphinx_env(tmp_path, build_dir)
    read_log.write_text("", encoding="utf-8")
    _env, second_warning_text = _sphinx._build_sphinx_env(tmp_path, build_dir, files=[checked])

    assert "Inconsistent title style" in first_warning_text
    assert "Inconsistent title style" in second_warning_text
    assert read_log.read_text(encoding="utf-8").splitlines() == ["index"]


@pytest.mark.integration
def test_cli_materializes_required_docutils_model_before_sphinx(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No lazy bare-Docutils parse may first occur after extension loading.

    ``--no-directives`` normally avoids Phase 1's doctree consumer, while
    prose-word sampling still needs that doctree later.  Materialize it
    before constructing Sphinx so extension side effects cannot influence
    the bare parser.
    """
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    events: list[str] = []
    original_parse = _helpers._parse_rst

    def recording_parse(
        path: Path,
        text: str | None = None,
        *,
        track_composition: bool = False,
    ) -> docutils.nodes.document:
        events.append("docutils")
        return original_parse(path, text, track_composition=track_composition)

    env = types.SimpleNamespace(
        found_docs={"test"},
        domaindata={},
        path2doc=lambda _path: "test",
    )

    def recording_sphinx_build(*_args: object, **_kwargs: object) -> tuple[object, str]:
        events.append("sphinx")
        return env, ""

    monkeypatch.setattr(_helpers, "_parse_rst", recording_parse)
    monkeypatch.setattr(_sphinx, "_build_sphinx_env", recording_sphinx_build)
    monkeypatch.setattr(_sphinx, "run_sphinx", lambda *_args: [])
    monkeypatch.setattr(_reports, "_top_prose_words", lambda *_args: ([], 0))
    monkeypatch.setattr(_reports, "_rare_prose_words", lambda *_args: ([], 0))
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "check",
            "--no-directives",
            "--word-samples",
            "1",
            str(p),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    capsys.readouterr()
    assert exc.value.code == 0
    assert events == ["docutils", "sphinx"]


@pytest.mark.integration
def test_cli_verified_mode_surfaces_phase2_inconsistent_title_style(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """End to end, the real regression: a fresh --build-dir, verified
    mode, --outline (so Phase 2 actually resolves structure) — the
    ERROR must reach the user, not vanish between Phase 2 and Phase 3."""
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    p = rst_repo / "index.rst"
    p.write_text(_INCONSISTENT_TITLE_STYLE_RST, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "--build-dir",
            str(rst_repo / "_build"),
            "outline",
            "--with-findings",
            str(p),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    out = capsys.readouterr().out
    assert "Inconsistent title style" in out
    assert exc.value.code == 1


@pytest.mark.integration
def test_cli_verified_mode_deduplicates_same_phase2_and_phase3_finding(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One Sphinx diagnostic emitted by both builds is one user finding."""
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    raw_warning = f"{p}:5: WARNING: repeated Sphinx diagnostic [review.test]\n"
    env = types.SimpleNamespace(
        found_docs={"test"},
        domaindata={},
        path2doc=lambda _path: "test",
    )
    duplicate = _types.Finding(
        lineno=5,
        severity=_types.Severity.WARNING,
        text="test.rst: repeated Sphinx diagnostic [review.test]",
    )
    monkeypatch.setattr(
        _sphinx,
        "_build_sphinx_env",
        lambda *_args, **_kwargs: (env, raw_warning),
    )
    monkeypatch.setattr(_sphinx, "run_sphinx", lambda *_args: [duplicate])
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--sphinx-src", str(rst_repo), "check", str(p)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    out = capsys.readouterr().out
    assert exc.value.code == 0
    assert out.count("repeated Sphinx diagnostic") == 1
    assert "0 error(s), 1 warning(s)" in out


@pytest.mark.unit
def test_did_you_mean_finds_close_match() -> None:
    result = _sphinx._did_you_mean("idnex", ["index", "other"])
    assert result is not None
    assert "index" in result


@pytest.mark.unit
def test_did_you_mean_returns_none_when_nothing_close() -> None:
    assert _sphinx._did_you_mean("totally-unrelated-xyz", ["index"]) is None


@pytest.mark.integration
def test_attach_did_you_mean_unknown_document_suggests_close_docname(
    build_sphinx_env: BuildSphinxEnv,
) -> None:
    env, _docname = build_sphinx_env("Title\n=====\n")
    finding = _types.Finding(4, _types.Severity.WARNING, "unknown document: 'idnex' [ref.doc]")
    result = _sphinx._attach_did_you_mean(finding, env)
    assert "did you mean" in result.text
    assert "'index'" in result.text


@pytest.mark.integration
def test_attach_did_you_mean_toctree_nonexisting_document(
    build_sphinx_env: BuildSphinxEnv,
) -> None:
    """'toctree contains reference to nonexisting document' has no colon
    before the quoted target — a different shape than 'unknown document:'."""
    env, _docname = build_sphinx_env("Title\n=====\n")
    finding = _types.Finding(
        4,
        _types.Severity.WARNING,
        "toctree contains reference to nonexisting document 'idnex' [toc.not_readable]",
    )
    result = _sphinx._attach_did_you_mean(finding, env)
    assert "did you mean" in result.text
    assert "'index'" in result.text


@pytest.mark.integration
def test_attach_did_you_mean_undefined_label_suggests_close_label(
    build_sphinx_env: BuildSphinxEnv,
) -> None:
    env, _docname = build_sphinx_env("Title\n=====\n\n.. _real-label:\n\nSection\n-------\n")
    finding = _types.Finding(4, _types.Severity.WARNING, "undefined label: 'real-labl' [ref.ref]")
    result = _sphinx._attach_did_you_mean(finding, env)
    assert "did you mean" in result.text
    assert "'real-label'" in result.text


@pytest.mark.integration
def test_attach_did_you_mean_no_suggestion_when_nothing_close(
    build_sphinx_env: BuildSphinxEnv,
) -> None:
    env, _docname = build_sphinx_env("Title\n=====\n")
    finding = _types.Finding(
        4,
        _types.Severity.WARNING,
        "unknown document: 'zzz-nothing-alike-qqq' [ref.doc]",
    )
    result = _sphinx._attach_did_you_mean(finding, env)
    assert result.text == finding.text


@pytest.mark.integration
def test_attach_did_you_mean_leaves_unrelated_findings_unchanged(
    build_sphinx_env: BuildSphinxEnv,
) -> None:
    env, _docname = build_sphinx_env("Title\n=====\n")
    finding = _types.Finding(
        4,
        _types.Severity.WARNING,
        "Inconsistent title style: skip from level 2 to 4.",
    )
    result = _sphinx._attach_did_you_mean(finding, env)
    assert result.text == finding.text


@pytest.mark.integration
def test_cli_did_you_mean_suggested_for_broken_doc_reference(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """End to end, real sphinx-build subprocess (Phase 3): a typo'd :doc:
    target gets a suggestion naming the real docname, right in the same
    WARNING line."""
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "other-page.rst").write_text("Other Page\n==========\n", encoding="utf-8")
    p = rst_repo / "index.rst"
    p.write_text("Title\n=====\n\n:doc:`other-pge`\n", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "--sphinx-src", str(rst_repo), "check", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "unknown document" in out
    assert "did you mean" in out
    assert "other-page" in out


@pytest.mark.integration
def test_bare_filenames_flags_mention_matching_known_docname(tmp_path: Path) -> None:
    env = _build_multi_file_env(
        tmp_path,
        {
            "a": "A\n=\n\nSee guide.rst for details.\n",
            "guide": "Guide\n=====\n",
        },
    )
    doc = _document.Document(tmp_path / "a.rst")
    violations = _sphinx.check_bare_filenames(env, "a", doc)
    assert len(violations) == 1
    assert violations[0].severity == "WARNING"
    assert "guide" in violations[0].text


@pytest.mark.unit
def test_local_asset_suffix_protocol_is_explicit_and_stable() -> None:
    assert (
        frozenset(
            {
                ".cfg",
                ".conf",
                ".csv",
                ".diff",
                ".ini",
                ".json",
                ".jsonl",
                ".log",
                ".markdown",
                ".md",
                ".patch",
                ".toml",
                ".tsv",
                ".txt",
                ".xml",
                ".yaml",
                ".yml",
            }
        )
        == _sphinx._TEXT_ASSET_SUFFIXES
    )
    assert frozenset({".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}) == _sphinx._IMAGE_ASSET_SUFFIXES


@pytest.mark.integration
@pytest.mark.parametrize("asset_name", ["plan.md", "diagram.svg"])
def test_bare_filenames_flags_existing_local_text_and_image_assets(
    tmp_path: Path,
    asset_name: str,
) -> None:
    env = _build_multi_file_env(
        tmp_path,
        {"a": f"A\n=\n\nRequired reading: ``{asset_name}``.\n"},
    )
    (tmp_path / asset_name).write_text("asset\n", encoding="utf-8")
    doc = _document.Document(tmp_path / "a.rst", tmp_path)

    violations = _sphinx.check_bare_filenames(env, "a", doc)

    assert len(violations) == 1
    assert violations[0].severity == "WARNING"
    assert asset_name in violations[0].text
    assert ":download:" in violations[0].text


@pytest.mark.integration
def test_bare_filenames_resolves_project_relative_local_asset_path(tmp_path: Path) -> None:
    sphinx_src = tmp_path / "docs"
    sphinx_src.mkdir()
    env = _build_multi_file_env(
        sphinx_src,
        {"proreus-gui/roadmap": ("Roadmap\n=======\n\nRequired reading: ``docs/proreus-gui/milestone-d-plan.md``.\n")},
    )
    asset = sphinx_src / "proreus-gui" / "milestone-d-plan.md"
    asset.write_text("plan\n", encoding="utf-8")
    doc = _document.Document(sphinx_src / "proreus-gui" / "roadmap.rst", tmp_path)

    violations = _sphinx.check_bare_filenames(env, "proreus-gui/roadmap", doc)

    assert len(violations) == 1
    assert "docs/proreus-gui/milestone-d-plan.md" in violations[0].text


@pytest.mark.integration
@pytest.mark.parametrize(
    ("body", "asset_name"),
    [
        (
            "Read ``plan.md``.\n\nDownload it: :download:`the plan <plan.md>`.\n",
            "plan.md",
        ),
        (
            "Read ``sample.txt`` below.\n\n.. literalinclude:: sample.txt\n",
            "sample.txt",
        ),
        (
            "Read ``included.txt`` below.\n\n.. include:: included.txt\n",
            "included.txt",
        ),
        (
            "View ``diagram.svg`` below.\n\n.. image:: diagram.svg\n",
            "diagram.svg",
        ),
        (
            "View ``figure.svg`` below.\n\n.. figure:: figure.svg\n",
            "figure.svg",
        ),
    ],
)
def test_bare_filenames_ignores_local_asset_integrated_by_sphinx(
    tmp_path: Path,
    body: str,
    asset_name: str,
) -> None:
    (tmp_path / asset_name).write_text("asset\n", encoding="utf-8")
    env = _build_multi_file_env(tmp_path, {"a": f"A\n=\n\n{body}"})
    doc = _document.Document(tmp_path / "a.rst", tmp_path)

    assert _sphinx.check_bare_filenames(env, "a", doc) == []


@pytest.mark.integration
def test_bare_filenames_treats_file_role_as_intentional_filename_mention(tmp_path: Path) -> None:
    env = _build_multi_file_env(
        tmp_path,
        {"a": "A\n=\n\nEdit :file:`settings.toml` locally.\n"},
    )
    (tmp_path / "settings.toml").write_text("key = 'value'\n", encoding="utf-8")
    doc = _document.Document(tmp_path / "a.rst", tmp_path)

    assert _sphinx.check_bare_filenames(env, "a", doc) == []


@pytest.mark.integration
def test_bare_filenames_does_not_globally_match_local_asset_basename(tmp_path: Path) -> None:
    env = _build_multi_file_env(
        tmp_path,
        {"guide/a": "A\n=\n\nRequired reading: ``plan.md``.\n"},
    )
    unrelated = tmp_path / "other" / "plan.md"
    unrelated.parent.mkdir()
    unrelated.write_text("unrelated plan\n", encoding="utf-8")
    doc = _document.Document(tmp_path / "guide" / "a.rst", tmp_path)

    assert _sphinx.check_bare_filenames(env, "guide/a", doc) == []


@pytest.mark.integration
def test_bare_filenames_ignores_configured_sphinx_source_suffix(tmp_path: Path) -> None:
    (tmp_path / "conf.py").write_text(
        "project = 'test'\nroot_doc = 'a'\nsource_suffix = {'.rst': 'restructuredtext', '.txt': 'restructuredtext'}\n",
        encoding="utf-8",
    )
    (tmp_path / "a.rst").write_text("A\n=\n\nSee ``guide.txt``.\n", encoding="utf-8")
    (tmp_path / "guide.txt").write_text("Guide\n=====\n", encoding="utf-8")
    env, _warnings = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    doc = _document.Document(tmp_path / "a.rst", tmp_path)

    assert "guide" in env.found_docs
    assert _sphinx.check_bare_filenames(env, "a", doc) == []


@pytest.mark.integration
@pytest.mark.parametrize("asset_location", ["missing", "outside"])
def test_bare_filenames_ignores_unresolved_or_outside_source_asset(
    tmp_path: Path,
    asset_location: str,
) -> None:
    sphinx_src = tmp_path / "docs"
    sphinx_src.mkdir()
    env = _build_multi_file_env(
        sphinx_src,
        {"a": "A\n=\n\nRequired reading: ``private-plan.md``.\n"},
    )
    if asset_location == "outside":
        (tmp_path / "private-plan.md").write_text("private\n", encoding="utf-8")
    doc = _document.Document(sphinx_src / "a.rst", tmp_path)

    assert _sphinx.check_bare_filenames(env, "a", doc) == []


@pytest.mark.integration
def test_bare_filenames_attributes_included_asset_mention_to_fragment(tmp_path: Path) -> None:
    env = _build_multi_file_env(
        tmp_path,
        {
            "index": "Index\n=====\n\n.. include:: fragments/note.rst\n",
            "fragments/note": ("Included note\n-------------\n\nRead ``included-plan.md`` before continuing.\n"),
        },
    )
    asset = tmp_path / "fragments" / "included-plan.md"
    asset.write_text("plan\n", encoding="utf-8")
    doc = _document.Document(tmp_path / "index.rst", tmp_path)

    violations = _sphinx.check_bare_filenames(env, "index", doc)

    assert len(violations) == 1
    assert violations[0].lineno == 4
    assert violations[0].source == "fragments/note.rst"


@pytest.mark.integration
def test_bare_filenames_ignores_self_mention(tmp_path: Path) -> None:
    env = _build_multi_file_env(
        tmp_path,
        {
            "a": "A\n=\n\nThis file, a.rst, describes itself.\n",
        },
    )
    doc = _document.Document(tmp_path / "a.rst")
    assert _sphinx.check_bare_filenames(env, "a", doc) == []


@pytest.mark.integration
def test_bare_filenames_ignores_unknown_filename(tmp_path: Path) -> None:
    env = _build_multi_file_env(
        tmp_path,
        {
            "a": "A\n=\n\nSee nonexistent.rst for details.\n",
        },
    )
    doc = _document.Document(tmp_path / "a.rst")
    assert _sphinx.check_bare_filenames(env, "a", doc) == []


@pytest.mark.integration
def test_bare_filenames_lists_multiple_candidates_when_ambiguous(
    tmp_path: Path,
) -> None:
    env = _build_multi_file_env(
        tmp_path,
        {
            "a": "A\n=\n\nSee guide.rst for details.\n",
            "sub1/guide": "Guide One\n=========\n",
            "sub2/guide": "Guide Two\n=========\n",
        },
    )
    doc = _document.Document(tmp_path / "a.rst")
    violations = _sphinx.check_bare_filenames(env, "a", doc)
    assert len(violations) == 1
    assert "sub1/guide" in violations[0].text
    assert "sub2/guide" in violations[0].text


@pytest.mark.integration
def test_bare_filenames_skips_when_too_many_candidates_share_basename(
    tmp_path: Path,
) -> None:
    """Real evidence: this Journal's own corpus has 1072 files named
    'Notes.rst' — a bare mention of that basename is not a specific,
    actionable reference candidate, so it must stay silent rather than
    dump an unusable wall of candidates."""
    files = {"a": "A\n=\n\nSee notes.rst for details.\n"}
    for i in range(10):
        files[f"day{i}/notes"] = f"Day {i}\n=====\n"
    env = _build_multi_file_env(tmp_path, files)
    doc = _document.Document(tmp_path / "a.rst")
    assert _sphinx.check_bare_filenames(env, "a", doc) == []


@pytest.mark.integration
def test_bare_filenames_skips_literal_block_content(tmp_path: Path) -> None:
    env = _build_multi_file_env(
        tmp_path,
        {
            "a": "A\n=\n\n::\n\n    See guide.rst for details.\n",
            "guide": "Guide\n=====\n",
        },
    )
    doc = _document.Document(tmp_path / "a.rst")
    assert _sphinx.check_bare_filenames(env, "a", doc) == []


@pytest.mark.integration
def test_bare_filenames_flags_mention_inside_inline_literal(tmp_path: Path) -> None:
    """The real downstream-project evidence's own shape: a filename wrapped in double
    backticks as the author's own emphasis, not code output."""
    env = _build_multi_file_env(
        tmp_path,
        {
            "a": "A\n=\n\nDocumented in ``guide.rst`` under Section One.\n",
            "guide": "Guide\n=====\n",
        },
    )
    doc = _document.Document(tmp_path / "a.rst")
    assert len(_sphinx.check_bare_filenames(env, "a", doc)) == 1


@pytest.mark.integration
@pytest.mark.parametrize(
    "reference",
    [
        ":doc:`guide.rst <guide>`",
        "`guide.rst <https://example.com/guide.rst>`_",
    ],
)
def test_bare_filenames_ignores_already_linked_filename_labels(tmp_path: Path, reference: str) -> None:
    env = _build_multi_file_env(
        tmp_path,
        {
            "a": f"A\n=\n\nSee {reference} for details.\n",
            "guide": "Guide\n=====\n",
        },
    )
    doc = _document.Document(tmp_path / "a.rst")

    assert _sphinx.check_bare_filenames(env, "a", doc) == []


@pytest.mark.integration
def test_cli_bare_filenames_warning_shown(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\nroot_doc = "a"\n', encoding="utf-8")
    (rst_repo / "a.rst").write_text("A\n=\n\nSee guide.rst for details.\n", encoding="utf-8")
    (rst_repo / "guide.rst").write_text("Guide\n=====\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "check",
            str(rst_repo / "a.rst"),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "WARNING:" in out
    assert "guide" in out


@pytest.mark.integration
def test_cli_local_asset_warning_shown(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\nroot_doc = "a"\n', encoding="utf-8")
    (rst_repo / "a.rst").write_text("A\n=\n\nRequired reading: ``plan.md``.\n", encoding="utf-8")
    (rst_repo / "plan.md").write_text("# Plan\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "check",
            str(rst_repo / "a.rst"),
        ],
    )

    with pytest.raises(SystemExit):
        cli.main()

    out = capsys.readouterr().out
    assert "WARNING: plan.md names a real local asset" in out
    assert "use :download:, include/literalinclude, image/figure, or :file:" in out


@pytest.mark.integration
def test_cli_json_bare_filenames_included(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\nroot_doc = "a"\n', encoding="utf-8")
    (rst_repo / "a.rst").write_text("A\n=\n\nSee guide.rst for details.\n", encoding="utf-8")
    (rst_repo / "guide.rst").write_text("Guide\n=====\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "check",
            "--format=json",
            str(rst_repo / "a.rst"),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    data = json.loads(capsys.readouterr().out)
    findings = data["files"][0]["findings"]
    assert any(f["severity"] == "WARNING" and "guide" in f["text"] for f in findings)


@pytest.mark.integration
def test_sphinx_src_omitted_runs_heuristic_phase2_skips_phase3(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No --sphinx-src at all: Phase 2 still runs, but in labeled heuristic
    mode (no real Sphinx env is built) — only Phase 3 (which has no
    heuristic equivalent) is actually skipped."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Phase 2: Python Sphinx rules (heuristic — no --sphinx-src given" in out
    assert "Phase 3: Sphinx build — skipped (no --sphinx-src given)" in out


@pytest.mark.integration
def test_sphinx_src_missing_conf_py_errors_before_phase1(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--sphinx-src DIR with no conf.py in DIR is a hard error, not a skip —
    and it happens before Phase 1 even starts."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")
    empty_dir = rst_repo / "not_sphinx"
    empty_dir.mkdir()

    monkeypatch.setattr("sys.argv", ["check_rst.py", "--sphinx-src", str(empty_dir), "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "no conf.py found" in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_sphinx_src_valid_dir_runs_phase2_and_phase3(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--sphinx-src DIR with a real conf.py in DIR runs both Phase 2 and
    Phase 3, in that order."""
    p = rst_repo / "index.rst"
    p.write_text(_GOOD_BLOCK + "\n.. toctree::\n", encoding="utf-8")
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "--sphinx-src", str(rst_repo), "check", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "Phase 2: Python Sphinx rules" in out
    assert "Phase 3: Sphinx build integrity" in out
    assert "runtime: check_rst 0.4.0, Python " in out
    assert "Sphinx " in out
    assert "docutils " in out
    assert out.index("Phase 2: Python Sphinx rules") < out.index("Phase 3: Sphinx build integrity")


@pytest.mark.integration
def test_cli_invalid_sphinx_configuration_is_clean_error_not_traceback(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text("this is not valid Python(\n", encoding="utf-8")
    document = rst_repo / "index.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "check", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Sphinx environment build failed" in out
    assert "ConfigError" in out
    assert "syntax error" in out
    assert "Traceback" not in out


@pytest.mark.integration
def test_outline_without_sphinx_src_shows_heuristic_headings_and_code_blocks(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--outline with no --sphinx-src: the merged structure now prints
    during Phase 2 (heuristic mode), never Phase 1 — one place for
    --outline's output regardless of whether --sphinx-src is given."""
    p = rst_repo / "test.rst"
    p.write_text(
        "Chapter One\n===========\n\n.. code-block:: bash\n\n   echo hi\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", "--with-findings", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out

    phase1_block = out[out.index("Phase 1: RST rules") : out.index("Phase 2: Python Sphinx rules")]
    assert "Outline:" not in phase1_block

    phase2_block = out[out.index("Phase 2: Python Sphinx rules") : out.index("Phase 3:")]
    assert "Outline:" in phase2_block
    assert "levels: 1 '='" in phase2_block
    assert "1-6:= Chapter One" in phase2_block
    assert "code-block" in phase2_block


@pytest.mark.integration
def test_outline_with_sphinx_src_merges_headings_and_code_blocks(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--outline with --sphinx-src: headings and code-blocks appear together,
    sorted by line, in ONE block under Phase 2 — not split across phases."""
    p = rst_repo / "index.rst"
    p.write_text(
        "Chapter One\n===========\n\n.. code-block:: bash\n\n   echo hi\n",
        encoding="utf-8",
    )
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "outline",
            "--with-findings",
            str(p),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out

    # Phase 1 must not print its own separate outline when --sphinx-src is given.
    phase1_block = out[out.index("Phase 1: RST rules") : out.index("Phase 2: Python Sphinx rules")]
    assert "Outline:" not in phase1_block

    phase2_block = out[out.index("Phase 2: Python Sphinx rules") : out.index("Phase 3:")]
    assert "Outline:" in phase2_block
    heading_idx = phase2_block.index("1-6:= Chapter One")
    code_idx = phase2_block.index("code-block")
    assert heading_idx < code_idx  # heading (line 1) before code-block (line 4)


@pytest.mark.integration
def test_outline_with_sphinx_src_uses_sphinx_doctree_for_headings(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verified mode must derive sections, not only code blocks, from Sphinx.

    Bare docutils cannot parse ``only`` and drops its nested content.  The
    dummy Sphinx builder does parse ``.. only:: dummy`` and its nested
    section is therefore part of the verified structure promised by
    ``--outline``.
    """
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    p = rst_repo / "index.rst"
    p.write_text(
        textwrap.dedent("""\
            #######
            Title
            #######

            .. only:: dummy

               ********
               Nested
               ********

               Body.
            """),
        encoding="utf-8",
    )
    monkeypatch.setattr(_sphinx, "run_sphinx", lambda *_args: [])
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "outline",
            "--no-adornments",
            "--no-directives",
            str(p),
        ],
    )

    with pytest.raises(SystemExit):
        cli.main()

    out = capsys.readouterr().out
    assert "Title" in out
    assert "Nested" in out


@pytest.mark.integration
def test_verified_outline_attributes_included_heading_to_physical_source(
    tmp_path: Path,
) -> None:
    """An expanded include must not reuse the owner's lines or adornment.

    This is the prerequisite characterization for effective-document rules:
    the section participates in index's hierarchy, while its editable source
    remains fragment.rst line 4 and its adornment remains ``*``.
    """
    (tmp_path / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    index = tmp_path / "index.rst"
    index.write_text(
        "#####\nIndex\n#####\n\n.. include:: fragment.rst\n",
        encoding="utf-8",
    )
    (tmp_path / "fragment.rst").write_text(
        ".. provenance offset\n\nIncluded\n********\n\nBody.\n",
        encoding="utf-8",
    )

    env, _ = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    document = _document.Document(index, tmp_path)
    entries = _document.build_outline(
        index,
        doc=document,
        doctree=env.get_doctree("index"),
        source_root=tmp_path,
    )

    included = next(entry for entry in entries if entry.title == "Included")
    assert (included.lineno, included.char, included.end) == (3, "*", 6)
    assert included.provenance == _types.SourceProvenance(
        source="fragment.rst",
        origin=_types.SourceOrigin.INCLUDE,
        include_chain=(
            _types.IncludeSite(
                source="index.rst",
                lineno=5,
                target="fragment.rst",
                mode="parsed",
            ),
        ),
    )


@pytest.mark.integration
def test_verified_include_entries_preserve_nested_clipped_chain(tmp_path: Path) -> None:
    """Nested includes retain every owner edge and correct start-line offsets."""
    (tmp_path / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    index = tmp_path / "index.rst"
    index.write_text(
        "#####\nIndex\n#####\n\n.. include:: parts/outer.rst\n   :start-line: 2\n",
        encoding="utf-8",
    )
    parts = tmp_path / "parts"
    parts.mkdir()
    (parts / "outer.rst").write_text(
        "discarded\ndiscarded too\n\nOuter\n*****\n\n.. include:: parts/inner.rst\n",
        encoding="utf-8",
    )
    (parts / "inner.rst").write_text("Inner\n=====\n", encoding="utf-8")

    env, _ = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    document = _document.Document(index, tmp_path)
    tree = env.get_doctree("index")
    headings = _document.build_outline(index, doc=document, doctree=tree, source_root=tmp_path)
    includes = _sphinx.find_includes(env, "index", document, doctree=tree)

    assert [
        (entry.provenance.source if entry.provenance else None, entry.lineno, entry.target) for entry in includes
    ] == [
        (None, 5, "parts/outer.rst"),
        ("parts/outer.rst", 7, "parts/inner.rst"),
    ]
    inner = next(entry for entry in headings if entry.title == "Inner")
    assert inner.provenance is not None
    assert [site.target for site in inner.provenance.include_chain] == [
        "parts/outer.rst",
        "parts/inner.rst",
    ]
    assert next(entry for entry in headings if entry.title == "Outer").lineno == 4


@pytest.mark.integration
def test_toctree_inside_include_retains_include_provenance(tmp_path: Path) -> None:
    """Navigation composition nested in source composition keeps both edges."""
    (tmp_path / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    index = tmp_path / "index.rst"
    index.write_text("Index\n=====\n\n.. include:: navigation.rst\n", encoding="utf-8")
    (tmp_path / "navigation.rst").write_text(
        ".. toctree::\n   :maxdepth: 1\n\n   child\n",
        encoding="utf-8",
    )
    (tmp_path / "child.rst").write_text("Child\n=====\n", encoding="utf-8")

    env, _ = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    clusters = _sphinx.find_toctrees(env, "index", _document.Document(index, tmp_path))

    container = clusters[0][0]
    assert isinstance(container, _types.ToctreeEntry)
    assert container.lineno == 1
    assert container.provenance is not None
    assert container.provenance.source == "navigation.rst"
    assert isinstance(clusters[0][1], _types.OutlineEntry)
    assert clusters[0][1].docname == "child"

    tree = env.get_doctree("index")
    headings = _document.build_outline(index, doctree=tree, source_root=tmp_path)
    includes = _sphinx.find_includes(env, "index", doctree=tree)
    local, include_clusters = _sphinx.partition_composed_entries([*headings, *includes])
    nested_includes, root_toctrees = _sphinx.nest_composed_clusters(include_clusters, clusters)
    combined = _sphinx._merge_toctree_clusters(local, [*nested_includes, *root_toctrees])
    assert [type(entry) for entry in combined] == [
        _types.OutlineEntry,
        _types.IncludeEntry,
        _types.ToctreeEntry,
        _types.OutlineEntry,
    ]


@pytest.mark.integration
def test_verified_include_cycle_is_visible_in_composition_entries(tmp_path: Path) -> None:
    """Docutils' source-and-clip cycle refusal remains a visible path edge."""
    (tmp_path / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    index = tmp_path / "index.rst"
    index.write_text("Index\n=====\n\n.. include:: part.rst\n", encoding="utf-8")
    (tmp_path / "part.rst").write_text(".. include:: index.rst\n", encoding="utf-8")

    env, _ = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    document = _document.Document(index, tmp_path)
    includes = _sphinx.find_includes(env, "index", document)

    assert len(includes) == 2
    assert includes[1].cycle == "index.rst"
    assert includes[1].provenance is not None
    assert includes[1].provenance.source == "part.rst"


@pytest.mark.integration
def test_missing_include_target_is_not_misreported_as_a_cycle(tmp_path: Path) -> None:
    """The reactive branch reads Docutils' own live clip_options/include_log
    instead of matching its diagnostic's wording — confirm it doesn't
    false-positive on some *other* DirectiveError a failed include raises
    (a missing target), only on a genuine circular inclusion."""
    (tmp_path / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    index = tmp_path / "index.rst"
    index.write_text("Index\n=====\n\n.. include:: nonexistent.rst\n", encoding="utf-8")

    env, warnings = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    document = _document.Document(index, tmp_path)
    includes = _sphinx.find_includes(env, "index", document)

    assert "nonexistent.rst" in warnings
    assert len(includes) == 1
    assert includes[0].target == "nonexistent.rst"
    assert includes[0].cycle is None


@pytest.mark.integration
def test_include_cycle_identity_allows_disjoint_clip_of_active_source(tmp_path: Path) -> None:
    """Filename alone is not a cycle: Docutils keys the active edge by clipping too."""
    (tmp_path / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    index = tmp_path / "index.rst"
    index.write_text(
        "Index\n=====\n\nBody fragment.\n\n.. include:: index.rst\n   :start-line: 3\n   :end-line: 4\n",
        encoding="utf-8",
    )

    env, _ = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    includes = _sphinx.find_includes(env, "index", _document.Document(index, tmp_path))

    assert len(includes) == 1
    assert includes[0].resolved == "index.rst"
    assert includes[0].cycle is None
    assert includes[0].site is not None
    assert includes[0].site.clip == (3, 4, None, None)


@pytest.mark.integration
def test_disjoint_self_include_restores_outer_provenance_after_clip(tmp_path: Path) -> None:
    """Leaving a nested self-clip must pop back to the outer include site."""
    (tmp_path / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    index = tmp_path / "index.rst"
    index.write_text("Index\n=====\n\n.. include:: fragment.rst\n", encoding="utf-8")
    fragment = tmp_path / "fragment.rst"
    fragment.write_text(
        "Fragment\n--------\n\nBefore.\n\nMARKERSTART\nClipped paragraph.\nMARKEREND\n\n"
        ".. include:: fragment.rst\n"
        "   :start-after: MARKERSTART\n"
        "   :end-before: MARKEREND\n\n"
        "Trailing\n~~~~~~~~\n",
        encoding="utf-8",
    )

    env, _ = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    document = _document.Document(index, tmp_path)
    outline = _document.build_outline(
        index,
        doc=document,
        doctree=env.get_doctree("index"),
        source_root=tmp_path,
    )

    trailing = next(entry for entry in outline if entry.title == "Trailing")
    assert trailing.lineno == 14
    assert trailing.provenance is not None
    assert [site.target for site in trailing.provenance.include_chain] == ["fragment.rst"]


@pytest.mark.integration
@pytest.mark.parametrize(
    ("options", "mode"),
    [
        ("   :literal:\n", "literal"),
        ("   :code: python\n", "code:python"),
        ("   :parser: rst\n", "parser:Parser"),
    ],
)
def test_include_modes_are_explicit(tmp_path: Path, options: str, mode: str) -> None:
    """Literal, code, and custom-parser inclusion are not conflated."""
    (tmp_path / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    index = tmp_path / "index.rst"
    index.write_text(f"Index\n=====\n\n.. include:: payload.rst\n{options}", encoding="utf-8")
    (tmp_path / "payload.rst").write_text("Payload\n-------\n", encoding="utf-8")

    env, _ = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    tree = env.get_doctree("index")
    include = _sphinx.find_includes(env, "index", _document.Document(index, tmp_path), doctree=tree)[0]

    assert include.mode == mode
    assert include.site is not None
    assert include.site.exact is True
    headings = _document.build_outline(index, doctree=tree, source_root=tmp_path)
    assert ("Payload" in [entry.title for entry in headings]) is options.startswith("   :parser:")


@pytest.mark.integration
def test_start_after_end_before_preserve_physical_heading_line(tmp_path: Path) -> None:
    """Text clipping maps logical parser lines back to the selected source span."""
    (tmp_path / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    index = tmp_path / "index.rst"
    index.write_text(
        "Index\n=====\n\n.. include:: fragment.rst\n   :start-after: BEGIN\n   :end-before: END\n",
        encoding="utf-8",
    )
    (tmp_path / "fragment.rst").write_text(
        "discarded\nBEGIN\nIncluded\n--------\nBody.\nEND\ndiscarded\n",
        encoding="utf-8",
    )

    env, _ = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    tree = env.get_doctree("index")
    headings = _document.build_outline(index, doctree=tree, source_root=tmp_path)

    included = next(entry for entry in headings if entry.title == "Included")
    assert (included.lineno, included.end, included.char) == (3, 5, "-")
    assert included.provenance is not None
    assert included.provenance.exact is True


@pytest.mark.integration
def test_verified_conditionals_declare_parser_effective_resolution(tmp_path: Path) -> None:
    """Stored doctrees expose conditions without pretending they are resolved."""
    (tmp_path / "conf.py").write_text(
        'project = "test"\nextensions = ["sphinx.ext.ifconfig"]\nfeature = True\n',
        encoding="utf-8",
    )
    index = tmp_path / "index.rst"
    index.write_text(
        textwrap.dedent("""\
            Index
            =====

            .. only:: html

               HTML
               ----

            .. ifconfig:: feature

               Feature
               -------
            """),
        encoding="utf-8",
    )

    env, _ = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    entries = _sphinx.find_conditionals(env, "index", _document.Document(index, tmp_path))

    assert [(entry.kind, entry.expression, entry.resolution) for entry in entries] == [
        ("only", "html", "builder-dependent"),
        ("ifconfig", "feature", "builder-dependent"),
    ]


@pytest.mark.integration
def test_verified_source_read_mutation_marks_root_coordinates_inexact(tmp_path: Path) -> None:
    """Extension-rewritten source must not masquerade as physical root lines."""
    (tmp_path / "conf.py").write_text(
        textwrap.dedent("""\
            project = "test"

            def rewrite(app, docname, source):
                source[0] = "Injected\\n========\\n\\n" + source[0]

            def setup(app):
                app.connect("source-read", rewrite)
            """),
        encoding="utf-8",
    )
    index = tmp_path / "index.rst"
    index.write_text("Physical\n--------\n", encoding="utf-8")

    env, _ = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    entries = _document.build_outline(
        index,
        doc=_document.Document(index, tmp_path),
        doctree=env.get_doctree("index"),
        source_root=tmp_path,
        root_transformed=_sphinx._source_was_transformed(env, "index"),
    )

    assert entries[0].title == "Injected"
    assert entries[0].char == "?"
    assert entries[0].provenance is not None
    assert entries[0].provenance.origin == _types.SourceOrigin.TRANSFORMED
    assert entries[0].provenance.exact is False


@pytest.mark.integration
def test_rst_prologue_heading_has_synthetic_provenance(tmp_path: Path) -> None:
    """Configured RST injection is structural but has no editable file range."""
    (tmp_path / "conf.py").write_text(
        'project = "test"\nrst_prolog = "Prologue\\n========"\n',
        encoding="utf-8",
    )
    index = tmp_path / "index.rst"
    index.write_text("Physical\n--------\n", encoding="utf-8")

    env, _ = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    entries = _document.build_outline(
        index,
        doc=_document.Document(index, tmp_path),
        doctree=env.get_doctree("index"),
        source_root=tmp_path,
    )

    prologue = next(entry for entry in entries if entry.title == "Prologue")
    assert prologue.char == "?"
    assert prologue.provenance is not None
    assert prologue.provenance.source == "<rst_prologue>"
    assert prologue.provenance.origin == _types.SourceOrigin.RST_PROLOGUE


@pytest.mark.integration
def test_verified_include_read_mutation_marks_include_chain_inexact(tmp_path: Path) -> None:
    """An extension-mutated fragment remains visible but is not called physical."""
    (tmp_path / "conf.py").write_text(
        textwrap.dedent("""\
            project = "test"

            def rewrite(app, path, docname, source):
                source[0] = source[0].replace("Included", "Generated")

            def setup(app):
                app.connect("include-read", rewrite)
            """),
        encoding="utf-8",
    )
    index = tmp_path / "index.rst"
    index.write_text("#######\nIndex\n#######\n\n.. include:: fragment.rst\n", encoding="utf-8")
    (tmp_path / "fragment.rst").write_text("**********\nIncluded\n**********\n", encoding="utf-8")

    env, _ = _sphinx._build_sphinx_env(tmp_path, tmp_path / "_build")
    tree = env.get_doctree("index")
    entries = _document.build_outline(
        index,
        doc=_document.Document(index, tmp_path),
        doctree=tree,
        source_root=tmp_path,
    )

    generated = next(entry for entry in entries if entry.title == "Generated")
    assert generated.char == "?"
    assert generated.provenance is not None
    assert generated.provenance.origin == _types.SourceOrigin.INCLUDE
    assert generated.provenance.exact is False


@pytest.mark.integration
def test_cli_verified_outline_and_json_expose_composition_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The provenance model is a public text and JSON contract, not hidden AST state."""
    (tmp_path / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    index = tmp_path / "index.rst"
    index.write_text("#######\nIndex\n#######\n\n.. include:: fragment.rst\n", encoding="utf-8")
    (tmp_path / "fragment.rst").write_text("**********\nIncluded\n**********\n", encoding="utf-8")
    monkeypatch.setattr(_sphinx, "run_sphinx", lambda *_args: [])
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(tmp_path),
            "outline",
            "--quiet",
            "--verbose",
            "--with-findings",
            str(index),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert '5: include "fragment.rst" (parsed)' in output
    assert "fragment.rst:2-3:* Included" in output
    assert "1 include" in output

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(tmp_path), "check", "--format", "json", str(index)],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    data = json.loads(capsys.readouterr().out)
    model = data["files"][0]
    assert model["structure_stage"] == "parser-effective"
    assert model["includes"][0]["resolved"] == "fragment.rst"
    included = next(entry for entry in model["outline"] if entry["title"] == "Included")
    assert included["provenance"]["source"] == "fragment.rst"


@pytest.mark.integration
def test_multiple_toctree_check_flags_same_child_twice_in_one_parent(
    tmp_path: Path,
) -> None:
    env = _build_multi_file_env(
        tmp_path,
        {
            "index": "Index\n=====\n\n.. toctree::\n\n   child\n   child\n",
            "child": "Child\n=====\n",
        },
    )

    findings = _sphinx.check_multiple_toctree_parents(env, [tmp_path / "index.rst"])

    assert len(findings) == 1
    assert findings[0].severity == "WARNING"
    assert findings[0].lineno == 4
    assert "child" in findings[0].text
    assert "index" in findings[0].text


@pytest.mark.integration
def test_multiple_toctree_check_flags_child_under_distinct_parents(
    tmp_path: Path,
) -> None:
    env = _build_multi_file_env(
        tmp_path,
        {
            "index": "Index\n=====\n",
            "parent-a": "Parent A\n========\n\n.. toctree::\n\n   child\n",
            "parent-b": "Parent B\n========\n\n.. toctree::\n\n   child\n",
            "child": "Child\n=====\n",
        },
    )

    findings = _sphinx.check_multiple_toctree_parents(env, [tmp_path / "parent-a.rst", tmp_path / "child.rst"])

    assert len(findings) == 2
    assert {f.severity for f in findings} == {"WARNING"}
    assert all("parent-a" in f.text and "parent-b" in f.text for f in findings)


@pytest.mark.integration
def test_multiple_toctree_check_single_reference_is_clean(tmp_path: Path) -> None:
    env = _build_multi_file_env(
        tmp_path,
        {
            "index": "Index\n=====\n\n.. toctree::\n\n   child\n",
            "child": "Child\n=====\n",
        },
    )

    assert _sphinx.check_multiple_toctree_parents(env, [tmp_path / "index.rst", tmp_path / "child.rst"]) == []


@pytest.mark.integration
def test_cli_selected_toctree_parent_surfaces_child_anchored_anomaly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The selected parent must surface a concern Sphinx anchors to its child."""
    (tmp_path / "conf.py").write_text(
        'project = "test"\nextensions = []\nroot_doc = "index"\n',
        encoding="utf-8",
    )
    parent = tmp_path / "index.rst"
    parent.write_text(
        "#######\nIndex\n#######\n\n.. toctree::\n\n   child\n   child\n",
        encoding="utf-8",
    )
    (tmp_path / "child.rst").write_text("#######\nChild\n#######\n", encoding="utf-8")
    monkeypatch.setattr(_sphinx, "run_sphinx", lambda *_args: [])
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(tmp_path),
            "check",
            "--quiet",
            str(parent),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert f"{parent}:5: WARNING:" in out
    assert "child" in out


@pytest.mark.integration
def test_multiple_toctree_check_survives_persistent_cache_rerun(tmp_path: Path) -> None:
    (tmp_path / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    parent = tmp_path / "index.rst"
    parent.write_text("Index\n=====\n\n.. toctree::\n\n   child\n   child\n", encoding="utf-8")
    (tmp_path / "child.rst").write_text("Child\n=====\n", encoding="utf-8")
    build_dir = tmp_path / "_build"

    _sphinx._build_sphinx_env(tmp_path, build_dir, files=[parent])
    env, _warnings = _sphinx._build_sphinx_env(tmp_path, build_dir, files=[parent])

    findings = _sphinx.check_multiple_toctree_parents(env, [parent])
    assert len(findings) == 1


@pytest.mark.integration
def test_toctree_child_doctree_is_fetched_only_once_per_encounter(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found by code review: _expand_one_toctree fetched a child
    document's doctree once (to build its own outline entries via
    build_outline) and then a SECOND time, redundantly, inside
    _expand_toctrees's own recursive scan for that same child's toctree
    directives -- for every included child, leaf or not, since
    env.get_doctree() unpickles a fresh document object from disk on
    every single call (BuildEnvironment keeps no doctree cache of its
    own) rather than reusing the one _expand_one_toctree already has in
    hand.
    """
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    parent = rst_repo / "index.rst"
    parent.write_text("Index\n=====\n\n.. toctree::\n\n   child\n", encoding="utf-8")
    (rst_repo / "child.rst").write_text("Child\n=====\n", encoding="utf-8")

    env, _warnings = _sphinx._build_sphinx_env(rst_repo, rst_repo / "_build", files=[parent])

    calls: collections.Counter[str] = collections.Counter()
    real_get_doctree = env.get_doctree

    def counting_get_doctree(docname: str) -> docutils.nodes.document:
        calls[docname] += 1
        doctree: docutils.nodes.document = real_get_doctree(docname)
        return doctree

    monkeypatch.setattr(env, "get_doctree", counting_get_doctree)

    _sphinx.find_toctrees(env, "index")

    assert calls["child"] == 1, f"child.rst's doctree was fetched {calls['child']} time(s), expected exactly 1"


@pytest.mark.integration
def test_toctree_recurses_into_included_documents(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A single-level toctree pulls in each target's own headings, depth
    offset by the toctree container's own depth (Index=1, Section A=2,
    so sub1's own top heading — locally depth 1 — lands at 2+1=3)."""
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text(
        textwrap.dedent("""\
            Index
            =====

            Section A
            ---------

            .. toctree::
               :maxdepth: 2

               sub1
               sub2
            """),
        encoding="utf-8",
    )
    (rst_repo / "sub1.rst").write_text("Sub One\n=======\n\nSub One Child\n-------------\n", encoding="utf-8")
    (rst_repo / "sub2.rst").write_text("Sub Two\n=======\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "outline",
            str(rst_repo / "index.rst"),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out

    assert "toctree (2 entries, maxdepth=2)" in out
    assert "sub1:1-5:= Sub One" in out
    assert "sub1:4-5:- Sub One Child" in out
    assert "sub2:1-2:= Sub Two" in out
    # Depth math: sub1's own local depth-1 title lands one level deeper
    # than the toctree container that pulled it in (10-space indent),
    # its own local depth-2 child one level deeper still.
    assert "          7-11: toctree (2 entries, maxdepth=2)" in out
    assert "              sub1:1-5:= Sub One" in out
    assert "                  sub1:4-5:- Sub One Child" in out


@pytest.mark.integration
def test_toctree_recurses_across_multiple_levels(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A nested toctree (sub1 -> subsub1) is followed recursively, not
    only one level deep — --outline-depth is the only bound, never a
    per-toctree :maxdepth:."""
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text("Index\n=====\n\n.. toctree::\n\n   sub1\n", encoding="utf-8")
    (rst_repo / "sub1.rst").write_text("Sub One\n=======\n\n.. toctree::\n\n   subsub1\n", encoding="utf-8")
    (rst_repo / "subsub1.rst").write_text("Sub Sub One\n===========\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "outline",
            str(rst_repo / "index.rst"),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out

    assert "sub1:1-6:= Sub One" in out
    assert "subsub1:1-2:= Sub Sub One" in out
    # Provenance belongs only to entries pulled from another document:
    # the root container is local to index.rst and stays bare, while the
    # nested container must be self-identifying when read as one line.
    assert "index:4-6: toctree" not in out
    assert "sub1:4-6: toctree (1 entry, maxdepth=unlimited)" in out
    # subsub1 must appear strictly after sub1's own toctree line, nested
    # one level deeper than sub1's own heading.
    assert out.index("sub1:1-6:= Sub One") < out.index("subsub1:1-2:= Sub Sub One")


@pytest.mark.integration
def test_toctree_cycle_is_reported_and_does_not_hang(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """index -> a -> b -> index: the revisit of 'index' stops that branch
    with a visible marker instead of recursing forever."""
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text("Index\n=====\n\n.. toctree::\n\n   a\n", encoding="utf-8")
    (rst_repo / "a.rst").write_text("Doc A\n=====\n\n.. toctree::\n\n   b\n", encoding="utf-8")
    (rst_repo / "b.rst").write_text("Doc B\n=====\n\n.. toctree::\n\n   index\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "outline",
            str(rst_repo / "index.rst"),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out

    assert "a:1-6:= Doc A" in out
    assert "b:1-6:= Doc B" in out
    assert "toctree cycle" in out
    assert "b:4: toctree cycle" in out
    assert "'index' is already an ancestor" in out


@pytest.mark.integration
def test_toctree_diamond_shows_heading_again_without_reexpanding(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A document reachable via two different toctrees (a->b and index->b,
    non-cyclic) gets its heading twice, but its own nested toctree is only
    walked once — the second occurrence shows no nested toctree line."""
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text("Index\n=====\n\n.. toctree::\n\n   a\n   b\n", encoding="utf-8")
    (rst_repo / "a.rst").write_text("Doc A\n=====\n\n.. toctree::\n\n   b\n", encoding="utf-8")
    (rst_repo / "b.rst").write_text("Doc B\n=====\n\nBody of B.\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "outline",
            str(rst_repo / "index.rst"),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out

    assert out.count("b:1-4:= Doc B") == 2


@pytest.mark.integration
def test_toctree_sections_only_hides_container_keeps_cross_file_headings(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--sections-only hides the toctree CONTAINER marker (a leaf) but
    keeps the cross-file headings it pulled in (real sections)."""
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text("Index\n=====\n\n.. toctree::\n\n   sub1\n", encoding="utf-8")
    (rst_repo / "sub1.rst").write_text("Sub One\n=======\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "outline",
            "--sections-only",
            str(rst_repo / "index.rst"),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out

    assert "toctree (" not in out
    assert "sub1:1-2:= Sub One" in out


@pytest.mark.integration
def test_toctree_outline_depth_bounds_across_file_boundary(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--outline-depth applies uniformly to depth, including nested
    documents pulled in via toctree — not just this file's own headings."""
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text("Index\n=====\n\n.. toctree::\n\n   sub1\n", encoding="utf-8")
    (rst_repo / "sub1.rst").write_text("Sub One\n=======\n\nSub One Child\n-------------\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "outline",
            "--outline-depth",
            "2",
            str(rst_repo / "index.rst"),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out

    # The toctree container itself is shallow enough to stay visible, but
    # sub1's own title AND its own child heading both land deeper than
    # --outline-depth 2 once offset by the container's depth — hidden on
    # both sides of the file boundary, uniformly, not just locally.
    assert "toctree (1 entry, maxdepth=unlimited)" in out
    assert "Sub One" not in out
    assert "2 deeper entries hidden — --outline-depth 2" in out


@pytest.mark.integration
def test_no_toctree_flag_suppresses_recursion(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--no-toctree opts out of toctree recursion entirely."""
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text("Index\n=====\n\n.. toctree::\n\n   sub1\n", encoding="utf-8")
    (rst_repo / "sub1.rst").write_text("Sub One\n=======\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "outline",
            "--no-toctree",
            str(rst_repo / "index.rst"),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    # Search only the Outline: section's own body, not the whole capture —
    # pytest's own tmp_path for THIS test's name literally contains
    # "no_toctree", which would false-positive a bare substring check
    # against the full output (which echoes the checked file's path).
    out = capsys.readouterr().out
    outline_body = out[out.index("levels:") :]

    assert "toctree" not in outline_body
    assert "Sub One" not in outline_body


@pytest.mark.integration
def test_toctree_json_shape_includes_toctrees_and_cross_file_ids(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--json reports local and foreign toctree-container provenance and
    merges cross-file headings into "outline" with their OWN document's
    id — never the requesting file's id."""
    (rst_repo / "conf.py").write_text('project = "test"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "index.rst").write_text("Index\n=====\n\n.. toctree::\n\n   sub1\n", encoding="utf-8")
    (rst_repo / "sub1.rst").write_text("Sub One\n=======\n\n.. toctree::\n\n   subsub1\n", encoding="utf-8")
    (rst_repo / "subsub1.rst").write_text("Sub Sub One\n===========\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "check",
            "--format=json",
            str(rst_repo / "index.rst"),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    data = json.loads(capsys.readouterr().out)
    file_record = data["files"][0]

    assert len(file_record["toctrees"]) == 2
    assert file_record["toctrees"][0]["item_count"] == 1
    assert [entry["docname"] for entry in file_record["toctrees"]] == [None, "sub1"]
    ids = {e["id"] for e in file_record["outline"]}
    assert "sub1:Sub One" in ids
    assert "subsub1:Sub Sub One" in ids
    assert "index:Index" in ids


@pytest.mark.integration
def test_toctree_invisible_without_sphinx_src(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Heuristic mode (no --sphinx-src) never recurses: toctree is not
    even a recognized directive to bare docutils."""
    (rst_repo / "sub1.rst").write_text("Sub One\n=======\n", encoding="utf-8")
    p = rst_repo / "index.rst"
    p.write_text("Index\n=====\n\n.. toctree::\n\n   sub1\n", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "outline", str(p)])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out

    assert "sub1:" not in out
    assert "Sub One" not in out
