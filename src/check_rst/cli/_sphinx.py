# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Phase 2/3 Sphinx integration (verified build, references, toctrees) — check_rst project

from __future__ import annotations

import collections
import dataclasses
import difflib
import pathlib
import re
import subprocess
import sys
from typing import TYPE_CHECKING

import docutils.nodes

if TYPE_CHECKING:
    from collections.abc import Iterable

    import sphinx.environment


from . import _helpers
from ._document import (
    Document,
    _outline_preview,
    _resolve_document,
    build_outline,
)
from ._helpers import (
    CALL_COUNTS,
    _block_depth,
    _indented_extent,
    _node_line,
)
from ._types import (
    _NON_PROSE_NODE_TYPES,
    AdmonitionEntry,
    BlockQuoteEntry,
    CodeBlockEntry,
    CommentEntry,
    Finding,
    ListEntry,
    OutlineEntry,
    ReferenceEntry,
    Severity,
    TableEntry,
    ToctreeEntry,
)

# Sphinx warning line formats:
#   /abs/path/file.rst:line: WARNING: message [tag]
#   /abs/path/file.rst: WARNING: message [tag]
# Some project/configuration diagnostics have no source line.  Preserve those
# with line 0 instead of silently dropping them.
_WARNING_RE = re.compile(
    r"^(?P<path>.+\.rst)(?::(?P<line>\d+))?: "
    r"(?P<level>WARNING|ERROR): (?P<msg>.+)$"
)


# Strips ANSI SGR escape codes (colored terminal output) before _WARNING_RE
# matching.  Confirmed necessary (2026-07-20): Sphinx's IN-PROCESS build
# colorizes its console stream even when the target is an io.StringIO()
# with no real isatty() — the leading "\x1b[31m" breaks _WARNING_RE's '^'
# anchor, silently dropping every match.  Defensive on the subprocess path
# too (run_sphinx): if sphinx-build's own color detection ever disagrees
# with ours, the same anchor break would apply there.
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


# Docutils/Sphinx restatements of Phase 0/1 defects that --fix resolves.
# Under --skip-fixable these are duplicates, not human-review warnings.
_FIXABLE_SPHINX_MESSAGES = (
    "Title overline too short",
    "Title underline too short",
    "Title overline & underline mismatch",
    "Inconsistent title style",
)


