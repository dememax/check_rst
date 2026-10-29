# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Tests for benchmark-only reader phase timing — check_rst project
"""Specify exclusive phase accounting and reader timing exports."""

from __future__ import annotations

import importlib
import json
import types
from typing import TYPE_CHECKING

from check_rst.cli import _helpers

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    import pytest


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
