# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Tests for deterministic performance-history rendering — check_rst project
"""Specify PF-1's artifact validation and complete RST page rendering."""

from __future__ import annotations

import importlib
import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


def _module() -> ModuleType:
    return importlib.import_module("tools.perf_history")


def _host(*, os_name: str = "Test OS A") -> dict[str, str | int]:
    return {
        "label": "public-host",
        "os": os_name,
        "kernel": "test-kernel",
        "cpu_model": "Test CPU",
        "cpu_cores": 8,
        "ram_bytes": 16_000_000_000,
        "python": "3.14.test",
        "docutils": "0.23",
        "sphinx": "9.1.test",
    }


def _record(
    *,
    name: str,
    host: dict[str, str | int],
    commit: str,
    measured_at: str = "2026-10-29T12:00:00Z",
) -> dict[str, object]:
    return {
        "commit": commit,
        "measured_at": measured_at,
        "check_rst_version": "0.7.4",
        "host_facts": host,
        "scenario": {
            "name": name,
            "command": ["--no-config", "outline", "small.rst"],
            "parameters": {"mode": "heuristic"},
        },
        "repetitions": 2,
        "measurements": [
            {
                "elapsed_seconds": 2.0,
                "user_cpu_seconds": 1.5,
                "system_cpu_seconds": 0.25,
                "peak_rss_bytes": 12_345_678,
                "exit_status": 0,
                "stdout_sha256": "a" * 64,
            }
        ],
        "structural_counts": {"_parse_rst": 2, "_read_source": 1},
        "summary": {
            "elapsed_seconds": {"median": 1.5, "minimum": 1.0},
            "user_cpu_seconds": {"median": 1.25, "minimum": 1.0},
            "system_cpu_seconds": {"median": 0.25, "minimum": 0.2},
            "peak_rss_bytes": {"maximum": 12_345_678},
        },
        "verified_cold_warm_output_agreement": True,
    }


@pytest.mark.unit
def test_empty_history_renders_complete_page() -> None:
    rendered = _module().render_page([])

    for title, character in (
        ("Performance history", "#"),
        ("Host environments", "*"),
        ("Test suite", "*"),
        ("Benchmarks", "*"),
    ):
        adornment = character * (len(title) + 2)
        assert f"{adornment}\n{title}\n{adornment}" in rendered
    assert "No measurements are recorded yet." in rendered
    assert "seconds" in rendered
    assert "MiB" in rendered


@pytest.mark.unit
def test_history_is_stably_ordered_deduplicated_and_keeps_changed_host_facts() -> None:
    module = _module()
    first_host = _host()
    changed_host = _host(os_name="Test OS B")
    first = _record(name="scenario-z", host=first_host, commit="b" * 40)
    second = _record(name="scenario-a", host=changed_host, commit="a" * 40)
    artifacts = [
        {"format_version": 1, "host": first_host, "records": [first, second]},
        {"format_version": 1, "host": changed_host, "records": [second]},
    ]

    rendered = module.render_page(artifacts)

    assert "Test OS A" in rendered
    assert "Test OS B" in rendered
    assert rendered.index("scenario-a") < rendered.index("scenario-z")
    assert rendered.count("scenario-a") == 1
    assert module.render_page(list(reversed(artifacts))) == rendered


@pytest.mark.unit
def test_history_is_chronological_and_renders_compact_safe_cells() -> None:
    module = _module()
    host = _host()
    host["label"] = "|public-host_"
    earlier = _record(
        name="scenario-z",
        host=host,
        commit="f" * 40,
        measured_at="2026-10-29T11:59:58Z",
    )
    later = _record(
        name="scenario-a",
        host=host,
        commit="0" * 40,
        measured_at="2026-10-29T12:00:00Z",
    )

    rendered = module.render_page([{"format_version": 1, "host": host, "records": [later, earlier]}])

    assert rendered.index("2026-10-29T11:59:58Z") < rendered.index("2026-10-29T12:00:00Z")
    assert rendered.index("ffffffffffff") < rendered.index("000000000000")
    assert "f" * 40 not in rendered
    assert "0" * 40 not in rendered
    assert r"\|public-host\_" in rendered


@pytest.mark.unit
def test_conflicting_duplicate_history_rows_are_refused() -> None:
    module = _module()
    host = _host()
    first = _record(name="scenario-a", host=host, commit="a" * 40)
    changed = json.loads(json.dumps(first))
    changed["repetitions"] = 3

    with pytest.raises(module.HistoryError, match="conflicting duplicate"):
        module.render_page(
            [
                {"format_version": 1, "host": host, "records": [first]},
                {"format_version": 1, "host": host, "records": [changed]},
            ]
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("contents", "message"),
    [
        pytest.param("not JSON\n", "cannot read artifact", id="malformed-json"),
        pytest.param('{"format_version": 3, "host": {}, "records": []}\n', "unsupported format_version", id="version"),
    ],
)
def test_malformed_or_unsupported_artifact_is_refused(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    contents: str,
    message: str,
) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_text(contents, encoding="utf-8")

    status = _module().main(["--output", str(tmp_path / "history.rst"), str(artifact)])

    assert status == 1
    assert message in capsys.readouterr().err


@pytest.mark.unit
def test_check_mode_detects_a_stale_page_without_writing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    page = tmp_path / "history.rst"
    page.write_text(module.render_page([]), encoding="utf-8")

    assert module.main(["--output", str(page), "--check"]) == 0
    page.write_text("stale\n", encoding="utf-8")
    assert module.main(["--output", str(page), "--check"]) == 1
    assert page.read_text(encoding="utf-8") == "stale\n"
    assert "differs from rendered history" in capsys.readouterr().err
