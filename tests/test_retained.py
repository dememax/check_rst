# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Retained-WARNING sidecar contract tests — check_rst project
"""Reviewed WARNINGs keep a durable, reason-bearing disposition.

A committed ``.check_rst-retained.toml`` (decided 2026-09-26) beside the
project configuration records ``retain`` decisions.  Identity is the
project-relative owning source path, the stable rule code, and the SHA-256
of the whitespace-normalized source line — never the line number or the
message wording.  A reason is mandatory, only WARNINGs can be retained, a
retained WARNING stays counted and visible in JSON, and an entry that no
longer matches anything in a whole-file check is reported as stale.
"""

from __future__ import annotations

import hashlib
import json
import textwrap
from typing import TYPE_CHECKING

import pytest
from _support import _git

from check_rst import cli

if TYPE_CHECKING:
    from pathlib import Path

_DOC = textwrap.dedent("""\
    #######
    Title
    #######

    **Register item.** kept on purpose.

    **Heading-ish opener.** needs a decision.
    """)


def _digest(line: str) -> str:
    return hashlib.sha256(" ".join(line.split()).encode("utf-8")).hexdigest()


def _sidecar(root: Path, *entries: dict[str, str], extra: str = "") -> None:
    blocks = ["[[retain]]\n" + "".join(f'{key} = "{value}"\n' for key, value in entry.items()) for entry in entries]
    (root / ".check_rst-retained.toml").write_text(
        "version = 1\n" + extra + "\n" + "\n".join(blocks),
        encoding="utf-8",
    )


def _entry(path: str, code: str, line: str, reason: str = "One item in a compact co-equal register.") -> dict[str, str]:
    return {"path": path, "code": code, "source-sha256": _digest(line), "reason": reason}


