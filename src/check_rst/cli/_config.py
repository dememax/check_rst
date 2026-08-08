# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Per-repo .check_rst.toml/pyproject.toml configuration loading — check_rst project

from __future__ import annotations

import dataclasses
import tomllib
from typing import TYPE_CHECKING, NoReturn

from . import _helpers
from ._helpers import CALL_COUNTS

if TYPE_CHECKING:
    import pathlib

_CONFIG_KEYS = frozenset({"sphinx-src", "build-dir"})


@dataclasses.dataclass(frozen=True, slots=True)
class LoadedConfig:
    """A validated config together with the directory its paths use."""

    source: str
    root: pathlib.Path
    values: dict[str, str]


def _config_error(source: str, message: str, *, explicit: bool = True) -> NoReturn:
    label = f"--config {source}" if explicit else source
    print(f"check_rst: {label}: {message}")
    raise SystemExit(1)


def _config_table(
    path: pathlib.Path,
    source: str,
    *,
    explicit: bool,
) -> dict[str, str] | None:
    """Read and validate one supported TOML config file."""
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        _config_error(source, f"invalid TOML: {exc}", explicit=explicit)
    except OSError as exc:
        _config_error(source, str(exc), explicit=explicit)

    if path.name == "pyproject.toml":
        tool = data.get("tool", {})
        table = tool.get("check_rst", {}) if isinstance(tool, dict) else {}
    else:
        table = data
    if not table:
        if explicit:
            _config_error(source, "does not declare check_rst settings", explicit=True)
        return None
    if not isinstance(table, dict):
        _config_error(
            source,
            "check_rst settings must be a TOML table",
            explicit=explicit,
        )

    unknown = set(table) - _CONFIG_KEYS
    if unknown:
        print(
            f"check_rst: unknown key(s) in {source}: "
            f"{', '.join(sorted(unknown))} — known keys: "
            f"{', '.join(sorted(_CONFIG_KEYS))}"
        )
        raise SystemExit(1)
    for key, value in table.items():
        if not isinstance(value, str):
            print(f"check_rst: {source}: {key} must be a string, got {type(value).__name__}")
            raise SystemExit(1)
    return table


def _load_config(explicit_path: pathlib.Path | None = None) -> LoadedConfig:
    """Load an explicit config or discover one in the working directory.

    Looks for `.check_rst.toml` (whole file is the table) first, then
    `pyproject.toml` `[tool.check_rst]` — the dedicated file wins when
    both exist.  An explicit path disables that cwd discovery.  Relative
    settings are resolved later against the returned root.
    """
    CALL_COUNTS["_load_config"] += 1
    if explicit_path is not None:
        path = explicit_path.expanduser()
        if not path.is_absolute():
            path = _helpers.PROJECT_ROOT / path
        path = path.resolve()
        source = str(path)
        if not path.exists():
            _config_error(source, "file not found")
        if not path.is_file():
            _config_error(source, "not a regular file")
        table = _config_table(path, source, explicit=True)
        assert table is not None
        return LoadedConfig(source, path.parent, table)

    for name in (".check_rst.toml", "pyproject.toml"):
        path = _helpers.PROJECT_ROOT / name
        if not path.is_file():
            continue
        table = _config_table(path, name, explicit=False)
        if table is None:
            continue
        return LoadedConfig(name, _helpers.PROJECT_ROOT.resolve(), table)
    return LoadedConfig("", _helpers.PROJECT_ROOT.resolve(), {})
