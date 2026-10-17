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

Every lexical site is proven by a parse of its file (P4b, and Codex's P4
checkpoint).  It runs when Docutils executes it; it is text in a literal
block, a comment, or another verbatim node; it is rejected when Docutils
refuses the invocation itself, which then includes nothing.  Any other site
is unknown, and unavailable: content an unknown directive leaves unparsed
may still be parsed by Sphinx.

A structural edit applies only when every available context needs the same
edit, confined to the file.  An edit that also changes another file, a line
a clip cuts, or one of Docutils' synthetic lines is refused, because fix
changes only the file it plans.  Each mapping is proven by recomposing the
context from the mapped file: the result must be the planner's own output.
Then Docutils itself parses the root with its real include directives, the
planned text standing in for the file, and must read the section tree the
planner expects (contract rule 5, P4d).
"""

from __future__ import annotations

import contextlib
import dataclasses
import difflib
import pathlib
from typing import TYPE_CHECKING

import docutils.frontend
import docutils.io
import docutils.nodes
import docutils.parsers.rst
import docutils.utils
from docutils.parsers.rst import Directive, directives, roles
from docutils.parsers.rst.directives.misc import Include as DocutilsInclude

from ._formatting import _structure_plan, _title_style_events, adornment_findings, hierarchy_findings
from ._helpers import _normalize_source, _read_source
from ._includes import (
    IncludeGraph,
    IncludeGuard,
    LexicalInclude,
    Selection,
    Variant,
    docutils_text,
    effective_input,
    lexical_includes,
    tab_width,
)
from ._types import Finding, FindingCode, Severity

if TYPE_CHECKING:
    import os
    from collections.abc import Iterator, Sequence

    from ._includes import IncludeUniverse
    from ._sphinx import PlanningFacts

type _Ranges = list[tuple[int, int]] | None

_UTF8 = frozenset({"utf-8", "utf8", "utf_8"})
_CLIP_OPTIONS = ("start-line", "end-line", "start-after", "end-before")
_STANDALONE = "standalone use"


@dataclasses.dataclass(frozen=True, slots=True)
class _Origin:
    """Where one composed line comes from: a canonical file and its 0-based
    physical line, *partial* when a clip boundary falls inside it.

    *reported* is the 1-based line Docutils gives it: Docutils numbers an
    inserted text from its own first line, so a clip shifts the number.
    *expanded* marks a line whose tabs Docutils expands, so its composed
    text is not its physical text and no edit may be written back to it.
    """

    path: pathlib.Path
    index: int
    partial: bool = False
    reported: int = 0
    expanded: bool = False


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


# Nodes whose text Docutils keeps verbatim: a line inside one is text.
_VERBATIM = (
    docutils.nodes.literal_block,
    docutils.nodes.comment,
    docutils.nodes.raw,
    docutils.nodes.doctest_block,
    docutils.nodes.math_block,
)


@contextlib.contextmanager
def _builtins_only(include: type[Directive]) -> Iterator[None]:
    """Parse with Docutils' built-in directives and roles alone, and *include*.

    check_rst's own parses read files nobody selected, so like CR-30's they
    must never run what an extension registered in the process.  Docutils
    looks a name up in its registered dicts first, then in its own tables:
    every directive entry imports from Docutils' own package, and the role
    table is narrowed to roles Docutils' modules define.  Fresh dicts for
    the parse leave exactly the built-ins; the originals are restored after.
    A registry of an unexpected shape fails closed, with RuntimeError.
    """
    directive_module, role_module = vars(directives), vars(roles)
    registered = directive_module.get("_directives")
    local_roles = role_module.get("_roles")
    canonical_roles = role_module.get("_role_registry")
    if not (isinstance(registered, dict) and isinstance(local_roles, dict) and isinstance(canonical_roles, dict)):
        raise RuntimeError("Docutils' directive or role registry is unavailable")
    directive_module["_directives"] = {"include": include}
    role_module["_roles"] = {}
    role_module["_role_registry"] = {
        name: role for name, role in canonical_roles.items() if getattr(role, "__module__", "").startswith("docutils.")
    }
    try:
        yield
    finally:
        directive_module["_directives"] = registered
        role_module["_roles"] = local_roles
        role_module["_role_registry"] = canonical_roles


def _probe_directive(seen: set[str]) -> type[Directive]:
    """An ``include`` that records its argument and reads nothing."""

    class _ProbeInclude(Directive):
        required_arguments = 1
        final_argument_whitespace = True
        option_spec = DocutilsInclude.option_spec

        def run(self) -> list[docutils.nodes.Node]:
            seen.add(self.arguments[0])
            return []

    return _ProbeInclude


# The four verdicts of a probe parse on one lexical site.
_RUN, _TEXT, _REJECTED, _UNKNOWN = "run", "text", "rejected", "unknown"
_NO_INCLUDE = frozenset({_TEXT, _REJECTED})


def _probe_sites(path: pathlib.Path, lines: Sequence[str], sites: Sequence[LexicalInclude]) -> dict[int, str]:
    """Return each site's verdict, by 1-based directive line, from a parse.

    Each site's argument becomes a unique token, and the file is parsed with
    an ``include`` that validates like Docutils' own and only records the
    tokens it receives.  A recorded token ran.  A token in a verbatim node is
    text.  Inside an error report, a token is rejected when the reported
    block is that include itself, and unknown when it is a container that
    Docutils did not parse, such as an unknown directive.  An unseen token
    proves nothing either.
    """
    probed = list(lines)
    tokens: dict[str, int] = {}
    for site in sites:
        token = f"check-rst-probe-{site.line}-end"
        # The argument sits on the directive line, or continues on the next.
        for index in (site.line - 1, site.line):
            if index < len(probed) and (cut := probed[index].rfind(site.argument)) >= 0:
                probed[index] = probed[index][:cut] + token + probed[index][cut + len(site.argument) :]
                tokens[token] = site.line
                break
    verdicts = dict.fromkeys((site.line for site in sites), _UNKNOWN)
    if not tokens:
        return verdicts
    seen: set[str] = set()
    settings = docutils.frontend.get_default_settings(docutils.parsers.rst.Parser())
    settings.halt_level = 5
    settings.report_level = 5
    settings.file_insertion_enabled = False
    document = docutils.utils.new_document(str(path), settings)
    with _builtins_only(_probe_directive(seen)):
        docutils.parsers.rst.Parser().parse("\n".join(probed), document)
    for node in document.findall(docutils.nodes.Text):
        for token, site_line in tokens.items():
            if token not in node or token in seen:
                continue
            ancestors: list[docutils.nodes.Element] = []
            parent = node.parent
            while parent is not None:
                ancestors.append(parent)
                parent = parent.parent
            report = next((item for item in ancestors if isinstance(item, docutils.nodes.system_message)), None)
            if report is not None:
                quoted = next((item for item in ancestors if isinstance(item, docutils.nodes.literal_block)), None)
                head = quoted.astext().lstrip().partition("\n")[0].lower() if quoted is not None else ""
                verdicts[site_line] = _REJECTED if head.startswith(".. include::") and token in head else _UNKNOWN
            elif any(isinstance(item, _VERBATIM) for item in ancestors):
                verdicts[site_line] = _TEXT
    for token, site_line in tokens.items():
        if token in seen:
            verdicts[site_line] = _RUN
    return verdicts


@contextlib.contextmanager
def _planned_input(text: str) -> Iterator[None]:
    """Make Docutils' FileInput, which ``Include.read_file`` opens, read
    *text*.  Docutils then clips it exactly as it clips the file."""
    original = docutils.io.FileInput

    class _PlannedInput(docutils.io.FileInput):
        def read(self) -> str:
            return text

    vars(docutils.io)["FileInput"] = _PlannedInput
    try:
        yield
    finally:
        vars(docutils.io)["FileInput"] = original


def _planned_include(own: pathlib.Path, own_text: str, sphinx_src: pathlib.Path | None) -> type[Directive]:
    """Docutils' own include, reading *own* as its planned text, with
    Sphinx's reading of a leading "/" when a source directory is known."""

    class _PlannedInclude(DocutilsInclude):
        def run(self) -> Sequence[docutils.nodes.Node]:
            if sphinx_src is not None and self.arguments[0].startswith("/"):
                self.arguments[0] = str(sphinx_src / self.arguments[0].lstrip("/"))
            return super().run()

        def read_file(self, path: str | os.PathLike[str]) -> str:
            if pathlib.Path(path).resolve() == own:
                with _planned_input(own_text):
                    return super().read_file(path)
            return super().read_file(path)

    return _PlannedInclude


