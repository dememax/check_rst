# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Serial subprocess performance recorder for generated reader scenarios — check_rst project
"""Record a repeatable reader-latency matrix in a host-scoped JSON artifact."""

from __future__ import annotations

import argparse
import ast
import dataclasses
import datetime
import hashlib
import json
import os
import pathlib
import platform
import re
import shlex
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Literal, cast

import docutils
import sphinx

if TYPE_CHECKING or __package__:
    from tools.perf_corpus import CorpusSize, GeneratedProject, generate_project
else:
    from perf_corpus import CorpusSize, GeneratedProject, generate_project

SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[1]
SUBPROCESS_RUNNER = SOURCE_ROOT / "tools" / "perf_subprocess.py"
FORMAT_VERSION = 2
TEST_SUITE_SCENARIO = "project-test-suite"
TEST_OUTCOMES = ("passed", "failed", "skipped", "errors", "xfailed", "xpassed")
PYTEST_SUMMARY_PATTERN = re.compile(r"^=+\s+(?P<body>.+?)\s+in\s+\d+(?:\.\d+)?s(?:\s+\([^)]*\))?\s+=+$")
PYTEST_OUTCOME_PATTERN = re.compile(r"(?P<count>\d+)\s+(?P<outcome>passed|failed|skipped|errors?|xfailed|xpassed)\b")
DEFAULT_SMALL_UNRELATED = 4
DEFAULT_LARGE_UNRELATED = 64
DEFAULT_LARGE_PAGE_SECTIONS = 64
DEFAULT_FRAGMENT_INCLUDERS = 3
type ParameterValue = str | int | bool
type Runner = Callable[[Sequence[str], pathlib.Path, pathlib.Path], "RunResult"]


class RecorderError(RuntimeError):
    """A cleanly reportable safety, execution, or artifact error."""


@dataclasses.dataclass(frozen=True, slots=True)
class HostFacts:
    """Public host facts; the label is supplied, never discovered."""

    label: str
    os: str
    kernel: str
    cpu_model: str
    cpu_cores: int
    ram_bytes: int
    python: str
    docutils: str
    sphinx: str


@dataclasses.dataclass(frozen=True, slots=True)
class Scenario:
    """One command/mode/size combination with stable command placeholders."""

    name: str
    command: tuple[str, ...]
    cwd: pathlib.Path
    parameters: dict[str, ParameterValue]
    build_mode: Literal["none", "cold", "warm"]
    sphinx_source: pathlib.Path | None = None
    repetitions: int | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class RunResult:
    """Resources, result bytes, and structural counts from one subprocess."""

    elapsed_seconds: float
    user_cpu_seconds: float
    system_cpu_seconds: float
    peak_rss_bytes: int
    exit_status: int
    stdout: bytes
    structural_counts: dict[str, int]


def host_facts_json(facts: HostFacts) -> dict[str, str | int]:
    return dataclasses.asdict(facts)


def _utc_measurement_time() -> str:
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _cpu_model() -> str:
    cpuinfo = pathlib.Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip() in {"model name", "Hardware", "Processor"} and value.strip():
                return value.strip()
    return platform.processor() or platform.machine() or "unknown"


def _ram_bytes() -> int:
    page_size = os.sysconf("SC_PAGE_SIZE")
    page_count = os.sysconf("SC_PHYS_PAGES")
    if not isinstance(page_size, int) or not isinstance(page_count, int):
        raise RecorderError("could not determine physical RAM")
    return page_size * page_count


