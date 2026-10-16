# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# A file's structural fix planned in its composed include contexts (CR-43) — check_rst project
"""Plan a file's structural fix in every include context it has (CR-43, P4a).

A file meant for ``.. include::`` has no standalone hierarchy authority: its
titles mean what they mean in each document that composes it.  Full fix and
diff therefore compose every root document that reaches the file (a
transitive includer that nothing includes, or one declared standalone) as
Docutils composes it, plan the parser-free structural fix on the composed
lines, and map the edits back to the file's own lines.  The file's
standalone use, when it has one, is one more context.

Composition is lexical, and exact for the includes it accepts: a structural
include at indent 0, without ``:parser:`` or a non-UTF-8 ``:encoding:``,
whose target can be read and whose clip matches.  The clipped lines replace
the directive block, followed by the two lines Docutils appends to every
inclusion: a blank line and an end-of-inclusion comment.  Any other include
makes the context unavailable.

A structural edit applies only when every available context needs the same
edit, confined to the file.  An edit that also changes another file, a line
a clip cuts, or one of Docutils' synthetic lines is refused, because fix
changes only the file it plans.  Each mapping is proven by recomposing the
context from the mapped file: the result must be the planner's own output.
"""

from __future__ import annotations

import dataclasses
import difflib
from typing import TYPE_CHECKING

from ._formatting import _structure_plan, _title_style_events
from ._helpers import _normalize_source, _read_source
from ._includes import IncludeGuard, LexicalInclude, lexical_includes
from ._types import Finding, FindingCode, Severity

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence

    from ._includes import IncludeUniverse

type _Ranges = list[tuple[int, int]] | None
type _Selection = list[tuple[str, int, bool]]

_UTF8 = frozenset({"utf-8", "utf8", "utf_8"})
_CLIP_OPTIONS = ("start-line", "end-line", "start-after", "end-before")
_STANDALONE = "standalone use"


@dataclasses.dataclass(frozen=True, slots=True)
class _Origin:
    """Where one composed line comes from: a canonical file and its 0-based
    physical line, *partial* when a clip boundary falls inside it."""

    path: pathlib.Path
    index: int
    partial: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class _Composition:
    """A root document's composed lines; a ``None`` origin is a line Docutils
    adds after an inclusion."""

    root: pathlib.Path
    lines: tuple[str, ...]
    origins: tuple[_Origin | None, ...]


class _UncomposableError(Exception):
    """An include the lexical composer cannot reproduce exactly."""

    def __init__(self, site: LexicalInclude, reason: str) -> None:
        super().__init__(reason)
        self.site = site
        self.reason = reason


def _clip(lines: Sequence[str], options: dict[str, str]) -> _Selection | None:
    """Return Docutils' clipped selection of *lines*, in its clipping order.

    Each entry is a selected line's text, its 0-based physical index and
    whether a text clip cuts it.  None means an option is malformed or a text
    clip matches nothing, which Docutils reports as an error.  An empty text
    clip is refused too: its meaning differs between Docutils versions.
    """
    try:
        start = int(options["start-line"]) if "start-line" in options else None
        end = int(options["end-line"]) if "end-line" in options else None
    except ValueError:
        return None
    indices = list(range(len(lines)))[start:end]
    joined = "\n".join(lines[index] for index in indices)
    begin, finish = 0, len(joined)
    after = options.get("start-after")
    if after is not None:
        match = joined.find(after) if after else -1
        if match < 0:
            return None
        begin = match + len(after)
    before = options.get("end-before")
    if before is not None:
        match = joined.find(before, begin) if before else -1
        if match < 0:
            return None
        finish = match
    selected = joined[begin:finish].splitlines()
    first = joined.count("\n", 0, begin)
    cut_first = begin > 0 and joined[begin - 1] != "\n"
    cut_last = finish < len(joined) and joined[finish] != "\n"
    return [
        (text, indices[first + offset], (offset == 0 and cut_first) or (offset == len(selected) - 1 and cut_last))
        for offset, text in enumerate(selected)
    ]


def _check_composable(site: LexicalInclude) -> None:
    if site.indent > 0:
        raise _UncomposableError(site, "indented inside another construct")
    options = dict(site.options)
    if "parser" in options:
        raise _UncomposableError(site, "it sets :parser:")
    encoding = options.get("encoding")
    if encoding is not None and encoding.lower() not in _UTF8:
        raise _UncomposableError(site, "it sets :encoding:")