type _Section = tuple[pathlib.Path | None, int | None, int]
"""A section's identity: its title's canonical source, the line Docutils
reports for the title (its underline), and its nesting depth."""


def _docutils_sections(
    root: pathlib.Path, root_text: str, own: pathlib.Path, own_text: str, sphinx_src: pathlib.Path | None
) -> list[_Section]:
    """Return every section Docutils parses in *root*, in document order.

    The parse runs Docutils' real include directives, with *own* read as its
    planned text, so it checks the lexical composition and the planned titles
    together.  No transform runs, so a lone top section stays a section.
    """
    settings = docutils.frontend.get_default_settings(docutils.parsers.rst.Parser())
    settings.halt_level = 5
    settings.report_level = 5
    document = docutils.utils.new_document(str(root), settings)
    with _builtins_only(_planned_include(own, own_text, sphinx_src)):
        docutils.parsers.rst.Parser().parse(root_text, document)
    sections: list[_Section] = []
    for section in document.findall(docutils.nodes.section):
        depth = 1
        parent = section.parent
        while parent is not None:
            depth += isinstance(parent, docutils.nodes.section)
            parent = parent.parent
        title = section.children[0] if section.children else None
        source = getattr(title, "source", None)
        line = getattr(title, "line", None)
        sections.append((pathlib.Path(source).resolve() if isinstance(source, str) else None, line, depth))
    return sections