def _build_sphinx_env(
    sphinx_src: pathlib.Path,
    build_dir: pathlib.Path,
    files: list[pathlib.Path] | None = None,
) -> tuple[sphinx.environment.BuildEnvironment, str]:
    """Build a real, in-process Sphinx environment rooted at *sphinx_src*.

    Returns (env, warning_text): warning_text is this build's own captured
    console warning stream, in the same 'path:line: LEVEL: msg' shape
    run_sphinx's subprocess produces (parse with
    _findings_from_sphinx_output).  The caller MUST surface it — this
    build's own structural docutils warnings (e.g. an inconsistent title
    style) are otherwise lost for good: they get resolved into the doctree
    this function writes to the shared --build-dir, so Phase 3's separate
    sphinx-build subprocess finds that doctree already fresh and never
    re-parses the file to reproduce them (confirmed by direct
    reproduction, 2026-07-20 — see _findings_from_sphinx_output).

    Uses the "dummy" builder: resolves the full environment and every
    document's doctree (directives, options, cross-references) exactly as a
    real build would, but writes no HTML output. This is what lets Phase 2
    parse Sphinx-only directive options (code-block's :caption:/:linenos:,
    etc.) that Phase 1's bare docutils parser doesn't know about, without
    the AttributeError a hand-registered directive would raise — Sphinx's
    own CodeBlock reaches for self.env, which exists here precisely because
    this is a genuine Sphinx application, not a bare docutils parse (confirmed
    by direct testing: registering Sphinx's real CodeBlock directive onto a
    bare docutils parser crashes on a caption with no explicit language,
    content that already exists in this project's own calendar/ files).

    doctreedir is shared with Phase 3's --build-dir so a doctree computed by
    one phase is reused by the other rather than recomputed twice.

    Building a Sphinx app registers its own directives/roles (its "toctree",
    "code-block", etc.) into docutils' process-global registry, and that
    registration outlives the app — confirmed by direct testing: a bare
    docutils parse running later in the same process inherited Sphinx's
    "toctree" directive and crashed the exact self.env way this function
    exists to avoid, breaking Phase 1 for the rest of the process. Sphinx's
    own docutils_namespace() snapshots and restores that registry, so the
    construction and build are scoped inside it; get_doctree() afterwards is
    a pure unpickle of an already-built tree and needs no registry state.

    When *files* is given, those checked documents are deliberately re-read
    even if Sphinx's incremental environment considers them unchanged.  This
    reproduces persistent read-time diagnostics without discarding the shared
    environment or re-reading unrelated documents: ``env-get-outdated`` is
    Sphinx's supported hook for adding selected docnames to the incremental
    read set.
    """
    CALL_COUNTS["_build_sphinx_env"] += 1
    import io

    from sphinx.application import Sphinx
    from sphinx.util.docutils import docutils_namespace

    warning_stream = io.StringIO()
    with docutils_namespace():
        app = Sphinx(
            srcdir=str(sphinx_src),
            confdir=str(sphinx_src),
            outdir=str(build_dir / "_dummy"),
            doctreedir=str(build_dir / ".doctrees"),
            buildername="dummy",
            status=io.StringIO(),
            warning=warning_stream,
        )
        if files:
            checked_paths = tuple(path.resolve() for path in files)

            def force_checked_docs(
                _app: Sphinx,
                env: sphinx.environment.BuildEnvironment,
                _added: set[str],
                _changed: set[str],
                _removed: set[str],
            ) -> list[str]:
                docnames = []
                for path in checked_paths:
                    docname = env.path2doc(str(path))
                    if docname is not None and docname in env.found_docs:
                        docnames.append(docname)
                return docnames

            app.connect("env-get-outdated", force_checked_docs)
        app.build()
    return app.env, warning_stream.getvalue()


def _build_sphinx_env_checked(
    sphinx_src: pathlib.Path,
    build_dir: pathlib.Path,
    files: list[pathlib.Path] | None = None,
) -> tuple[sphinx.environment.BuildEnvironment, str]:
    """CLI boundary for _build_sphinx_env: one diagnostic, never a traceback."""
    try:
        return _build_sphinx_env(sphinx_src, build_dir, files)
    except Exception as exc:
        detail = " ".join(str(exc).splitlines())
        print(f"check_rst: Sphinx environment build failed: {type(exc).__name__}: {detail}")
        raise SystemExit(1) from exc


def _docname_for(env: sphinx.environment.BuildEnvironment, path: pathlib.Path) -> str | None:
    """Return the Sphinx docname for *path*, or None if it isn't part of
    this Sphinx project's document tree (not reachable from --sphinx-src).

    env.path2doc() is a pure path transform — it happily returns a docname-
    shaped string for a path outside srcdir entirely (confirmed by direct
    testing), so reachability is checked separately against env.found_docs,
    the set of documents Sphinx actually read.
    """
    docname = env.path2doc(str(path.resolve()))
    if docname is None or docname not in env.found_docs:
        return None
    return docname


def _resolve_xref_target(
    env: sphinx.environment.BuildEnvironment, refdoc: str, reftype: str, target: str
) -> str | None:
    """Resolve a pending_xref's raw target to the real docname it points
    at, or None if unresolvable.

    The SAME lookup Sphinx itself performs — sphinx.util.docname_join for
    :doc: (confirmed by direct read of sphinx.domains.std's own
    _resolve_doc_xref), env.domaindata['std']['anonlabels'] for :ref:/
    :term: (confirmed by direct probe: docutils already lowercases a
    :ref: role's target at parse time, matching anonlabels' own keys) —
    so a reference this reports as resolved is exactly one Phase 3 would
    accept.  Any other reftype (a domain this tool has no resolver for)
    returns None rather than guessing.
    """
    if reftype == "doc":
        from sphinx.util import docname_join

        docname = docname_join(refdoc, target)
        return docname if docname in env.found_docs else None
    if reftype in ("ref", "term"):
        anonlabels = env.domaindata.get("std", {}).get("anonlabels", {})
        entry = anonlabels.get(target.lower())
        return entry[0] if entry else None
    return None


