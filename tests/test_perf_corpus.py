# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Tests for the deterministic generated performance corpus — check_rst project
"""Verify the owned corpus shape used by performance measurements."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


@pytest.mark.integration
def test_generated_performance_corpus_is_byte_deterministic_and_has_reader_shape(tmp_path: Path) -> None:
    from tools.perf_corpus import CorpusSize, generate_project

    size = CorpusSize(unrelated_documents=4, large_page_sections=3, fragment_includers=3)
    first = generate_project(tmp_path / "first", size)
    second = generate_project(tmp_path / "second", size)

    assert _snapshot(first.root) == _snapshot(second.root)
    assert first.small_target == first.root / "small.rst"
    assert first.large_target == first.root / "large.rst"
    assert first.small_title == "Small target"
    assert first.large_title == "Large target"
    assert len(list(first.root.glob("*.rst"))) == 11
    assert (first.root / "large.rst").read_text(encoding="utf-8").count("Large section ") == 3
    for number in range(1, 4):
        assert ".. include:: fragment.rst" in (first.root / f"includer-{number:02d}.rst").read_text(encoding="utf-8")


@pytest.mark.integration
def test_generated_project_size_changes_only_unrelated_documents(tmp_path: Path) -> None:
    from tools.perf_corpus import CorpusSize, generate_project

    small = generate_project(
        tmp_path / "small-project",
        CorpusSize(unrelated_documents=1, large_page_sections=2, fragment_includers=3),
    )
    large = generate_project(
        tmp_path / "large-project",
        CorpusSize(unrelated_documents=6, large_page_sections=2, fragment_includers=3),
    )

    assert len(list(large.root.glob("unrelated-*.rst"))) - len(list(small.root.glob("unrelated-*.rst"))) == 5
    assert small.small_target.read_bytes() == (large.root / "small.rst").read_bytes()
    assert small.large_target.read_bytes() == (large.root / "large.rst").read_bytes()
    assert (small.root / "fragment.rst").read_bytes() == (large.root / "fragment.rst").read_bytes()