class Composer:
    """Compose root documents lexically, reading each file once per run.

    Every file is read as Phase 0 normalizes it, the text fix plans from; the
    file being planned supplies its own current lines instead.
    """

    def __init__(self, universe: IncludeUniverse) -> None:
        self.universe = universe
        self._lines: dict[pathlib.Path, list[str] | None] = {}

    def disk_lines(self, path: pathlib.Path) -> list[str] | None:
        real = path.resolve()
        if real not in self._lines:
            try:
                self._lines[real] = _normalize_source(_read_source(path))[0].splitlines()
            except OSError, UnicodeError:
                self._lines[real] = None
        return self._lines[real]

    def compose(self, root: pathlib.Path, own: pathlib.Path, own_lines: Sequence[str]) -> _Composition:
        """Compose *root*, with *own*'s lines taken from *own_lines*.

        Raises _UncomposableError at the first include that cannot be
        reproduced exactly.
        """
        lines: list[str] = []
        origins: list[_Origin | None] = []

        def text_of(path: pathlib.Path) -> list[str] | None:
            return list(own_lines) if path.resolve() == own else self.disk_lines(path)

        def expand(path: pathlib.Path, selection: _Selection, stack: tuple[tuple[object, ...], ...]) -> None:
            real = path.resolve()
            full = text_of(path) or []
            sites = {
                site.line - 1: site
                for site in lexical_includes(path, text="\n".join(full), sphinx_src=self.universe.sphinx_src)
                if site.structural
            }
            position = {index: offset for offset, (_text, index, _cut) in enumerate(selection)}
            offset = 0
            while offset < len(selection):
                text, index, cut = selection[offset]
                site = sites.get(index)
                if site is None or cut:
                    lines.append(text)
                    origins.append(_Origin(real, index, cut))
                    offset += 1
                    continue
                _check_composable(site)
                block = range(index, site.block_end)
                if any(line not in position or selection[position[line]][2] for line in block):
                    raise _UncomposableError(site, "its includer's clip cuts through it")
                target = text_of(site.target)
                if target is None:
                    raise _UncomposableError(site, "its target cannot be read")
                options = dict(site.options)
                clipped = _clip(target, options)
                if clipped is None:
                    raise _UncomposableError(site, "its clipping options do not match its target")
                identity = (site.canonical_target, *(options.get(name) for name in _CLIP_OPTIONS))
                if identity in stack:
                    raise _UncomposableError(site, "it is part of an include cycle")
                expand(site.target, clipped, (*stack, identity))
                lines.extend(["", f'.. end of inclusion from "{site.argument}"'])
                origins.extend([None, None])
                offset = position[site.block_end - 1] + 1

        root_lines = text_of(root) or []
        expand(
            root,
            [(text, index, False) for index, text in enumerate(root_lines)],
            ((root.resolve(), None, None, None, None),),
        )
        return _Composition(root, tuple(lines), tuple(origins))


def _style_token(style: tuple[str, bool]) -> str:
    return f"{style[0]}{'o' if style[1] else 'u'}"


@dataclasses.dataclass(frozen=True, slots=True)
class _Outcome:
    """One context's verdict: the file's planned lines, or a refusal."""

    label: str
    lines: tuple[str, ...] = ()
    refusal: Finding | None = None


