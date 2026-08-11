# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Tests for check_rst.cli's _helpers domain — check_rst project

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import docutils.nodes
import docutils.utils
import pytest
from _support import _rst

from check_rst import cli
from check_rst.cli import _helpers, _lint

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_atomic_write_failure_preserves_destination_and_removes_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed final replace cannot expose a partial candidate or temp file."""
    destination = tmp_path / "document.rst"
    original = b"original source\n"
    destination.write_bytes(original)

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        _helpers._atomic_write_bytes(destination, b"replacement source\n")

    assert destination.read_bytes() == original
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.unit
def test_atomic_write_preserves_mode_owner_and_updates_a_symlink_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target.rst"
    target.write_bytes(b"original\n")
    target.chmod(0o640)
    link = tmp_path / "link.rst"
    link.symlink_to(target)
    original = target.stat()
    ownership: list[tuple[int, int]] = []
    real_fchown = os.fchown

    def record_fchown(fd: int, uid: int, gid: int) -> None:
        ownership.append((uid, gid))
        real_fchown(fd, uid, gid)

    monkeypatch.setattr(os, "fchown", record_fchown)

    _helpers._atomic_write_bytes(link, b"replacement\n")

    assert link.is_symlink()
    assert target.read_bytes() == b"replacement\n"
    assert target.stat().st_mode & 0o777 == 0o640
    assert ownership == [(original.st_uid, original.st_gid)]
    assert (target.stat().st_uid, target.stat().st_gid) == (original.st_uid, original.st_gid)


@pytest.mark.unit
def test_atomic_write_refuses_multiply_linked_destination(tmp_path: Path) -> None:
    destination = tmp_path / "document.rst"
    peer = tmp_path / "peer.rst"
    original = b"shared original\n"
    destination.write_bytes(original)
    os.link(destination, peer)

    with pytest.raises(OSError, match="2 hard links"):
        _helpers._atomic_write_bytes(destination, b"replacement\n")

    assert destination.read_bytes() == original
    assert peer.read_bytes() == original
    assert destination.samefile(peer)
    assert {path.name for path in tmp_path.iterdir()} == {"document.rst", "peer.rst"}


@pytest.mark.unit
def test_indented_extent_is_relative_to_anchor_but_can_continue_block_quote_indent() -> None:
    directive = [
        "  .. code-block:: text",
        "",
        "     payload",
        "",
        "  sibling prose",
        "* next item",
    ]
    quote = [
        "    first quote line",
        "    second quote line",
        "",
        "  sibling prose",
    ]

    assert _helpers._indented_extent(directive, 1) == 3
    assert _helpers._indented_extent(quote, 1, allow_same_indent=True) == 2


@pytest.mark.unit
def test_indented_extent_ignores_tabs_inside_line_content() -> None:
    """Only the leading whitespace prefix contributes to indentation."""
    tab_in_anchor_content = [
        "   a\tb",
        " sibling at a shallower source column",
    ]
    tab_in_body_content = [
        "   marker",
        "    a\tb",
        "sibling",
    ]

    assert _helpers._indented_extent(tab_in_anchor_content, 1) == 1
    assert _helpers._indented_extent(tab_in_body_content, 1) == 2


@pytest.mark.unit
@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("#####", True),
        ("***", True),
        ("===", True),
        ("---", True),
        ("^^^", True),
        ('"""', True),
        ("#", True),  # single char is valid
        ("", False),
        ("abc", False),
        ("# #", False),  # mixed content
        ("~~~~", True),  # valid RST (docutils nonalphanum7bit), outside the project's
        ("++++", True),  # own preferred hierarchy #*=-^" — still a real adornment
        ("````", True),  # (see check_hierarchy's WARNING for this distinction)
        ("——", False),  # em-dash: non-alphanumeric but non-ASCII, outside docutils'
        (" ###", False),  # leading space
        ("..", False),  # exactly the docutils comment marker — explicit markup takes
        ("...", True),  # precedence over a title line, so '..' is never an adornment;
        (
            "....",
            True,
        ),  # three or more dots don't match the comment pattern and stay valid
    ],
)
def test_is_adornment(line: str, expected: bool) -> None:
    assert _helpers._is_adornment(line) == expected


@pytest.mark.unit
def test_has_non_prose_ancestor_true_for_each_base_skip_type() -> None:
    """Direct test of the shared ancestor walk extracted (code review) out
    of three copy-pasted call sites — Document.prose_text,
    check_homoglyphs, check_bare_filenames. A Text node nested inside any
    of the base non-prose container types is flagged regardless of how
    many plain layers (a bare paragraph here) sit in between."""
    containers: tuple[docutils.nodes.Element, ...] = (
        docutils.nodes.literal_block(),
        docutils.nodes.comment(),
        docutils.nodes.raw("", ""),
        docutils.nodes.topic(),
        docutils.nodes.system_message(),
    )
    for container in containers:
        paragraph = docutils.nodes.paragraph()
        text = docutils.nodes.Text("hello")
        paragraph.append(text)
        container.append(paragraph)
        assert _helpers._has_non_prose_ancestor(text), container


@pytest.mark.unit
def test_has_non_prose_ancestor_false_for_ordinary_prose() -> None:
    """A Text node nested only inside ordinary containers (no non-prose
    ancestor anywhere up to the root) is real prose — not skipped."""
    document = docutils.utils.new_document("test")
    paragraph = docutils.nodes.paragraph()
    emphasis = docutils.nodes.emphasis()
    text = docutils.nodes.Text("hello")
    emphasis.append(text)
    paragraph.append(emphasis)
    document.append(paragraph)
    assert not _helpers._has_non_prose_ancestor(text)