def _planned_sections(composition: _Composition) -> list[_Section]:
    """Return the sections the planner expects, in document order: each
    title's underline origin, and its level as Docutils ranks styles, by
    first encounter."""
    ranks: dict[tuple[str, bool], int] = {}
    sections: list[_Section] = []
    for index, style in _title_style_events(list(composition.lines)):
        origin = composition.origins[index + 1] if index + 1 < len(composition.origins) else None
        rank = ranks.setdefault(style, len(ranks) + 1)
        sections.append((origin.path, origin.reported, rank) if origin is not None else (None, None, rank))
    return sections


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
        self._texts: dict[pathlib.Path, str | None] = {}
        self._verdicts: dict[tuple[pathlib.Path, tuple[str, ...]], dict[int, str]] = {}

    def structural_sites(self, path: pathlib.Path, lines: Sequence[str]) -> list[tuple[LexicalInclude, str]]:
        """Return the structural sites of the text Docutils parses, *lines*,
        each with its probe verdict, parsing each distinct text once.  Lines
        are those of *lines*, not physical ones.  A parse that cannot be
        isolated proves nothing: every site is then unknown."""
        sites = [
            site
            for site in lexical_includes(path, text="\n".join(lines), sphinx_src=self.universe.sphinx_src)
            if site.structural
        ]
        key = (path.resolve(), tuple(lines))
        if key not in self._verdicts:
            try:
                self._verdicts[key] = _probe_sites(path, lines, sites) if sites else {}
            except RuntimeError:
                self._verdicts[key] = dict.fromkeys((site.line for site in sites), _UNKNOWN)
        verdicts = self._verdicts[key]
        return [(site, verdicts.get(site.line, _UNKNOWN)) for site in sites]

    def variant_verdicts(self, path: pathlib.Path, variant: Variant) -> dict[int, str]:
        """Return the verdict of every structural site in *path*'s effective
        input *variant*, by its parsed line there: a physical line can hold
        several sites, each with its own verdict."""
        text = self.disk_text(path)
        selection = effective_input(text, variant) if text is not None else None
        if selection is None:
            return {}
        parsed = [line for line, _index, _cut in selection]
        return {site.line: verdict for site, verdict in self.structural_sites(path, parsed)}

    def confirm_sites(self) -> None:
        """Probe every lexical site in the universe's graph, in the effective
        input it was found in, and drop those that include nothing there,
        text or rejected.  A verdict in one variant never removes a site
        from another."""
        groups: dict[tuple[pathlib.Path, Variant], pathlib.Path] = {}
        for site in self.universe.graph.sites:
            if site.structural:
                groups.setdefault((site.canonical_includer, site.variant), site.includer)
        dropped: set[tuple[pathlib.Path, Variant, int]] = set()
        for (real, variant), includer in groups.items():
            dropped.update(
                (real, variant, parsed_line)
                for parsed_line, verdict in self.variant_verdicts(includer, variant).items()
                if verdict in _NO_INCLUDE
            )
        if dropped:
            graph = self.universe.graph

            def kept(site: LexicalInclude) -> bool:
                return (site.canonical_includer, site.variant, site.parsed_line) not in dropped

            self.universe.graph = IncludeGraph(
                [site for site in graph.sites if kept(site)],
                graph.unreadable,
                [site for site in graph.unresolved if kept(site)],
                graph.scanned,
            )

    def disk_text(self, path: pathlib.Path) -> str | None:
        """Return *path*'s text as Docutils reads it, before string2lines."""
        real = path.resolve()
        if real not in self._texts:
            try:
                self._texts[real] = docutils_text(_read_source(path))
            except OSError, UnicodeError:
                self._texts[real] = None
        return self._texts[real]

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

        def text_of(path: pathlib.Path) -> str | None:
            """The text Docutils reads; the planned file's own lines are
            already as Phase 0 normalizes them, and fix writes them so."""
            return "\n".join(own_lines) if path.resolve() == own else self.disk_text(path)

        def physical_of(path: pathlib.Path) -> Sequence[str]:
            return own_lines if path.resolve() == own else (self.disk_lines(path) or [])

        def expand(path: pathlib.Path, selection: Selection, stack: tuple[tuple[object, ...], ...]) -> None:
            real = path.resolve()
            physical = physical_of(path)
            # The lines Docutils parses, from effective_input: clipped,
            # control whitespace converted, tabs expanded, as Docutils orders
            # it.  Sites are scanned in them, so one a clip or a conversion
            # creates is found (Codex's third and fourth P4 looks); their
            # lines are offsets into the selection.
            parsed = [line for line, _index, _cut in selection]
            sites = {
                site.line - 1: (site, verdict)
                for site, verdict in self.structural_sites(path, parsed)
                if verdict not in _NO_INCLUDE
            }
            offset = 0
            while offset < len(selection):
                text, index, cut = selection[offset]
                found = sites.get(offset)
                if found is None:
                    lines.append(text)
                    # Docutils numbers an inserted text from its own first line.
                    expanded = index < len(physical) and "\t" in physical[index]
                    origins.append(_Origin(real, index, cut, offset + 1, expanded))
                    offset += 1
                    continue
                relative, verdict = found
                # The physical site, for messages and identity.
                site = dataclasses.replace(relative, line=index + 1)
                if verdict != _RUN and site.indent == 0:
                    raise _UncomposableError(site, "check_rst cannot confirm that Docutils runs it")
                _check_composable(site)
                target = text_of(site.target)
                if target is None:
                    raise _UncomposableError(site, "its target cannot be read")
                options = dict(site.options)
                if tab_width(site.target_variant) is None:
                    raise _UncomposableError(site, "its :tab-width: is not a number")
                clipped = effective_input(target, site.target_variant)
                if clipped is None:
                    raise _UncomposableError(site, "its clipping options do not match its target")
                identity = (site.canonical_target, *(options.get(name) for name in _CLIP_OPTIONS))
                if identity in stack:
                    raise _UncomposableError(site, "it is part of an include cycle")
                expand(site.target, clipped, (*stack, identity))
                lines.extend(["", f'.. end of inclusion from "{site.argument}"'])
                origins.extend([None, None])
                offset = relative.block_end

        # The root is read whole at Docutils' default tab_width setting, 8.
        empty: Variant = ()
        expand(root, effective_input(text_of(root) or "", empty) or [], ((root.resolve(), None, None, None, None),))
        return _Composition(root, tuple(lines), tuple(origins))


