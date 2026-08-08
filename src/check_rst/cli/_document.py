# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# The Document read-only facade and its domain mixins — check_rst project

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, cast

import docutils.nodes

from . import _helpers
from ._helpers import (
    _changed_line_ranges,
    _findall_node_types,
    _normalize_source,
    _read_source,
)
from ._types import (
    _INLINE_CONTAINER_TYPES,
    _NON_PROSE_NODE_TYPES,
    AdmonitionEntry,
    BlockQuoteEntry,
    CodeBlockEntry,
    CommentEntry,
    Finding,
    ListEntry,
    OutlineEntry,
    TableEntry,
)

if TYPE_CHECKING:
    import pathlib


class _DocumentCore:
    """The read/parse foundation every Document domain builds on: the
    Phase 0-normalized text, its lines, the git diff ranges, and the
    docutils doctree. Split out of Document (found by code review:
    Document was one ~15-property god object — splitting an
    outline-domain module from a prose/wordstats module still forced
    both to import the whole class, since neither sub-domain had its
    own smaller facade) so each domain mixin below depends on only
    this small core, not on its sibling domains' properties.

    Lazy (cached_property), so a consumer pays only for what it
    touches; CALL_COUNTS assertions pin the one-read/one-parse
    contract in the tests. Deliberately read-only: fixers keep working
    on their own mutating line buffer and write to disk; after a fixer
    writes, construct a NEW Document. Invalidation is explicit in the
    object lifetime — which is exactly what makes the caching safe (a
    path-keyed cache would serve stale text after --fix writes).
    """

    def __init__(
        self,
        path: pathlib.Path,
        project_root: pathlib.Path | None = None,
    ) -> None:
        self.path = path
        self.project_root = _helpers.PROJECT_ROOT if project_root is None else project_root

    @functools.cached_property
    def source(self) -> str:
        return _read_source(self.path)

    @functools.cached_property
    def _normalized(self) -> tuple[str, list[Finding]]:
        return _normalize_source(self.source)

    @property
    def text(self) -> str:
        return self._normalized[0]

    @property
    def hygiene(self) -> list[Finding]:
        return self._normalized[1]

    @functools.cached_property
    def lines(self) -> list[str]:
        return self.text.splitlines()

    @functools.cached_property
    def ranges(self) -> list[tuple[int, int]] | None:
        return _changed_line_ranges(self.path, self.project_root)

    @functools.cached_property
    def doctree(self) -> docutils.nodes.document:
        return _helpers._parse_rst(self.path, text=self.text)


class _DocumentInlineMixin(_DocumentCore):
    """Inline-markup domain: consumed by check_nested_inline_markup's own
    warning and check_directives' misdiagnosis guard — nothing else in
    Document needs this, so it depends on _DocumentCore alone."""

    @functools.cached_property
    def nested_inline_by_node(self) -> dict[int, tuple[docutils.nodes.Node, ...]]:
        """Successful explicit inline constructs found inside each outer span.

        Both the dedicated warning and check_directives' misdiagnosis guard
        consume this map in one CLI run.  Cache the expensive grammar probes on
        the same read-only Document lifetime so each outer node is re-parsed
        exactly once, not once per consumer.
        """
        from ._checks import _nested_inline_nodes

        result: dict[int, tuple[docutils.nodes.Node, ...]] = {}
        for outer in _findall_node_types(self.doctree, _INLINE_CONTAINER_TYPES):
            nested = _nested_inline_nodes(outer, self.doctree)
            if nested:
                result[id(outer)] = nested
        return result


