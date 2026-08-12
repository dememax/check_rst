# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Parsed-source composition capture and provenance mapping — check_rst project

from __future__ import annotations

import codecs
import contextlib
import pathlib
from typing import TYPE_CHECKING, Any, cast

import docutils.nodes
from docutils.parsers.rst import Directive, directives
from docutils.parsers.rst.directives.misc import Include as DocutilsInclude

from ._helpers import _normalize_source, _read_source
from ._types import IncludeSite, SourceOrigin, SourceProvenance

if TYPE_CHECKING:
    from collections.abc import Iterator


_INCLUDE_MARKER = "check_rst_include"


def is_include_marker(node: docutils.nodes.Node) -> bool:
    """Return whether *node* is check_rst's invisible parser marker."""
    return isinstance(node, docutils.nodes.comment) and _INCLUDE_MARKER in node


def _option_text(value: object) -> str:
    """Return a stable, serializable spelling for a converted option."""
    if value is None:
        return ""
    if isinstance(value, type):
        return f"{value.__module__}.{value.__qualname__}"
    return str(value)


def _include_mode(options: dict[str, object]) -> str:
    if "literal" in options:
        return "literal"
    if "code" in options:
        return f"code:{options['code']}"
    if "parser" in options:
        parser = options["parser"]
        return f"parser:{getattr(parser, '__name__', parser)}"
    return "parsed"


def _clip_span(path: pathlib.Path, options: dict[str, object]) -> tuple[int, int | None, bool]:
    """Map the included parser's line 1 back to the physical target.

    Docutils currently starts clipped input at logical line 1 even for
    ``:start-line:`` (its own source contains a TODO for this).  Reproduce
    its clipping order over the physical text and retain the offset and last
    selected physical line.  A read failure is not hidden: provenance remains
    present but is marked inexact, while Docutils/Sphinx emits the canonical
    include diagnostic itself.
    """
    try:
        encoding = cast("str", options.get("encoding") or "utf-8")
        text = path.read_text(encoding=encoding)
    except LookupError, OSError, UnicodeError:
        return 0, None, False

    all_lines = text.splitlines()
    start = cast("int | None", options.get("start-line")) or 0
    end_value = cast("int | None", options.get("end-line"))
    end = len(all_lines) if end_value is None else min(end_value, len(all_lines))
    selected = "\n".join(all_lines[start:end])
    start_offset = start

    start_after = cast("str | None", options.get("start-after"))
    if start_after == "":
        start_after = "\n\n"
    if start_after:
        match = selected.find(start_after)
        if match < 0:
            return start_offset, end, False
        consumed = selected[: match + len(start_after)]
        start_offset += consumed.count("\n")
        selected = selected[match + len(start_after) :]

    end_before = cast("str | None", options.get("end-before"))
    if end_before == "":
        match = selected.find("\n\n")
        if match > 0:
            selected = selected[: match + 1]
    elif end_before:
        match = selected.find(end_before)
        if match < 0:
            return start_offset, end, False
        selected = selected[:match]

    selected_lines = selected.splitlines()
    last_line = start_offset + len(selected_lines)
    return start_offset, last_line, True