def collect_host_facts(label: str) -> HostFacts:
    """Collect D5's facts without consulting a hostname source."""
    try:
        os_name = platform.freedesktop_os_release().get("PRETTY_NAME", platform.system())
    except OSError:
        os_name = platform.system()
    return HostFacts(
        label=label,
        os=os_name,
        kernel=platform.release(),
        cpu_model=_cpu_model(),
        cpu_cores=os.cpu_count() or 0,
        ram_bytes=_ram_bytes(),
        python=platform.python_version(),
        docutils=docutils.__version__,
        sphinx=sphinx.__version__,
    )


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _non_negative_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record the reader-latency matrix with the worktree CLI.")
    parser.add_argument("--artifact", required=True, type=pathlib.Path, help="host-scoped JSON artifact path")
    parser.add_argument("--host-label", required=True, help="public label supplied by the user; never a hostname")
    parser.add_argument("--repetitions", type=_positive_integer, default=3)
    parser.add_argument("--replace", action="store_true", help="replace matching host/commit/scenario records")
    parser.add_argument("--dry-run", action="store_true", help="list commands without generating or running anything")
    parser.add_argument("--test-suite", action="store_true", help="also measure one project test-suite run")
    parser.add_argument(
        "--small-project-unrelated", type=_non_negative_integer, default=DEFAULT_SMALL_UNRELATED, metavar="N"
    )
    parser.add_argument(
        "--large-project-unrelated", type=_non_negative_integer, default=DEFAULT_LARGE_UNRELATED, metavar="N"
    )
    parser.add_argument(
        "--large-page-sections", type=_positive_integer, default=DEFAULT_LARGE_PAGE_SECTIONS, metavar="N"
    )
    parser.add_argument("--fragment-includers", type=_positive_integer, default=DEFAULT_FRAGMENT_INCLUDERS, metavar="N")
    return parser


def _git(repository: pathlib.Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
    )
    if result.returncode:
        raise RecorderError(f"git {' '.join(arguments)} failed with status {result.returncode}")
    return result.stdout.decode("utf-8", errors="surrogateescape").strip()


def _require_clean_worktree(repository: pathlib.Path) -> None:
    status = _git(repository, "status", "--porcelain")
    if status:
        entries = len(status.splitlines())
        raise RecorderError(f"worktree is dirty ({entries} status entr{'y' if entries == 1 else 'ies'})")


def _worktree_version(source_root: pathlib.Path) -> str:
    metadata_path = source_root / "src" / "check_rst" / "__init__.py"
    try:
        metadata = ast.parse(metadata_path.read_text(encoding="utf-8"), filename=str(metadata_path))
    except (OSError, SyntaxError) as exc:
        raise RecorderError(f"cannot read worktree version from {metadata_path}") from exc
    for statement in metadata.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__version__" for target in statement.targets):
            continue
        if isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
            return statement.value.value
    raise RecorderError(f"worktree version is missing from {metadata_path}")


def _external_artifact_path(path: pathlib.Path, repository: pathlib.Path) -> pathlib.Path:
    resolved = path.expanduser().resolve()
    if resolved.is_relative_to(repository):
        raise RecorderError(f"artifact path must be outside the measured worktree: {resolved}")
    return resolved


def _reader_command(
    *,
    command: Literal["context", "outline"],
    title: str,
    target: str,
    mode: Literal["verified-cold", "verified-warm", "heuristic"],
    no_toctree: bool,
) -> tuple[str, ...]:
    arguments: list[str] = [command]
    if no_toctree:
        arguments.append("--no-toctree")
    if command == "context":
        arguments.extend((title, target))
    else:
        arguments.append(target)
    if mode == "heuristic":
        return ("--no-config", *arguments)
    return (
        "--no-config",
        "--sphinx-src",
        "{sphinx_src}",
        "--build-dir",
        "{build_dir}",
        *arguments,
    )


def _generated_scenarios(projects: dict[str, GeneratedProject]) -> list[Scenario]:
    scenarios: list[Scenario] = []
    for project_size in ("small", "large"):
        project = projects[project_size]
        for target_size, target, title in (
            ("small", project.small_target, project.small_title),
            ("large", project.large_target, project.large_title),
        ):
            for command in ("context", "outline"):
                for mode in ("verified-cold", "verified-warm", "heuristic"):
                    recursion_modes = (False,) if mode == "heuristic" else (False, True)
                    for no_toctree in recursion_modes:
                        recursion = "no-toctree" if no_toctree else "toctree"
                        scenarios.append(
                            Scenario(
                                name=f"generated-{project_size}-{target_size}-{command}-{mode}-{recursion}",
                                command=_reader_command(
                                    command=command,
                                    title=title,
                                    target=target.name,
                                    mode=mode,
                                    no_toctree=no_toctree,
                                ),
                                cwd=project.root,
                                parameters={
                                    "corpus": "generated",
                                    "project_size": project_size,
                                    "target_size": target_size,
                                    "unrelated_documents": project.size.unrelated_documents,
                                    "large_page_sections": project.size.large_page_sections,
                                    "fragment_includers": project.size.fragment_includers,
                                    "command": command,
                                    "mode": mode,
                                    "no_toctree": no_toctree,
                                },
                                build_mode=(
                                    "cold" if mode == "verified-cold" else "warm" if mode == "verified-warm" else "none"
                                ),
                                sphinx_source=project.root if mode != "heuristic" else None,
                            )
                        )
    return scenarios


