# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Tests for check_rst.cli's _config domain (.check_rst.toml/pyproject.toml) — check_rst project

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from _support import _BAD_BLOCK, _GOOD_BLOCK, _git

if TYPE_CHECKING:
    import types
    from pathlib import Path


@pytest.mark.integration
def test_config_dedicated_file_applies_and_is_echoed(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    (rst_repo / ".check_rst.toml").write_text(
        f'sphinx-src = "{rst_repo}"\nbuild-dir = "{rst_repo}/_build"\n',
        encoding="utf-8",
    )
    p = rst_repo / "index.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "config: .check_rst.toml" in out  # applied values are echoed
    assert "sphinx-src" in out
    assert "Phase 3: Sphinx build integrity" in out  # verified mode ON via config


@pytest.mark.integration
def test_config_pyproject_table_applies(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    (rst_repo / "pyproject.toml").write_text(
        f'[tool.check_rst]\nsphinx-src = "{rst_repo}"\nbuild-dir = "{rst_repo}/_build"\n',
        encoding="utf-8",
    )
    p = rst_repo / "index.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "config: pyproject.toml" in out
    assert "Phase 3: Sphinx build integrity" in out


@pytest.mark.integration
def test_config_build_dir_without_sphinx_source_is_reported_inactive(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = rst_repo / ".check_rst.toml"
    config.write_text('build-dir = "_build"\n', encoding="utf-8")
    document = rst_repo / "doc.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(document)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "config: .check_rst.toml" in out
    assert "build-dir=_build inactive (no sphinx-src)" in out
    assert "Phase 3: Sphinx build — skipped" in out
    assert not (rst_repo / "_build").exists()


@pytest.mark.integration
def test_config_cli_flags_override(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI always wins: a config pointing at a conf.py-less directory must
    not be path-validated when the CLI supplies its own --sphinx-src."""
    bad = rst_repo / "not_sphinx"
    bad.mkdir()
    (rst_repo / ".check_rst.toml").write_text(f'sphinx-src = "{bad}"\n', encoding="utf-8")
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    p = rst_repo / "index.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--sphinx-src", str(rst_repo), "--build-dir", str(rst_repo / "_build"), "check", str(p)],
    )
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0  # config's bad path never used
    out = capsys.readouterr().out
    assert "no conf.py" not in out


@pytest.mark.integration
def test_config_unknown_key_fails_loudly(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A typo'd key is a mistake worth failing on immediately — same
    precedent as a --sphinx-src without conf.py."""
    (rst_repo / ".check_rst.toml").write_text('sphix-src = "."\n', encoding="utf-8")
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "sphix-src" in out
    assert "unknown key" in out


@pytest.mark.integration
def test_no_config_skips_auto_discovery(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--no-config runs as if the working directory declared no project
    facts at all — a valid, discoverable .check_rst.toml is never applied
    (no "config: ..." echo, no verified Sphinx mode from its sphinx-src)."""
    (rst_repo / ".check_rst.toml").write_text('sphinx-src = "."\n', encoding="utf-8")
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "--no-config", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "config:" not in out
    assert "Sphinx" not in out.split("\n")[0]  # runtime line carries no Sphinx version


@pytest.mark.integration
def test_no_config_skips_even_a_malformed_config(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The strongest evidence discovery is truly skipped, not just
    deprioritized: a committed .check_rst.toml with an unknown key would
    normally fail loudly on discovery alone (test_config_unknown_key_fails_
    loudly above) — --no-config must never even read it, let alone validate
    it, so the same file causes no error at all here."""
    (rst_repo / ".check_rst.toml").write_text('sphix-src = "."\n', encoding="utf-8")
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "--no-config", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "unknown key" not in out


@pytest.mark.integration
def test_no_config_rejects_explicit_config(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--no-config and --config are a direct contradiction — one says skip
    config loading, the other explicitly requests it; neither can silently
    win over the other."""
    config = rst_repo / "check-rst.toml"
    config.write_text('sphinx-src = "."\n', encoding="utf-8")
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--no-config", "--config", str(config), "check", str(p)],
    )
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--no-config is incompatible with --config" in out


@pytest.mark.integration
def test_config_dedicated_file_wins_over_pyproject(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    (rst_repo / ".check_rst.toml").write_text(
        f'sphinx-src = "{rst_repo}"\nbuild-dir = "{rst_repo}/_build"\n',
        encoding="utf-8",
    )
    (rst_repo / "pyproject.toml").write_text('[tool.check_rst]\nsphinx-src = "/nonexistent"\n', encoding="utf-8")
    p = rst_repo / "index.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit) as exc:
        check_rst.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "config: .check_rst.toml" in out


@pytest.mark.integration
def test_config_echo_suppressed_when_quiet(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    (rst_repo / ".check_rst.toml").write_text(
        f'sphinx-src = "{rst_repo}"\nbuild-dir = "{rst_repo}/_build"\n',
        encoding="utf-8",
    )
    p = rst_repo / "index.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", "--quiet", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()
    out = capsys.readouterr().out
    assert "config:" not in out


@pytest.mark.integration
def test_explicit_config_from_foreign_cwd_resolves_relative_values_from_config(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--config names the project explicitly: its paths are config-relative,
    while the process may run from an entirely unrelated directory."""
    project = tmp_path / "project"
    docs = project / "docs"
    docs.mkdir(parents=True)
    (docs / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    document = docs / "index.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    config = project / ".check_rst.toml"
    config.write_text(
        'sphinx-src = "docs"\nbuild-dir = "_build"\n',
        encoding="utf-8",
    )
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    monkeypatch.setattr(check_rst._helpers, "PROJECT_ROOT", foreign)
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--config", str(config.relative_to(foreign, walk_up=True)), "check", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert f"config: {config.resolve()}" in out
    assert f"Phase 2: Python Sphinx rules ({project / '_build'})" in out
    assert f"Phase 3: Sphinx build integrity ({project / '_build'})" in out


@pytest.mark.integration
def test_explicit_config_bare_run_discovers_git_changes_from_config_root(
    check_rst: types.ModuleType,
    tmp_git_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With no positional files, --config also defines where bare Git
    discovery and diff scoping run; invocation cwd must be irrelevant."""
    document = tmp_git_repo / "changed.rst"
    # The committed error must stay out of scope when only the appended line
    # changes; this proves diff queries use the config-selected repository.
    document.write_text(_BAD_BLOCK, encoding="utf-8")
    config = tmp_git_repo / ".check_rst.toml"
    config.write_text('build-dir = "_build"\n', encoding="utf-8")
    _git(tmp_git_repo, "add", "changed.rst", ".check_rst.toml")
    _git(tmp_git_repo, "commit", "-m", "base")
    document.write_text(_BAD_BLOCK + "\nChanged.\n", encoding="utf-8")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    monkeypatch.setattr(check_rst._helpers, "PROJECT_ROOT", foreign)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--config", str(config), "check"])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "1 file(s) checked" in out
    assert "no changed .rst files" not in out


@pytest.mark.integration
def test_explicit_config_suppresses_cwd_config_discovery(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = project / ".check_rst.toml"
    config.write_text('build-dir = "_build"\n', encoding="utf-8")
    document = project / "index.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / ".check_rst.toml").write_text('sphix-src = "typo must not be loaded"\n', encoding="utf-8")
    monkeypatch.chdir(foreign)
    monkeypatch.setattr(check_rst._helpers, "PROJECT_ROOT", foreign)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--config", str(config), "check", str(document)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert f"config: {config.resolve()}" in out
    assert "unknown key" not in out


@pytest.mark.integration
def test_explicit_pyproject_config_uses_tool_table(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = project / "pyproject.toml"
    config.write_text('[tool.check_rst]\nbuild-dir = "_build"\n', encoding="utf-8")
    document = project / "index.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    monkeypatch.setattr(check_rst._helpers, "PROJECT_ROOT", foreign)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--config", str(config), "check", str(document)])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    assert f"config: {config.resolve()}" in capsys.readouterr().out


@pytest.mark.integration
def test_explicit_config_json_uses_config_root_for_document_ids(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    docs = project / "docs"
    docs.mkdir(parents=True)
    config = project / ".check_rst.toml"
    config.write_text('build-dir = "_build"\n', encoding="utf-8")
    document = docs / "index.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    monkeypatch.setattr(check_rst._helpers, "PROJECT_ROOT", foreign)
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--config", str(config), "check", "--format=json", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["config"]["source"] == str(config.resolve())
    assert data["files"][0]["outline"][0]["id"] == "docs/index:Title"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("problem", "message"),
    [
        ("missing", "file not found"),
        ("directory", "not a regular file"),
        ("malformed", "invalid TOML"),
        ("empty", "does not declare check_rst settings"),
    ],
)
def test_explicit_config_errors_cleanly_before_actions(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    problem: str,
    message: str,
) -> None:
    config = tmp_path / "selected.toml"
    if problem == "directory":
        config.mkdir()
    elif problem == "malformed":
        config.write_text('sphinx-src = ["unterminated"\n', encoding="utf-8")
    elif problem == "empty":
        config.write_text("", encoding="utf-8")

    def unexpected_action(*_args: object, **_kwargs: object) -> None:
        pytest.fail("invalid explicit config must stop before Git or Sphinx")

    monkeypatch.setattr(check_rst._helpers, "_changed_rst_files", unexpected_action)
    monkeypatch.setattr(check_rst._sphinx, "_build_sphinx_env", unexpected_action)
    monkeypatch.setattr(check_rst._sphinx, "run_sphinx", unexpected_action)
    monkeypatch.setattr("sys.argv", ["check_rst.py", "--config", str(config), "check"])

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--config" in out
    assert message in out
    assert "Phase 1" not in out


@pytest.mark.integration
def test_explicit_config_values_are_overridden_by_cli_paths(
    check_rst: types.ModuleType,
    rst_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_dir = tmp_path / "config-project"
    config_dir.mkdir()
    config = config_dir / ".check_rst.toml"
    config.write_text(
        'sphinx-src = "missing"\nbuild-dir = "occupied"\n',
        encoding="utf-8",
    )
    (rst_repo / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    document = rst_repo / "index.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    build_dir = rst_repo / "_build"
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--config",
            str(config),
            "--sphinx-src",
            str(rst_repo),
            "--build-dir",
            str(build_dir),
            "check",
            str(document),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "no conf.py" not in out
    assert "not a directory" not in out


@pytest.mark.integration
def test_refs_accepts_explicit_config(
    check_rst: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "conf.py").write_text('project = "test"\n', encoding="utf-8")
    document = tmp_path / "index.rst"
    document.write_text(_GOOD_BLOCK, encoding="utf-8")
    config = tmp_path / ".check_rst.toml"
    config.write_text('sphinx-src = "."\nbuild-dir = "_build"\n', encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check_rst.py", "--config", str(config), "refs", str(document)],
    )

    with pytest.raises(SystemExit) as exc:
        check_rst.main()

    assert exc.value.code == 0
    assert f"References: {document}" in capsys.readouterr().out


@pytest.mark.integration
def test_call_counts_heuristic_run_never_builds_sphinx(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CALL_COUNTS pin the execution stack (Max, 2026-07-19): a bare
    heuristic-mode run must never build a Sphinx environment nor run
    sphinx-build.  This is exactly the regression the counters caught the
    day they were added — a config leak made "heuristic" CLI tests silently
    run full Journal builds; wall-clock raised suspicion, the counters
    proved it deterministically, and this assertion now FAILS instead of
    merely running slowly."""
    p = rst_repo / "test.rst"
    p.write_text(_GOOD_BLOCK, encoding="utf-8")

    check_rst.CALL_COUNTS.clear()
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check", str(p)])
    with pytest.raises(SystemExit):
        check_rst.main()

    assert check_rst.CALL_COUNTS["_build_sphinx_env"] == 0
    assert check_rst.CALL_COUNTS["run_sphinx"] == 0
    assert check_rst.CALL_COUNTS["_load_config"] == 1
    assert check_rst.CALL_COUNTS["_parse_rst"] >= 1


@pytest.mark.integration
def test_call_counts_verified_run_builds_exactly_once(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verified mode: one env build and one sphinx-build PER RUN, never per
    file — the counters make the O(1)-vs-O(files) distinction a test fact
    instead of a performance impression."""
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    a = rst_repo / "index.rst"
    a.write_text(_GOOD_BLOCK, encoding="utf-8")
    b = rst_repo / "other.rst"
    b.write_text(_GOOD_BLOCK, encoding="utf-8")

    check_rst.CALL_COUNTS.clear()
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "--build-dir",
            str(rst_repo / "_build"),
            "check",
            str(a),
            str(b),
        ],
    )
    with pytest.raises(SystemExit):
        check_rst.main()

    assert check_rst.CALL_COUNTS["_build_sphinx_env"] == 1
    assert check_rst.CALL_COUNTS["run_sphinx"] == 1


@pytest.mark.integration
def test_call_counts_toctree_anomalies_computed_once_per_run(
    check_rst: types.ModuleType,
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Found by code review: check_multiple_toctree_parents rebuilt the
    whole project-wide parents_by_child/anomalies graph from
    env.toctree_includes from scratch on every call, but Phase 2's own
    loop called it once PER FILE with the same, unchanged env — O(files)
    redundant rebuilds of one project-wide graph. _toctree_anomalies
    (the split-out, cacheable half) must run exactly once per run, no
    matter how many files are selected, the same one-computation
    contract test_call_counts_verified_run_builds_exactly_once already
    pins for _build_sphinx_env/run_sphinx."""
    (rst_repo / "conf.py").write_text('project = "t"\nextensions = []\n', encoding="utf-8")
    a = rst_repo / "index.rst"
    a.write_text(_GOOD_BLOCK, encoding="utf-8")
    b = rst_repo / "other.rst"
    b.write_text(_GOOD_BLOCK, encoding="utf-8")

    check_rst.CALL_COUNTS.clear()
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_rst.py",
            "--sphinx-src",
            str(rst_repo),
            "--build-dir",
            str(rst_repo / "_build"),
            "check",
            str(a),
            str(b),
        ],
    )
    with pytest.raises(SystemExit):
        check_rst.main()

    assert check_rst.CALL_COUNTS["_toctree_anomalies"] == 1