def find_references(env: sphinx.environment.BuildEnvironment, docname: str) -> list[ReferenceEntry]:
    """Every role and toctree reference *docname* itself writes, in document
    order — its OUTGOING document graph.

    Reads the raw, still-unresolved sphinx.addnodes.pending_xref nodes
    env.get_doctree() carries: resolution happens later, during a
    builder's write phase, and is never written back to the pickled
    doctree (confirmed by direct probe, 2026-07-22) — exactly the target
    text the author wrote, before Sphinx joins/looks it up.

    Toctree nodes are different: Sphinx resolves them during reading and
    stores the actual child docnames in ``includefiles``.  Consuming that
    list includes explicit entries and every glob expansion while excluding
    external URLs, exactly matching the live document graph.
    """
    from sphinx.addnodes import pending_xref, toctree

    doc = env.get_doctree(docname)
    entries: list[ReferenceEntry] = []
    for node in doc.findall():
        if isinstance(node, pending_xref):
            reftype = node.get("reftype", "")
            target = node.get("reftarget", "")
            resolved = _resolve_xref_target(env, docname, reftype, target)
            entries.append(ReferenceEntry(docname, _node_line(node), reftype, target, resolved))
        elif isinstance(node, toctree):
            entries.extend(
                ReferenceEntry(
                    docname,
                    _node_line(node),
                    "toctree",
                    target,
                    target,
                )
                for target in node.get("includefiles", ())
            )
    return entries


def find_incoming_references(env: sphinx.environment.BuildEnvironment, target_docname: str) -> list[ReferenceEntry]:
    """Every OTHER document's reference that resolves to *target_docname*
    — the inverse of find_references, built by scanning every document's
    doctree once (confirmed by direct probe, 2026-07-22: ~2.6s across
    this Journal's full 1444 documents — fine for an on-demand --refs
    call, not something to run on every default invocation)."""
    incoming: list[ReferenceEntry] = []
    for docname in sorted(env.found_docs):
        if docname == target_docname:
            continue
        for entry in find_references(env, docname):
            if entry.resolved == target_docname:
                incoming.append(entry)
    return incoming


def _toctree_anomalies(
    env: sphinx.environment.BuildEnvironment,
) -> dict[str, list[str]]:
    """The project-wide multiple-toctree-parent graph, derived once from
    ``env.toctree_includes`` — split out of check_multiple_toctree_parents
    (found by code review: that function rebuilt this same graph from
    scratch on every call, but its one real per-file caller, Phase 2's
    ``for path in files`` loop, invokes it once per file against the SAME,
    already-built env — O(files) redundant rebuilds of one project-wide
    graph). Callers that only ever check one file at a time (--context,
    always exactly one document per invocation, with its own freshly
    built env) can still let check_multiple_toctree_parents compute this
    lazily; a caller processing many files against one shared env should
    compute this once up front and pass it through instead."""
    CALL_COUNTS["_toctree_anomalies"] += 1
    parents_by_child: dict[str, list[str]] = {}
    for parent, children in getattr(env, "toctree_includes", {}).items():
        for child in children:
            parents_by_child.setdefault(child, []).append(parent)
    return {child: parents for child, parents in parents_by_child.items() if len(parents) > 1}