def _public_scenarios(repository: pathlib.Path, commit: str) -> list[Scenario]:
    scenarios: list[Scenario] = []
    for mode in ("verified-cold", "verified-warm", "heuristic"):
        no_toctree = mode != "heuristic"
        recursion = "no-toctree" if no_toctree else "toctree"
        scenarios.append(
            Scenario(
                name=f"public-context-{recursion}-{mode}",
                command=_reader_command(
                    command="context",
                    title="Piping anti-patterns",
                    target="docs/guide.rst",
                    mode=mode,
                    no_toctree=no_toctree,
                ),
                cwd=repository,
                parameters={
                    "corpus": "check_rst-docs",
                    "measured_commit": commit,
                    "project_size": "repository-docs",
                    "target_size": "small",
                    "command": "context",
                    "mode": mode,
                    "no_toctree": no_toctree,
                },
                build_mode=("cold" if mode == "verified-cold" else "warm" if mode == "verified-warm" else "none"),
                sphinx_source=repository / "docs" if mode != "heuristic" else None,
            )
        )
    return scenarios


def _dry_run_scenarios(repository: pathlib.Path) -> list[Scenario]:
    placeholder = GeneratedProject(
        root=pathlib.Path("<temporary-generated-project>"),
        small_target=pathlib.Path("<temporary-generated-project>/small.rst"),
        large_target=pathlib.Path("<temporary-generated-project>/large.rst"),
        size=CorpusSize(
            unrelated_documents=DEFAULT_SMALL_UNRELATED,
            large_page_sections=DEFAULT_LARGE_PAGE_SECTIONS,
            fragment_includers=DEFAULT_FRAGMENT_INCLUDERS,
        ),
    )
    return _generated_scenarios({"small": placeholder, "large": placeholder}) + _public_scenarios(
        repository, "<measured-commit>"
    )


def _test_suite_scenario(repository: pathlib.Path) -> Scenario:
    return Scenario(
        name=TEST_SUITE_SCENARIO,
        command=(sys.executable, "-m", "pytest"),
        cwd=repository,
        parameters={"kind": "test-suite"},
        build_mode="none",
        repetitions=1,
    )


def _command_for(scenario: Scenario, build_dir: pathlib.Path | None) -> tuple[str, ...]:
    replacements = {
        "{sphinx_src}": str(scenario.sphinx_source) if scenario.sphinx_source is not None else "",
        "{build_dir}": str(build_dir) if build_dir is not None else "",
    }
    return tuple(replacements.get(argument, argument) for argument in scenario.command)


def _read_counts(path: pathlib.Path) -> dict[str, int]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecorderError("subprocess did not write valid structural counts") from exc
    counts: object = raw.get("call_counts") if isinstance(raw, dict) else None
    if not isinstance(counts, dict) or not all(
        isinstance(key, str) and isinstance(value, int) for key, value in counts.items()
    ):
        raise RecorderError("subprocess structural counts are not a string-to-integer object")
    return cast("dict[str, int]", counts)


def _subprocess_command(command: Sequence[str], counts_file: pathlib.Path) -> tuple[tuple[str, ...], bool]:
    if tuple(command[:3]) == (sys.executable, "-m", "pytest"):
        return tuple(command), False
    return (
        (sys.executable, str(SUBPROCESS_RUNNER), "--counts-file", str(counts_file), "--", *command),
        True,
    )


def _run_command(command: Sequence[str], cwd: pathlib.Path, counts_file: pathlib.Path) -> RunResult:
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(SOURCE_ROOT / "src"), existing_pythonpath) if part
    )
    full_command, exports_counts = _subprocess_command(command, counts_file)
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        started = time.perf_counter()
        process = subprocess.Popen(full_command, cwd=cwd, env=environment, stdout=stdout_file, stderr=stderr_file)
        _pid, wait_status, usage = os.wait4(process.pid, 0)
        elapsed = time.perf_counter() - started
        exit_status = os.waitstatus_to_exitcode(wait_status)
        process.returncode = exit_status
        stdout_file.seek(0)
        stdout = stdout_file.read()
    peak_rss_bytes = int(usage.ru_maxrss) if sys.platform == "darwin" else int(usage.ru_maxrss) * 1024
    return RunResult(
        elapsed_seconds=elapsed,
        user_cpu_seconds=usage.ru_utime,
        system_cpu_seconds=usage.ru_stime,
        peak_rss_bytes=peak_rss_bytes,
        exit_status=exit_status,
        stdout=stdout,
        structural_counts=_read_counts(counts_file) if exports_counts else {},
    )


