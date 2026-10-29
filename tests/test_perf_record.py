# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Tests for the subprocess performance recorder — check_rst project
"""Specify repeatability, safety, and artifact contracts for PF-2."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import pytest

if TYPE_CHECKING:
    from types import ModuleType


class _RunResultLike(Protocol):
    elapsed_seconds: float
    user_cpu_seconds: float
    system_cpu_seconds: float
    peak_rss_bytes: int
    exit_status: int
    stdout: bytes


def _module() -> ModuleType:
    return importlib.import_module("tools.perf_record")


def _host(module: ModuleType, label: str = "chosen-label") -> object:
    return module.HostFacts(
        label=label,
        os="Test OS",
        kernel="test-kernel",
        cpu_model="Test CPU",
        cpu_cores=8,
        ram_bytes=16_000_000_000,
        python="3.14.test",
        docutils="0.23",
        sphinx="9.1.test",
    )


def _scenario(module: ModuleType, root: Path) -> object:
    return module.Scenario(
        name="generated-small-small-context-heuristic-toctree",
        command=("--no-config", "context", "Small target", "small.rst"),
        cwd=root,
        parameters={
            "command": "context",
            "mode": "heuristic",
            "project_size": "small",
            "target_size": "small",
            "no_toctree": False,
        },
        build_mode="none",
    )


def _result(
    module: ModuleType,
    *,
    elapsed: float = 2.0,
    stdout: bytes = b"stable\n",
    exit_status: int = 0,
) -> _RunResultLike:
    return cast(
        "_RunResultLike",
        module.RunResult(
            elapsed_seconds=elapsed,
            user_cpu_seconds=1.5,
            system_cpu_seconds=0.25,
            peak_rss_bytes=12_345_678,
            exit_status=exit_status,
            stdout=stdout,
            structural_counts={"_parse_rst": 2, "_read_source": 1},
        ),
    )


@pytest.mark.integration
def test_recorder_writes_complete_artifact_and_timing_summary(tmp_path: Path) -> None:
    module = _module()
    results = [_result(module, elapsed=2.0), _result(module, elapsed=1.0)]

    artifact = module.record_scenarios(
        artifact_path=tmp_path / "performance.json",
        host=_host(module),
        commit="1" * 40,
        check_rst_version="0.7.4",
        measured_at="2026-10-29T12:00:00Z",
        scenarios=[_scenario(module, tmp_path)],
        repetitions=2,
        replace=False,
        temporary_root=tmp_path / "runs",
        runner=lambda _command, _cwd, _counts: results.pop(0),
    )

    assert artifact["format_version"] == 2
    assert artifact["host"] == {
        "label": "chosen-label",
        "os": "Test OS",
        "kernel": "test-kernel",
        "cpu_model": "Test CPU",
        "cpu_cores": 8,
        "ram_bytes": 16_000_000_000,
        "python": "3.14.test",
        "docutils": "0.23",
        "sphinx": "9.1.test",
    }
    [record] = artifact["records"]
    assert record["commit"] == "1" * 40
    assert record["check_rst_version"] == "0.7.4"
    assert record["measured_at"] == "2026-10-29T12:00:00Z"
    assert record["scenario"]["name"] == "generated-small-small-context-heuristic-toctree"
    assert record["repetitions"] == 2
    assert record["structural_counts"] == {"_parse_rst": 2, "_read_source": 1}
    assert record["summary"] == {
        "elapsed_seconds": {"median": 1.5, "minimum": 1.0},
        "user_cpu_seconds": {"median": 1.5, "minimum": 1.5},
        "system_cpu_seconds": {"median": 0.25, "minimum": 0.25},
        "peak_rss_bytes": {"maximum": 12_345_678},
    }
    assert {measurement["stdout_sha256"] for measurement in record["measurements"]} == {
        hashlib.sha256(b"stable\n").hexdigest()
    }
    assert json.loads((tmp_path / "performance.json").read_text(encoding="utf-8")) == artifact


@pytest.mark.integration
def test_duplicate_is_refused_before_running_and_replace_is_explicit(tmp_path: Path) -> None:
    module = _module()
    artifact_path = tmp_path / "performance.json"
    arguments = {
        "artifact_path": artifact_path,
        "host": _host(module),
        "commit": "2" * 40,
        "check_rst_version": "0.7.4",
        "scenarios": [_scenario(module, tmp_path)],
        "repetitions": 1,
        "temporary_root": tmp_path / "runs",
    }
    record_scenarios = module.record_scenarios
    module_error = module.RecorderError
    record_scenarios(**arguments, replace=False, runner=lambda *_args: _result(module, elapsed=2.0))

    def must_not_run(*_args: object) -> None:
        pytest.fail("duplicate check must precede measurement")

    with pytest.raises(module_error, match="already contains"):
        record_scenarios(**arguments, replace=False, runner=must_not_run)

    replaced = record_scenarios(
        **arguments,
        replace=True,
        runner=lambda *_args: _result(module, elapsed=3.0),
    )
    assert len(replaced["records"]) == 1
    assert replaced["records"][0]["summary"]["elapsed_seconds"]["median"] == 3.0


@pytest.mark.integration
@pytest.mark.parametrize(
    ("difference", "message"),
    [
        pytest.param("exit", "exit status", id="exit-status"),
        pytest.param("stdout", "stdout", id="stdout-hash"),
        pytest.param("counts", "structural counts", id="structural-counts"),
    ],
)
def test_repetition_disagreement_is_an_error(tmp_path: Path, difference: str, message: str) -> None:
    module = _module()
    first = _result(module)
    second = _result(
        module,
        stdout=b"changed\n" if difference == "stdout" else b"stable\n",
        exit_status=1 if difference == "exit" else 0,
    )
    if difference == "counts":
        second = module.RunResult(
            elapsed_seconds=second.elapsed_seconds,
            user_cpu_seconds=second.user_cpu_seconds,
            system_cpu_seconds=second.system_cpu_seconds,
            peak_rss_bytes=second.peak_rss_bytes,
            exit_status=second.exit_status,
            stdout=second.stdout,
            structural_counts={"_parse_rst": 3, "_read_source": 1},
        )
    results = [first, second]

    with pytest.raises(module.RecorderError, match=message):
        module.record_scenarios(
            artifact_path=tmp_path / "performance.json",
            host=_host(module),
            commit="3" * 40,
            check_rst_version="0.7.4",
            scenarios=[_scenario(module, tmp_path)],
            repetitions=2,
            replace=False,
            temporary_root=tmp_path / "runs",
            runner=lambda _command, _cwd, _counts: results.pop(0),
        )


@pytest.mark.integration
def test_dirty_worktree_is_refused_before_dry_run(
    tmp_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    (tmp_git_repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    monkeypatch.chdir(tmp_git_repo)

    status = module.main(
        ["--artifact", str(tmp_git_repo / "artifact.json"), "--host-label", "chosen-label", "--dry-run"]
    )

    assert status == 1
    assert "worktree is dirty" in capsys.readouterr().err
    assert not (tmp_git_repo / "artifact.json").exists()


@pytest.mark.integration
def test_dry_run_lists_full_reader_matrix_without_running(
    tmp_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    monkeypatch.chdir(tmp_git_repo)
    monkeypatch.setattr(module, "generate_project", lambda *_args, **_kwargs: pytest.fail("generated a corpus"))
    artifact = tmp_git_repo.parent / f"{tmp_git_repo.name}-artifact.json"

    status = module.main(
        ["--artifact", str(artifact), "--host-label", "chosen-label", "--dry-run"],
        runner=lambda *_args: pytest.fail("ran a scenario"),
    )

    output = capsys.readouterr()
    assert status == 0
    assert len(output.out.splitlines()) == 43
    assert "public-context-no-toctree-verified-cold" in output.out
    assert "public-context-toctree-heuristic" in output.out
    assert "heuristic-no-toctree" not in output.out
    assert output.err == ""
    assert not artifact.exists()


@pytest.mark.integration
def test_test_suite_option_records_one_injected_run_and_outcome_counts(
    tmp_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    monkeypatch.chdir(tmp_git_repo)
    monkeypatch.setattr(module, "collect_host_facts", lambda label: _host(module, label))
    monkeypatch.setattr(module, "generate_project", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(module, "_generated_scenarios", lambda _projects: [])
    monkeypatch.setattr(module, "_public_scenarios", lambda _repository, _commit: [])
    artifact = tmp_git_repo.parent / f"{tmp_git_repo.name}-artifact.json"
    commands: list[tuple[str, ...]] = []
    pytest_stdout = (
        b"1 passed in test output\n"
        b"===== 1 error, 2 failed, 2375 passed, 7 skipped, 5 xfailed, 3 xpassed in 4.00s =====\n"
        b"999 passed after the summary\n"
    )

    def fake_runner(command: tuple[str, ...], _cwd: Path, _counts: Path) -> _RunResultLike:
        commands.append(command)
        return cast(
            "_RunResultLike",
            module.RunResult(4.0, 3.0, 0.5, 20_000_000, 1, pytest_stdout, {}),
        )

    status = module.main(
        ["--artifact", str(artifact), "--host-label", "invented-host", "--test-suite"],
        runner=fake_runner,
    )

    assert status == 0
    assert len(commands) == 1
    assert commands[0][1:3] == ("-m", "pytest")
    recorded = json.loads(artifact.read_text(encoding="utf-8"))
    [record] = recorded["records"]
    assert record["scenario"]["name"] == "project-test-suite"
    assert record["repetitions"] == 1
    assert record["test_counts"] == {
        "passed": 2375,
        "failed": 2,
        "skipped": 7,
        "errors": 1,
        "xfailed": 5,
        "xpassed": 3,
    }
    assert record["measurements"] == [
        {
            "elapsed_seconds": 4.0,
            "exit_status": 1,
            "peak_rss_bytes": 20_000_000,
            "stdout_sha256": hashlib.sha256(pytest_stdout).hexdigest(),
            "system_cpu_seconds": 0.5,
            "user_cpu_seconds": 3.0,
        }
    ]


@pytest.mark.unit
def test_pytest_counts_refuses_outcome_phrases_without_a_final_summary() -> None:
    module = _module()

    with pytest.raises(module.RecorderError, match="final summary"):
        module._pytest_counts(b"2 failed, 2375 passed, 7 skipped in ordinary output\n")


@pytest.mark.integration
def test_test_suite_dry_run_lists_command_without_running(
    tmp_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    monkeypatch.chdir(tmp_git_repo)
    artifact = tmp_git_repo.parent / f"{tmp_git_repo.name}-artifact.json"

    status = module.main(
        ["--artifact", str(artifact), "--host-label", "invented-host", "--test-suite", "--dry-run"],
        runner=lambda *_args: pytest.fail("ran the test suite"),
    )

    output = capsys.readouterr()
    assert status == 0
    suite_line = next(line for line in output.out.splitlines() if line.startswith("project-test-suite:"))
    expected_command = shlex.join((sys.executable, "-m", "pytest"))
    assert suite_line == f"project-test-suite: cwd={tmp_git_repo} command={expected_command}"
    assert str(module.SUBPROCESS_RUNNER) not in suite_line
    assert output.err == ""
    assert not artifact.exists()


@pytest.mark.unit
def test_test_suite_uses_direct_subprocess_instead_of_check_rst_runner(tmp_path: Path) -> None:
    module = _module()
    suite = module._test_suite_scenario(tmp_path)

    suite_command, suite_counts = module._subprocess_command(suite.command, tmp_path / "suite-counts.json")
    reader_command, reader_counts = module._subprocess_command(
        ("--no-config", "outline", "small.rst"), tmp_path / "reader-counts.json"
    )

    assert suite_command == suite.command
    assert suite_counts is False
    assert reader_command[:2] == (sys.executable, str(module.SUBPROCESS_RUNNER))
    assert reader_counts is True


@pytest.mark.integration
def test_artifact_inside_measured_worktree_is_refused(
    tmp_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    monkeypatch.chdir(tmp_git_repo)

    status = module.main(["--artifact", "artifact.json", "--host-label", "chosen-label", "--dry-run"])

    assert status == 1
    assert "artifact path must be outside the measured worktree" in capsys.readouterr().err
    assert not (tmp_git_repo / "artifact.json").exists()


@pytest.mark.integration
def test_module_invocation_records_worktree_version_despite_decoy(
    tmp_git_repo: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    decoy_root = tmp_git_repo.parent / f"{tmp_git_repo.name}-decoy"
    decoy_package = decoy_root / "check_rst"
    decoy_package.mkdir(parents=True)
    (decoy_package / "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
    artifact = tmp_git_repo.parent / f"{tmp_git_repo.name}-performance.json"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(decoy_root), str(project_root)))

    help_result = subprocess.run(
        [sys.executable, "-m", "tools.perf_record", "--help"],
        cwd=project_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert help_result.returncode == 0, help_result.stderr

    worktree_environment = environment.copy()
    worktree_environment["PYTHONPATH"] = str(project_root / "src")
    version_result = subprocess.run(
        [sys.executable, "-c", "import check_rst; print(check_rst.__version__)"],
        cwd=project_root,
        env=worktree_environment,
        check=True,
        capture_output=True,
        text=True,
    )

    harness = textwrap.dedent(
        """
        import sys
        from tools import perf_record

        def fake_runner(_command, _cwd, _counts_file):
            return perf_record.RunResult(0.1, 0.05, 0.01, 1024, 0, b"stable\\n", {"_parse_rst": 1})

        raise SystemExit(perf_record.main([
            "--artifact", sys.argv[1],
            "--host-label", "test-host",
            "--repetitions", "1",
            "--small-project-unrelated", "0",
            "--large-project-unrelated", "0",
            "--large-page-sections", "1",
            "--fragment-includers", "2",
        ], runner=fake_runner))
        """
    )
    record_result = subprocess.run(
        [sys.executable, "-c", harness, str(artifact)],
        cwd=tmp_git_repo,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert record_result.returncode == 0, record_result.stderr
    recorded = json.loads(artifact.read_text(encoding="utf-8"))
    assert {record["check_rst_version"] for record in recorded["records"]} == {version_result.stdout.strip()}


@pytest.mark.integration
def test_generated_scenarios_retain_concrete_corpus_sizes(tmp_path: Path) -> None:
    from tools.perf_corpus import CorpusSize, generate_project

    module = _module()
    projects = {
        "small": generate_project(tmp_path / "small", CorpusSize(2, 5, 4)),
        "large": generate_project(tmp_path / "large", CorpusSize(7, 5, 4)),
    }

    scenarios = module._generated_scenarios(projects)
    small = next(
        scenario for scenario in scenarios if scenario.name == "generated-small-small-context-heuristic-toctree"
    )
    large = next(
        scenario for scenario in scenarios if scenario.name == "generated-large-small-context-heuristic-toctree"
    )
    assert small.parameters["unrelated_documents"] == 2
    assert large.parameters["unrelated_documents"] == 7
    assert small.parameters["large_page_sections"] == large.parameters["large_page_sections"] == 5
    assert small.parameters["fragment_includers"] == large.parameters["fragment_includers"] == 4


@pytest.mark.unit
def test_host_label_comes_only_from_the_option(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    monkeypatch.setattr(module.platform, "node", lambda: pytest.fail("read the hostname"))

    facts = module.collect_host_facts("user-supplied")

    assert facts.label == "user-supplied"
    assert "hostname" not in module.host_facts_json(facts)