def check_multiple_toctree_parents(
    env: sphinx.environment.BuildEnvironment,
    files: list[pathlib.Path],
    anomalies: dict[str, list[str]] | None = None,
) -> list[Finding]:
    """Report selected documents implicated in repeated toctree inclusion.

    Sphinx records the authoritative resolved graph in
    ``env.toctree_includes`` but only logs its own concern at INFO level,
    anchored to the child document.  Deriving the finding from the graph
    keeps it independent of Sphinx's console wording and lets a selected
    parent surface a problem that Sphinx itself locates on an unselected
    child.  Repeating one child twice in the same parent and including it
    from two distinct parents are both represented by more than one parent
    occurrence and are intentionally treated alike.

    *anomalies*: pass the result of a single shared ``_toctree_anomalies(env)``
    call when checking many files against the same env, so the project-wide
    graph is derived once rather than once per file; omitted (None), it is
    computed here, on this one call — correct for a single-file caller.
    """
    if anomalies is None:
        anomalies = _toctree_anomalies(env)
    findings: list[Finding] = []
    for path in files:
        docname = _docname_for(env, path)
        if docname is None:
            continue
        for child, parents in sorted(anomalies.items()):
            if docname != child and docname not in parents:
                continue
            lineno = 0
            if docname in parents:
                lineno = next(
                    (
                        entry.lineno
                        for entry in find_references(env, docname)
                        if entry.reftype == "toctree" and entry.resolved == child
                    ),
                    0,
                )
            counts = collections.Counter(parents)
            parent_list = ", ".join(
                f"{parent!r}" + (f" ({count} times)" if count > 1 else "") for parent, count in sorted(counts.items())
            )
            findings.append(
                Finding(
                    lineno,
                    Severity.WARNING,
                    f"document {child!r} is referenced by multiple toctree entries: {parent_list}",
                )
            )
    return findings


def find_toctrees(
    env: sphinx.environment.BuildEnvironment,
    docname: str,
    doc: Document | None = None,
) -> list[list[ToctreeEntry | OutlineEntry]]:
    """Return one CLUSTER per top-level ``.. toctree::`` directive in
    *docname* — each cluster a self-contained ``[container, *pulled-in
    entries]`` list, recursively expanded across every document that
    directive points at, in turn (2026-07-26) — the first entry kind
    whose items can point outside the file being outlined.

    One cluster per ROOT-level directive, not one flat list, so a
    caller merging this into *docname*'s own local outline entries can
    splice each cluster in at its container's real position without
    re-sorting a cross-file entry by its (meaningless-here) foreign
    line number — see _merge_toctree_clusters.

    Verified mode only: toctree is invisible to bare docutils entirely
    (confirmed by direct probe — without a real Sphinx environment it
    is not even recognized as a directive, let alone resolved), so
    there is no heuristic-mode equivalent — the same constraint as
    --refs/check_bare_filenames.

    Depth continues seamlessly across the file boundary: a toctree
    container sits at _block_depth within its OWN document; each
    document it points at is entered at that container's own depth, so
    document's own LOCAL headings (already depth 1 for its own title,
    2 for its own subsections, from build_outline) land at
    container_depth + local_depth — confirmed by direct probe against
    a real 2-level nested project that this matches exactly how deep a
    heading reached by list nesting or section nesting alone would
    land, so --outline-depth needs no special case to bound it.

    Two things full, unbounded recursion needs, neither silent:

    * Lazy cycle detection — the current traversal PATH (the chain of
      docnames walked to reach this point) is tracked, not a
      precomputed whole-project graph.  The moment a toctree would
      recurse into a docname already on that path, that branch stops
      with a visible ToctreeEntry(cycle=...) marker naming it, and its
      siblings continue normally.
    * Diamond de-duplication — a docname already fully expanded via a
      DIFFERENT, non-cyclic path (a document reachable from more than
      one toctree is an entirely normal project shape, not an error)
      still gets its own heading entry the second time it is reached,
      but is not expanded again — avoiding duplicate, potentially large
      output for the same real subtree.
    """
    from sphinx.addnodes import toctree as toctree_node_cls

    document = _resolve_document(pathlib.Path(env.doc2path(docname)), doc)
    # env.get_doctree(), never document.doctree: a toctree node's
    # includefiles/maxdepth attributes are populated by Sphinx's own
    # toctree-directive processing during the environment read, which a
    # bare docutils parse of the same file never runs — confirmed by
    # direct probe (see find_toctrees' own docstring: toctree is
    # "invisible to bare docutils entirely").  This applies at EVERY
    # level of recursion, including the root docname itself, not only
    # the children — document.doctree is used only for .lines below.
    doctree = env.get_doctree(docname)
    seen = {docname}
    return [
        _expand_one_toctree(node, env, document, depth_offset=0, path=(docname,), seen=seen)
        for node in doctree.findall(toctree_node_cls)
    ]