def _measurement_json(result: RunResult) -> dict[str, object]:
    return {
        "elapsed_seconds": result.elapsed_seconds,
        "user_cpu_seconds": result.user_cpu_seconds,
        "system_cpu_seconds": result.system_cpu_seconds,
        "peak_rss_bytes": result.peak_rss_bytes,
        "exit_status": result.exit_status,
        "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
    }


def _summary(results: Sequence[RunResult]) -> dict[str, object]:
    return {
        "elapsed_seconds": {
            "median": statistics.median(result.elapsed_seconds for result in results),
            "minimum": min(result.elapsed_seconds for result in results),
        },
        "user_cpu_seconds": {
            "median": statistics.median(result.user_cpu_seconds for result in results),
            "minimum": min(result.user_cpu_seconds for result in results),
        },
        "system_cpu_seconds": {
            "median": statistics.median(result.system_cpu_seconds for result in results),
            "minimum": min(result.system_cpu_seconds for result in results),
        },
        "peak_rss_bytes": {"maximum": max(result.peak_rss_bytes for result in results)},
    }


def _verify_repetitions(scenario: Scenario, results: Sequence[RunResult]) -> None:
    first = results[0]
    if any(result.exit_status != first.exit_status for result in results[1:]):
        raise RecorderError(f"{scenario.name}: repetitions disagree on exit status")
    first_hash = hashlib.sha256(first.stdout).digest()
    if any(hashlib.sha256(result.stdout).digest() != first_hash for result in results[1:]):
        raise RecorderError(f"{scenario.name}: repetitions disagree on stdout hash")
    if any(result.structural_counts != first.structural_counts for result in results[1:]):
        raise RecorderError(f"{scenario.name}: repetitions disagree on structural counts")


def _pytest_counts(stdout: bytes) -> dict[str, int]:
    text = stdout.decode("utf-8", errors="replace")
    summary_body = next(
        (
            match.group("body")
            for line in reversed(text.splitlines())
            if (match := PYTEST_SUMMARY_PATTERN.fullmatch(line.strip())) is not None
        ),
        None,
    )
    if summary_body is None:
        raise RecorderError("project-test-suite: pytest output has no final summary line")
    counts = dict.fromkeys(TEST_OUTCOMES, 0)
    found = False
    for match in PYTEST_OUTCOME_PATTERN.finditer(summary_body):
        outcome = match.group("outcome")
        counts["errors" if outcome in {"error", "errors"} else outcome] = int(match.group("count"))
        found = True
    if not found:
        raise RecorderError("project-test-suite: pytest final summary has no test outcomes")
    return counts


def _record_one(
    scenario: Scenario,
    repetitions: int,
    temporary_root: pathlib.Path,
    runner: Runner,
    *,
    ordinal: int,
) -> tuple[dict[str, object], str]:
    scenario_root = temporary_root / f"scenario-{ordinal:03d}"
    scenario_root.mkdir(parents=True, exist_ok=False)
    warm_build = scenario_root / "warm-build" if scenario.build_mode == "warm" else None
    if warm_build is not None:
        runner(_command_for(scenario, warm_build), scenario.cwd, scenario_root / "counts-prime.json")

    results: list[RunResult] = []
    for repetition in range(1, repetitions + 1):
        build_dir = scenario_root / f"cold-build-{repetition:03d}" if scenario.build_mode == "cold" else warm_build
        results.append(
            runner(
                _command_for(scenario, build_dir),
                scenario.cwd,
                scenario_root / f"counts-{repetition:03d}.json",
            )
        )
    _verify_repetitions(scenario, results)
    stdout_hash = hashlib.sha256(results[0].stdout).hexdigest()
    record: dict[str, object] = {
        "scenario": {
            "name": scenario.name,
            "command": list(scenario.command),
            "parameters": scenario.parameters,
        },
        "repetitions": repetitions,
        "measurements": [_measurement_json(result) for result in results],
        "structural_counts": results[0].structural_counts,
        "summary": _summary(results),
        "verified_cold_warm_output_agreement": None,
    }
    if scenario.name == TEST_SUITE_SCENARIO:
        record["test_counts"] = _pytest_counts(results[0].stdout)
    return record, stdout_hash


