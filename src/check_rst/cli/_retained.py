# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Retained-WARNING sidecar: reviewed dispositions with mandatory reasons — check_rst project
"""Durable ``retain`` decisions for reviewed WARNINGs.

The semantic rules ask every reviewed WARNING for a disposition: promote,
rewrite, or retain with a stated reason.  A committed
``.check_rst-retained.toml`` beside the project configuration stores the
retain decisions (decided 2026-09-26), so a reviewed WARNING stops looking
like an unreviewed one without editing the source — adopted or generated
files cannot carry inline annotations.

Identity is the project-relative owning source path, the stable rule code,
and the SHA-256 of the whitespace-normalized source line.  The line number
is not identity (edits above it move it) and neither is the message text
(its wording may improve).  Only an exactly located WARNING can match:
ERRORs are never acknowledged away, and an approximate line has no proven
span to digest.
"""

from __future__ import annotations

import dataclasses
import hashlib
import pathlib
import re
import tomllib
from typing import TYPE_CHECKING, NoReturn

from ._types import FindingCode, Severity

if TYPE_CHECKING:
    from collections.abc import Callable

    from ._types import Finding

RETAINED_FILE = ".check_rst-retained.toml"
_TOP_KEYS = frozenset({"version", "retain"})
_REQUIRED_KEYS = ("path", "code", "source-sha256", "reason")
# Provenance metadata only: never part of the matching identity.
_OPTIONAL_KEYS = frozenset({"reviewer", "date"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclasses.dataclass(frozen=True, slots=True)
class Retention:
    """One validated ``[[retain]]`` entry; *entry* is its 1-based position."""

    entry: int
    path: str
    code: FindingCode
    source_sha256: str
    reason: str


@dataclasses.dataclass(slots=True)
class RetainedSet:
    """The loaded sidecar plus which entries matched a WARNING this run."""

    entries: tuple[Retention, ...]
    matched: set[int] = dataclasses.field(default_factory=set)

    def match(self, path: str, code: FindingCode, digest: str) -> Retention | None:
        """Return the entry retaining this identity, recording the match."""
        for retention in self.entries:
            if (retention.path, retention.code, retention.source_sha256) == (path, code, digest):
                self.matched.add(retention.entry)
                return retention
        return None

    def stale(self, judged_paths: set[str]) -> list[Retention]:
        """Entries for a fully judged source that matched no WARNING."""
        return [r for r in self.entries if r.path in judged_paths and r.entry not in self.matched]


def span_digest(line: str) -> str:
    """SHA-256 of one source line with whitespace runs collapsed.

    Re-indenting or re-wrapping whitespace keeps a retention valid; any
    change to the construct's own text makes it stale for review.
    """
    return hashlib.sha256(" ".join(line.split()).encode("utf-8")).hexdigest()


def _fail(message: str) -> NoReturn:
    print(f"check_rst: {RETAINED_FILE}: {message}")
    raise SystemExit(1)


def _retention(index: int, raw: object) -> Retention:
    if not isinstance(raw, dict):
        _fail(f"retain entry {index}: must be a table")
    missing = [key for key in _REQUIRED_KEYS if key not in raw]
    if missing:
        _fail(f"retain entry {index}: missing key(s): {', '.join(missing)}")
    unknown = set(raw) - set(_REQUIRED_KEYS) - _OPTIONAL_KEYS
    if unknown:
        _fail(f"retain entry {index}: unknown key(s): {', '.join(sorted(unknown))}")
    for key, value in raw.items():
        if not isinstance(value, str):
            _fail(f"retain entry {index}: {key} must be a string, got {type(value).__name__}")
    path = pathlib.PurePosixPath(raw["path"])
    if path.is_absolute() or ".." in path.parts or not path.parts:
        _fail(f"retain entry {index}: path must be project-relative")
    try:
        code = FindingCode(raw["code"])
    except ValueError:
        _fail(f"retain entry {index}: unknown code {raw['code']!r}")
    if not _SHA256_RE.fullmatch(raw["source-sha256"]):
        _fail(f"retain entry {index}: source-sha256 must be 64 lowercase hex digits")
    if not raw["reason"].strip():
        _fail(f"retain entry {index}: reason must not be empty")
    return Retention(index, str(path), code, raw["source-sha256"], raw["reason"].strip())


def load_retained(root: pathlib.Path) -> RetainedSet | None:
    """Load and fully validate the sidecar in *root*, or None when absent.

    Any malformed content fails loudly, exactly like a malformed project
    configuration: a silently ignored retention would resurface reviewed
    WARNINGs, and a silently accepted one could hide an unreviewed one.
    """
    path = root / RETAINED_FILE
    if not path.is_file():
        return None
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        _fail(f"invalid TOML: {exc}")
    except OSError as exc:
        _fail(str(exc))
    unknown = set(data) - _TOP_KEYS
    if unknown:
        _fail(f"unknown key(s): {', '.join(sorted(unknown))} — known keys: {', '.join(sorted(_TOP_KEYS))}")
    if data.get("version") != 1:
        _fail("version must be 1")
    raw_entries = data.get("retain", [])
    if not isinstance(raw_entries, list):
        _fail("retain must be an array of tables")
    return RetainedSet(tuple(_retention(index, raw) for index, raw in enumerate(raw_entries, start=1)))


def annotate_retention(
    findings: list[Finding],
    retained: RetainedSet | None,
    owning_path: Callable[[Finding], str | None],
    owning_line: Callable[[Finding], str | None],
) -> list[Finding]:
    """Give each retainable WARNING its span digest and any retention.

    Retainable means an exactly located, first-party WARNING whose owning
    source line can be read.  Every such finding gets ``source_sha256`` —
    the value an author copies into a new entry — whether or not a sidecar
    exists; a matching entry adds its reason as ``retained``.
    """
    annotated: list[Finding] = []
    for finding in findings:
        if (
            finding.severity != Severity.WARNING
            or not finding.location_exact
            or finding.lineno <= 0
            or finding.sphinx is not None
        ):
            annotated.append(finding)
            continue
        path = owning_path(finding)
        line = owning_line(finding)
        if path is None or line is None:
            annotated.append(finding)
            continue
        digest = span_digest(line)
        hit = retained.match(path, finding.code, digest) if retained is not None else None
        annotated.append(
            dataclasses.replace(finding, source_sha256=digest, retained=hit.reason if hit is not None else None)
        )
    return annotated