def _expand_toctrees(
    env: sphinx.environment.BuildEnvironment,
    docname: str,
    document: Document,
    depth_offset: int,
    path: tuple[str, ...],
    seen: set[str],
) -> list[ToctreeEntry | OutlineEntry]:
    """Flatten every toctree directive found in *docname* (used only when
    recursing INTO a child document — its own toctree directives, if
    more than one, all nest inside the single cluster of the directive
    that brought us here, so no per-directive clustering is needed at
    this level; only find_toctrees' own root call needs clusters).

    env.get_doctree(docname), never document.doctree — see find_toctrees.
    """
    from sphinx.addnodes import toctree as toctree_node_cls

    doctree = env.get_doctree(docname)
    entries: list[ToctreeEntry | OutlineEntry] = []
    for node in doctree.findall(toctree_node_cls):
        entries.extend(_expand_one_toctree(node, env, document, depth_offset, path, seen))
    return entries


def _expand_one_toctree(
    node: docutils.nodes.Node,
    env: sphinx.environment.BuildEnvironment,
    document: Document,
    depth_offset: int,
    path: tuple[str, ...],
    seen: set[str],
) -> list[ToctreeEntry | OutlineEntry]:
    """Expand a single ``toctree`` doctree node: its own container entry,
    the headings of every document it includes, and — recursively —
    each of those documents' own toctrees, in turn."""
    lines = document.lines
    local_depth = _block_depth(node)
    toctree_depth = depth_offset + local_depth
    includefiles = list(node.get("includefiles", ()))
    maxdepth = node.get("maxdepth", -1)
    start = _node_line(node)
    end = _indented_extent(lines, start) if includefiles else start
    # path[0] is the document the caller asked to outline.  Provenance is
    # emitted only after crossing that file boundary: stamping the root too
    # would make local and foreign containers indistinguishable again.
    source_docname = path[-1] if len(path) > 1 else None
    entries: list[ToctreeEntry | OutlineEntry] = [
        ToctreeEntry(
            start,
            toctree_depth,
            len(includefiles),
            maxdepth,
            end,
            docname=source_docname,
        )
    ]

    for child_docname in includefiles:
        if child_docname in path:
            entries.append(
                ToctreeEntry(
                    start,
                    toctree_depth + 1,
                    cycle=child_docname,
                    docname=source_docname,
                )
            )
            continue

        child_path = pathlib.Path(env.doc2path(child_docname))
        child_doctree = env.get_doctree(child_docname)
        child_headings = build_outline(child_path, doctree=child_doctree)
        for h in child_headings:
            entries.append(
                dataclasses.replace(
                    h,
                    depth=toctree_depth + h.depth,
                    docname=child_docname,
                )
            )

        if child_docname in seen:
            # Diamond: already expanded via a different, non-cyclic path
            # — its headings are shown again (real content, reachable
            # from here too) but not recursed into again.
            continue
        seen.add(child_docname)
        child_document = Document(child_path)
        entries.extend(
            _expand_toctrees(
                env,
                child_docname,
                child_document,
                depth_offset=toctree_depth,
                path=(*path, child_docname),
                seen=seen,
            )
        )
    return entries


