# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Internal finding-code identity tests — check_rst project
"""Every production finding carries a stable internal rule code.

Codes are ``<domain>.<condition>`` dotted-kebab identities.  They let later
work prove duplicates, dispatch shared explanations, and key retained
WARNINGs without parsing message text, whose wording may improve at any time.
Until the public-output decision, codes stay internal: text and JSON output
must not change.
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import TYPE_CHECKING

import pytest
from _support import _build_multi_file_env, _rst

from check_rst import cli
from check_rst.cli import _document, _formatting, _helpers, _lint, _sphinx, _types

if TYPE_CHECKING:
    from pathlib import Path

_CODE_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+(?:-[a-z0-9]+)*")


@pytest.mark.unit
def test_finding_codes_are_unique_domain_condition_names() -> None:
    values = [code.value for code in _types.FindingCode]
    assert len(values) == len(set(values))
    assert [value for value in values if not _CODE_RE.fullmatch(value)] == []


@pytest.mark.unit
def test_finding_cannot_be_constructed_without_code() -> None:
    with pytest.raises(TypeError):
        _types.Finding(1, _types.Severity.ERROR, "missing identity")  # type: ignore[call-arg]


@pytest.mark.unit
def test_hygiene_findings_name_each_normalization_rule() -> None:
    text = "\ufeffTitle\r\nline\rnext\u2028more\vspace\nprose  \n=====  \n"
    _normalized, findings, _counts = _helpers._normalize_source_detailed(text)
    assert [finding.code for finding in findings] == [
        "hygiene.bom",
        "hygiene.crlf",
        "hygiene.lone-cr",
        "hygiene.line-separator",
        "hygiene.control-whitespace",
        "hygiene.trailing-whitespace",
        "hygiene.trailing-whitespace",
    ]


@pytest.mark.integration
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Title\n=========\n\nText.\n", "adornment.underline-only"),
        ("=======\nTitle\n-------\n\nText.\n", "adornment.char-mismatch"),
        ("####\nTitle\n####\n\nText.\n", "adornment.length"),
        ("#######\n Title\n#######\n\nText.\n", "adornment.title-spaces"),
        ("Para.\n#######\nTitle\n#######\n\nText.\n", "adornment.blank-before"),
        ("#######\nTitle\n#######\nText.\n", "adornment.blank-after"),
    ],
)
def test_adornment_findings_name_their_geometry_rule(tmp_path: Path, source: str, expected: str) -> None:
    findings = _formatting.check_adornments(_rst(tmp_path, source), whole_file=True)
    codes = {finding.code for finding in findings}
    assert expected in codes
    assert all(code.startswith("adornment.") for code in codes)


@pytest.mark.integration
def test_hierarchy_findings_name_order_and_preference_rules(tmp_path: Path) -> None:
    path = _rst(tmp_path, "*****\nA\n*****\n\n~~~\nB\n~~~\n\nText.\n")
    codes = [finding.code for finding in _formatting.check_hierarchy(path)]
    assert "hierarchy.order" in codes
    assert "hierarchy.nonpreferred-char" in codes


@pytest.mark.integration
def test_second_top_level_title_has_hierarchy_code(tmp_path: Path) -> None:
    path = _rst(tmp_path, "#####\nFirst\n#####\n\nText.\n\n######\nSecond\n######\n\nMore.\n")
    findings = _formatting.check_single_top_level(path)
    assert [finding.code for finding in findings] == ["hierarchy.second-title"]


@pytest.mark.integration
def test_semantic_lint_findings_name_their_rule(tmp_path: Path) -> None:
    path = _rst(
        tmp_path,
        """\
        #####
        Title
        #####

        See Аuthor here.

        Some **bold *emphasis* text** inside.

        **Opener.** text follows.

        **Standalone**

        .. rubric:: Rubric

        .. code: bash

           echo hidden
        """,  # noqa: RUF001
    )
    assert [f.code for f in _lint.check_homoglyphs(path)] == ["text.homoglyph"]
    assert [f.code for f in _lint.check_nested_inline_markup(path, True)] == ["inline.nested-markup"]
    for verbose in (False, True):
        assert [f.code for f in _lint.check_directives(path, True, verbose)] == [
            "pseudo-heading.bold-opener",
            "pseudo-heading.standalone-bold",
            "pseudo-heading.rubric",
            "directive.mistyped",
        ]


@pytest.mark.integration
def test_verified_reference_findings_name_their_rule(tmp_path: Path) -> None:
    env = _build_multi_file_env(
        tmp_path,
        {
            "a": "A\n=\n\nSee guide.rst and ``plan.md``.\n\n.. toctree::\n\n   guide\n   guide\n",
            "guide": "Guide\n=====\n",
        },
    )
    (tmp_path / "plan.md").write_text("# Plan\n", encoding="utf-8")
    doc = _document.Document(tmp_path / "a.rst")
    assert sorted(f.code for f in _sphinx.check_bare_filenames(env, "a", doc)) == sorted(
        ["reference.bare-filename", "reference.plain-local-asset"]
    )
    assert [f.code for f in _sphinx.check_multiple_toctree_parents(env, [tmp_path / "a.rst"])] == [
        "toctree.multiple-parents"
    ]


@pytest.mark.integration
def test_sphinx_console_findings_classify_title_restatements(tmp_path: Path) -> None:
    path = tmp_path / "doc.rst"
    path.write_text("Doc\n", encoding="utf-8")
    output = "\n".join(
        [
            f"{path}:3: WARNING: Title overline too short.",
            f"{path}:6: WARNING: Title underline too short.",
            f"{path}:9: ERROR: Title overline & underline mismatch.",
            f"{path}:24: ERROR: Inconsistent title style: skip from level 2 to 4.",
            f"{path}:30: WARNING: undefined label: 'nowhere' [ref.ref]",
        ]
    )
    findings = _sphinx._findings_from_sphinx_output(output, [path], tmp_path)
    assert [finding.code for finding in findings] == [
        "sphinx.title-overline-too-short",
        "sphinx.title-underline-too-short",
        "sphinx.title-adornment-mismatch",
        "sphinx.inconsistent-title-style",
        "sphinx.diagnostic",
    ]


@pytest.mark.integration
def test_failed_sphinx_build_without_located_error_has_build_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_build(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=2, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", failed_build)
    findings = _sphinx.run_sphinx([tmp_path / "doc.rst"], tmp_path / "_build", tmp_path, tmp_path)
    assert [finding.code for finding in findings] == ["sphinx.build-failed"]


@pytest.mark.integration
def test_json_findings_keep_public_fields_without_internal_code(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Internal codes stay out of JSON; location exactness is additive (schema 1)."""
    path = rst_repo / "test.rst"
    path.write_text("####\nTitle\n####\n\n**Opener.** text follows.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--format=json", str(path)])
    with pytest.raises(SystemExit):
        cli.main()
    findings = json.loads(capsys.readouterr().out)["files"][0]["findings"]
    assert findings
    assert {tuple(finding) for finding in findings} == {
        ("lineno", "severity", "text", "source", "fixable", "location_exact")
    }