def _run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    monkeypatch.setattr("sys.argv", ["check_rst.py", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return int(exc.value.code or 0), capsys.readouterr().out


@pytest.fixture
def doc(tmp_path: Path) -> Path:
    path = tmp_path / "doc.rst"
    path.write_text(_DOC, encoding="utf-8")
    return path


@pytest.mark.integration
def test_retained_warning_is_hidden_counted_and_kept_in_json(
    tmp_path: Path, doc: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _sidecar(tmp_path, _entry("doc.rst", "pseudo-heading.bold-opener", "**Register item.** kept on purpose."))

    code, out = _run(monkeypatch, capsys, "check", str(doc))

    assert code == 0
    assert "bold paragraph opener 'Register item.'" not in out
    assert f"{doc}:7: WARNING: bold paragraph opener 'Heading-ish opener.'" in out
    assert f"↷ {doc}: 1 retained WARNING(s)" in out
    assert "0 error(s), 1 warning(s), 1 retained WARNING(s)" in out

    _code, json_out = _run(monkeypatch, capsys, "check", "--format=json", str(doc))
    data = json.loads(json_out)
    findings = data["files"][0]["findings"]
    assert [(f["lineno"], f.get("retained")) for f in findings] == [
        (5, {"reason": "One item in a compact co-equal register."}),
        (7, None),
    ]
    assert findings[1]["source_sha256"] == _digest("**Heading-ish opener.** needs a decision.")
    assert data["summary"]["warnings"] == 1
    assert data["summary"]["retained"] == 1
    assert data["stale_retentions"] == []


@pytest.mark.integration
def test_verbose_output_shows_each_retention_reason(
    tmp_path: Path, doc: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _sidecar(tmp_path, _entry("doc.rst", "pseudo-heading.bold-opener", "**Register item.** kept on purpose."))

    _code, out = _run(monkeypatch, capsys, "check", "--verbose", str(doc))

    assert "  retained doc.rst:5 [pseudo-heading.bold-opener]: One item in a compact co-equal register." in out


@pytest.mark.integration
def test_errors_are_never_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "doc.rst"
    path.write_text("#####\nFirst\n#####\n\nText.\n\n######\nSecond\n######\n\nMore.\n", encoding="utf-8")
    _sidecar(tmp_path, _entry("doc.rst", "hierarchy.second-title", "Second"))

    code, out = _run(monkeypatch, capsys, "check", str(path))

    assert code == 1
    assert "second effective top-level title 'Second'" in out
    assert "retain entry 1 (doc.rst, hierarchy.second-title) matches no current WARNING" in out


@pytest.mark.integration
def test_changed_or_deleted_construct_leaves_a_stale_entry(
    tmp_path: Path, doc: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _sidecar(
        tmp_path,
        _entry("doc.rst", "pseudo-heading.bold-opener", "**Register item.** kept on purpose."),
        _entry("doc.rst", "pseudo-heading.bold-opener", "**Removed opener.** gone."),
    )
    doc.write_text(_DOC.replace("kept on purpose", "kept, reworded"), encoding="utf-8")

    _code, out = _run(monkeypatch, capsys, "check", str(doc))
    _code, json_out = _run(monkeypatch, capsys, "check", "--format=json", str(doc))

    assert "bold paragraph opener 'Register item.'" in out
    assert ".check_rst-retained.toml: WARNING: retain entry 1 (doc.rst, pseudo-heading.bold-opener)" in out
    assert ".check_rst-retained.toml: WARNING: retain entry 2 (doc.rst, pseudo-heading.bold-opener)" in out
    assert json.loads(json_out)["stale_retentions"] == [
        {"entry": 1, "path": "doc.rst", "code": "pseudo-heading.bold-opener"},
        {"entry": 2, "path": "doc.rst", "code": "pseudo-heading.bold-opener"},
    ]


@pytest.mark.integration
def test_partial_git_scope_does_not_judge_staleness(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = rst_repo / "doc.rst"
    doc.write_text(_DOC, encoding="utf-8")
    _sidecar(rst_repo, _entry("doc.rst", "pseudo-heading.bold-opener", "**Register item.** kept on purpose."))
    _git(rst_repo, "add", "doc.rst", ".check_rst-retained.toml")
    _git(rst_repo, "commit", "-m", "baseline")
    doc.write_text(_DOC + "\nA new paragraph.\n", encoding="utf-8")

    _code, out = _run(monkeypatch, capsys, "check", "--git-scope", str(doc))

    assert "retain entry" not in out


@pytest.mark.integration
def test_included_fragment_finding_is_retained_by_its_own_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "frag.rst").write_text("**Fragment item.** reviewed.\n", encoding="utf-8")
    root = tmp_path / "main.rst"
    root.write_text("######\nMain\n######\n\n.. include:: frag.rst\n", encoding="utf-8")
    _sidecar(tmp_path, _entry("frag.rst", "pseudo-heading.bold-opener", "**Fragment item.** reviewed."))

    _code, out = _run(monkeypatch, capsys, "check", str(root))

    assert "Fragment item" not in out
    assert "1 retained WARNING(s)" in out
    assert "retain entry" not in out


@pytest.mark.integration
def test_no_config_ignores_the_sidecar(
    tmp_path: Path, doc: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _sidecar(tmp_path, _entry("doc.rst", "pseudo-heading.bold-opener", "**Register item.** kept on purpose."))

    _code, out = _run(monkeypatch, capsys, "--no-config", "check", str(doc))

    assert "bold paragraph opener 'Register item.'" in out
    assert "retained" not in out


@pytest.mark.integration
@pytest.mark.parametrize(
    ("entry", "extra", "message"),
    [
        (
            {"path": "doc.rst", "code": "pseudo-heading.bold-opener", "source-sha256": "0" * 64, "reason": " "},
            "",
            "retain entry 1: reason must not be empty",
        ),
        (
            {"path": "doc.rst", "code": "no.such-rule", "source-sha256": "0" * 64, "reason": "r"},
            "",
            "retain entry 1: unknown code 'no.such-rule'",
        ),
        (
            {"path": "doc.rst", "code": "pseudo-heading.bold-opener", "source-sha256": "abc", "reason": "r"},
            "",
            "retain entry 1: source-sha256 must be 64 lowercase hex digits",
        ),
        (
            {"path": "/abs/doc.rst", "code": "pseudo-heading.bold-opener", "source-sha256": "0" * 64, "reason": "r"},
            "",
            "retain entry 1: path must be project-relative",
        ),
        (
            {"path": "doc.rst", "code": "pseudo-heading.bold-opener", "source-sha256": "0" * 64},
            "",
            "retain entry 1: missing key(s): reason",
        ),
        (
            {"path": "doc.rst", "code": "pseudo-heading.bold-opener", "source-sha256": "0" * 64, "reason": "r"},
            "glob = true\n",
            "unknown key(s): glob",
        ),
    ],
    ids=["empty-reason", "unknown-code", "bad-digest", "absolute-path", "missing-reason", "unknown-top-key"],
)
def test_invalid_sidecar_fails_loudly(
    tmp_path: Path,
    doc: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    entry: dict[str, str],
    extra: str,
    message: str,
) -> None:
    _sidecar(tmp_path, entry, extra=extra)

    code, out = _run(monkeypatch, capsys, "check", str(doc))

    assert code == 1
    assert f"check_rst: .check_rst-retained.toml: {message}" in out
