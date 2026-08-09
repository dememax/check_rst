# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Word-stats, --context, --refs formatting, and diff-json — check_rst project

from __future__ import annotations

import collections
import dataclasses
import functools
import importlib.metadata
import json
import pathlib
import platform
import re
import shutil
import sys
import tempfile
from typing import TYPE_CHECKING, Any

import docutils.nodes

from check_rst import __version__

if TYPE_CHECKING:
    import sphinx.environment


from . import _helpers
from ._document import Document, build_outline
from ._formatting import (
    check_adornments,
    check_hierarchy,
    check_single_top_level,
)
from ._lint import check_directives, check_homoglyphs, check_nested_inline_markup
from ._sphinx import (
    _build_sphinx_env_checked,
    _docname_for,
    _findings_from_sphinx_output,
    _merge_toctree_clusters,
    check_bare_filenames,
    check_multiple_toctree_parents,
    find_code_blocks,
    find_incoming_references,
    find_references,
    find_toctrees,
)
from ._types import (
    AdmonitionEntry,
    BlockQuoteEntry,
    CodeBlockEntry,
    CommentEntry,
    ContextMatch,
    Finding,
    ListEntry,
    OutlineEntry,
    ReferenceEntry,
    StopwordsUnavailable,
    TableEntry,
    ToctreeEntry,
    WordStatsUnavailable,
)


def _format_references(
    path: pathlib.Path,
    outgoing: list[ReferenceEntry],
    incoming: list[ReferenceEntry],
) -> str:
    lines = [f"References: {path}", "outgoing:"]
    if outgoing:
        for e in outgoing:
            status = e.resolved if e.resolved is not None else "BROKEN"
            lines.append(f"  {e.lineno}: {e.reftype} -> {e.target} ({status})")
    else:
        lines.append("  (none)")
    lines.append("incoming:")
    if incoming:
        lines.extend(f"  {e}" for e in incoming)
    else:
        lines.append("  (none)")
    return "\n".join(lines)


def _runtime_metadata(verified: bool, word_samples: bool) -> dict[str, Any]:
    """Return versions of the runtime components that affect results."""
    sphinx_runtime: dict[str, str | None] | None = None
    if verified or word_samples:
        try:
            sphinx_version = importlib.metadata.version("Sphinx")
        except importlib.metadata.PackageNotFoundError:
            sphinx_version = None
        sphinx_runtime = {"version": sphinx_version}

    stemmer_runtime: dict[str, str | None] | None = None
    if word_samples:
        try:
            stemmer_version = importlib.metadata.version("snowballstemmer")
        except importlib.metadata.PackageNotFoundError:
            stemmer_version = None
        stemmer_runtime = {"version": stemmer_version}

    return {
        "check_rst": {"version": __version__},
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
        },
        "docutils": {"version": getattr(docutils, "__version__", None)},
        "sphinx": sphinx_runtime,
        "snowballstemmer": stemmer_runtime,
    }


def _format_runtime(metadata: dict[str, Any]) -> str:
    """Render _runtime_metadata as one concise human-readable line."""
    parts = [
        f"check_rst {metadata['check_rst']['version']}",
        f"Python {metadata['python']['version']}",
    ]
    if metadata["sphinx"] is not None:
        parts.append(f"Sphinx {metadata['sphinx']['version'] or 'unknown'}")
    parts.append(f"docutils {metadata['docutils']['version'] or 'unknown'}")
    if metadata["snowballstemmer"] is not None:
        parts.append(f"snowballstemmer {metadata['snowballstemmer']['version'] or 'unavailable'}")
    return "runtime: " + ", ".join(parts)


_WORD_TOKEN_RE = re.compile(r"\w+")


_CYRILLIC_RE = re.compile("[\u0430-\u044f\u0451]")  # lowercase Cyrillic incl. io


def _find_stopwords(mod: object, names: tuple[str, ...]) -> frozenset[str]:
    """Return the stopword set exposed on *mod* under any of *names*.

    Raises StopwordsUnavailable, never a placeholder, when none resolve
    to a non-empty set — a stat silently omitted here is a stat nobody
    notices went missing."""
    for name in names:
        found = getattr(mod, name, None)
        if found:
            return frozenset(found)
    tried = " or ".join(names)
    mod_name = getattr(mod, "__name__", repr(mod))
    raise StopwordsUnavailable(f"{mod_name} has neither {tried}")


@functools.cache
def _stopword_sets() -> dict[str, frozenset[str]]:
    """The en/ru/fr stopword lists this trilingual journal needs, from
    sphinx.search.  Kept per-language: besides filtering, the en/fr
    lists double as a deterministic language detector — whichever list
    a document's tokens hit more often is the document's Latin
    language, and picks the Latin stemmer (Max, on a downstream project's French
    page: "wrong language taken as a base for another language").

    Raises StopwordsUnavailable — never returns None — when sphinx.search
    isn't importable or its internals have moved again; see
    _find_stopwords."""
    try:
        import sphinx.search.en
        import sphinx.search.fr
        import sphinx.search.ru
    except ImportError as exc:
        raise StopwordsUnavailable(f"sphinx.search not importable: {exc}") from exc
    return {
        "en": _find_stopwords(sphinx.search.en, ("ENGLISH_STOPWORDS", "english_stopwords")),
        "ru": _find_stopwords(sphinx.search.ru, ("RUSSIAN_STOPWORDS", "russian_stopwords")),
        "fr": _find_stopwords(sphinx.search.fr, ("FRENCH_STOPWORDS", "french_stopwords")),
    }