def _tracking_include_class(base: type[Directive]) -> type[Directive]:
    """Return a transparent include subclass which leaves an invisible marker.

    The marker is a standard Docutils comment, so every Sphinx writer already
    knows how to ignore it.  Keeping it in the doctree is what distinguishes
    adjacent repeated inclusions of the same file; source paths alone cannot.
    """

    base_run = base.run

    def run(self: Directive) -> list[docutils.nodes.Node]:
        raw_target = self.arguments[0]
        mapped_source, mapped_line = self.state_machine.get_source_and_line(self.lineno)
        owner_source = str(mapped_source or self.state.document.current_source)
        owner_lineno = mapped_line if isinstance(mapped_line, int) else self.lineno
        options = dict(self.options)
        env = getattr(self.state.document.settings, "env", None)
        if raw_target.startswith("<") and raw_target.endswith(">"):
            initial_resolved = raw_target
        elif env is not None:
            _relative, absolute = env.relfn2path(raw_target)
            initial_resolved = str(absolute)
        else:
            initial_resolved = str((pathlib.Path(owner_source).parent / raw_target).resolve())
        clip = (
            options.get("start-line"),
            options.get("end-line"),
            options.get("start-after"),
            options.get("end-before"),
        )
        resolved_identity = str(pathlib.Path(initial_resolved).resolve())
        # include_log is a real instance attribute docutils sets in
        # document.__init__ — no published type stub declares it (dated
        # snapshots checked directly, 2026-08-12: absent from types-docutils'
        # nodes.pyi), so mypy can't see it without this narrow ignore.
        active_identities = {
            (str(pathlib.Path(str(source)).resolve()), tuple(active_clip))
            for source, active_clip in self.state.document.include_log  # type: ignore[attr-defined]
        }
        # Docutils' own include_log always carries '' (not None) for absent
        # start-after/end-before (see Include.run's self.clip_options) — only
        # the comparison tuple is reshaped to match; the public `clip` above
        # keeps its None defaults, since IncludeSite's tested contract relies
        # on them.
        docutils_clip = (clip[0], clip[1], clip[2] or "", clip[3] or "")
        cycle = initial_resolved if (resolved_identity, docutils_clip) in active_identities else None
        marker = docutils.nodes.comment()
        marker.source = owner_source
        marker.line = owner_lineno
        record: dict[str, object] = {
            "owner_source": owner_source,
            "owner_lineno": owner_lineno,
            "target": raw_target,
            "resolved": initial_resolved,
            "mode": _include_mode(options),
            "options": tuple(sorted((name, _option_text(value)) for name, value in options.items())),
            "clip": clip,
            "line_offset": 0,
            "end_line": None,
            "exact": True,
            "cycle": cycle,
        }
        marker[_INCLUDE_MARKER] = record
        self.state.parent += marker

        previous_active = getattr(env, "_check_rst_active_include", None) if env is not None else None
        if env is not None:
            env._check_rst_active_include = record
        try:
            if codecs.lookup(cast("str", options.get("encoding") or "utf-8")).name == "utf-8":
                # Root documents pass through Phase 0 before parsing.  The
                # include directive reads its own target, so select Python's
                # BOM-aware UTF-8 codec here to give included input the same
                # leading-BOM semantics without changing the recorded user
                # option or accepting BOMs as project policy.
                self.options["encoding"] = "utf-8-sig"
        except LookupError:
            # Leave invalid codec names to Docutils' canonical diagnostic.
            pass
        try:
            result = list(base_run(self))
        except Exception as exc:
            # docutils raises DirectiveError(level, message) via
            # Exception.__init__(self) with no args, so str(exc) is always
            # '' — the real text lives in .msg (confirmed against docutils'
            # own states.Body.run_directive, which itself only ever reads
            # .msg). getattr(...) falls back to str(exc) for any other
            # exception type, so no DirectiveError import is needed here.
            message = " ".join(str(getattr(exc, "msg", exc)).splitlines())
            if "circular inclusion" in message:
                record["cycle"] = raw_target
            record["exact"] = False
            raise
        finally:
            if env is not None:
                env._check_rst_active_include = previous_active

        resolved = self.options.get("source", self.arguments[0])
        resolved_path = pathlib.Path(str(resolved))
        offset, end_line, exact = _clip_span(resolved_path, options)
        record.update(
            {
                "resolved": str(resolved),
                "line_offset": offset,
                "end_line": end_line,
                "exact": bool(record["exact"]) and exact,
            }
        )
        return result

    return cast("type[Directive]", type("_CheckRstTrackedInclude", (base,), {"run": run}))


def _directive_registry() -> dict[str, type[Directive]]:
    """Return docutils' own private include-directive registry dict.

    directives._directives is real at runtime, but leading-underscore
    names aren't part of its published type stub (dated snapshots checked
    directly, 2026-08-12) — one narrow ignore here instead of one at each
    of this module's three call sites. The cast is required too: the
    ignore only silences attr-defined on the access itself, not
    warn_return_any's separate complaint about returning the resulting
    Any from a function declared to return a concrete dict type.
    """
    return cast("dict[str, type[Directive]]", directives._directives)  # type: ignore[attr-defined]


@contextlib.contextmanager
def tracked_docutils_include() -> Iterator[None]:
    """Temporarily instrument bare Docutils' standard include directive."""
    old = _directive_registry().get("include")
    directives.register_directive("include", _tracking_include_class(DocutilsInclude))
    try:
        yield
    finally:
        if old is None:
            _directive_registry().pop("include", None)
        else:
            directives.register_directive("include", old)


# Tracks which wrapped classes instrument_sphinx_include has already produced,
# so a repeated call (e.g. across tests in one process) doesn't wrap a
# wrapper.  A set keyed by class identity avoids a dynamically-added class
# attribute, which docutils' own Directive type has no declared slot for.
_TRACKED_INCLUDE_BASES: set[type[Directive]] = set()


