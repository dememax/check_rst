# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Tests for the subprocess performance recorder — check_rst project
"""Specify repeatability, safety, and artifact contracts for PF-2."""

from __future__ import annotations

import hashlib
import importlib
import json
from typing import TYPE_CHECKING, Protocol, cast

import pytest

if TYPE_CHECKING:
    from pathlib import Path
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
        scenarios=[_scenario(module, tmp_path)],
        repetitions=2,
        replace=False,
        temporary_root=tmp_path / "runs",
        runner=lambda _command, _cwd, _counts: results.pop(0),
    )

    assert artifact["format_version"] == 1
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

    status = module.main(
        ["--artifact", str(tmp_git_repo / "artifact.json"), "--host-label", "chosen-label", "--dry-run"],
        runner=lambda *_args: pytest.fail("ran a scenario"),
    )

    output = capsys.readouterr()
    assert status == 0
    assert len(output.out.splitlines()) == 43
    assert "public-context-no-toctree-verified-cold" in output.out
    assert "public-context-toctree-heuristic" in output.out
    assert "heuristic-no-toctree" not in output.out
    assert output.err == ""
    assert not (tmp_git_repo / "artifact.json").exists()


@pytest.mark.unit
def test_host_label_comes_only_from_the_option(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    monkeypatch.setattr(module.platform, "node", lambda: pytest.fail("read the hostname"))

    facts = module.collect_host_facts("user-supplied")

    assert facts.label == "user-supplied"
    assert "hostname" not in module.host_facts_json(facts)
