# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Declared standalone and fragment roles and their pattern contract (CR-43, D9a) — check_rst project
"""D9a declares two roles, each in ``.check_rst.toml`` and on the command line:
``standalone`` (also a standalone document, although a visible file includes
it) and ``fragments`` (a fragment whose includer check_rst cannot see).  This
pair pins how they are read, merged and matched.  What a role then does to a
title model belongs to later CR-43 pairs.

The pattern contract: pathname globs over regular files under the discovery
roots, ignored files included; ``*``, ``?`` and ``[...]`` within one path
component and ``**`` across directories; hidden names only by an explicit
dot; configuration patterns relative to the configuration file, never
absolute; command-line patterns relative to the working directory or
absolute, but only inside the roots; an unmatched pattern or a symlink
escaping the roots exits 1 and names the pattern.
"""

from __future__ import annotations

import importlib
import json
import os
from typing import TYPE_CHECKING

import pytest
from _support import _locked

from check_rst import cli
from check_rst.cli import _config, _helpers

if TYPE_CHECKING:
    import types
    from pathlib import Path

    from check_rst.cli._includes import DeclaredRoles


@pytest.fixture
def roles() -> types.ModuleType:
    return importlib.import_module("check_rst.cli._includes")


def _write(path: Path, text: str = "Text.\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _resolve(roles: types.ModuleType, root: Path, *patterns: tuple[str, str, str, Path]) -> DeclaredRoles:
    declared = [roles.RolePattern(role, pattern, source, base) for role, pattern, source, base in patterns]
    resolved: DeclaredRoles = roles.resolve_roles(declared, (root.resolve(),))
    return resolved


# ---------------------------------------------------------------------------
# Configuration keys
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_configuration_accepts_standalone_and_fragments_pattern_arrays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".check_rst.toml").write_text(
        'standalone = ["cv.en.rst"]\nfragments = ["parts/*.rst", "contact.rst"]\n', encoding="utf-8"
    )
    monkeypatch.setattr(_helpers, "PROJECT_ROOT", tmp_path)

    loaded = _config._load_config()

    assert loaded.values == {}
    assert loaded.roles == {"standalone": ("cv.en.rst",), "fragments": ("parts/*.rst", "contact.rst")}


@pytest.mark.integration
@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('fragments = "parts/*.rst"\n', "fragments must be an array of pattern strings"),
        ("standalone = [1]\n", "standalone must be an array of pattern strings"),
        ('fragments = ["/abs/part.rst"]\n', "configuration patterns are relative to the configuration file"),
        ('fragments = [""]\n', "fragments must be an array of pattern strings"),
    ],
    ids=["string", "non-string-element", "absolute", "empty"],
)
def test_configuration_rejects_malformed_role_patterns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], text: str, message: str
) -> None:
    (tmp_path / ".check_rst.toml").write_text(text, encoding="utf-8")
    monkeypatch.setattr(_helpers, "PROJECT_ROOT", tmp_path)

    with pytest.raises(SystemExit) as exc:
        _config._load_config()

    assert exc.value.code == 1
    assert message in capsys.readouterr().out


@pytest.mark.integration
def test_the_unknown_key_message_lists_the_role_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".check_rst.toml").write_text('fragment = ["parts/*.rst"]\n', encoding="utf-8")
    monkeypatch.setattr(_helpers, "PROJECT_ROOT", tmp_path)

    with pytest.raises(SystemExit):
        _config._load_config()

    assert "known keys: build-dir, fragments, sphinx-src, standalone" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The pattern contract
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_patterns_glob_within_components_and_across_directories(roles: types.ModuleType, tmp_path: Path) -> None:
    root = tmp_path.resolve()
    one = _write(root / "parts" / "one.rst")
    two = _write(root / "parts" / "deep" / "two.rst")
    _write(root / "parts" / "notes.txt")
    _write(root / "parts" / ".hidden.rst")
    _write(root / ".private" / "secret.rst")
    _write(root / "c1.rst")
    _write(root / "c2.rst")

    star = _resolve(roles, root, ("fragments", "parts/*.rst", "cli", root))
    globstar = _resolve(roles, root, ("fragments", "**/*.rst", "cli", root))
    char_class = _resolve(roles, root, ("fragments", "c[12].rst", "cli", root))
    explicit_dot = _resolve(roles, root, ("fragments", "parts/.*.rst", "cli", root))

    assert star.fragments == frozenset({one})
    assert globstar.fragments == frozenset({one, two, root / "c1.rst", root / "c2.rst"})
    assert char_class.fragments == frozenset({root / "c1.rst", root / "c2.rst"})
    assert explicit_dot.fragments == frozenset({root / "parts" / ".hidden.rst"})