@functools.cache
def _prose_stemmers() -> tuple[object, object, object]:
    """(cyrillic, latin, extra-french) stemmers.  The first two GROUP
    inflections — the displayed word is always a real surface form, never
    a stem; Latin routes to the English stemmer (French words group
    slightly imperfectly — a cosmetic approximation of grouping, never of
    display).  The French stemmer is the extra suppressor for the
    rare-words sibling annotation: probed on a real downstream document, the
    naive annotation was ~80% French inflections; any stemmer agreeing
    the two words are one suppresses the pair."""
    try:
        import snowballstemmer
    except ImportError as exc:
        raise WordStatsUnavailable(f"snowballstemmer not importable: {exc}") from exc
    return (
        snowballstemmer.stemmer("russian"),
        snowballstemmer.stemmer("english"),
        snowballstemmer.stemmer("french"),
    )


def _prose_word_groups(
    prose_texts: list[str],
) -> dict[str, collections.Counter[str]]:
    """Stem-grouped word counts over *prose_texts*.

    Two passes: the first counts en/fr stopword hits — the stopword lists
    doubling as a deterministic language detector — so the second can
    route Latin tokens to the RIGHT stemmer (French inflections like
    vérifie/vérifier/vérifiée group only under the French stemmer; the
    old always-English routing mis-based French documents).  Cyrillic
    always routes to Russian.  Tokens containing digits are identifier
    debris (git hashes, timestamps), excluded from all word statistics.

    Raises WordStatsUnavailable when either the stopword tables or the
    required stemmers are unavailable.
    """
    sets = _stopword_sets()
    stop = frozenset().union(*sets.values())
    kept: list[str] = []
    en_hits = 0
    fr_hits = 0
    for text in prose_texts:
        for word in _WORD_TOKEN_RE.findall(text.lower()):
            if word in sets["en"]:
                en_hits += 1
            if word in sets["fr"]:
                fr_hits += 1
            if len(word) <= 2 or word in stop or any(ch.isdigit() for ch in word):
                continue
            kept.append(word)
    stemmers = _prose_stemmers()
    groups: dict[str, collections.Counter[str]] = {}
    for word in kept:
        cyr, lat_en, lat_fr = stemmers
        lat = lat_fr if fr_hits > en_hits else lat_en
        key = (cyr if _CYRILLIC_RE.search(word) else lat).stemWord(word)  # type: ignore[attr-defined]
        groups.setdefault(key, collections.Counter())[word] += 1
    return groups


def _top_prose_words(prose_texts: list[str], n: int) -> tuple[list[tuple[str, int]], int]:
    """Return (n most frequent meaningful words, count of suppressed word
    groups beyond n) — bounded output, never silent truncation.

    Raises WordStatsUnavailable when either the stopword tables or the
    required stemmers are unavailable."""
    groups = _prose_word_groups(prose_texts)
    ranked = sorted(
        ((sum(forms.values()), forms) for forms in groups.values()),
        key=lambda item: (-item[0], item[1].most_common(1)[0][0]),
    )
    top = [(forms.most_common(1)[0][0], total) for total, forms in ranked[:n]]
    return top, max(0, len(ranked) - n)


def _one_edit_apart(a: str, b: str) -> bool:
    """True when *a* and *b* differ by exactly one edit: a substitution,
    an insertion/deletion, or an adjacent transposition — the classical
    shape of a typo.  Chosen over a similarity-ratio cutoff after the
    ratio missed a real, confessed, journal-attested mistake by 0.013:
    ratio(померял, померил) = 0.857 < the 0.87 cutoff, while the word
    occurs once against 146 correct occurrences."""
    la, lb = len(a), len(b)
    if abs(la - lb) > 1 or a == b:
        return False
    if la == lb:
        diffs = [i for i in range(la) if a[i] != b[i]]
        if len(diffs) == 1:
            return True
        return (
            len(diffs) == 2 and diffs[1] == diffs[0] + 1 and a[diffs[0]] == b[diffs[1]] and a[diffs[1]] == b[diffs[0]]
        )
    if la > lb:
        a, b = b, a  # a is the shorter
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1 :]


