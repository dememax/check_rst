# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Deterministic performance-history renderer — check_rst project
"""Render host-scoped performance artifacts as one complete RST history."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import re
import sys
import tempfile
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

FORMAT_VERSION = 2
MEASURED_AT_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
ENUMERATED_PREFIX_PATTERN = re.compile(r"(?:[0-9A-Za-z#]+[.)]|\([0-9A-Za-z#]+\))\s")
HOST_FIELDS = (
    "label",
    "os",
    "kernel",
    "cpu_model",
    "cpu_cores",
    "ram_bytes",
    "python",
    "docutils",
    "sphinx",
)
TEST_OUTCOMES = ("passed", "failed", "skipped", "errors", "xfailed", "xpassed")
type JsonObject = dict[str, object]
type HostValue = str | int
type HostFacts = dict[str, HostValue]
type HostKey = tuple[HostValue, ...]
type RowKey = tuple[str, str, HostKey]


class HistoryError(RuntimeError):
    """A cleanly reportable artifact or rendering error."""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render deterministic RST performance history.")
    parser.add_argument("artifacts", nargs="*", type=pathlib.Path, help="host-scoped perf_record JSON artifacts")
    parser.add_argument("--output", required=True, type=pathlib.Path, help="complete RST page to write or check")
    parser.add_argument("--check", action="store_true", help="fail without writing when OUTPUT differs")
    return parser


def _object(value: object, context: str) -> JsonObject:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise HistoryError(f"{context} must be an object")
    return cast("JsonObject", value)


def _string(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise HistoryError(f"{context} must be a string")
    return value


def _integer(value: object, context: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or (positive and value < 1):
        qualifier = "positive " if positive else ""
        raise HistoryError(f"{context} must be a {qualifier}integer")
    return value


def _number(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise HistoryError(f"{context} must be a number")
    return float(value)


def _measured_at(value: object, context: str) -> str:
    measured_at = _string(value, context)
    if MEASURED_AT_PATTERN.fullmatch(measured_at) is None:
        raise HistoryError(f"{context} must be a UTC ISO 8601 timestamp without subseconds")
    try:
        datetime.datetime.strptime(measured_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise HistoryError(f"{context} must be a valid UTC timestamp") from exc
    return measured_at


def _host_facts(value: object, context: str) -> HostFacts:
    raw = _object(value, context)
    if set(raw) != set(HOST_FIELDS):
        raise HistoryError(f"{context} must contain exactly the supported host facts")
    result: HostFacts = {}
    for field in HOST_FIELDS:
        field_context = f"{context}.{field}"
        if field in {"cpu_cores", "ram_bytes"}:
            result[field] = _integer(raw[field], field_context)
        else:
            result[field] = _string(raw[field], field_context)
    return result


def _host_key(host: HostFacts) -> HostKey:
    return tuple(host[field] for field in HOST_FIELDS)


def _measurement(value: object, context: str) -> None:
    raw = _object(value, context)
    for field in ("elapsed_seconds", "user_cpu_seconds", "system_cpu_seconds"):
        _number(raw.get(field), f"{context}.{field}")
    _integer(raw.get("peak_rss_bytes"), f"{context}.peak_rss_bytes")
    _integer(raw.get("exit_status"), f"{context}.exit_status")
    _string(raw.get("stdout_sha256"), f"{context}.stdout_sha256")


def _summary(value: object, context: str) -> None:
    raw = _object(value, context)
    for field in ("elapsed_seconds", "user_cpu_seconds", "system_cpu_seconds"):
        values = _object(raw.get(field), f"{context}.{field}")
        _number(values.get("median"), f"{context}.{field}.median")
        _number(values.get("minimum"), f"{context}.{field}.minimum")
    rss = _object(raw.get("peak_rss_bytes"), f"{context}.peak_rss_bytes")
    _integer(rss.get("maximum"), f"{context}.peak_rss_bytes.maximum")


def _validate_record(value: object, context: str) -> JsonObject:
    record = _object(value, context)
    _string(record.get("commit"), f"{context}.commit")
    _measured_at(record.get("measured_at"), f"{context}.measured_at")
    _string(record.get("check_rst_version"), f"{context}.check_rst_version")
    _host_facts(record.get("host_facts"), f"{context}.host_facts")
    scenario = _object(record.get("scenario"), f"{context}.scenario")
    _string(scenario.get("name"), f"{context}.scenario.name")
    command = scenario.get("command")
    if not isinstance(command, list) or not all(isinstance(argument, str) for argument in command):
        raise HistoryError(f"{context}.scenario.command must be a string array")
    parameters = _object(scenario.get("parameters"), f"{context}.scenario.parameters")
    if not all(isinstance(item, str | int | bool) for item in parameters.values()):
        raise HistoryError(f"{context}.scenario.parameters has an unsupported value")
    _integer(record.get("repetitions"), f"{context}.repetitions", positive=True)
    measurements = record.get("measurements")
    if not isinstance(measurements, list) or not measurements:
        raise HistoryError(f"{context}.measurements must be a non-empty array")
    for index, measurement in enumerate(measurements):
        _measurement(measurement, f"{context}.measurements[{index}]")
    counts = _object(record.get("structural_counts"), f"{context}.structural_counts")
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in counts.values()):
        raise HistoryError(f"{context}.structural_counts must contain integer values")
    _summary(record.get("summary"), f"{context}.summary")
    agreement = record.get("verified_cold_warm_output_agreement")
    if agreement is not None and not isinstance(agreement, bool):
        raise HistoryError(f"{context}.verified_cold_warm_output_agreement must be boolean or null")
    if "test_counts" in record:
        test_counts = _object(record["test_counts"], f"{context}.test_counts")
        if set(test_counts) != set(TEST_OUTCOMES):
            raise HistoryError(f"{context}.test_counts must contain exactly the supported pytest outcomes")
        for field in TEST_OUTCOMES:
            _integer(test_counts[field], f"{context}.test_counts.{field}")
    return record


def load_artifact(path: pathlib.Path) -> JsonObject:
    """Load and validate one format-version-2 recorder artifact."""
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoryError(f"cannot read artifact {path}: {exc}") from exc
    artifact = _object(raw, f"artifact {path}")
    version = artifact.get("format_version")
    if version != FORMAT_VERSION:
        raise HistoryError(f"unsupported format_version {version!r} in artifact {path}")
    _host_facts(artifact.get("host"), f"artifact {path}.host")
    records = artifact.get("records")
    if not isinstance(records, list):
        raise HistoryError(f"artifact {path}.records must be an array")
    for index, record in enumerate(records):
        _validate_record(record, f"artifact {path}.records[{index}]")
    return artifact


def _deduplicated_records(artifacts: Sequence[JsonObject]) -> list[JsonObject]:
    by_key: dict[RowKey, tuple[str, JsonObject]] = {}
    for artifact_index, artifact in enumerate(artifacts):
        records = artifact.get("records")
        if not isinstance(records, list):
            raise HistoryError(f"artifact {artifact_index}.records must be an array")
        for record_index, value in enumerate(records):
            record = _validate_record(value, f"artifact {artifact_index}.records[{record_index}]")
            scenario = cast("JsonObject", record["scenario"])
            host = _host_facts(record["host_facts"], "record.host_facts")
            key = (
                cast("str", record["commit"]),
                cast("str", scenario["name"]),
                _host_key(host),
            )
            canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
            previous = by_key.get(key)
            if previous is not None and previous[0] != canonical:
                raise HistoryError(f"conflicting duplicate performance row for commit {key[0]}, scenario {key[1]}")
            by_key[key] = (canonical, record)
    records = [item[1] for item in by_key.values()]

    def chronology(record: JsonObject) -> tuple[str, str, HostKey, str]:
        scenario = cast("JsonObject", record["scenario"])
        host = _host_facts(record["host_facts"], "record.host_facts")
        return (
            cast("str", record["measured_at"]),
            cast("str", scenario["name"]),
            _host_key(host),
            cast("str", record["commit"]),
        )

    return sorted(records, key=chronology)


def _heading(title: str, character: str) -> list[str]:
    adornment = character * (len(title) + 2)
    return [adornment, title, adornment, ""]


def _cell(value: object) -> str:
    text = " ".join(str(value).split()) or "—"
    starts_block_markup = not text[0].isalnum() or ENUMERATED_PREFIX_PATTERN.match(text) is not None
    escaped = (
        text.replace("\\", "\\\\")
        .replace("*", "\\*")
        .replace("`", "\\`")
        .replace("::", "\\:\\:")
        .replace("_", "\\_")
        .replace("|", "\\|")
    )
    if starts_block_markup and not escaped.startswith("\\"):
        escaped = f"\\{escaped}"
    return escaped


def _list_table(title: str, headers: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    lines = [f".. list-table:: {title}", "   :header-rows: 1", ""]
    for row in (headers, *rows):
        lines.append(f"   * - {_cell(row[0])}")
        lines.extend(f"     - {_cell(value)}" for value in row[1:])
    lines.append("")
    return lines


def _summary_values(record: JsonObject) -> tuple[str, ...]:
    summary = cast("JsonObject", record["summary"])
    values: list[str] = []
    for field in ("elapsed_seconds", "user_cpu_seconds", "system_cpu_seconds"):
        field_summary = cast("JsonObject", summary[field])
        median = cast("float | int", field_summary["median"])
        minimum = cast("float | int", field_summary["minimum"])
        values.extend((f"{median:.6f}", f"{minimum:.6f}"))
    rss = cast("JsonObject", summary["peak_rss_bytes"])
    values.append(f"{cast('int', rss['maximum']) / (1024 * 1024):.2f}")
    return tuple(values)


def _record_prefix(record: JsonObject, environment_id: str) -> tuple[object, ...]:
    scenario = cast("JsonObject", record["scenario"])
    return (
        record["measured_at"],
        cast("str", record["commit"])[:12],
        record["check_rst_version"],
        environment_id,
        scenario["name"],
        record["repetitions"],
    )


def render_page(artifacts: Sequence[JsonObject]) -> str:
    """Render a complete page from already-loaded artifacts."""
    records = _deduplicated_records(artifacts)
    hosts = sorted({_host_key(_host_facts(record["host_facts"], "record.host_facts")) for record in records})
    environment_ids = {host: f"E{index}" for index, host in enumerate(hosts, 1)}

    lines = [
        ".. Copyright (C) 2026 Maxime P. DEMENTYEV",
        ".. SPDX-License-Identifier: GPL-3.0-only",
        ".. Versioned performance measurements — check_rst project",
        "",
        *_heading("Performance history", "#"),
        "This page is rendered deterministically from host-scoped JSON artifacts.",
        "Times are seconds and peak resident set size (RSS) is MiB.",
        "Measurement timestamps use UTC with one-second precision.",
        "User CPU beside elapsed wall time distinguishes computation from waiting.",
        "",
        *_heading("Host environments", "*"),
    ]
    if not hosts:
        lines.extend(("No measurements are recorded yet.", ""))
    else:
        host_rows = []
        for host in hosts:
            facts = dict(zip(HOST_FIELDS, host, strict=True))
            host_rows.append(
                (
                    environment_ids[host],
                    facts["label"],
                    facts["os"],
                    facts["kernel"],
                    facts["cpu_model"],
                    facts["cpu_cores"],
                    f"{cast('int', facts['ram_bytes']) / (1024**3):.2f}",
                    facts["python"],
                    facts["docutils"],
                    facts["sphinx"],
                )
            )
        lines.extend(
            _list_table(
                "Recorded host environments",
                ("Environment", "Label", "OS", "Kernel", "CPU", "Cores", "RAM (GiB)", "Python", "Docutils", "Sphinx"),
                host_rows,
            )
        )

    test_records = [record for record in records if "test_counts" in record]
    lines.extend(_heading("Test suite", "*"))
    if not test_records:
        lines.extend(("No measurements are recorded yet.", ""))
    else:
        test_rows = []
        for record in test_records:
            host = _host_key(_host_facts(record["host_facts"], "record.host_facts"))
            counts = cast("JsonObject", record["test_counts"])
            test_rows.append(
                (
                    *_record_prefix(record, environment_ids[host]),
                    counts["passed"],
                    counts["failed"],
                    counts["skipped"],
                    counts["errors"],
                    counts["xfailed"],
                    counts["xpassed"],
                    *_summary_values(record),
                )
            )
        lines.extend(
            _list_table(
                "Project test-suite measurements",
                (
                    "Measured (UTC)",
                    "Commit",
                    "Version",
                    "Environment",
                    "Scenario",
                    "Runs",
                    "Passed",
                    "Failed",
                    "Skipped",
                    "Errors",
                    "Xfailed",
                    "Xpassed",
                    "Wall median (s)",
                    "Wall min (s)",
                    "User median (s)",
                    "User min (s)",
                    "System median (s)",
                    "System min (s)",
                    "Peak RSS max (MiB)",
                ),
                test_rows,
            )
        )

    benchmark_records = [record for record in records if "test_counts" not in record]
    lines.extend(_heading("Benchmarks", "*"))
    if not benchmark_records:
        lines.extend(("No measurements are recorded yet.", ""))
    else:
        benchmark_rows = []
        for record in benchmark_records:
            host = _host_key(_host_facts(record["host_facts"], "record.host_facts"))
            counts = cast("JsonObject", record["structural_counts"])
            counts_text = ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "—"
            agreement = record["verified_cold_warm_output_agreement"]
            agreement_text = "yes" if agreement is True else "no" if agreement is False else "not compared"
            benchmark_rows.append(
                (
                    *_record_prefix(record, environment_ids[host]),
                    *_summary_values(record),
                    counts_text,
                    agreement_text,
                )
            )
        lines.extend(
            _list_table(
                "Reader and transformation benchmarks",
                (
                    "Measured (UTC)",
                    "Commit",
                    "Version",
                    "Environment",
                    "Scenario",
                    "Runs",
                    "Wall median (s)",
                    "Wall min (s)",
                    "User median (s)",
                    "User min (s)",
                    "System median (s)",
                    "System min (s)",
                    "Peak RSS max (MiB)",
                    "Structural counts",
                    "Cold/warm output",
                ),
                benchmark_rows,
            )
        )
    return "\n".join(lines)


def _write_page(path: pathlib.Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(arguments: list[str] | None = None) -> int:
    args = _build_parser().parse_args(arguments)
    try:
        artifacts = [load_artifact(path) for path in args.artifacts]
        rendered = render_page(artifacts)
        if args.check:
            try:
                committed = args.output.read_text(encoding="utf-8")
            except OSError:
                committed = ""
            if committed != rendered:
                raise HistoryError(f"{args.output} differs from rendered history")
        else:
            _write_page(args.output, rendered)
    except HistoryError as exc:
        print(f"perf_history: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