@pytest.mark.integration
def test_a_pattern_naming_only_a_directory_matches_nothing(roles: types.ModuleType, tmp_path: Path) -> None:
    root = tmp_path.resolve()
    _write(root / "parts" / "one.rst")

    with pytest.raises(roles.RolePatternError, match=r"fragments pattern 'parts' matches no file"):
        _resolve(roles, root, ("fragments", "parts", "--fragment", root))


@pytest.mark.integration
def test_an_ignored_file_can_be_declared_explicitly(roles: types.ModuleType, tmp_git_repo: Path) -> None:
    """The role-pattern domain includes ignored files: an explicit
    declaration must be able to protect an ignored or generated fragment,
    although the automatic includer scan skips it."""
    root = tmp_git_repo.resolve()
    _write(root / ".gitignore", "generated/\n")
    generated = _write(root / "generated" / "gen.rst")

    declared = _resolve(roles, root, ("fragments", "generated/gen.rst", "--fragment", root))

    assert declared.fragments == frozenset({generated})
    assert generated not in roles.scan_population((root,))


@pytest.mark.integration
def test_symlinked_duplicates_canonicalize_to_one_member(roles: types.ModuleType, tmp_path: Path) -> None:
    root = tmp_path.resolve()
    real = _write(root / "real" / "part.rst")
    (root / "alias.rst").symlink_to(os.path.relpath(real, root))

    declared = _resolve(roles, root, ("fragments", "*.rst", "cli", root), ("fragments", "real/*.rst", "cli", root))

    assert declared.fragments == frozenset({real})


@pytest.mark.integration
def test_a_symlink_escaping_the_roots_is_rejected(
    roles: types.ModuleType, tmp_path_factory: pytest.TempPathFactory
) -> None:
    root = tmp_path_factory.mktemp("root").resolve()
    outside = _write(tmp_path_factory.mktemp("outside") / "part.rst")
    (root / "link.rst").symlink_to(outside)

    with pytest.raises(roles.RolePatternError, match=r"resolves outside the discovery roots"):
        _resolve(roles, root, ("fragments", "link.rst", "--fragment", root))


@pytest.mark.integration
@pytest.mark.parametrize("form", ["absolute", "dotdot"])
def test_a_command_line_pattern_outside_the_roots_is_rejected(
    roles: types.ModuleType, tmp_path_factory: pytest.TempPathFactory, form: str
) -> None:
    root = tmp_path_factory.mktemp("root").resolve()
    _write(root / "inside.rst")
    outside = _write(tmp_path_factory.mktemp("outside") / "part.rst")
    pattern = str(outside) if form == "absolute" else os.path.relpath(outside, root)

    with pytest.raises(roles.RolePatternError, match=r"is outside the discovery roots"):
        _resolve(roles, root, ("fragments", pattern, "--fragment", root))


@pytest.mark.integration
def test_an_absolute_command_line_pattern_inside_the_roots_is_accepted(roles: types.ModuleType, tmp_path: Path) -> None:
    root = tmp_path.resolve()
    part = _write(root / "parts" / "one.rst")

    declared = _resolve(roles, root, ("fragments", str(root / "parts" / "*.rst"), "--fragment", root))

    assert declared.fragments == frozenset({part})


@pytest.mark.integration
def test_a_pattern_that_may_match_inside_an_unreadable_directory_fails(roles: types.ModuleType, tmp_path: Path) -> None:
    """A partial match set would silently drop part of a declaration's
    protection, so it fails like an unmatched pattern."""
    root = tmp_path.resolve()
    _write(root / "docs" / "a.rst")
    _write(root / "private" / "b.rst")

    with (
        _locked(root / "private"),
        pytest.raises(
            roles.RolePatternError,
            match=r"fragments pattern '\*\*/\*\.rst' may match a file in .*private, which cannot be read",
        ),
    ):
        _resolve(roles, root, ("fragments", "**/*.rst", "--fragment", root))


@pytest.mark.integration
def test_an_unreadable_directory_that_a_pattern_cannot_reach_is_harmless(
    roles: types.ModuleType, tmp_path: Path
) -> None:
    root = tmp_path.resolve()
    doc = _write(root / "docs" / "a.rst")
    _write(root / "private" / "b.rst")

    with _locked(root / "private"):
        resolved = _resolve(roles, root, ("fragments", "docs/*.rst", "--fragment", root))

    assert resolved.fragments == {doc}