def _merge_toctree_clusters(
    local_entries: list[
        OutlineEntry | CodeBlockEntry | BlockQuoteEntry | TableEntry | AdmonitionEntry | CommentEntry | ListEntry
    ],
    clusters: list[list[ToctreeEntry | OutlineEntry]],
) -> list[
    OutlineEntry
    | CodeBlockEntry
    | BlockQuoteEntry
    | TableEntry
    | AdmonitionEntry
    | CommentEntry
    | ListEntry
    | ToctreeEntry
]:
    """Splice each toctree cluster from find_toctrees into *local_entries*
    (already sorted by lineno) at its own container's position, WITHOUT
    re-sorting the cluster's own contents by their raw line number — a
    cross-file heading's .lineno is a position in ANOTHER file, not
    comparable to this file's own line numbers, so the cluster (already
    in correct document/recursion order from find_toctrees) is spliced
    in as one contiguous, internally-unsorted block.
    """
    merged: list[
        OutlineEntry
        | CodeBlockEntry
        | BlockQuoteEntry
        | TableEntry
        | AdmonitionEntry
        | CommentEntry
        | ListEntry
        | ToctreeEntry
    ] = []
    idx = 0
    for cluster in clusters:
        if not cluster:
            continue
        anchor = cluster[0].lineno
        while idx < len(local_entries) and local_entries[idx].lineno < anchor:
            merged.append(local_entries[idx])
            idx += 1
        merged.extend(cluster)
    merged.extend(local_entries[idx:])
    return merged


# A bare filename mention: 'guide.rst', 'coding-standards.rst' — matched by
# basename only, since prose almost never spells out the full
# project-relative path a docname carries.
_BARE_FILENAME_RE = re.compile(r"\b([\w-]+)\.rst\b")


# Real evidence, this Journal's own corpus: 1072 files are named
# 'Notes.rst' — a bare mention of that basename is not a specific,
# actionable reference candidate, so a basename shared by more files than
# this must stay silent rather than dump an unusable wall of candidates.
_MAX_BARE_FILENAME_CANDIDATES = 5


def check_bare_filenames(
    env: sphinx.environment.BuildEnvironment,
    docname: str,
    doc: Document,
) -> list[Finding]:
    """Flag a bare '<name>.rst' filename mentioned as plain prose text
    where a real :doc:/:ref: cross-reference belongs (Max, 2026-07-23,
    evidence from a downstream project: several 'coding-standards.rst' prose mentions in
    that project's own docs are plain text, not links) — the mirror image
    of "did you mean": here a reference is MISSING where one should
    exist, not broken.

    Matched by basename against every known docname's own last path
    segment (env.found_docs).  Silent when the mentioned name matches no
    known doc at all (nothing confident to suggest), matches only THIS
    document's own docname (mentioning your own filename is not a
    missing cross-reference), or matches more than
    _MAX_BARE_FILENAME_CANDIDATES docs (too common a basename to be a
    specific suggestion — confirmed by real evidence, see above).
    Otherwise lists every remaining candidate, never guesses a single one.

    Scans the same author-facing prose Text nodes as check_homoglyphs
    (_NON_PROSE_NODE_TYPES) — deliberately including inline literal spans
    (unlike a literal_block): the real evidence is a filename wrapped in
    double backticks as the author's own emphasis, not captured code
    output.  WARNING, not ERROR: converting to a real cross-reference is a
    content decision (which role, which target syntax), never
    auto-fixable.
    """
    by_basename: dict[str, list[str]] = {}
    for d in env.found_docs:
        by_basename.setdefault(d.rsplit("/", 1)[-1], []).append(d)

    from sphinx.addnodes import pending_xref

    findings: list[Finding] = []
    # Production uses Sphinx's doctree so genuine pending_xref/reference
    # nodes remain distinguishable from prose.  The fallback keeps this
    # checker usable with the deliberately minimal environment doubles in
    # unit tests and by direct library callers.
    get_doctree = getattr(env, "get_doctree", None)
    sphinx_doctree = get_doctree(docname) if callable(get_doctree) else doc.doctree
    for text_node in sphinx_doctree.findall(docutils.nodes.Text):
        node: docutils.nodes.Node | None = text_node.parent
        skipped = False
        while node is not None:
            if isinstance(
                node,
                (*_NON_PROSE_NODE_TYPES, docutils.nodes.reference, pending_xref),
            ):
                skipped = True
                break
            node = node.parent
        if skipped:
            continue
        s = str(text_node)
        base_line = _node_line(text_node)
        for m in _BARE_FILENAME_RE.finditer(s):
            name = m.group(1)
            candidates = sorted(c for c in by_basename.get(name, ()) if c != docname)
            if not candidates or len(candidates) > _MAX_BARE_FILENAME_CANDIDATES:
                continue
            lineno = base_line + s[: m.start()].count("\n")
            targets = ", ".join(repr(c) for c in candidates)
            findings.append(
                Finding(
                    lineno,
                    Severity.WARNING,
                    f"{name}.rst mentioned as plain text — did you mean a "
                    f":doc:/:ref: cross-reference? possible target(s): {targets}",
                )
            )
    return findings