def _style_token(style: tuple[str, bool]) -> str:
    return f"{style[0]}{'o' if style[1] else 'u'}"


@dataclasses.dataclass(frozen=True, slots=True)
class ContextPlan:
    """A file's full-mode include planning (CR-43 P4 and P5).

    *guard* names an unavailable context, *stage* judges the available
    ones, and *standalone* says whether the file's own standalone use is a
    context.  With neither, the file keeps today's standalone plan.
    """

    guard: IncludeGuard | None = None
    stage: ContextStage | None = None
    standalone: bool = True


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

    @property
    def has_standalone(self) -> bool:
        """Whether the file's own standalone use is one of its contexts."""
        return any(label == _STANDALONE for _root, label in self.roots)

    def check(self, lines: list[str], ranges: _Ranges) -> list[Finding]:
        """Return the file's structural findings judged in its contexts (P5a).

        A refusal of the plan, a conflict between the contexts, an edit
        outside the file or a composed ambiguity, is then the only finding:
        like a refused fix, a refused file has no finding that claims a fix
        (rule 4).  Otherwise each context's adornment and hierarchy findings
        on the file's own lines are mapped back to them, worded with the
        document that composes them.  Findings on another file's lines are
        that file's to report when it is checked.
        """
        _planned, refusals = self(lines, ranges)
        if refusals:
            return list(refusals)
        found: dict[tuple[str, int], Finding] = {}
        for root, _label in self.roots:
            composition = self.composer.compose(root, self.own, lines)
            if all(
                origin is not None and origin.path == self.own and not origin.partial for origin in composition.origins
            ):
                own = adornment_findings(list(lines), ranges) + hierarchy_findings(list(lines), ranges)
            else:
                composed = list(composition.lines)
                composed_ranges = self._composed_ranges(composition, ranges)
                own = []
                for finding in adornment_findings(composed, composed_ranges) + hierarchy_findings(
                    composed, composed_ranges
                ):
                    origin = composition.origins[finding.lineno - 1] if 0 < finding.lineno <= len(composed) else None
                    if origin is None or origin.path != self.own:
                        continue
                    # The file's own composed document needs no naming.
                    text = finding.text
                    if root.resolve() != self.own:
                        text = f"in the document {self._shown(root)} composes, {text}"
                    own.append(dataclasses.replace(finding, lineno=origin.index + 1, text=text))
            for finding in own:
                found.setdefault((finding.code, finding.lineno), finding)
        return sorted(found.values(), key=lambda finding: finding.lineno)

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
        recomposed = self.composer.compose(root, self.own, mapped) if mapped is not None else None
        if mapped is None or recomposed is None or list(recomposed.lines) != fixed:
            return _Outcome(
                label,
                refusal=self._finding(
                    min(start for start, _end, _new in edits) + 1,
                    f"check_rst cannot map the title edits of the document {self._shown(root)} composes back to "
                    "this file — make that document's titles consistent by hand",
                ),
            )
        if not self._parses_as_planned(root, mapped, recomposed):
            return _Outcome(
                label,
                refusal=self._finding(
                    min(start for start, _end, _new in edits) + 1,
                    f"in the document {self._shown(root)} composes, Docutils would read the planned titles as a "
                    "different section tree, so fix leaves them unchanged — edit its titles by hand in context",
                ),
            )
        return _Outcome(label, tuple(mapped))

    def _parses_as_planned(self, root: pathlib.Path, mapped: list[str], planned: _Composition) -> bool:
        """Rule 5: Docutils' own parse of the planned root has the planned
        section tree, title by title: the same source line becomes a section
        at the same depth.  A parse that fails proves nothing, so it refuses."""
        own_text = "\n".join(mapped) + "\n"
        root_text = own_text if root.resolve() == self.own else self.composer.disk_text(root)
        if root_text is None:
            return False
        try:
            parsed = _docutils_sections(root, root_text, self.own, own_text, self.composer.universe.sphinx_src)
        except Exception:  # any parser failure: the plan is unproven
            return False
        expected = _planned_sections(planned)
        return all(path is not None for path, _line, _depth in expected) and parsed == expected

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
            # A pure insertion keeps its anchor line, so only its position
            # matters: an expanded anchor is fine, a clip-cut one is not.
            rewrites = old_start < old_end
            stray = next(
                (
                    position
                    for position, origin in zip(touched, origins, strict=True)
                    if origin is None or origin.partial or (rewrites and origin.expanded) or origin.path != self.own
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
    universe: IncludeUniverse,
    composer: Composer,
    path: pathlib.Path,
    sphinx: PlanningFacts | None = None,
) -> ContextPlan:
    """Return *path*'s unavailable-context guard and its context stage.

    ``(None, None)`` keeps today's standalone plan: a file nothing includes,
    with no include of its own and no declaration, is its own only context.
    The stage judges the available contexts; the guard, when one context is
    unavailable, still refuses any edit that changes the title model.

    In verified mode, *sphinx* adds the project's facts: a document of the
    environment has a standalone context, and a project that may transform
    an include leaves only an include-free standalone context available.
    """
    real = path.resolve()
    guard = universe.unavailable_guard(path)
    graph = universe.graph
    standalone = (
        (not graph.may_be_included(real) and real not in universe.declared)
        or real in universe.standalone
        or (sphinx is not None and real in sphinx.documents)
    )
    roots, cycle = graph.root_contexts(real, standalone=universe.standalone)
    if cycle is not None:
        site = f"{universe.shown(cycle.includer)}:{cycle.line}"
        cyclic = IncludeGuard("uncomposable", site, "it is part of an include cycle", cycle)
        return ContextPlan(guard or cyclic, None, standalone)
    if (
        not roots
        and real in graph.scanned
        and not any(site.canonical_includer == real and not site.variant for site in graph.sites)
    ):
        # The graph read this file whole and found no include of its own:
        # its standalone plan stands, and the check reads it only once.
        return ContextPlan(guard, None, standalone)
    own_lines = composer.disk_lines(path)
    own_selection = effective_input("\n".join(own_lines), ()) if own_lines else None
    own_parsed = [line for line, _index, _cut in own_selection or []]
    own_includes = any(verdict not in _NO_INCLUDE for _site, verdict in composer.structural_sites(path, own_parsed))
    if not roots and not own_includes:
        return ContextPlan(guard, None, standalone)
    if sphinx is not None and sphinx.transform is not None:
        guard = guard or IncludeGuard("transformed", sphinx.transform)
        alone = [(path, _STANDALONE)] if standalone and not own_includes else []
        return ContextPlan(guard, ContextStage(composer, path, alone) if alone else None, standalone)
    candidates = [(root, universe.shown(root)) for root in roots]
    if standalone:
        candidates.append((path, _STANDALONE))
    available: list[tuple[pathlib.Path, str]] = []
    for root, label in candidates:
        try:
            composition = composer.compose(root, real, own_lines or [])
        except _UncomposableError as error:
            if guard is None:
                site = f"{universe.shown(error.site.includer)}:{error.site.line}"
                guard = IncludeGuard("uncomposable", site, error.reason, error.site)
            continue
        # A lexical root whose own path never reaches the file, through a
        # clip or an alias, is no context of it.
        if any(origin is not None and origin.path == real for origin in composition.origins):
            available.append((root, label))
    return ContextPlan(guard, ContextStage(composer, path, available) if available else None, standalone)
