# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Tests for release wheel-content verification — check_rst project

from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING

import pytest

from tools import verify_wheel_contents

if TYPE_CHECKING:
    import pathlib


@pytest.mark.unit
def test_verify_wheel_contents_rejects_stale_and_missing_modules(tmp_path: pathlib.Path) -> None:
    source = tmp_path / "check_rst"
    source.mkdir()
    (source / "__init__.py").write_text("", encoding="utf-8")
    wheel = tmp_path / "package.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("check_rst/stale.py", "")

    assert verify_wheel_contents.verify(wheel, source) == [
        "unexpected wheel module: check_rst/stale.py",
        "missing wheel module: check_rst/__init__.py",
    ]


@pytest.mark.unit
def test_verify_wheel_contents_accepts_exact_package_sources(tmp_path: pathlib.Path) -> None:
    source = tmp_path / "check_rst"
    source.mkdir()
    (source / "__init__.py").write_text("", encoding="utf-8")
    wheel = tmp_path / "package.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("check_rst/__init__.py", "")

    assert verify_wheel_contents.verify(wheel, source) == []