def find_code_blocks(
    env: sphinx.environment.BuildEnvironment,
    docname: str,
    lines: list[str] | None = None,
) -> list[CodeBlockEntry]:
    """Return every real code-block in document *docname*, in document order.

    Requires a genuine Sphinx environment (see _build_sphinx_env). Under
    Sphinx's own CodeBlock directive, every recognized code-block carries a
    "language" attribute — set to the explicit argument, or to the
    project's highlight_language when none is given — which is what this
    keys on. A plain "::" literal block or ".. parsed-literal::" never gets
    this attribute, and a ".. code-block::" merely quoted as example text
    inside another literal block never produces its own node at all
    (Sphinx never re-parses literal content), so both are correctly
    excluded without any text-based heuristic.

    lineno is the directive's own line, which Sphinx sets explicitly via
    set_source_info() during parsing — reliable and stable, unlike bare
    docutils' fuzzy (and sometimes None) .line for the same node kind.
    """
    doc = env.get_doctree(docname)
    entries: list[CodeBlockEntry] = []
    for node in doc.findall(docutils.nodes.literal_block):
        lang = node.get("language")
        if lang is None:
            continue
        depth = _block_depth(node)
        lineno = node.line if isinstance(node.line, int) else 0
        end = _indented_extent(lines, lineno) if lines and lineno else 0
        preview = _outline_preview(node.astext())
        entries.append(CodeBlockEntry(lineno, depth, lang, preview, end))
    return entries


def _findings_from_sphinx_output(
    raw_output: str,
    files: list[pathlib.Path],
    project_root: pathlib.Path | None = None,
) -> list[Finding]:
    """Parse sphinx-build-style 'path:line: LEVEL: msg' console lines into
    Findings, filtered to *files*.

    Shared by run_sphinx (Phase 3's separate sphinx-build subprocess) and
    _build_sphinx_env's caller (Phase 2's in-process build) — same console-
    output shape either way, and Phase 2's own warnings need the identical
    treatment: found by direct reproduction (2026-07-20) that Phase 2's
    build captured its warnings into an io.StringIO() nothing read, and
    since it shares --build-dir with Phase 3, the doctree it wrote was
    already fresh by the time Phase 3's separate sphinx-build ran — Sphinx's
    own incremental logic skipped re-parsing, so a real structural ERROR
    (confirmed: 'Inconsistent title style: skip from level 2 to 4') was
    lost between the two phases, never surfacing in either one.
    """
    root = _helpers.PROJECT_ROOT if project_root is None else project_root
    explicit = {f.resolve() for f in files}
    findings: list[Finding] = []
    for raw in _ANSI_ESCAPE_RE.sub("", raw_output).splitlines():
        m = _WARNING_RE.match(raw)
        if m:
            p = pathlib.Path(m.group("path")).resolve()
            if p in explicit:
                try:
                    rel = p.relative_to(root)
                except ValueError:
                    rel = p
                line = m.group("line")
                findings.append(
                    Finding(
                        lineno=int(line) if line is not None else 0,
                        severity=Severity(m.group("level")),
                        text=f"{rel}: {m.group('msg')}",
                    )
                )
    return findings


