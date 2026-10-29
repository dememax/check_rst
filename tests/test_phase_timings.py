# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Tests for benchmark-only reader phase timing — check_rst project
"""Specify exclusive phase accounting and reader timing exports."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from check_rst.cli import _helpers

if TYPE_CHECKING:
    from types import ModuleType


_SOURCE_ROOT = Path(__file__).resolve().parents[1]
_PERF_SUBPROCESS = _SOURCE_ROOT / "tools" / "perf_subprocess.py"


def _module() -> ModuleType:
    return importlib.import_module("check_rst.cli._timing")


def test_phase_timings_exclude_nested_time_and_record_total() -> None:
    module = _module()
    readings = iter(
        (
            (0.0, 0.0),
            (1.0, 1.0),
            (3.0, 2.0),
            (5.0, 4.0),
            (8.0, 6.0),
            (10.0, 8.0),
        )
    )
    timings = module.PhaseTimings(clock=lambda: next(readings))

    timings.enable()
    with timings.total(), timings.phase("parent"), timings.phase("child"):
        pass

    assert timings.snapshot() == {
        "total": {"wall_seconds": 10.0, "cpu_seconds": 8.0},
        "phases": {
            "child": {"wall_seconds": 2.0, "cpu_seconds": 2.0},
            "parent": {"wall_seconds": 5.0, "cpu_seconds": 3.0},
        },
    }


def test_perf_subprocess_exports_counts_and_phase_timings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("tools.perf_subprocess")
    timings = {
        "total": {"wall_seconds": 3.0, "cpu_seconds": 2.5},
        "phases": {
            "query-formatting": {"wall_seconds": 0.25, "cpu_seconds": 0.2},
        },
    }
    monkeypatch.setattr(
        module,
        "PHASE_TIMINGS",
        types.SimpleNamespace(snapshot=lambda: timings),
        raising=False,
    )
    _helpers.CALL_COUNTS.update({"_parse_rst": 2, "_read_source": 1})
    destination = tmp_path / "counts.json"

    module._write_counts(destination)

    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "call_counts": {"_parse_rst": 2, "_read_source": 1},
        "phase_timings": timings,
    }


@pytest.mark.integration
@pytest.mark.parametrize(
    ("mode", "no_toctree", "expected_names"),
    [
        pytest.param(
            "verified-context",
            False,
            {
                "configuration-discovery",
                "planning-facts",
                "include-universe",
                "verified-environment",
                "doctree-relationships",
                "query-formatting",
            },
            id="verified-context",
        ),
        pytest.param(
            "verified-context",
            True,
            {
                "configuration-discovery",
                "planning-facts",
                "include-universe",
                "verified-environment",
                "doctree-relationships",
                "query-formatting",
            },
            id="verified-context-no-toctree",
        ),
        pytest.param(
            "heuristic-outline",
            False,
            {
                "configuration-discovery",
                "include-universe",
                "doctree-relationships",
                "query-formatting",
            },
            id="heuristic-outline",
        ),
    ],
)
def test_reader_phase_names_are_stable_and_export_does_not_change_output(
    tmp_path: Path,
    mode: str,
    no_toctree: bool,
    expected_names: set[str],
) -> None:
    (tmp_path / "conf.py").write_text('project = "phase-test"\nextensions = []\n', encoding="utf-8")
    (tmp_path / "index.rst").write_text("Target\n======\n\nBody.\n", encoding="utf-8")
    build_dir = tmp_path / "_build"
    if mode == "verified-context":
        command = [
            "--no-config",
            "--sphinx-src",
            str(tmp_path),
            "--build-dir",
            str(build_dir),
            "context",
        ]
        if no_toctree:
            command.append("--no-toctree")
        command.extend(("Target", "index.rst"))
    else:
        command = ["--no-config", "outline", "index.rst"]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(_SOURCE_ROOT / "src"), environment.get("PYTHONPATH")) if part
    )

    exported: list[subprocess.CompletedProcess[bytes]] = []
    names: list[set[str]] = []
    for run in range(2):
        counts_file = tmp_path / f"counts-{run}.json"
        result = subprocess.run(
            [sys.executable, str(_PERF_SUBPROCESS), "--counts-file", str(counts_file), "--", *command],
            cwd=tmp_path,
            env=environment,
            check=False,
            capture_output=True,
        )
        exported.append(result)
        payload = json.loads(counts_file.read_text(encoding="utf-8"))
        names.append(set(payload["phase_timings"]["phases"]))
    plain = subprocess.run(
        [sys.executable, "-m", "check_rst", *command],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
    )

    assert names == [expected_names, expected_names]
    assert [result.returncode for result in exported] == [plain.returncode, plain.returncode] == [0, 0]
    assert [result.stdout for result in exported] == [plain.stdout, plain.stdout]
    assert [result.stderr for result in exported] == [plain.stderr, plain.stderr]