@pytest.mark.unit
def test_has_non_prose_ancestor_extra_types_only_apply_when_passed() -> None:
    """extra_types is opt-in per call, not a global change to the base
    skip-set: check_bare_filenames alone widens it with reference/
    pending_xref, so the same Text node must be prose for one caller and
    non-prose for the other, from the identical doctree shape."""
    reference = docutils.nodes.reference()
    text = docutils.nodes.Text("guide.rst")
    reference.append(text)

    assert not _helpers._has_non_prose_ancestor(text)
    assert _helpers._has_non_prose_ancestor(text, extra_types=(docutils.nodes.reference,))


@pytest.mark.integration
@pytest.mark.parametrize("lang", ["C", "en_US.UTF-8", "fr_FR.UTF-8"])
def test_cli_bare_invocation_outside_git_repo_clean_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    lang: str,
) -> None:
    """Bare check_rst (git auto-detection) outside any git repository must
    fail with a one-line diagnostic, not a CalledProcessError traceback —
    the same loud-and-clean precedent as a missing conf.py in --sphinx-src
    or a nonexistent --recursive directory.  Found by direct probing
    (2026-07-18): the 'project-agnostic, call from any project' tool
    crashed with a raw traceback when that project wasn't a git repo.

    Parametrized across locales (Max, 2026-08-11): this diagnostic used to
    detect "not a git repository" by substring-matching a git subprocess's
    own human-readable stderr, which is translated under LANG/LC_ALL —
    confirmed broken live under fr_FR.UTF-8, where git's French message
    silently failed to match and check_rst leaked git's raw text instead of
    its own clean diagnostic. pygit2.discover_repository (no subprocess, no
    translated text) fixed this structurally, but nothing short of actually
    running under a non-English locale proves it stays fixed."""
    monkeypatch.setenv("LANG", lang)
    monkeypatch.setenv("LC_ALL", lang)
    monkeypatch.setattr(_helpers, "PROJECT_ROOT", tmp_path)  # no .git here
    monkeypatch.setattr("sys.argv", ["check_rst.py", "check"])

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "not a git repository" in out


@pytest.mark.integration
def test_directives_mistyped_directive_single_colon_flagged(tmp_path: Path) -> None:
    """'.. code: bash' (single colon) is a legal RST comment — the content
    silently disappears from the build and no other phase flags it (found
    via a real typo in a calendar note, 2026-07-18).  Warn."""
    p = _rst(tmp_path, "Text.\n\n.. code: bash\n\n    pandoc --from gfm\n")
    violations = _lint.check_directives(p, True)
    assert len(violations) == 1
    assert "mistyped directive" in violations[0]
    assert "code" in violations[0]
    assert violations[0].severity == "WARNING"


@pytest.mark.integration
def test_directives_mistyped_directive_docutils_name_flagged(tmp_path: Path) -> None:
    """Any docutils directive name qualifies, not just 'code'."""
    p = _rst(tmp_path, ".. note: remember to flush the cache\n")
    violations = _lint.check_directives(p, True)
    assert any("mistyped directive" in v for v in violations)


@pytest.mark.integration
def test_directives_mistyped_directive_sphinx_name_flagged(tmp_path: Path) -> None:
    """Common Sphinx directive names are covered too (toctree, etc.)."""
    p = _rst(tmp_path, ".. toctree: pages/index\n")
    violations = _lint.check_directives(p, True)
    assert any("mistyped directive" in v for v in violations)


@pytest.mark.integration
def test_directives_mistyped_directive_case_insensitive(tmp_path: Path) -> None:
    """Directive names are case-insensitive in docutils; so is the lint."""
    p = _rst(tmp_path, ".. Note: remember\n")
    violations = _lint.check_directives(p, True)
    assert any("mistyped directive" in v for v in violations)


@pytest.mark.integration
def test_directives_todo_comment_not_flagged(tmp_path: Path) -> None:
    """'.. TODO: …' is an extremely common genuine-comment idiom and 'todo'
    is not a docutils directive (nor in the Sphinx supplement, deliberately)
    — never flagged."""
    p = _rst(tmp_path, ".. TODO: fix this paragraph later\n")
    assert _lint.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_plain_comment_not_flagged(tmp_path: Path) -> None:
    """An ordinary comment stays invisible to the lint."""
    p = _rst(tmp_path, ".. this file is maintained by hand\n")
    assert _lint.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_unknown_name_comment_not_flagged(tmp_path: Path) -> None:
    """A name-colon shape with an unknown name is a legit comment tag."""
    p = _rst(tmp_path, ".. myproject-tag: value\n")
    assert _lint.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_real_directive_not_flagged(tmp_path: Path) -> None:
    """A correctly written directive produces no comment node at all."""
    p = _rst(tmp_path, ".. code:: bash\n\n    echo ok\n")
    assert _lint.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_mistyped_directive_in_literal_block_not_flagged(
    tmp_path: Path,
) -> None:
    """The typo QUOTED AS AN EXAMPLE inside a real code-block is literal
    text, never parsed as a comment — no warning."""
    p = _rst(tmp_path, ".. code:: rst\n\n    .. code: bash\n\n        oops\n")
    assert _lint.check_directives(p, True) == []


@pytest.mark.integration
def test_directives_mistyped_directive_in_block_quote_not_flagged(
    tmp_path: Path,
) -> None:
    """Inside a blockquote it is quoted material — exempt, same as bold and
    rubric (the whole quoted subtree is skipped)."""
    p = _rst(tmp_path, "He sent:\n\n    .. code: bash\n\n        quoted\n")
    assert _lint.check_directives(p, True) == []