def instrument_sphinx_include() -> None:
    """Wrap the include class registered by the fully initialized Sphinx app."""
    base = _directive_registry().get("include")
    if base is None:
        raise RuntimeError("Sphinx did not register its include directive")
    if base in _TRACKED_INCLUDE_BASES:
        return
    tracked = _tracking_include_class(base)
    _TRACKED_INCLUDE_BASES.add(tracked)
    directives.register_directive("include", tracked)


def mark_include_read_before(_app: object, _path: pathlib.Path, _docname: str, source: list[str]) -> None:
    """Capture included text before project listeners mutate it."""
    env = getattr(_app, "env", None)
    record = getattr(env, "_check_rst_active_include", None)
    if isinstance(record, dict):
        record["include_read_before"] = source[0]


def mark_include_read_after(_app: object, _path: pathlib.Path, _docname: str, source: list[str]) -> None:
    """Mark physical coordinates inexact when ``include-read`` changed text."""
    env = getattr(_app, "env", None)
    record = getattr(env, "_check_rst_active_include", None)
    if isinstance(record, dict):
        before = record.pop("include_read_before", source[0])
        if source[0] != before:
            record["exact"] = False


def mark_source_read_before(app: object, docname: str, source: list[str]) -> None:
    """Capture root source before project ``source-read`` listeners."""
    env = getattr(app, "env", None)
    if env is not None:
        pending = getattr(env, "_check_rst_source_read_before", {})
        pending[docname] = source[0]
        env._check_rst_source_read_before = pending


def mark_source_read_after(app: object, docname: str, source: list[str]) -> None:
    """Remember documents whose extension-provided source is not physical."""
    env = getattr(app, "env", None)
    if env is None:
        return
    pending = getattr(env, "_check_rst_source_read_before", {})
    before = pending.pop(docname, source[0])
    transformed: set[str] = getattr(env, "_check_rst_transformed_sources", set())
    if source[0] != before:
        transformed.add(docname)
    else:
        transformed.discard(docname)
    env._check_rst_transformed_sources = transformed


def _normalise_source(source: str, source_root: pathlib.Path) -> str:
    if source.startswith("<") and source.endswith(">"):
        return source
    path = pathlib.Path(source)
    try:
        return str(path.resolve().relative_to(source_root.resolve()))
    except ValueError:
        return str(path.resolve())


def _source_origin(source: str) -> SourceOrigin:
    if source == "<rst_prologue>":
        return SourceOrigin.RST_PROLOGUE
    if source == "<rst_epilogue>":
        return SourceOrigin.RST_EPILOGUE
    if source.startswith("<"):
        return SourceOrigin.GENERATED
    return SourceOrigin.INCLUDE