def _rare_prose_words(prose_texts: list[str], n: int) -> tuple[list[tuple[str, str | None, int]], int]:
    """The other extreme (Max, 2026-07-19), in its honest form: once-only
    prose words as (word, closest frequent sibling or None, sibling count)
    — the tool states the deterministic facts, the human judges typo vs
    morphology vs legitimate word.

    A MUTUAL pair — two once-words one edit apart, the small-page typo
    signature — is one symmetric fact and is reported once, as
    ``a ↔ b``, never as two reciprocal annotations (the "loop" display
    Max flagged).  Pairs sort first, then one-directional annotations
    (a rare word with a more frequent sibling one edit away —
    substitution, insertion/deletion, or adjacent transposition: the
    classical typo shape) — on a single page they are the spell-scan candidates —
    then plain once-words alphabetically.  Suppressions keep precision
    honest: identifier debris (mixed alphanumerics: git hashes,
    timestamps) is excluded, and a sibling pair unified by ANY stemmer
    (ru/en/fr) is a mere inflection, not a candidate (probed on the real
    downstream document: without this, ~80% of annotations were French
    morphology).

    Raises WordStatsUnavailable when either the stopword tables or the
    required stemmers are unavailable.
    """
    groups = _prose_word_groups(prose_texts)
    once: list[str] = []
    surfaces: dict[str, int] = {}
    for forms in groups.values():
        total = sum(forms.values())
        surface = forms.most_common(1)[0][0]
        surfaces[surface] = total
        if total == 1:  # debris already excluded at the groups level
            once.append(surface)
    stemmers = _prose_stemmers()
    annotated: list[tuple[str, str | None, int]] = []
    plain: list[tuple[str, str | None, int]] = []
    # Any other word can be the sibling — a small page's typo pair is two
    # once-words one edit apart (fameworks/frameworks, found by Max on a
    # real note); a frequency threshold on the sibling blinded exactly
    # that primary use-case.  Most frequent sibling preferred.
    by_frequency = sorted(surfaces, key=lambda w: (-surfaces[w], w))
    siblings: dict[str, str | None] = {}
    for word in sorted(once):
        sibling = next(
            (f for f in by_frequency if f != word and _one_edit_apart(word, f)),
            None,
        )
        if sibling is not None and any(
            st.stemWord(word) == st.stemWord(sibling)  # type: ignore[attr-defined]
            for st in stemmers
        ):
            sibling = None  # inflection, not a candidate
        siblings[word] = sibling
    pairs: list[tuple[str, str | None, int]] = []
    for word in sorted(once):
        sibling = siblings[word]
        if sibling is None:
            plain.append((word, None, 0))
        elif siblings.get(sibling) == word:
            if word < sibling:  # report the symmetric fact once
                pairs.append((word, sibling, surfaces[sibling]))
        else:
            annotated.append((word, sibling, surfaces[sibling]))
    ordered = pairs + annotated + plain
    return ordered[:n], max(0, len(ordered) - n)


def _docname_id(path: pathlib.Path, project_root: pathlib.Path | None = None) -> str:
    """Stable document name for section ids: path relative to the project
    root, without extension — the autosectionlabel prefix convention."""
    root = _helpers.PROJECT_ROOT if project_root is None else project_root
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return path.stem
    return str(rel.with_suffix(""))


def _json_file_model(
    document: Document,
    code_blocks: list[CodeBlockEntry],
    word_samples: int,
    outline_entries: list[OutlineEntry] | None = None,
    toctree_entries: list[ToctreeEntry] | None = None,
    project_root: pathlib.Path | None = None,
) -> dict[str, Any]:
    """The per-file document model for --json: outline with stable ids,
    code-blocks, blockquote previews, statistics.

    word_samples == 0 (default outside --verbose/--word-samples, Max,
    2026-07-20) skips top_words/rare_words entirely — null, no error —
    same "pay for what you don't use" contract as the text footer: the
    stopword/stemmer machinery is never touched unless requested.

    toctree_entries (2026-07-26): the toctree CONTAINER markers found by
    find_toctrees, reported separately under "toctrees" — the headings
    they pull in from other documents are real sections, so they are
    merged straight into "outline" instead.  Both entry kinds expose a
    nullable docname: None for this file, the source docname after crossing
    a toctree boundary."""
    docname = _docname_id(document.path, project_root)
    outline = []
    outline_id_counts: collections.Counter[str] = collections.Counter()
    for entry in outline_entries if outline_entries is not None else document.outline:
        d = dataclasses.asdict(entry)
        # A cross-file heading's own Sphinx docname (entry.docname) IS its
        # stable identifier already — never re-derived from this file's
        # own `docname`, which would collide every cross-file entry onto
        # this document's id.
        base_id = f"{entry.docname or docname}:{entry.title}"
        outline_id_counts[base_id] += 1
        occurrence = outline_id_counts[base_id]
        d["id"] = base_id if occurrence == 1 else f"{base_id}#{occurrence}"
        outline.append(d)
    toctrees = []
    for toctree_entry in toctree_entries or []:
        toctrees.append(dataclasses.asdict(toctree_entry))
    # top_words/rare_words null + word_stats_error set is an explicit,
    # typed failure signal (never a bare null with no reason) — see
    # StopwordsUnavailable.  null with word_stats_error also null means
    # "not requested", distinguishable from "requested but unavailable".
    top_words: tuple[list[tuple[str, int]], int] | None
    rare_words: tuple[list[tuple[str, str | None, int]], int] | None
    word_stats_error: str | None
    if word_samples:
        try:
            top_words = _top_prose_words([document.prose_text], word_samples)
            rare_words = _rare_prose_words([document.prose_text], word_samples)
            word_stats_error = None
        except WordStatsUnavailable as exc:
            top_words = rare_words = None
            word_stats_error = str(exc)
    else:
        top_words = rare_words = None
        word_stats_error = None
    return {
        "outline": outline,
        "toctrees": toctrees,
        "code_blocks": [dataclasses.asdict(e) for e in code_blocks],
        "block_quotes": [dataclasses.asdict(e) for e in document.block_quotes],
        "tables": [dataclasses.asdict(e) for e in document.tables],
        "admonitions": [dataclasses.asdict(e) for e in document.admonitions],
        "comments": [dataclasses.asdict(e) for e in document.comments],
        "lists": [dataclasses.asdict(e) for e in document.lists],
        "stats": {
            "lines": len(document.lines),
            "empty_lines": sum(1 for line in document.lines if not line.strip()),
            "chars": len(document.text),
            "bytes": len(document.text.encode("utf-8")),
            "spaces": document.text.count(" "),
            "chars_distinct": len(set(document.text)),
            "chars_once": [
                f"U+{ord(c):04X}" for c in sorted(ch for ch, n in collections.Counter(document.text).items() if n == 1)
            ],
            "words": len(document.text.split()),
            "words_distinct": len(set(document.text.split())),
            # (top-10 list, suppressed-count) — same no-silent-truncation
            # contract as the footer.
            "top_words": top_words,
            # ([word, sibling|null, sibling-count], suppressed) — the other
            # extreme: once-only words with the closest-frequent-sibling
            # FACT; typo-vs-morphology judgment stays human.
            "rare_words": rare_words,
            "word_stats_error": word_stats_error,
        },
    }