class ContextStage:
    """The structural stage of one file's fix plan, judged in its contexts.

    Called like ``_structure_plan``, with the file's lines at the stage the
    planner reached; it returns the agreed lines, or the lines unchanged with
    the refusal that blocks them.
    """

    def __init__(self, composer: Composer, path: pathlib.Path, roots: Sequence[tuple[pathlib.Path, str]]) -> None:
        self.composer = composer
        self.own = path.resolve()
        self.roots = tuple(roots)
        self._cache: dict[
            tuple[tuple[str, ...], tuple[tuple[int, int], ...] | None], tuple[list[str], tuple[Finding, ...]]
        ] = {}

    def __call__(self, lines: list[str], ranges: _Ranges) -> tuple[list[str], tuple[Finding, ...]]:
        key = (tuple(lines), None if ranges is None else tuple(ranges))
        if key not in self._cache:
            self._cache[key] = self._judge(lines, ranges)
        cached_lines, refusals = self._cache[key]
        return list(cached_lines), refusals

    def _judge(self, lines: list[str], ranges: _Ranges) -> tuple[list[str], tuple[Finding, ...]]:
        outcomes = [self._plan_in(root, label, lines, ranges) for root, label in self.roots]
        refused = next((outcome.refusal for outcome in outcomes if outcome.refusal is not None), None)
        if refused is not None:
            return list(lines), (refused,)
        first = outcomes[0]
        for other in outcomes[1:]:
            if other.lines != first.lines:
                return list(lines), (self._conflict(lines, first, other),)
        return list(first.lines), ()

    def _shown(self, path: pathlib.Path) -> str:
        return self.composer.universe.shown(path)

    def _finding(self, lineno: int, text: str) -> Finding:
        return Finding(
            lineno=lineno, severity=Severity.ERROR, text=text, fixable=False, code=FindingCode.INCLUDE_CONTEXT_CONFLICT
        )

    def _plan_in(self, root: pathlib.Path, label: str, lines: list[str], ranges: _Ranges) -> _Outcome:
        try:
            composition = self.composer.compose(root, self.own, lines)
        except _UncomposableError as error:
            # Availability is classified from the file on disk; the planner's
            # own edits cannot add an include, so this is a defensive refusal.
            where = f"{self._shown(error.site.includer)}:{error.site.line}"
            return _Outcome(
                label, refusal=self._finding(1, f"the include at {where} cannot be composed ({error.reason})")
            )
        if all(origin is not None and origin.path == self.own and not origin.partial for origin in composition.origins):
            # The file alone: its own plan, with its own refusals as check
            # reports them.
            fixed, refusals = _structure_plan(list(lines), ranges)
            return _Outcome(label, tuple(fixed), refusals[0] if refusals else None)
        fixed, refusals = _structure_plan(list(composition.lines), self._composed_ranges(composition, ranges))
        if refusals:
            where = self._where(composition, refusals[0].lineno - 1)
            return _Outcome(
                label,
                refusal=self._finding(
                    self._first_title(lines),
                    f"in the document {self._shown(root)} composes, the titles are ambiguous at {where} "
                    f"({refusals[0].code}), so fix cannot plan them — resolve that first",
                ),
            )
        edits, foreign = self._attribute(composition, fixed)
        if not edits:
            return _Outcome(label, tuple(lines))
        if foreign is not None:
            return _Outcome(
                label,
                refusal=self._finding(
                    min(start for start, _end, _new in edits) + 1,
                    f"in the document {self._shown(root)} composes, its title change also needs {foreign} to "
                    "change, and fix changes only this file — make that document's titles consistent by hand",
                ),
            )
        mapped = self._apply(lines, edits)
        if mapped is None or list(self.composer.compose(root, self.own, mapped).lines) != fixed:
            return _Outcome(
                label,
                refusal=self._finding(
                    min(start for start, _end, _new in edits) + 1,
                    f"check_rst cannot map the title edits of the document {self._shown(root)} composes back to "
                    "this file — make that document's titles consistent by hand",
                ),
            )
        return _Outcome(label, tuple(mapped))

    def _composed_ranges(self, composition: _Composition, ranges: _Ranges) -> list[tuple[int, int]]:
        """Translate the file's own 1-based ranges into composed coordinates.

        Geometry is fixed only on this file's lines, never on an includer's:
        a fragment's line 2 is not its includer's line 2.  ``None`` (the whole
        file) becomes every line of this file in the composition.
        """
        wanted = None if ranges is None else {index for start, end in ranges for index in range(start - 1, end)}
        runs: list[tuple[int, int]] = []
        for position, origin in enumerate(composition.origins, start=1):
            if origin is None or origin.path != self.own or origin.partial:
                continue
            if wanted is not None and origin.index not in wanted:
                continue
            if runs and runs[-1][1] == position - 1:
                runs[-1] = (runs[-1][0], position)
            else:
                runs.append((position, position))
        return runs

    def _where(self, composition: _Composition, position: int) -> str:
        origin = composition.origins[position] if 0 <= position < len(composition.origins) else None
        if origin is None:
            return "an inclusion boundary"
        return f"{self._shown(origin.path)}:{origin.index + 1}"

    def _attribute(
        self, composition: _Composition, fixed: list[str]
    ) -> tuple[list[tuple[int, int, list[str]]], str | None]:
        """Split the composed edits into this file's physical edits and the
        location of the first edit anywhere else.

        An inserted line belongs to the line it is inserted before: the
        planner inserts overlines and blank lines above a title.
        """
        edits: list[tuple[int, int, list[str]]] = []
        foreign: str | None = None
        count = len(composition.lines)
        matcher = difflib.SequenceMatcher(a=list(composition.lines), b=fixed, autojunk=False)
        for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
            if tag == "equal":
                continue
            touched = list(range(old_start, old_end)) if old_start < old_end else [min(old_start, count - 1)]
            origins = [composition.origins[position] for position in touched]
            stray = next(
                (
                    position
                    for position, origin in zip(touched, origins, strict=True)
                    if origin is None or origin.partial or origin.path != self.own
                ),
                None,
            )
            if stray is not None:
                foreign = foreign or self._where(composition, stray)
                continue
            indices = [origin.index for origin in origins if origin is not None]
            replacement = fixed[new_start:new_end]
            if old_start == old_end:
                at = indices[0] if old_start < count else indices[0] + 1
                edits.append((at, at, replacement))
            elif indices == list(range(indices[0], indices[-1] + 1)):
                edits.append((indices[0], indices[-1] + 1, replacement))
            else:
                foreign = foreign or self._where(composition, touched[0])
        return edits, foreign

    @staticmethod
    def _apply(lines: list[str], edits: list[tuple[int, int, list[str]]]) -> list[str] | None:
        """Apply physical edits; a repeated inclusion repeats its edits, so
        identical ones merge, and any other overlap fails the mapping."""
        unique: list[tuple[int, int, list[str]]] = []
        for edit in sorted(edits, key=lambda item: (item[0], item[1])):
            if unique and unique[-1] == edit:
                continue
            if unique and (edit[0] < unique[-1][1] or (edit[0] == unique[-1][0] == unique[-1][1])):
                return None
            unique.append(edit)
        mapped = list(lines)
        for start, end, replacement in reversed(unique):
            mapped[start:end] = replacement
        return mapped

    @staticmethod
    def _first_title(lines: list[str]) -> int:
        events = _title_style_events(lines)
        return events[0][0] + 1 if events else 1

    def _conflict(self, lines: list[str], first: _Outcome, other: _Outcome) -> Finding:
        original = _title_style_events(lines)
        ours = _title_style_events(list(first.lines))
        theirs = _title_style_events(list(other.lines))
        if len(original) == len(ours) == len(theirs):
            for title, mine, yours in zip(original, ours, theirs, strict=True):
                if mine[1] != yours[1]:
                    return self._finding(
                        title[0] + 1,
                        f"its include contexts need different title styles here: {first.label} needs "
                        f"{_style_token(mine[1])!r} and {other.label} needs {_style_token(yours[1])!r}, so fix "
                        "cannot choose one — make the documents that include it agree",
                    )
        differing = next(
            (index for index, (mine, yours) in enumerate(zip(first.lines, other.lines, strict=False)) if mine != yours),
            min(len(first.lines), len(other.lines)),
        )
        return self._finding(
            differing + 1,
            f"its include contexts need different title edits here: {first.label} and {other.label} disagree, "
            "so fix cannot choose one — make the documents that include it agree",
        )