def _load_artifact(path: pathlib.Path, host: HostFacts) -> dict[str, object]:
    if not path.exists():
        return {"format_version": FORMAT_VERSION, "host": host_facts_json(host), "records": []}
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecorderError(f"cannot read artifact: {path}") from exc
    if not isinstance(raw, dict) or raw.get("format_version") != FORMAT_VERSION:
        raise RecorderError(f"unsupported or malformed artifact: {path}")
    existing_host = raw.get("host")
    records = raw.get("records")
    if not isinstance(existing_host, dict) or existing_host.get("label") != host.label:
        raise RecorderError(f"artifact belongs to a different host label: {path}")
    if not isinstance(records, list):
        raise RecorderError(f"artifact records are malformed: {path}")
    artifact = cast("dict[str, object]", raw)
    artifact["host"] = host_facts_json(host)
    return artifact


def _record_key(record: object) -> tuple[str, str] | None:
    if not isinstance(record, dict):
        return None
    commit = record.get("commit")
    scenario = record.get("scenario")
    if not isinstance(commit, str) or not isinstance(scenario, dict):
        return None
    name = scenario.get("name")
    return (commit, name) if isinstance(name, str) else None


def _set_output_agreement(records: Sequence[dict[str, object]], hashes: dict[str, str]) -> None:
    by_signature: dict[tuple[ParameterValue, ...], dict[str, tuple[dict[str, object], str]]] = {}
    for record in records:
        scenario = cast("dict[str, object]", record["scenario"])
        parameters = cast("dict[str, ParameterValue]", scenario["parameters"])
        mode = parameters.get("mode")
        if mode not in {"verified-cold", "verified-warm"}:
            continue
        signature = tuple(
            parameters.get(key, "")
            for key in ("corpus", "project_size", "target_size", "command", "no_toctree", "measured_commit")
        )
        by_signature.setdefault(signature, {})[mode] = (record, hashes[cast("str", scenario["name"])])
    for modes in by_signature.values():
        if set(modes) != {"verified-cold", "verified-warm"}:
            continue
        cold, cold_hash = modes["verified-cold"]
        warm, warm_hash = modes["verified-warm"]
        agreement = cold_hash == warm_hash
        cold["verified_cold_warm_output_agreement"] = agreement
        warm["verified_cold_warm_output_agreement"] = agreement


