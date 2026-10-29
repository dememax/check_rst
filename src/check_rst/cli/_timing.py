# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Benchmark-only exclusive reader phase accounting — check_rst project
"""Collect stable reader phase timings without changing the CLI contract."""

from __future__ import annotations

import contextlib
import dataclasses
import time
from collections.abc import Callable, Iterator
from typing import TypedDict

type Clock = Callable[[], tuple[float, float]]


class DurationJson(TypedDict):
    """One wall/CPU duration pair in the benchmark export."""

    wall_seconds: float
    cpu_seconds: float


class PhaseTimingsJson(TypedDict):
    """Complete timing payload written beside structural call counts."""

    total: DurationJson
    phases: dict[str, DurationJson]


@dataclasses.dataclass(slots=True)
class _Duration:
    wall_seconds: float = 0.0
    cpu_seconds: float = 0.0

    def add(self, started: tuple[float, float], finished: tuple[float, float]) -> None:
        self.wall_seconds += finished[0] - started[0]
        self.cpu_seconds += finished[1] - started[1]

    def to_json(self) -> DurationJson:
        return {"wall_seconds": self.wall_seconds, "cpu_seconds": self.cpu_seconds}


@dataclasses.dataclass(slots=True)
class _ActivePhase:
    name: str
    started: tuple[float, float]


class _PhaseHandle:
    """Idempotently close one phase begun without a lexical ``with`` block."""

    def __init__(self, timings: PhaseTimings, active: _ActivePhase | None) -> None:
        self._timings = timings
        self._active = active

    def stop(self) -> None:
        active = self._active
        if active is None:
            return
        self._timings._stop(active)
        self._active = None


def _process_clock() -> tuple[float, float]:
    return time.perf_counter(), time.process_time()


class PhaseTimings:
    """Aggregate exclusive named phases under one inclusive command total.

    Entering a child phase pauses its parent.  The parent resumes when the
    child exits, so phase values can be summed without double-counting nested
    work.  The command total is independent and intentionally remains
    inclusive, leaving unclassified time derivable by subtraction.
    """

    def __init__(self, *, clock: Clock = _process_clock) -> None:
        self._clock = clock
        self._enabled = False
        self._phases: dict[str, _Duration] = {}
        self._stack: list[_ActivePhase] = []
        self._total = _Duration()
        self._total_started: tuple[float, float] | None = None

    def enable(self) -> None:
        """Reset and enable collection for one benchmark subprocess."""
        if self._stack or self._total_started is not None:
            raise RuntimeError("cannot reset active phase timings")
        self._enabled = True
        self._phases.clear()
        self._total = _Duration()

    def disable(self) -> None:
        """Disable collection after the completed snapshot has been exported."""
        if self._stack or self._total_started is not None:
            raise RuntimeError("cannot disable active phase timings")
        self._enabled = False

    @contextlib.contextmanager
    def total(self) -> Iterator[None]:
        """Measure the inclusive command total when collection is enabled."""
        if not self._enabled:
            yield
            return
        if self._total_started is not None:
            raise RuntimeError("command total is already active")
        self._total_started = self._clock()
        try:
            yield
        finally:
            started = self._total_started
            if started is None:
                raise RuntimeError("command total ended without a start")
            self._total.add(started, self._clock())
            self._total_started = None

    def begin(self, name: str) -> _PhaseHandle:
        """Begin *name* and return a handle for non-lexical phase boundaries."""
        if not self._enabled:
            return _PhaseHandle(self, None)
        now = self._clock()
        if self._stack:
            parent = self._stack[-1]
            self._phases.setdefault(parent.name, _Duration()).add(parent.started, now)
        active = _ActivePhase(name, now)
        self._stack.append(active)
        return _PhaseHandle(self, active)

    @contextlib.contextmanager
    def phase(self, name: str) -> Iterator[None]:
        """Measure one exclusive occurrence of the stable phase *name*."""
        handle = self.begin(name)
        try:
            yield
        finally:
            handle.stop()

    def _stop(self, active: _ActivePhase) -> None:
        if not self._stack or self._stack[-1] is not active:
            raise RuntimeError("phase timings must end in stack order")
        now = self._clock()
        self._phases.setdefault(active.name, _Duration()).add(active.started, now)
        self._stack.pop()
        if self._stack:
            self._stack[-1].started = now

    def snapshot(self) -> PhaseTimingsJson:
        """Return the completed deterministic export shape."""
        if self._stack or self._total_started is not None:
            raise RuntimeError("cannot snapshot active phase timings")
        return {
            "total": self._total.to_json(),
            "phases": {name: duration.to_json() for name, duration in sorted(self._phases.items())},
        }


PHASE_TIMINGS = PhaseTimings()

CONFIGURATION_DISCOVERY = "configuration-discovery"
PLANNING_FACTS = "planning-facts"
INCLUDE_UNIVERSE = "include-universe"
VERIFIED_ENVIRONMENT = "verified-environment"
DOCTREE_RELATIONSHIPS = "doctree-relationships"
QUERY_FORMATTING = "query-formatting"