def _is_sphinx_fixable_duplicate(
    finding: Finding,
    suppressed_paths: set[pathlib.Path],
    project_root: pathlib.Path,
) -> bool:
    """Return whether Sphinx merely restated a suppressed fixable defect."""
    if not any(message in finding.text for message in _FIXABLE_SPHINX_MESSAGES):
        return False
    root = project_root.resolve()
    for path in suppressed_paths:
        resolved = path.resolve()
        try:
            displayed = resolved.relative_to(root)
        except ValueError:
            displayed = resolved
        if finding.text.startswith(f"{displayed}: "):
            return True
    return False


# Matches Sphinx's own two broken-:doc:-target message shapes — note
# "unknown document:" has a colon before the quote, "nonexisting document"
# does not (confirmed by direct probe, 2026-07-22: `sphinx-build` on a typo'd
# `:doc:` role emits "unknown document: 'x' [ref.doc]"; a typo'd toctree
# entry emits "toctree contains reference to nonexisting document 'x'
# [toc.not_readable]" — same target, differently worded).
_BROKEN_DOC_REF_RE = re.compile(r"(?:unknown document: |nonexisting document )'([^']+)'")


_BROKEN_LABEL_REF_RE = re.compile(r"undefined label: '([^']+)'")


def _did_you_mean(target: str, candidates: Iterable[str]) -> str | None:
    """Return a ' — did you mean: ...?' suffix for the closest candidates
    to *target*, or None if nothing is close enough to be worth suggesting."""
    matches = difflib.get_close_matches(target, list(candidates), n=3, cutoff=0.6)
    if not matches:
        return None
    return f" — did you mean: {', '.join(repr(m) for m in matches)}?"


def _attach_did_you_mean(finding: Finding, env: sphinx.environment.BuildEnvironment) -> Finding:
    """Append a 'did you mean' suggestion to a broken-:doc:/:ref: finding,
    using the SAME live Sphinx environment Phase 2 already built for this
    run (env.found_docs, env.domaindata['std']['anonlabels']) — never
    objects.inv, which needs a completed HTML build and holds less than the
    env already in hand.  Findings that aren't a broken :doc:/:ref: (or
    whose target has no close candidate) pass through unchanged.  Closes
    the guess-and-wait loop the contract otherwise leaves to a human/AI on a
    broken cross-reference (Max, 2026-07-22, item 2 of the priority list).
    """
    m = _BROKEN_DOC_REF_RE.search(finding.text)
    if m:
        suggestion = _did_you_mean(m.group(1), env.found_docs)
        if suggestion:
            return dataclasses.replace(finding, text=finding.text + suggestion)
        return finding
    m = _BROKEN_LABEL_REF_RE.search(finding.text)
    if m:
        anonlabels = env.domaindata.get("std", {}).get("anonlabels", {})
        suggestion = _did_you_mean(m.group(1), anonlabels)
        if suggestion:
            return dataclasses.replace(finding, text=finding.text + suggestion)
        return finding
    return finding


def run_sphinx(
    files: list[pathlib.Path],
    build_dir: pathlib.Path,
    sphinx_src: pathlib.Path,
    project_root: pathlib.Path | None = None,
) -> list[Finding]:
    """Run sphinx-build; return ERROR/WARNING findings for the checked files."""
    CALL_COUNTS["run_sphinx"] += 1
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sphinx",
            "--builder",
            "html",
            str(sphinx_src),
            str(build_dir),
        ],
        capture_output=True,
        text=True,
    )
    findings = _findings_from_sphinx_output(result.stdout + result.stderr, files, project_root)
    if result.returncode != 0 and not any(finding.severity == Severity.ERROR for finding in findings):
        findings.append(
            Finding(
                lineno=0,
                severity=Severity.ERROR,
                text=(
                    f"sphinx-build exited {result.returncode} "
                    "(failure may be outside the checked files — run without file filter)"
                ),
            )
        )
    return findings