class CompositionIndex:
    """Provenance lookup derived from include markers in doctree order."""

    def __init__(
        self,
        doctree: docutils.nodes.document,
        root_path: pathlib.Path,
        source_root: pathlib.Path,
        *,
        root_transformed: bool = False,
    ) -> None:
        self.root_source = _normalise_source(str(root_path), source_root)
        self.source_root = source_root
        self.root_transformed = root_transformed
        self._provenance: dict[int, SourceProvenance | None] = {}
        self._source_lines: dict[tuple[pathlib.Path, str], list[str]] = {}
        self.include_nodes: list[
            tuple[docutils.nodes.comment, IncludeSite, SourceProvenance | None, dict[str, object]]
        ] = []
        self._build(doctree)

    def _build(self, doctree: docutils.nodes.document) -> None:
        chain: list[IncludeSite] = []

        def adjust(source: str, logical_line: int | None = None) -> None:
            nonlocal chain
            if source == self.root_source:
                chain = []
                return
            matches = [i for i, site in enumerate(chain) if site.target == source]
            if logical_line is not None and logical_line > 0:
                bounded_matches = [
                    i
                    for i in matches
                    if chain[i].end_line is None
                    or logical_line + chain[i].line_offset <= cast("int", chain[i].end_line)
                ]
                if bounded_matches:
                    matches = bounded_matches
            if matches:
                chain = chain[: matches[-1] + 1]
            elif chain:
                chain = []

        for order, node in enumerate(doctree.findall()):
            if isinstance(node, docutils.nodes.comment) and _INCLUDE_MARKER in node:
                record = cast("dict[str, Any]", node[_INCLUDE_MARKER])
                owner = _normalise_source(str(record["owner_source"]), self.source_root)
                adjust(owner, int(record["owner_lineno"]))
                owner_offset = chain[-1].line_offset if chain and chain[-1].target == owner else 0
                owner_lineno = int(record["owner_lineno"]) + owner_offset
                resolved = _normalise_source(str(record["resolved"]), self.source_root)
                owner_exact = all(site.exact for site in chain)
                exact = bool(record["exact"]) and owner_exact
                if owner == self.root_source:
                    provenance = (
                        SourceProvenance(owner, SourceOrigin.TRANSFORMED, (), False, order)
                        if self.root_transformed
                        else None
                    )
                else:
                    provenance = SourceProvenance(owner, SourceOrigin.INCLUDE, tuple(chain), owner_exact, order)
                site = IncludeSite(
                    source=owner,
                    lineno=owner_lineno,
                    target=resolved,
                    mode=str(record["mode"]),
                    options=cast("tuple[tuple[str, str], ...]", record["options"]),
                    clip=cast(
                        "tuple[str | int | None, str | int | None, str | int | None, str | int | None]",
                        record["clip"],
                    ),
                    line_offset=int(record["line_offset"]),
                    end_line=cast("int | None", record["end_line"]),
                    exact=exact,
                    order=order,
                )
                self._provenance[id(node)] = provenance
                self.include_nodes.append((node, site, provenance, record))
                cycle = cast("str | None", record["cycle"])
                if cycle is None:
                    chain = [*chain, site]
                continue

            raw_source = getattr(node, "source", None)
            if not isinstance(raw_source, str):
                self._provenance[id(node)] = None
                continue
            source = _normalise_source(raw_source, self.source_root)
            node_line = node.line if isinstance(node.line, int) else None
            adjust(source, node_line)
            if source == self.root_source:
                provenance = (
                    SourceProvenance(source, SourceOrigin.TRANSFORMED, (), False, order)
                    if self.root_transformed
                    else None
                )
            elif source.startswith("<"):
                provenance = SourceProvenance(source, _source_origin(source), (), False, order)
            else:
                matching = bool(chain and chain[-1].target == source)
                provenance = SourceProvenance(
                    source,
                    SourceOrigin.INCLUDE,
                    tuple(chain),
                    matching and all(site.exact for site in chain),
                    order,
                )
            self._provenance[id(node)] = provenance

    def provenance(self, node: docutils.nodes.Node) -> SourceProvenance | None:
        return self._provenance.get(id(node))

    def physical_line(self, node: docutils.nodes.Node, logical_line: int) -> int:
        if logical_line <= 0:
            return 0
        provenance = self.provenance(node)
        if provenance and provenance.include_chain:
            return logical_line + provenance.include_chain[-1].line_offset
        return logical_line

    def source_path(self, provenance: SourceProvenance | None, root_path: pathlib.Path) -> pathlib.Path | None:
        if provenance is None:
            return root_path
        if provenance.source.startswith("<"):
            return None
        path = pathlib.Path(provenance.source)
        return path if path.is_absolute() else self.source_root / path

    def source_lines(
        self,
        provenance: SourceProvenance | None,
        root_path: pathlib.Path,
        root_lines: list[str],
    ) -> list[str]:
        """Return normalized physical lines using the active include codec."""
        if provenance is None:
            return root_lines
        if not provenance.exact:
            return []
        path = self.source_path(provenance, root_path)
        if path is None:
            return []
        options = dict(provenance.include_chain[-1].options) if provenance.include_chain else {}
        encoding = options.get("encoding") or "utf-8"
        key = (path, encoding)
        cached = self._source_lines.get(key)
        if cached is not None:
            return cached
        try:
            lines = _normalize_source(_read_source(path, encoding))[0].splitlines()
        except LookupError, OSError, UnicodeError:
            lines = []
        self._source_lines[key] = lines
        return lines

    @staticmethod
    def included_provenance(
        site: IncludeSite,
        owner: SourceProvenance | None,
    ) -> SourceProvenance:
        """Return the physical identity of one parsed include occurrence."""
        owner_chain = owner.include_chain if owner is not None else ()
        return SourceProvenance(
            site.target,
            SourceOrigin.INCLUDE,
            (*owner_chain, site),
            site.exact,
            site.order,
        )

    def source_end(self, provenance: SourceProvenance | None, lines: list[str]) -> int:
        if not lines:
            return 0
        if provenance and provenance.include_chain:
            end_line = provenance.include_chain[-1].end_line
            return len(lines) if end_line is None else end_line
        return len(lines)
