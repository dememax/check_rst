# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Tests for check_rst.cli's _sphinx domain (Phase 2/3 Sphinx integration) — check_rst project

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import types
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from _support import _GOOD_BLOCK, BuildSphinxEnv, _build_multi_file_env

from check_rst import cli
from check_rst.cli import _document, _helpers, _reports, _sphinx, _types

if TYPE_CHECKING:
    import docutils.nodes


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

    assert runtime["check_rst"]["version"] == "0.3.0"
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
        "check_rst 0.3.0\nCopyright (C) 2026 Maxime P. DEMENTYEV\nLicense: GPL-3.0-only\n"
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

    def recording_parse(path: Path, text: str | None = None) -> docutils.nodes.document:
        events.append("docutils")
        return original_parse(path, text)

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
    assert "runtime: check_rst 0.3.0, Python " in out
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