class _DocumentProseMixin(_DocumentCore):
    """Prose domain: word-stats and check_homoglyphs' shared skip-list
    consumer — depends on _DocumentCore's doctree alone, not on the
    outline domain's entry-finder properties below."""

    @functools.cached_property
    def prose_text(self) -> str:
        """The document's prose: text the author wrote as text.

        Doctree Text nodes, skipping literal blocks (code is not prose),
        comments, raw passthrough, and generated topics (a
        ``.. contents::`` directive's title is apparatus, not content —
        it was rank 2 in the first raw-frequency probe).  Bare docutils:
        no Sphinx build or configuration involved.

        The parser's own voice is not the author's prose either: under
        bare docutils every :doc: role and Sphinx-only directive produces
        a system_message whose text ("unknown directive type", "no role
        entry") leaked into the word statistics — on the reference note
        (2025-06-25) the "top prose words" were doc/directive/role/
        unknown: docutils' error vocabulary, not Max's.  Found by the
        semantic-vs-deterministic comparison the test method prescribes:
        the AI reads the repetitions, the tool counts, disagreement is a
        bug on one side or the other.  _NON_PROSE_NODE_TYPES (shared with
        check_homoglyphs) is exactly this skip-list.
        """
        parts: list[str] = []
        for text_node in self.doctree.findall(docutils.nodes.Text):
            node: docutils.nodes.Node | None = text_node.parent
            skipped = False
            while node is not None:
                if isinstance(node, _NON_PROSE_NODE_TYPES):
                    skipped = True
                    break
                node = node.parent
            if not skipped:
                parts.append(str(text_node))
        return "\n".join(parts)


class _DocumentOutlineMixin(_DocumentCore):
    """Outline domain: every entry-finder consumed by --outline/--json and
    check_bare_filenames/toctree reporting — the largest single cluster,
    but still only dependent on _DocumentCore, not on the inline-markup
    or prose domains above.

    Each finder below takes ``doc: Document | None`` (the pre-split type,
    still correct: most of their other callers pass a real Document and
    some, like check_bare_filenames, use cross-domain attributes on it)
    — so passing `self` needs one cast per property here. Nobody ever
    instantiates this mixin on its own; it exists only as part of the
    composed Document below, so the cast states a fact, not a hope."""

    @functools.cached_property
    def outline(self) -> list[OutlineEntry]:
        from ._checks import build_outline

        return build_outline(self.path, doc=cast("Document", self))

    @functools.cached_property
    def block_quotes(self) -> list[BlockQuoteEntry]:
        from ._checks import find_block_quotes

        return find_block_quotes(self.path, doc=cast("Document", self))

    @functools.cached_property
    def admonitions(self) -> list[AdmonitionEntry]:
        from ._checks import find_admonitions

        return find_admonitions(self.path, doc=cast("Document", self))

    @functools.cached_property
    def comments(self) -> list[CommentEntry]:
        from ._checks import find_comments

        return find_comments(self.path, doc=cast("Document", self))

    @functools.cached_property
    def lists(self) -> list[ListEntry]:
        from ._checks import find_lists

        return find_lists(self.path, doc=cast("Document", self))

    @functools.cached_property
    def code_blocks_heuristic(self) -> list[CodeBlockEntry]:
        from ._checks import find_code_blocks_heuristic

        return find_code_blocks_heuristic(self.path, doc=cast("Document", self))

    @functools.cached_property
    def tables(self) -> list[TableEntry]:
        from ._checks import find_tables

        return find_tables(self.path, doc=cast("Document", self))


class Document(_DocumentInlineMixin, _DocumentProseMixin, _DocumentOutlineMixin):
    """Read-only facade over one .rst file — stage 1 of the document
    model, composed from _DocumentCore plus its three domain mixins
    above. Every existing `document.outline`/`.tables`/`.text`/... call
    site keeps working unchanged: composition via inheritance preserves
    the exact same attribute surface (confirmed by direct probe: a
    diamond-shared _DocumentCore base plus functools.cached_property
    behaves identically whether attributes live on one class or are
    assembled from mixins, under both CPython and strict mypy).  What
    changes is where each domain's code CAN live once cli.py is
    eventually split into modules: each mixin above already depends on
    _DocumentCore alone, never on a sibling mixin, so a future outline
    module only needs to import _DocumentCore, not the prose or
    inline-markup domains bundled with it today.
    """


def _resolve_document(path: pathlib.Path, doc: Document | None) -> Document:
    """Return *doc* if the caller already has one, else construct a fresh
    Document for *path* — the one-liner every checker/reporter used to
    duplicate inline (14 call sites, found by code review): a caller
    chaining off another Document (e.g. via Document.tables/.outline)
    passes it through and never re-reads or re-parses the file; a caller
    with none still gets one lazily, on first touch."""
    return doc if doc is not None else Document(path)