def full_mode_planning(
    universe: IncludeUniverse, composer: Composer, path: pathlib.Path
) -> tuple[IncludeGuard | None, ContextStage | None]:
    """Return *path*'s unavailable-context guard and its context stage.

    ``(None, None)`` keeps today's standalone plan: a file nothing includes,
    with no include of its own and no declaration, is its own only context.
    The stage judges the available contexts; the guard, when one context is
    unavailable, still refuses any edit that changes the title model.
    """
    real = path.resolve()
    guard = universe.unavailable_guard(path)
    graph = universe.graph
    roots, cycle = graph.root_contexts(real, standalone=universe.standalone)
    if cycle is not None:
        site = f"{universe.shown(cycle.includer)}:{cycle.line}"
        return guard or IncludeGuard("uncomposable", site, "it is part of an include cycle"), None
    own_lines = composer.disk_lines(path)
    own_includes = own_lines is not None and any(
        site.structural for site in lexical_includes(path, text="\n".join(own_lines), sphinx_src=universe.sphinx_src)
    )
    standalone = (not graph.may_be_included(real) and real not in universe.declared) or real in universe.standalone
    if not roots and not own_includes:
        return guard, None
    candidates = [(root, universe.shown(root)) for root in roots]
    if standalone:
        candidates.append((path, _STANDALONE))
    available: list[tuple[pathlib.Path, str]] = []
    for root, label in candidates:
        try:
            composer.compose(root, real, own_lines or [])
        except _UncomposableError as error:
            if guard is None:
                site = f"{universe.shown(error.site.includer)}:{error.site.line}"
                guard = IncludeGuard("uncomposable", site, error.reason)
            continue
        available.append((root, label))
    return guard, (ContextStage(composer, path, available) if available else None)
