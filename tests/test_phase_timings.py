# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Tests for benchmark-only reader phase timing — check_rst project
"""Specify exclusive phase accounting and reader timing exports."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType


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