def _generic_entry_kind(entry: object) -> str:
    """Human-readable kind derived from a class name, with useful refinements.

    The fallback is deliberately generic: adding a new ``SomethingEntry`` to
    the outline stream automatically makes it resolvable by --context.
    """
    if isinstance(entry, OutlineEntry):
        return "section"
    if isinstance(entry, ListEntry):
        if entry.item_count is not None:
            return f"{entry.kind} list"
        return f"{entry.kind} item"
    if isinstance(entry, CodeBlockEntry):
        return "code block"
    if isinstance(entry, BlockQuoteEntry):
        return "blockquote"
    if isinstance(entry, AdmonitionEntry):
        return f"{entry.kind} admonition"
    if isinstance(entry, ToctreeEntry):
        return "toctree cycle" if entry.cycle is not None else "toctree"
    name = type(entry).__name__
    if name.endswith("Entry"):
        name = name[:-5]
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).lower()
    return words or "entry"


def _entry_slug(kind: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", kind.lower()).strip("-") or "entry"


def _entry_lineno(entry: object) -> int:
    value = getattr(entry, "lineno", 0)
    return value if isinstance(value, int) else 0


def _entry_end(entry: object) -> int:
    start = _entry_lineno(entry)
    value = getattr(entry, "end", start)
    return value if isinstance(value, int) and value >= start else start


def _entry_depth(entry: object) -> int:
    value = getattr(entry, "depth", 1)
    return value if isinstance(value, int) and value >= 1 else 1


def _entry_string_values(entry: object) -> tuple[str, ...]:
    """All non-empty string fields, generically, as semantic exact matches."""
    values: list[str] = []
    if dataclasses.is_dataclass(entry):
        for field in dataclasses.fields(entry):
            value = getattr(entry, field.name)
            if isinstance(value, str) and value:
                values.append(value)
    else:
        for value in vars(entry).values() if hasattr(entry, "__dict__") else ():
            if isinstance(value, str) and value:
                values.append(value)
    return tuple(dict.fromkeys(values))


def _context_candidates(entries: list[object], local_docname: str) -> list[ContextMatch]:
    universal_counts: collections.Counter[str] = collections.Counter()
    section_counts: collections.Counter[str] = collections.Counter()
    candidates: list[ContextMatch] = []
    for index, entry in enumerate(entries):
        explicit_docname = getattr(entry, "docname", None)
        source_docname = explicit_docname if isinstance(explicit_docname, str) and explicit_docname else local_docname
        kind = _generic_entry_kind(entry)
        universal_base = f"{source_docname}:{_entry_slug(kind)}@{_entry_lineno(entry)}"
        universal_counts[universal_base] += 1
        universal_occurrence = universal_counts[universal_base]
        universal_selector = universal_base if universal_occurrence == 1 else f"{universal_base}#{universal_occurrence}"

        selector = universal_selector
        if isinstance(entry, OutlineEntry):
            section_base = f"{source_docname}:{entry.title}"
            section_counts[section_base] += 1
            occurrence = section_counts[section_base]
            selector = section_base if occurrence == 1 else f"{section_base}#{occurrence}"

        candidates.append(
            ContextMatch(
                index=index,
                entry=entry,
                selector=selector,
                universal_selector=universal_selector,
                kind=kind,
                source_docname=source_docname,
                match_texts=_entry_string_values(entry),
            )
        )
    return candidates


def _resolve_context_matches(entries: list[object], query: str, local_docname: str) -> list[ContextMatch]:
    """Resolve an exact selector first, then exact semantic field text.

    Selector precedence matters for duplicate titles: ``doc:Title`` is the
    stable identity of the first section, while bare ``Title`` deliberately
    remains ambiguous.  No substring/fuzzy fallback may silently choose a
    structurally different entry.
    """
    candidates = _context_candidates(entries, local_docname)
    by_selector = [candidate for candidate in candidates if query in (candidate.selector, candidate.universal_selector)]
    if by_selector:
        return by_selector
    return [candidate for candidate in candidates if query in candidate.match_texts]


def _context_relationships(
    candidates: list[ContextMatch], selected: ContextMatch
) -> tuple[
    ContextMatch | None,
    ContextMatch | None,
    ContextMatch | None,
    list[ContextMatch],
    list[ContextMatch],
]:
    """Return parent, previous/next sibling, direct children, and full path."""
    parents: dict[int, int | None] = {}
    children: dict[int | None, list[int]] = collections.defaultdict(list)
    stack: list[int] = []
    for candidate in candidates:
        depth = _entry_depth(candidate.entry)
        while stack and _entry_depth(candidates[stack[-1]].entry) >= depth:
            stack.pop()
        parent_index = stack[-1] if stack else None
        parents[candidate.index] = parent_index
        children[parent_index].append(candidate.index)
        stack.append(candidate.index)

    parent_index = parents[selected.index]
    parent = candidates[parent_index] if parent_index is not None else None
    sibling_indices = children[parent_index]
    position = sibling_indices.index(selected.index)
    previous = candidates[sibling_indices[position - 1]] if position else None
    following = candidates[sibling_indices[position + 1]] if position + 1 < len(sibling_indices) else None
    direct_children = [candidates[index] for index in children[selected.index]]

    path: list[ContextMatch] = []
    cursor: int | None = selected.index
    while cursor is not None:
        path.append(candidates[cursor])
        cursor = parents[cursor]
    path.reverse()
    return parent, previous, following, direct_children, path


def _context_entry_label(candidate: ContextMatch) -> str:
    entry = candidate.entry
    if isinstance(entry, OutlineEntry):
        return f'section "{entry.title}"'
    if isinstance(entry, ListEntry):
        if entry.item_count is not None:
            plural = "s" if entry.item_count != 1 else ""
            return f"{entry.kind} list ({entry.marker!r}, {entry.item_count} item{plural})"
        text = entry.marker if entry.kind == "definition" else entry.preview
        return f'{candidate.kind} "{text}"'
    if isinstance(entry, CodeBlockEntry):
        language = entry.language or "no language"
        suffix = f': "{entry.preview}"' if entry.preview else ""
        return f"code block ({language}){suffix}"
    if isinstance(entry, BlockQuoteEntry):
        return f'blockquote "{entry.preview}"'
    if isinstance(entry, TableEntry):
        title = entry.caption or entry.preview
        return f'table "{title}"' if title else "table"
    if isinstance(entry, AdmonitionEntry):
        title = entry.title or entry.preview
        return f'{candidate.kind} "{title}"' if title else candidate.kind
    if isinstance(entry, CommentEntry):
        return f'comment "{entry.preview}"'
    if isinstance(entry, ToctreeEntry):
        return str(entry).strip().split(": ", 1)[-1]
    values = _entry_string_values(entry)
    return f'{candidate.kind} "{values[0]}"' if values else candidate.kind


def _context_candidate_line(candidate: ContextMatch) -> str:
    start = _entry_lineno(candidate.entry)
    end = _entry_end(candidate.entry)
    extent = f"{start}-{end}" if end > start else str(start)
    return f"{candidate.selector} — {_context_entry_label(candidate)} — {extent}"


def _context_findings(document: Document) -> list[Finding]:
    """Phase 0/1 findings available without turning the query into a build."""
    findings = list(document.hygiene)
    findings.extend(check_adornments(document.path, True, doc=document))
    findings.extend(check_hierarchy(document.path, doc=document))
    findings.extend(check_single_top_level(document.path, doc=document))
    findings.extend(check_nested_inline_markup(document.path, True, doc=document))
    findings.extend(check_directives(document.path, True, True, doc=document))
    findings.extend(check_homoglyphs(document.path, doc=document))
    return list(dict.fromkeys(findings))


def _bounded_context_lines(lines: list[str], limit: int = 20) -> list[str]:
    shown = lines[:limit]
    hidden = len(lines) - len(shown)
    if hidden:
        shown.append(f"({hidden} more suppressed)")
    return shown


def _format_context(
    source_path: pathlib.Path,
    query: str,
    candidates: list[ContextMatch],
    selected: ContextMatch,
    findings: list[Finding],
    outgoing: list[ReferenceEntry] | None,
    incoming: list[ReferenceEntry] | None,
) -> str:
    parent, previous, following, children, path = _context_relationships(candidates, selected)
    start = _entry_lineno(selected.entry)
    end = _entry_end(selected.entry)
    extent = f"{start}-{end}" if end > start else str(start)
    applicable = [f for f in findings if f.lineno == 0 or start <= f.lineno <= end]

    lines = [
        f"Context: {source_path}",
        f"query: {query!r}",
        "entry:",
        f"  selector: {selected.selector}",
        f"  kind: {selected.kind}",
        f"  range: {extent}",
        f"  depth: {_entry_depth(selected.entry)}",
        f"  summary: {_context_entry_label(selected)}",
        "path:",
    ]
    lines.extend(f"  {_context_candidate_line(item)}" for item in path)
    lines.append(f"parent: {_context_candidate_line(parent)}" if parent is not None else "parent: (none)")
    lines.append("siblings:")
    lines.append(f"  previous: {_context_candidate_line(previous)}" if previous is not None else "  previous: (none)")
    lines.append(f"  next: {_context_candidate_line(following)}" if following is not None else "  next: (none)")
    lines.append("children:")
    if children:
        child_lines = [_context_candidate_line(child) for child in children]
        lines.extend(f"  {line}" for line in _bounded_context_lines(child_lines))
    else:
        lines.append("  (none)")

    lines.append("findings:")
    if applicable:
        lines.extend(f"  {finding.lineno}: {finding.severity}: {finding.text}" for finding in applicable)
    else:
        lines.append("  (none in selected range)")

    lines.append("references:")
    if outgoing is None or incoming is None:
        lines.append("  unavailable — verified Sphinx mode required")
    else:
        scoped_outgoing = [e for e in outgoing if start <= e.lineno <= end]
        lines.append("  outgoing (selected range):")
        if scoped_outgoing:
            formatted = [
                f"{e.lineno}: {e.reftype} -> {e.target} ({e.resolved if e.resolved is not None else 'BROKEN'})"
                for e in scoped_outgoing
            ]
            lines.extend(f"    {line}" for line in _bounded_context_lines(formatted))
        else:
            lines.append("    (none)")
        lines.append("  incoming (document-level):")
        if incoming:
            lines.extend(f"    {line}" for line in _bounded_context_lines([str(entry) for entry in incoming]))
        else:
            lines.append("    (none)")
    return "\n".join(lines)


def _format_context_candidates(
    path: pathlib.Path,
    query: str,
    candidates: list[ContextMatch],
    matches: list[ContextMatch],
) -> str:
    lines = [
        f"check_rst: {path}: --context {query!r} is ambiguous: {len(matches)} exact matches",
        "candidates:",
    ]
    candidate_limit = 20
    for match in matches[:candidate_limit]:
        _parent, _previous, _following, _children, entry_path = _context_relationships(candidates, match)
        path_text = " > ".join(item.selector for item in entry_path)
        lines.append(f"  {_context_candidate_line(match)} — path: {path_text}")
    hidden = len(matches) - candidate_limit
    if hidden > 0:
        lines.append(f"  ({hidden} more candidates suppressed)")
    return "\n".join(lines)


def _run_context_query(
    query: str,
    path: pathlib.Path,
    project_root: pathlib.Path,
    sphinx_src: pathlib.Path | None,
    build_dir: pathlib.Path | None,
    no_toctree: bool,
) -> int:
    """Run the self-contained, read-only --context query."""
    try:
        document = Document(path, project_root)
        _ = document.doctree
    except UnicodeDecodeError as exc:
        line = exc.object.count(b"\n", 0, exc.start) + 1
        print(f"check_rst: {path}:{line}: not valid UTF-8 ({exc.reason})")
        return 1

    env: sphinx.environment.BuildEnvironment | None = None
    sphinx_findings: list[Finding] = []
    keep_build = build_dir is not None
    actual_build_dir = (
        build_dir if build_dir is not None else pathlib.Path(tempfile.mkdtemp(prefix="check_rst_context_"))
    )
    try:
        if sphinx_src is None:
            local_docname = _docname_id(path, project_root)
            code_blocks = document.code_blocks_heuristic
            outline = document.outline
            clusters: list[list[ToctreeEntry | OutlineEntry]] = []
        else:
            env, warning_text = _build_sphinx_env_checked(sphinx_src, actual_build_dir, files=[path])
            local = _docname_for(env, path)
            if local is None:
                print(f"check_rst: {path}: not part of the --sphinx-src project")
                return 1
            local_docname = local
            code_blocks = find_code_blocks(env, local_docname, document.lines)
            outline = build_outline(path, doc=document, doctree=env.get_doctree(local_docname))
            clusters = [] if no_toctree else find_toctrees(env, local_docname, document)
            sphinx_findings.extend(_findings_from_sphinx_output(warning_text, [path], project_root))
            sphinx_findings.extend(check_bare_filenames(env, local_docname, document))
            sphinx_findings.extend(check_multiple_toctree_parents(env, [path]))

        local_entries: list[
            OutlineEntry | CodeBlockEntry | BlockQuoteEntry | TableEntry | AdmonitionEntry | CommentEntry | ListEntry
        ] = sorted(
            [
                *outline,
                *code_blocks,
                *document.block_quotes,
                *document.tables,
                *document.admonitions,
                *document.comments,
                *document.lists,
            ],
            key=_entry_lineno,
        )
        entries: list[object] = []
        if clusters:
            entries.extend(_merge_toctree_clusters(local_entries, clusters))
        else:
            entries.extend(local_entries)
        candidates = _context_candidates(entries, local_docname)
        matches = _resolve_context_matches(entries, query, local_docname)
        if not matches:
            print(f"check_rst: {path}: no exact entry match for {query!r}\nhint: inspect selectors with outline {path}")
            return 1
        if len(matches) > 1:
            print(_format_context_candidates(path, query, candidates, matches))
            return 1

        selected = matches[0]
        source_path = path
        selected_document = document
        if env is not None and selected.source_docname != local_docname:
            source_path = pathlib.Path(env.doc2path(selected.source_docname))
            selected_document = Document(source_path, project_root)
            sphinx_findings = _findings_from_sphinx_output(warning_text, [source_path], project_root)
            sphinx_findings.extend(check_bare_filenames(env, selected.source_docname, selected_document))
            sphinx_findings.extend(check_multiple_toctree_parents(env, [source_path]))

        findings = _context_findings(selected_document) + sphinx_findings
        outgoing = find_references(env, selected.source_docname) if env is not None else None
        incoming = find_incoming_references(env, selected.source_docname) if env is not None else None
        print(
            _format_context(
                source_path,
                query,
                candidates,
                selected,
                list(dict.fromkeys(findings)),
                outgoing,
                incoming,
            )
        )
        return 0
    finally:
        if not keep_build:
            shutil.rmtree(actual_build_dir, ignore_errors=True)


def _load_json_dump(path: pathlib.Path) -> dict[str, Any]:
    """Load and validate one check_rst ``--json`` dump for ``--diff-json``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"check_rst: {path}: {exc.strerror}")
        raise SystemExit(1) from exc
    except UnicodeError as exc:
        print(f"check_rst: {path}: not valid UTF-8: {exc}")
        raise SystemExit(1) from exc
    except json.JSONDecodeError as exc:
        print(f"check_rst: {path}: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")
        raise SystemExit(1) from exc

    if not isinstance(data, dict):
        print(f"check_rst: {path}: top level must be an object")
        raise SystemExit(1)
    for key in ("files", "summary"):
        if key not in data:
            print(f"check_rst: {path}: missing required key {key!r}")
            raise SystemExit(1)
    if not isinstance(data["files"], list):
        print(f"check_rst: {path}: 'files' must be an array")
        raise SystemExit(1)
    if not isinstance(data["summary"], dict):
        print(f"check_rst: {path}: 'summary' must be an object")
        raise SystemExit(1)

    summary = data["summary"]
    for key in ("files_checked", "errors", "warnings"):
        if key not in summary:
            print(f"check_rst: {path}: summary missing {key!r}")
            raise SystemExit(1)
        if not isinstance(summary[key], int) or isinstance(summary[key], bool):
            print(f"check_rst: {path}: summary {key!r} must be an integer")
            raise SystemExit(1)

    for i, file_record in enumerate(data["files"]):
        if not isinstance(file_record, dict):
            print(f"check_rst: {path}: files[{i}] must be an object")
            raise SystemExit(1)
        for key in ("path", "outline", "findings"):
            if key not in file_record:
                print(f"check_rst: {path}: files[{i}] missing {key!r}")
                raise SystemExit(1)
        if not isinstance(file_record["path"], str):
            print(f"check_rst: {path}: files[{i}].path must be a string")
            raise SystemExit(1)
        if not isinstance(file_record["outline"], list):
            print(f"check_rst: {path}: files[{i}].outline must be an array")
            raise SystemExit(1)
        if not isinstance(file_record["findings"], list):
            print(f"check_rst: {path}: files[{i}].findings must be an array")
            raise SystemExit(1)

    return data


def _diff_json_dumps(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Structured semantic diff between two --json dumps (--diff-json).

    Logged 2026-07-18, independently re-confirmed 2026-07-21 by a real
    downstream-project session: "several times this session I rewrote a whole file...
    and had to manually eyeball 'same warning count, same categories as
    before' rather than get a machine answer."

    Matches files by path, outline entries by their stable
    'docname:title' id (built for exactly this — see _json_file_model),
    findings by (severity, text).  Deliberately NOT by line number: an
    unrelated earlier edit shifts every line after it, which would
    otherwise show every surviving finding as both resolved and added.
    """
    provenance_keys = ("schema_version", "mode", "runtime")
    provenance_changed = [key for key in provenance_keys if old.get(key) != new.get(key)]

    old_files = {f["path"]: f for f in old.get("files", [])}
    new_files = {f["path"]: f for f in new.get("files", [])}

    def summary_delta(key: str) -> dict[str, int]:
        o = old.get("summary", {}).get(key, 0)
        n = new.get("summary", {}).get(key, 0)
        return {"old": o, "new": n, "delta": n - o}

    summary = {k: summary_delta(k) for k in ("files_checked", "errors", "warnings")}

    files_diff: dict[str, Any] = {}
    for path in sorted(set(old_files) | set(new_files)):
        if path not in new_files:
            files_diff[path] = {"status": "removed"}
            continue
        if path not in old_files:
            files_diff[path] = {"status": "added"}
            continue
        o, n = old_files[path], new_files[path]
        old_outline = {e["id"]: e for e in o.get("outline", [])}
        new_outline = {e["id"]: e for e in n.get("outline", [])}
        added_ids = sorted(set(new_outline) - set(old_outline))
        removed_ids = sorted(set(old_outline) - set(new_outline))
        changed_ids = sorted(
            oid
            for oid in (set(old_outline) & set(new_outline))
            if (old_outline[oid]["depth"], old_outline[oid]["char"])
            != (new_outline[oid]["depth"], new_outline[oid]["char"])
        )

        def finding_key(f: dict[str, Any]) -> tuple[str, str]:
            return (f["severity"], f["text"])

        old_findings = collections.Counter(finding_key(f) for f in o.get("findings", []))
        new_findings = collections.Counter(finding_key(f) for f in n.get("findings", []))
        added_findings = list((new_findings - old_findings).elements())
        resolved_findings = list((old_findings - new_findings).elements())

        changed = bool(added_ids or removed_ids or changed_ids or added_findings or resolved_findings)
        files_diff[path] = {
            "status": "changed" if changed else "unchanged",
            "outline": {
                "added": added_ids,
                "removed": removed_ids,
                "hierarchy_changed": changed_ids,
            },
            "findings": {
                "added": [{"severity": s, "text": t} for s, t in added_findings],
                "resolved": [{"severity": s, "text": t} for s, t in resolved_findings],
            },
        }

    def sphinx_finding_key(finding: dict[str, Any]) -> tuple[str, str]:
        return (finding["severity"], finding["text"])

    old_sphinx = collections.Counter(sphinx_finding_key(finding) for finding in old.get("sphinx_findings", []))
    new_sphinx = collections.Counter(sphinx_finding_key(finding) for finding in new.get("sphinx_findings", []))
    added_sphinx = list((new_sphinx - old_sphinx).elements())
    resolved_sphinx = list((old_sphinx - new_sphinx).elements())
    return {
        "provenance": {
            "changed": provenance_changed,
            "old": {key: old.get(key) for key in provenance_keys},
            "new": {key: new.get(key) for key in provenance_keys},
        },
        "summary": summary,
        "files": files_diff,
        "sphinx_findings": {
            "added": [{"severity": severity, "text": text} for severity, text in added_sphinx],
            "resolved": [{"severity": severity, "text": text} for severity, text in resolved_sphinx],
        },
    }


def _format_json_diff(diff: dict[str, Any]) -> str:
    """Render _diff_json_dumps' structured result as a --diff-json report."""
    lines = ["Summary:"]
    provenance = diff.get("provenance", {})
    if provenance.get("changed"):
        lines.append("  WARNING: comparison provenance differs: " + ", ".join(provenance["changed"]))
    for key, d in diff["summary"].items():
        sign = "+" if d["delta"] > 0 else ""
        lines.append(f"  {key}: {d['old']} -> {d['new']} ({sign}{d['delta']})")

    sphinx_findings = diff.get("sphinx_findings", {})
    added_sphinx = sphinx_findings.get("added", [])
    resolved_sphinx = sphinx_findings.get("resolved", [])
    if added_sphinx or resolved_sphinx:
        lines.append(f"Sphinx findings: +{len(added_sphinx)} added, -{len(resolved_sphinx)} resolved")
        lines.extend(f"  + {finding['severity']}: {finding['text']}" for finding in added_sphinx)
        lines.extend(f"  - {finding['severity']}: {finding['text']}" for finding in resolved_sphinx)

    for path, fd in diff["files"].items():
        status = fd["status"]
        if status in ("added", "removed", "unchanged"):
            lines.append(f"\n{path}: {status}")
            continue

        lines.append(f"\n{path}: changed")
        outline = fd["outline"]
        if outline["added"] or outline["removed"] or outline["hierarchy_changed"]:
            parts = []
            if outline["added"]:
                parts.append(f"+{len(outline['added'])} section(s)")
            if outline["removed"]:
                parts.append(f"-{len(outline['removed'])} section(s)")
            parts.append(
                f"hierarchy changed: {', '.join(outline['hierarchy_changed'])}"
                if outline["hierarchy_changed"]
                else "hierarchy unchanged"
            )
            lines.append(f"  outline: {', '.join(parts)}")
            for oid in outline["added"]:
                lines.append(f"    + {oid}")
            for oid in outline["removed"]:
                lines.append(f"    - {oid}")

        findings = fd["findings"]
        if findings["added"] or findings["resolved"]:
            lines.append(f"  findings: +{len(findings['added'])} added, -{len(findings['resolved'])} resolved")
            for f in findings["added"]:
                lines.append(f"    + {f['severity']}: {f['text']}")
            for f in findings["resolved"]:
                lines.append(f"    - {f['severity']}: {f['text']}")
    return "\n".join(lines)