def _write_artifact(path: pathlib.Path, artifact: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            json.dump(artifact, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def record_scenarios(
    *,
    artifact_path: pathlib.Path,
    host: HostFacts,
    commit: str,
    check_rst_version: str,
    scenarios: Sequence[Scenario],
    repetitions: int,
    replace: bool,
    temporary_root: pathlib.Path,
    runner: Runner,
    measured_at: str | None = None,
) -> dict[str, object]:
    """Measure scenarios serially and atomically update one host artifact."""
    run_measured_at = measured_at if measured_at is not None else _utc_measurement_time()
    try:
        datetime.datetime.strptime(run_measured_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise RecorderError("measurement time must be a UTC ISO 8601 timestamp without subseconds") from exc
    artifact = _load_artifact(artifact_path, host)
    records = cast("list[object]", artifact["records"])
    requested_keys = {(commit, scenario.name) for scenario in scenarios}
    duplicates = requested_keys.intersection(key for record in records if (key := _record_key(record)) is not None)
    if duplicates and not replace:
        names = ", ".join(name for _commit, name in sorted(duplicates))
        raise RecorderError(f"artifact already contains host/commit/scenario record(s): {names}")
    if replace:
        records[:] = [record for record in records if _record_key(record) not in requested_keys]

    temporary_root.mkdir(parents=True, exist_ok=True)
    new_records: list[dict[str, object]] = []
    hashes: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="record-", dir=temporary_root) as run_name:
        run_root = pathlib.Path(run_name)
        for ordinal, scenario in enumerate(scenarios, 1):
            scenario_repetitions = scenario.repetitions if scenario.repetitions is not None else repetitions
            record, stdout_hash = _record_one(scenario, scenario_repetitions, run_root, runner, ordinal=ordinal)
            record["commit"] = commit
            record["check_rst_version"] = check_rst_version
            record["measured_at"] = run_measured_at
            record["host_facts"] = host_facts_json(host)
            new_records.append(record)
            hashes[scenario.name] = stdout_hash
    _set_output_agreement(new_records, hashes)
    records.extend(new_records)
    _write_artifact(artifact_path, artifact)
    return artifact


def _display_command(scenario: Scenario) -> str:
    scenario_command = _command_for(scenario, pathlib.Path("<build-dir>"))
    dispatched_command, _exports_counts = _subprocess_command(scenario_command, pathlib.Path("<counts.json>"))
    return shlex.join(dispatched_command)


def _print_summary(artifact: dict[str, object], commit: str, scenario_names: set[str]) -> None:
    print("scenario\tmode\tmedian_elapsed_s\tminimum_elapsed_s\tmedian_user_s\tmax_rss_bytes\tcounts")
    records = cast("list[object]", artifact["records"])
    for item in records:
        if not isinstance(item, dict) or item.get("commit") != commit:
            continue
        scenario = cast("dict[str, object]", item["scenario"])
        name = cast("str", scenario["name"])
        if name not in scenario_names:
            continue
        parameters = cast("dict[str, ParameterValue]", scenario["parameters"])
        summary = cast("dict[str, object]", item["summary"])
        elapsed = cast("dict[str, float]", summary["elapsed_seconds"])
        user = cast("dict[str, float]", summary["user_cpu_seconds"])
        rss = cast("dict[str, int]", summary["peak_rss_bytes"])
        counts = cast("dict[str, int]", item["structural_counts"])
        counts_text = ",".join(f"{key}={value}" for key, value in sorted(counts.items()))
        print(
            f"{name}\t{parameters.get('mode', parameters.get('kind', ''))}"
            f"\t{elapsed['median']:.6f}\t{elapsed['minimum']:.6f}"
            f"\t{user['median']:.6f}\t{rss['maximum']}\t{counts_text}"
        )


def main(arguments: list[str] | None = None, *, runner: Runner = _run_command) -> int:
    args = _build_parser().parse_args(arguments)
    repository = pathlib.Path.cwd().resolve()
    try:
        if not args.host_label.strip():
            raise RecorderError("--host-label must not be empty")
        _require_clean_worktree(repository)
        artifact_path = _external_artifact_path(args.artifact, repository)
        if args.dry_run:
            scenarios = _dry_run_scenarios(repository)
            if args.test_suite:
                scenarios.append(_test_suite_scenario(repository))
            for scenario in scenarios:
                print(f"{scenario.name}: cwd={scenario.cwd} command={_display_command(scenario)}")
            return 0

        commit = _git(repository, "rev-parse", "HEAD")
        check_rst_version = _worktree_version(SOURCE_ROOT)
        host = collect_host_facts(args.host_label)
        with tempfile.TemporaryDirectory(prefix="check-rst-perf-") as temporary_name:
            temporary = pathlib.Path(temporary_name)
            common_size = {
                "large_page_sections": args.large_page_sections,
                "fragment_includers": args.fragment_includers,
            }
            projects = {
                "small": generate_project(
                    temporary / "generated-small",
                    CorpusSize(unrelated_documents=args.small_project_unrelated, **common_size),
                ),
                "large": generate_project(
                    temporary / "generated-large",
                    CorpusSize(unrelated_documents=args.large_project_unrelated, **common_size),
                ),
            }
            scenarios = _generated_scenarios(projects) + _public_scenarios(repository, commit)
            if args.test_suite:
                scenarios.append(_test_suite_scenario(repository))
            artifact = record_scenarios(
                artifact_path=artifact_path,
                host=host,
                commit=commit,
                check_rst_version=check_rst_version,
                scenarios=scenarios,
                repetitions=args.repetitions,
                replace=args.replace,
                temporary_root=temporary / "runs",
                runner=runner,
            )
        _print_summary(artifact, commit, {scenario.name for scenario in scenarios})
    except (RecorderError, OSError, ValueError) as exc:
        print(f"perf_record: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
