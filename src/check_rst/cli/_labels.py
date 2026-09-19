# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Explicit target definitions and their physical destinations — check_rst project

"""Read label definitions from parsed RST, never from text matches in code blocks."""

from __future__ import annotations

import dataclasses
import pathlib
from typing import TYPE_CHECKING, cast

import docutils.nodes

from ._helpers import _node_line

if TYPE_CHECKING:
    import sphinx.environment

    from ._document import Document


@dataclasses.dataclass(frozen=True, slots=True)
class LabelDefinition:
    name: str
    line: int
    source: str | None
    target_kind: str
    target_title: str | None
    target_line: int


@dataclasses.dataclass(frozen=True, slots=True)
class TargetRecord:
    name: str
    kind: str
    docname: str
    anchor: str
    title: str


def project_targets(env: sphinx.environment.BuildEnvironment) -> list[TargetRecord]:
    """Read valid Sphinx cross-reference destinations from the live registry."""
    std = env.domaindata.get("std", {})
    anonlabels = cast("dict[str, tuple[str, str]]", std.get("anonlabels", {}))
    titles = cast("dict[str, tuple[str, str, object]]", std.get("labels", {}))
    result = [
        TargetRecord(name, "ref", docname, anchor, str(titles[name][2]) if name in titles else "")
        for name, (docname, anchor) in anonlabels.items()
        if docname in env.found_docs
    ]
    result.extend(
        TargetRecord(docname, "doc", docname, "", env.titles[docname].astext() if docname in env.titles else "")
        for docname in env.found_docs
    )
    return sorted(result, key=lambda record: (record.name.casefold(), record.kind, record.docname))


def target_location(env: sphinx.environment.BuildEnvironment, target: TargetRecord) -> tuple[pathlib.Path, int]:
    """Resolve a target's definition line; do not present an inferred line as exact."""
    from ._document import Document

    path = pathlib.Path(env.doc2path(target.docname))
    if target.kind == "doc":
        return path, 0
    document = Document(path, pathlib.Path(env.srcdir))
    for label in explicit_labels(document):
        if label.name.casefold() == target.name.casefold():
            if label.source is not None:
                return pathlib.Path(env.srcdir) / label.source, label.line
            return path, label.line
    for node in env.get_doctree(target.docname).findall(docutils.nodes.Element):
        if target.anchor not in cast("list[str]", node.get("ids", [])):
            continue
        if isinstance(node, docutils.nodes.section) and node.children:
            underline = getattr(node.children[0], "line", None)
            return path, underline - 1 if isinstance(underline, int) else 0
        return path, _node_line(node)
    return path, 0


def explicit_labels(document: Document) -> list[LabelDefinition]:
    """Return active internal ``.. _name:`` targets with source ownership.

    Docutils attaches an internal target to the following node. A target
    before a section is still a sibling of that section, so section ancestry
    alone would incorrectly attribute it to the preceding section.
    """
    definitions: list[LabelDefinition] = []
    fragment_lines: dict[str, dict[str, list[int]]] = {}
    for node in document.doctree.findall(docutils.nodes.target):
        names = cast("list[str]", node.get("names", []))
        if not names or node.get("refuri") or node.get("refname"):
            continue
        line, _lines, provenance = document.source_context(node)
        if provenance is not None and provenance.exact:
            source_path = document.composition.source_path(provenance, document.path)
            if source_path is not None:
                source_key = str(source_path.resolve())
                if source_key not in fragment_lines:
                    from ._document import Document

                    fragment = Document(source_path, document.project_root)
                    physical: dict[str, list[int]] = {}
                    for local in fragment.doctree.findall(docutils.nodes.target):
                        if local.source != str(source_path) or not isinstance(local.line, int):
                            continue
                        for local_name in cast("list[str]", local.get("names", [])):
                            physical.setdefault(local_name, []).append(local.line)
                    fragment_lines[source_key] = physical
                candidates = fragment_lines[source_key].get(names[0], [])
                if len(candidates) == 1:
                    line = candidates[0]
        following: docutils.nodes.Node | None = None
        cursor: docutils.nodes.Node = node
        while cursor.parent is not None and following is None:
            siblings = cursor.parent.children
            for sibling in siblings[siblings.index(cursor) + 1 :]:
                if not isinstance(sibling, docutils.nodes.target):
                    following = sibling
                    break
            cursor = cursor.parent
        kind = "location"
        title: str | None = None
        target_line = line
        if isinstance(following, docutils.nodes.section):
            kind = "section"
            heading = following.children[0]
            title = heading.astext()
            underline_line = getattr(heading, "line", None)
            target_line = document.source_context(heading)[0] - 1 if isinstance(underline_line, int) else 0
        elif isinstance(following, docutils.nodes.Element):
            kind = following.tagname
            target_line = document.source_context(following)[0]
        for name in names:
            definitions.append(
                LabelDefinition(
                    name, line, provenance.source if provenance is not None else None, kind, title, target_line
                )
            )
    return definitions