@pytest.mark.integration
def test_both_roles_may_name_the_same_file(roles: types.ModuleType, tmp_path: Path) -> None:
    root = tmp_path.resolve()
    cv = _write(root / "cv.rst")

    declared = _resolve(roles, root, ("standalone", "cv.rst", "cli", root), ("fragments", "cv.rst", "cli", root))

    assert (declared.standalone, declared.fragments) == (frozenset({cv}), frozenset({cv}))


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _main(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    monkeypatch.setattr("sys.argv", ["check_rst.py", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    code = exc.value.code
    return (code if isinstance(code, int) else 1), capsys.readouterr().out


@pytest.mark.integration
def test_an_unmatched_command_line_pattern_exits_1_and_names_itself(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = _write(rst_repo / "doc.rst", "#####\nDoc\n#####\n")
    monkeypatch.chdir(rst_repo)

    code, out = _main(monkeypatch, capsys, "--no-config", "--fragment", "typo/*.rst", "check", str(doc))

    assert code == 1
    assert "check_rst: --fragment: fragments pattern 'typo/*.rst' matches no file" in out


@pytest.mark.integration
def test_an_unmatched_configuration_pattern_exits_1_and_names_its_file(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = _write(rst_repo / "doc.rst", "#####\nDoc\n#####\n")
    (rst_repo / ".check_rst.toml").write_text('fragments = ["typo/*.rst"]\n', encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _main(monkeypatch, capsys, "check", str(doc))

    assert code == 1
    assert "check_rst: .check_rst.toml: fragments pattern 'typo/*.rst' matches no file" in out


@pytest.mark.integration
def test_no_config_drops_configured_patterns_and_keeps_command_line_ones(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = _write(rst_repo / "doc.rst", "#####\nDoc\n#####\n")
    _write(rst_repo / "parts" / "one.rst")
    (rst_repo / ".check_rst.toml").write_text('fragments = ["typo/*.rst"]\n', encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _main(
        monkeypatch, capsys, "--no-config", "--fragment", "parts/*.rst", "check", "--format=json", str(doc)
    )

    assert code == 0, out
    config = json.loads(out)["config"]
    assert config["source"] is None
    assert config["roles"] == {
        "standalone": [],
        "fragments": [{"pattern": "parts/*.rst", "source": "--fragment", "matches": ["parts/one.rst"]}],
    }


@pytest.mark.integration
def test_command_line_patterns_add_to_configured_ones_and_json_records_both(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = _write(rst_repo / "doc.rst", "#####\nDoc\n#####\n")
    _write(rst_repo / "parts" / "one.rst")
    _write(rst_repo / "cv.rst")
    (rst_repo / ".check_rst.toml").write_text('fragments = ["parts/*.rst"]\n', encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    code, out = _main(monkeypatch, capsys, "--standalone", "cv.rst", "check", "--format=json", str(doc))

    assert code == 0, out
    roles_record = json.loads(out)["config"]["roles"]
    assert roles_record == {
        "standalone": [{"pattern": "cv.rst", "source": "--standalone", "matches": ["cv.rst"]}],
        "fragments": [{"pattern": "parts/*.rst", "source": ".check_rst.toml", "matches": ["parts/one.rst"]}],
    }


@pytest.mark.integration
@pytest.mark.parametrize("command", [["list-table"], ["hierarchy"]])
def test_commands_without_a_title_model_accept_and_ignore_role_patterns(
    rst_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: list[str]
) -> None:
    doc = _write(rst_repo / "doc.rst", "#####\nDoc\n#####\n")
    monkeypatch.chdir(rst_repo)

    _code, out = _main(monkeypatch, capsys, "--no-config", "--fragment", "typo/*.rst", *command, str(doc))

    assert "matches no file" not in out
    assert "unrecognized arguments" not in out


@pytest.mark.integration
@pytest.mark.parametrize(
    ("command", "echo"),
    [
        (["check"], "fragments=parts/*.rst"),
        (["list-table"], "fragments=parts/*.rst inactive (list-table)"),
    ],
    ids=["applied", "inactive"],
)
def test_the_config_line_echoes_configured_role_patterns(
    rst_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: list[str],
    echo: str,
) -> None:
    """Applied configuration values are echoed (guide, "Applied values are
    echoed"): a configured role is either applied by a title-model command or
    shown as inactive for a command that ignores it."""
    doc = _write(rst_repo / "doc.rst", "#####\nDoc\n#####\n")
    _write(rst_repo / "parts" / "one.rst")
    (rst_repo / ".check_rst.toml").write_text('fragments = ["parts/*.rst"]\n', encoding="utf-8")
    monkeypatch.chdir(rst_repo)

    _code, out = _main(monkeypatch, capsys, *command, str(doc))

    config_line = next(line for line in out.splitlines() if line.startswith("config: .check_rst.toml"))
    assert echo in config_line
