.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Current status and retained design history — check_rst project

############################################
Roadmap: current status and design history
############################################

Seeded 2026-07-18 from external AI reviews and extended whenever real usage
produced new evidence.  The running design record below deliberately preserves
the motivation, rejected forks, former CLI spellings, and implementation-time
measurements that explain how a decision was reached.  Those historical facts
are not the current interface or status ledger.

The implementation, tests, current CLI help, and normative documentation are
the authority for what exists.  The status index below summarizes that evidence
as of 2026-08-12.  When later evidence changes an entry, update its status here
and its own ``Current status`` line while retaining the dated design history.

****************
Current status
****************

=================================
Shipped / implementation record
=================================

The following capabilities are implemented and protected by tests:

* JSON document model (current interface: ``check --format=json``).
* "Did you mean" reference suggestions; ``refs``; and ``context``.
* Blockquote, code-block, table, admonition, comment, and list entries in
  ``outline``; table identification; structure-only ``outline``; and
  ``--sections-only``.
* Per-repository configuration.
* Short underline-only title recognition, parsed composition provenance,
  effective single-title enforcement, homoglyph detection, missing document or
  local-asset integration, and nested-inline detection.
* ``diff-json`` section/finding comparison.
* Trailing-whitespace normalization, opt-in blank-line normalization, and
  opt-in title/prose spacing policies.
* Footer statistics, top/rare prose words, entry ranges, outline enrichment,
  the summary/``--quiet`` contract, and ``--max-output-lines``.
* ``fix --fast``/``diff --fast``, single-colon directive lint, the standing
  combined-Sphinx black-box fixture, recursive toctree outlines, the subcommand
  CLI, and the ``list-table`` transformation.
* The self-contained ``hierarchy`` verb, shipped independently on 2026-08-09
  and documented in :doc:`guide`; it has no separate historical proposal below.

==================
Agreed next work
==================

Three concrete capabilities remain agreed but unimplemented:

* ``list-targets [PATTERN]``.
* Table-column queries.
* A consolidated edit-validation cycle.

============================================
Deferred, awaiting evidence, or not queued
============================================

These entries are intentionally not presented as one uniform priority:

* Indentation normalization — awaiting frequency evidence.
* Documentation smells — candidate family awaiting separate triage.
* Semantic-diff coverage below sections — accepted extension, deferred.
* Configurable outline-preview length — logged, not implemented.
* Structure-aware list-to-section transformation — accepted, deferred.
* Native Markdown parsing — deferred; the documented Pandoc bridge may remain
  sufficient.
* Foreign-adornment configuration — deferred with its original urgency gone.
* Diff-hunk classification — logged from one workaround, not queued.

==========
Declined
==========

Grid-table auto-alignment, similarity-ranked hierarchy suggestions, cross-page
content consistency, navigation/search, raw Phase 0 min/max-frequency display,
and splitting ``_helpers.py`` without a stronger trigger remain declined.  The
last decision's quantitative snapshot is refreshed in its own entry below.

**********************************
Original agreed-direction record
**********************************

A read-only ``Document`` facade — one normalization and one scan per
file, checkers consume the object, fixers keep the mutating buffer —
with machine-readable output on top.  Staged plan, each stage
separately shippable:

=========================
The JSON document model
=========================

*Current status: shipped 2026-07-19; exposed as* ``check --format=json``
*since the 2026-08-07 subcommand redesign.*

A read-only ``Document`` facade — one object per file holding the normalized
text, lines, hygiene findings, doctree, outline, quotes and diff ranges,
computed at most once and shared by every checker (the one-read/one-parse
contract is pinned by ``CALL_COUNTS`` assertions, not wall-clock; fixers keep
their mutating buffer, and a fresh Document after ``fix`` writes makes
invalidation explicit in the object lifetime).  ``check --format=json`` dumps the model:
per-file findings, outline with stable ``docname:title`` ids (the
autosectionlabel prefix convention), code-blocks, blockquote previews,
statistics, and the run summary — one JSON object on stdout, nothing else, exit
code semantics unchanged; read-only, so not combinable with mutation or diff
output.

========================
Reference intelligence
========================

Current status: mixed. Suggestions and ``refs`` are shipped;
``list-targets`` is agreed next work.

Derived from the Phase 2 in-process Sphinx environment (*not* from parsing
``objects.inv`` — that artifact needs a completed HTML build and holds less
than the live ``env`` already in hand).  Three parts, staged separately (Max:
"did you mean" first):

----------------------------
"Did you mean" suggestions
----------------------------

*Current status: shipped 2026-07-22.*

Attached to a broken ``:doc:``/``:ref:`` finding, wherever it surfaces (Phase
2's own in-process build or Phase 3's ``sphinx-build`` subprocess — both
produce the identical message shape).  The target named in the WARNING is
matched against ``env.found_docs``/``env.domaindata['std']['anonlabels']`` with
``difflib.get_close_matches`` (cutoff 0.6); a close candidate appends `` — did
you mean: 'x', 'y'?`` to the finding's own text, no suggestion when nothing is
close enough.  Kills the guess-and-wait loop the contract otherwise leaves to a
human/AI on a typo'd cross-reference target.

----------------------------
``list-targets [PATTERN]``
----------------------------

*Current status: agreed next work; not implemented.*

A deterministic menu of valid ``:ref:``/``:doc:`` targets.  This repo alone has
7396 ``:ref:`` labels (autosectionlabel puts one on every heading) and 1444
``:doc:`` targets, so an unfiltered dump is unusable; agreed shape (Max) is
optional ``PATTERN`` (case-insensitive substring over id + title) and, when
omitted, print up to a cap then report the suppressed count — the same "never
silent truncation" contract ``--word-samples`` already uses for top/rare prose
words. Under the subcommand CLI (below) this is a project-wide, read-only
verb — ``--config``/``--sphinx-src``/``--build-dir`` apply as the global
options they already are, but the shape is otherwise new: an optional
positional ``PATTERN`` with no required file at all, unlike any of the
shapes already built (``full``, ``fast``, ``single-file`` all need at least
one file argument).

---------------
``refs FILE``
---------------

*Current status: shipped 2026-07-22; toctrees added 2026-07-25; renamed from*
``--refs`` *on 2026-08-07.*

Per-file incoming/outgoing reference reports (for this Journal: "which
aggregation pages point at this calendar note").  Outgoing scans *FILE*'s own
doctree for both ``sphinx.addnodes.pending_xref`` nodes — the raw,
still-unresolved ``:doc:``/``:ref:``/``:term:`` target an author wrote — and
``toctree`` nodes' resolved ``includefiles`` (including each glob expansion).
Incoming runs that combined scan once per document across the whole project
(confirmed by direct probe: ~2.6s across all 1444 documents), keeping whatever
resolves to *FILE*'s own docname.  Role target resolution reuses Sphinx's own
logic exactly — ``sphinx.util.docname_join`` for ``:doc:``,
``env.domaindata['std']['anonlabels']`` for ``:ref:``/``:term:`` — so a
reference this reports as resolved is exactly one Phase 3 would accept.  A
self-contained mode, same family as ``diff-json``.

========================
``context ENTRY FILE``
========================

*Current status: shipped 2026-07-28; renamed from* ``--context`` *on
2026-08-07.*

A targeted pre-edit briefing for ANY entry in the resolved document model, not
only a section.  Selection consumes the same heterogeneous entry stream as
``outline``; generic dataclass-field matching and a generated
``docname:kind@line`` selector mean future entry classes and anonymous
containers work without registration in the resolver.  Stable section ids take
precedence, then exact title/term/caption/preview values.  A unique match
reports range, kind, enclosing section/container path, parent, adjacent
siblings, direct children, applicable findings, range-scoped outgoing
references, and document-level incoming references.  Multiple exact matches
never guess: up to 20 compact candidates expose their selector, kind, path, and
range, followed by an explicit suppressed count. Proven first on the roadmap
item that specified it: the new command resolved this numbered-list leaf at
lines 75–88 and returned its parent list, previous/next roadmap items,
findings, and reference context without raw-markup grep.  This composes stages
1 and 2 and closes the gap where ``--sections-only`` hides leaf structure while
a complete outline is too large for a targeted query.

=====================================
Blockquote entries in ``--outline``
=====================================

*Current status: shipped 2026-07-18.*

(Max).  Since the blockquote exemption, quote zones are semantically
significant: they explain why no bold/rubric warnings fire there, and they show
composition — a note that is 80% quotation reads differently from one that is
80% original prose.  Each entry carries an ellipsis-truncated preview of the
quote's beginning (Max: a quick view in the structure); nested quotes report
once via the outer entry; bare Docutils, so both outline display modes are served by
the same function.

=============================
Per-repo configuration file
=============================

*Current status: shipped 2026-07-18.*

(Max) — ``.check_rst.toml`` (dedicated file wins) or ``pyproject.toml
[tool.check_rst]``, in the spirit of ``.clang-format``/``.prettierrc``: holds
``sphinx-src`` and ``build-dir`` so invocations stop carrying the long options.
This does NOT violate the never-auto-detect principle: a checked-in config is
an explicit, versioned statement of a project fact — not a guess.  The honesty
conditions all shipped: automatic discovery at the working directory only (no
parent-walking), explicit ``--config FILE`` selection from elsewhere,
config-relative values and bare Git scope, applied values echoed (``config:
.check_rst.toml — sphinx-src=., …``), CLI flags always override (an overridden
path is not applied or existence-checked), and unknown keys fail loudly — a
silently ignored typo would be worse than no config. The Journal now carries
its own; the 3-step loop became three bare commands, and the always-loaded
instruction layers shrank exactly as predicted.

===============
Table queries
===============

*Current status: agreed next work. Table identification is shipped; column
extraction is not.*

"give me column 2 of table 'VCS comparison'". A ``list-table`` linearizes a 2-D
structure row-major (A1, A2, A3, B1, B2, B3, …); recovering a column is stride
arithmetic over a long item stream — exactly the reshaping LLMs lose sync on,
and docutils has already undone it (every table syntax normalizes to the same
2-D ``table`` node; verified by probe, 2026-07-18).  Identification by the
caption text after ``.. list-table::``, with line-number/ordinal fallback for
uncaptioned tables and a loud error on duplicate captions.  Read-only: writing
a new column stays with the AI, but the query gives it self-verification —
edit, then read the column back.  Needs only a bare docutils parse, so it can
ship independently of stages 1–3.  **Table identification itself landed
2026-07-20** in "Table entries in ``--outline``" below
(``kind``/dims/caption/preview in ``--outline``) — the column-extraction query
proper is still open.

=======================
A structure-only view
=======================

*Current status: shipped 2026-07-18. The original* ``--outline-only`` *mode
became structure-only* ``outline`` *by default on 2026-08-07.*

(assessment finding on a real foreign document): "just show me the outline" of
an error-heavy file took four stacked flags (``--quiet --skip-fixable
--no-warnings --outline``) — and collided with the "never suppress with
--no-warnings" rule, written for the validation loop but stated unscoped.
Initially resolved by both proposed means: ``--outline-only`` (a display
filter — findings still counted in the footer, exit code honest, per "trims
display, never information") and a rule rewording scoped to the validation
loop.  The subcommand redesign then made that structure-only view the default
``outline`` behavior; ``--with-findings`` now layers findings back on.

============================================================
Code-block previews, no-quote language, and outline totals
============================================================

*Current status: shipped 2026-07-20.*

(Max) — extends the "Blockquote entries in ``--outline``" preview contract to
code-blocks: every code-block now carries a preview of its own content,
collapsed and truncated exactly like blockquote's, and the language loses the
``repr()`` quotes
(``code-block (python)``, not ``code-block ('python')``) that were pure
interpreter artifact, never RST syntax.  The ``levels:`` legend gained a
plain-sum total section count, and a new ``blocks:`` line totals
code-blocks/blockquotes/tables document-wide (see "Table entries in
``--outline``"), shown only when the document has any.  Every section's
bracketed subsection count also gained
cumulative code-block/blockquote/table counts for its whole subtree, including
nested subsections' own content — a deliberate choice over
direct-children-only: whole- subtree answers "how much is under this heading"
more usefully and is simpler to compute from the already-sorted, already-flat
entry list.  Blockquote's own preview bound moved from 60 characters/``…`` to
74/``...``, unifying it with code-block's new one.

================================
Table entries in ``--outline``
================================

*Current status: shipped 2026-07-20.*

(Max) — a third entry kind alongside code-blocks and blockquotes, listing every
table with its syntax ``kind`` (``grid``/``simple``/``table``/
``list``/``csv``), rows-x-cols dimensions, caption when present, and a preview
chaining every row's cells in document order (header row first) — the same
collapse/truncate contract as "Code-block previews, no-quote language, and
outline totals", over the *whole* table, not just its header.  A real Sphinx
build adds no trace of which syntax produced a table —
confirmed directly: grid tables, simple tables, and the
table/list-table/csv-table directives all produce the identical
``<table><tgroup>`` doctree shape — so ``kind`` is recovered by scanning the
raw source; bare docutils, no verified/heuristic split (unlike code-blocks,
which do need one). This is groundwork for the still-open "Table queries" idea
(the same row/kind facts a column query would need), not the query itself.

=====================================
Admonition entries in ``--outline``
=====================================

*Current status: shipped 2026-07-22.*

A fourth entry kind, found live: a ``.. important::`` tl;dr this very page
carries (see the top of this page) was completely invisible to ``--outline``,
even though docutils parsed it correctly all along (confirmed by direct probe:
``docutils.nodes.important`` at the exact line, simply no corresponding outline
entry kind to report it). ``docutils.nodes.Admonition`` covers all 10 kinds
uniformly (``attention``/``caution``/``danger``/``error``/``hint``/
``important``/``note``/``tip``/``warning``, plus the generic ``admonition``) —
bare docutils, no verified/heuristic split, same as blockquotes and tables
(Max: "they can have titles! Yes, it's like a table with caption, but the
content too as a snippet") — only the generic form carries an explicit title,
the other nine never do.  Counted in the ``blocks:`` legend and every section's
cumulative bracket count alongside code-blocks/blockquotes/tables (Max: "we
need to include them in the statistics: total, by section").

==================================
Comment entries in ``--outline``
==================================

*Current status: shipped 2026-07-22.*

A fifth entry kind, closing the mistyped-directive lint's blind spot
generically (Max: "we cannot cover all cases... they could be more complex
cases").  Every comment, not only ones matching a known directive name, is now
visible; ``suspicious`` reuses the Phase 1 lint's own heuristic so a flagged
comment's text and its WARNING sit in the same place instead of two
disconnected reports.  Bare docutils, no verified/heuristic split, same as
blockquotes/ admonitions/tables.

======================================
A consolidated edit-validation cycle
======================================

*Current status: agreed next work since 2026-07-29; not implemented.*

Expose one command (working name ``--edit-cycle``) that performs the existing
``check --skip-fixable`` → ``fix --fast`` → final-validation contract while reusing work
that applies to the same immutable input state.  Before ``--fix-only`` existed,
the list-to-section edit on this page measured 15.9 s, 15.6 s, and 15.1 s for
``check --skip-fixable``, ordinary ``fix``, and final validation — about 47 seconds
in three near-identical Sphinx builds before the separate 17.3-second outline
verification.  The current ``fix --fast`` has since removed the middle build.  A combined
command could still reuse the first verified state when the mutation plan is
empty; a real mutation necessarily invalidates it and requires one post-fix
build.  The command must retain explicit stage-labelled results, the final
honest exit status, Git-scope enforcement, and the rule that fixes are always
followed by validation; this is execution reuse, not a weaker workflow.  No
cache may silently cross an input-state boundary.

***********************************
Original accepted/deferred record
***********************************

=======================================================================
``_first_appearance_adornments`` blind to short underline-only titles
=======================================================================

*Current status: shipped 2026-07-21.*

(Max, 2026-07-20, initially reported — wrongly — as a Sphinx incremental-build
caching reliability question; reevaluated and corrected 2026-07-21 once a
clean, non-contaminated repro was built).  The real cause: the hierarchy scan
only recognized full overline+title+underline blocks, so a genuine but SHORT
title (below ``iter_underline_only``'s own ``MIN_UNDERLINE_ONLY_LEN=4`` floor,
never yet promoted to a full block — "Doc" underlined with three ``#``, say)
was entirely invisible to it.  The remap then "corrected" a later,
correctly-ranked character into the rank-1 slot already occupied by the
invisible heading, colliding two different headings on the same adornment
character — wrong regardless of whether a given arrangement also trips a
visible Sphinx-level symptom (traced by direct docutils inspection: reusing an
already-established SHALLOWER character deeper in the tree is silently
tolerated — it pops cleanly to that ancestor level — while the OPPOSITE
direction, reusing an established DEEPER character shallower, is what actually
produces "Inconsistent title style"). Fixed by teaching the scan docutils' own,
more permissive minimum (2 chars, confirmed by direct probe — a 1-char
underline glued to text produces only an INFO "possible title underline, too
short" and no section, but 2 chars already register as a real one), a
fundamentally different question from ``iter_underline_only``'s own stricter
promotion-safety floor.  The original caching theory is retracted: the "fix
reports an error, a separate confirm run then reports clean" divergence that
prompted it could not be cleanly reproduced on a careful redo, most likely an
artifact of mixed-up scratch directories across a long chain of manual probes
rather than a real Sphinx behavior — Sphinx's incremental caching (skip
re-parse and re-warn for unchanged content) is real, by design, and exactly
what makes repeat runs cheap; no evidence survived that it ever hides a
genuinely persisting finding.

========================================
Semantic diffs / document fingerprints
========================================

*Current status: shipped 2026-07-22; exposed as the* ``diff-json`` *verb since
2026-08-07.*

``diff-json OLD.json NEW.json`` compares two previously produced
``check --format=json``
dumps: files matched by path, outline entries by their stable ``docname:title``
id, findings by ``(severity, text)`` — deliberately never by line number, which
drifts with any unrelated edit elsewhere in the file (a finding that merely
shifted lines must never show up as both resolved and added).  Reports, per
changed file, which section ids were added/removed and whether any surviving
section's depth or adornment character changed ("added subsection, hierarchy
unchanged" is the literal shape of the report, not just the idea), plus which
findings are new versus resolved.  Logged 2026-07-18, independently
re-confirmed 2026-07-21 by a real downstream-project session hitting the exact gap this
closes: "several times this session I rewrote a whole file... and had to
manually eyeball 'same warning count, same categories as before' rather than
get a machine answer."  A self-contained mode — no RST is read or checked, and
no other flag applies alongside it — cheap once the JSON model existed
(stage 1), meaningless before it.

===========================
Indentation normalization
===========================

*Current status: awaiting frequency evidence; not queued.*

(field/definition list bodies) — a real LLM failure mode, but ``--fix``
rewriting body indentation is content-adjacent mutation; docutils already
reports the breakage. Wants evidence of actual frequency first.

======================
Documentation smells
======================

*Current status: candidate family awaiting separate triage; not queued.*

A metrics WARNING family, different personality from correctness checking.
Originally parked until the ``Document`` model landed (stage 1); that landed
2026-07-19 and the block-preview/outline machinery it unblocked has shipped
several times since — the blocker is stale.  Concrete candidate list (Max,
2026-07-24, from an external AI review): section with >20 subsections; section
over 1500 lines; heading depth >6; page with 40 code blocks; empty section;
section with no introductory paragraph; text before the document title;
single-child section; heading immediately followed by a list or code block with
no explanatory sentence; code block with no language or explanation;
single-item list; table never referenced; image never referenced.  These split
into two pieces of very different weight: everything except the last two is a
structural count or adjacency check over data ``--outline`` or the doctree
already exposes — nearly free; table/image "never referenced" needs a
corpus-wide asset/reference scan, the same cost class as ``refs``' incoming
scan, not a per-file check — its own design round, not a ride-along.

=================================================
Parsed composition provenance and control paths
=================================================

*Current status: shipped 2026-08-10; deliberately separated from the
title-rule batch.*

Effective structure cannot be validated from the root file's line array once
Docutils has expanded ``.. include::``.  The first live probe demonstrated
that an included heading inherited an unrelated root line, an unknown
adornment, and a root-file extent.  Repeated and nested includes also cannot
be reconstructed from ``node.source`` alone because the directive itself
normally disappears during parsing.

The implementation records every active include invocation with an invisible
Docutils comment marker during the real parse.  It exposes an ``IncludeEntry``
and a shared ``SourceProvenance``/``IncludeSite`` chain on headings and block
entries.  The chain records the directive owner, physical line, resolved
target, mode, options, and clipping identity.  Foreign entries use their own
physical source coordinates and are clustered at the owning directive rather
than sorted numerically against the root file.

The following decisions are fixed for later structural checks:

* An include cycle is identified exactly as Docutils identifies it: the active
  ``(resolved source, clipping options)`` pair.  The same file with a disjoint
  clip is legitimate.  A refused cycle remains a visible include-path entry;
  it is never silently truncated.
* Sphinx nested include arguments retain Sphinx's own resolution semantics:
  they are relative to the root source document's directory, not to the
  directory of the included fragment.
* ``source-read`` and ``include-read`` mutation is detected around extension
  listeners.  Affected entries remain visible but carry ``exact = false`` and
  an unknown adornment instead of claiming an editable physical coordinate.
  ``rst_prolog`` and ``rst_epilog`` use their synthetic Sphinx sources for the
  same reason.
* The stored Sphinx environment is explicitly ``parser-effective``.
  ``only`` and ``ifconfig`` containers are exposed as
  ``builder-dependent``; the dummy builder's tags are not presented as the
  final structure of an HTML, LaTeX, or other real build.
* Source composition and navigation composition remain distinct.  A toctree
  physically written in an included fragment carries the include provenance,
  while documents reached through that toctree retain their independent
  Sphinx docnames.  Include and toctree clusters can therefore nest without
  comparing foreign line numbers.

The single-title batch below now consumes these facts.  Composition remains a
separate implementation boundary: outline and JSON expose the parser-effective
tree, while the hard title conclusion resolves standard conditions for the
Phase 3 HTML builder on a copy.

======================================
Single top-level heading enforcement
======================================

*Current status: shipped. Source-only WARNING implemented 2026-07-26;
effective ERROR completed 2026-08-11; remediation lookup completed
2026-08-13.*

(Max, 2026-07-23: "the level-1 heading can only be one — it represents the
document's title") — confirmed live before implementation that a document with
two full ``#`` sections passed with 0 errors, 0 warnings, entirely silent, at
any ``sphinx-build`` verbosity.  ``check_single_top_level`` now flags every
effective parsed depth-1 section after the first as a non-fixable ERROR.
Severity records the proven invalid structure; ``fixable = false`` records that
the author must choose the page title.  Bare mode follows parsed includes;
verified mode additionally follows extension source mutation, synthetic
prologue/epilogue content, and the standard ``only``/``ifconfig`` branches
active for the Phase 3 HTML builder.  Foreign physical sources are reported
directly; transformed and synthetic sources use line 0 rather than a fabricated
edit coordinate.

The once-per-run hint gives the accepted repair shape and points at ``outline``:
its ``levels:`` legend reports the next free section character after the total.
Insert the chosen page title before the existing sections with a nine-character
underline made from that character, then run ``check_rst fix``.  See "A second
top-level title is legal RST and a real defect" in :doc:`rules` for the full
rationale and the real HTML-toctree defect.

======================================
Homoglyph / mixed-alphabet detection
======================================

*Current status: shipped 2026-07-26.*

(Max, 2026-07-24: "when letters look similar, but only one letter is from
another alphabet") — ``check_homoglyphs`` flags a WORD (not a line — this
corpus is deliberately trilingual, so scripts coexist on nearly every line)
mixing Cyrillic and Latin letters where every minority-script letter is a known
visual twin of a majority-script one.  See "A confusable letter is a keyboard
slip, not noise" in :doc:`rules` for the full rationale, the
hand-curated confusables table (no library on this system provides one), and
the real 6-catch, 8-correctly-silent evidence from scanning this Journal's own
corpus.

====================================================================
Bare document or asset filename mentioned without real integration
====================================================================

*Current status: shipped 2026-07-26; extended to local text/document and image
assets 2026-08-12.*

(Max, 2026-07-23 and 2026-08-12, real downstream-project evidence) —
``check_bare_filenames`` pairs naturally with the reference-intelligence
family, the mirror image of "did you mean": here a document reference or local
asset integration is missing where one should exist, not broken.

The initial implementation matched ``.rst`` basenames against known Sphinx
documents.  The 2026-08-12 extension also recognizes an agreed protocol of
common text/document and image suffixes, but only when the exact prose path
resolves to a real file inside the Sphinx source tree.  It never generalizes the
document rule into a project-wide asset-basename search.  See "A missing
reference is the mirror image of a broken one" and "Local assets need Sphinx
integration, not only a filename" in :doc:`rules` for the distinct confidence
gates, integration mechanisms, and deliberate silence conditions.

================================================
Semantic-diff coverage below the section level
================================================

*Current status: accepted extension, deferred.*

(Max, 2026-07-24, from the same illustrative example that reconfirmed
``diff-json``'s own value: "moved code block", "added one cross-reference") —
``diff-json`` today matches outline entries, hierarchy, and findings; it has
no equivalent match for individual code-blocks or references
moving/appearing/disappearing within an otherwise- unchanged section.  Logged,
not yet implemented — a real refinement to an already-shipped feature, not a
new one.

================================
Nested inline markup detection
================================

*Current status: shipped 2026-08-02.*

(Max, 2026-07-26, spotted live in ``**``ListEntry``**``) — RST inline markup
never nests, in either direction: confirmed by direct probe, ``**``code``**``,
````code **bold** code````, and even ``*emphasis **bold** emphasis*`` all parse
as ONE outer role whose text is the untouched inner markup, delimiters
included, not the intended nested styling.  Real, recurring evidence, not
hypothetical: the original 2026-07-26 scan found 175 occurrences across 49
files corpus-wide, overwhelmingly
``**``code``**`` in pandoc-converted Gemini/ChatGPT Markdown exports (Markdown
supports nesting bold around code; RST does not, and the conversion carries the
pattern through unchanged into silently broken RST).  Not silently ignored
today so much as silently MISDIAGNOSED: confirmed live against both real corpus
shapes — when the mangled ``<strong>`` node happens to be a paragraph's
leading/sole content, the existing bold-paragraph- opener/standalone-bold
visitor already fires on it, but reports it as a heading-substitute candidate
("bold paragraph opener '``image->data``'"), not as broken nested markup — a
WARNING that could steer a fix in the wrong direction (promote to a heading,
not pick one markup role).  When the same pattern sits mid-sentence (most of
the 175 occurrences: "You use **``XGrabServer()``** to lock the server"), that
visitor's own paragraph-opener condition never matches, and check_rst is
completely silent.  Detection is cheap and deterministic — bare docutils, a
visitor over ``strong``/``emphasis``/``literal`` nodes whose own text still
contains another complete markup delimiter pair, the same shape as
``check_directives``' existing visitors, but a NEW, more specific WARNING than
either existing outcome, not a variant of them.

Generalize the detector rather than enumerating nesting shapes by
hand (Max: "compare what was given to docutils and what is out —
this could give some cases we even don't know").  A regex over the
leftover text ("does it contain another delimiter pair") was the
first shape considered, but Max's own follow-up question — "so we
don't know if it is a formatting without grepping it?" — pointed at
a strictly better answer: docutils' own inline-markup grammar is
directly callable (``docutils.parsers.rst.states.Inliner.parse``),
so instead of approximating that grammar with a regex, RE-RUN it on
the leftover text itself and see what docutils' own rules make of
it.  Confirmed by direct probe, feeding each outer node's own text
back through a fresh ``Inliner``:

.. list-table::
   :header-rows: 1

   * - Leftover text (outer node's own content)
     - Re-parsed as
     - Verdict
   * - \`\`Abc\`\` (a bare double-backtick pair, as text)
     - a real ``literal`` node
     - accidental nesting — flag it
   * - :strong:\`x\` (role syntax, as text)
     - a real ``strong`` node
     - accidental nesting — flag it
   * - ``int** ptr`` (genuine C++ double-pointer in a code span)
     - plain, unrecognized ``Text``
     - genuine content — leave it alone
   * - ``x**y`` (an unbalanced, non-whitespace-bounded ``**``)
     - plain, unrecognized ``Text``
     - genuine content — leave it alone

This resolves the false-positive risk the regex version would have carried by
construction, not by a confidence hedge: the re-parse test uses docutils'
actual start-string/end-string and whitespace-boundary rules, the same ones
that make ``int** ptr`` and ``x**y`` safe inside a code span.  Implementation
probes a fresh document so discovering a reference or target cannot mutate the
real doctree.  Only a successfully parsed *explicit* inline construct counts:
plain ``Text``, invalid/unbalanced ``problematic`` nodes, and implicitly
recognized URLs or email addresses do not prove that markup syntax was nested.
This last predicate came from implementation-time corpus evidence: a literal
URL re-parses as a ``reference`` even though it contains no nested delimiter or
role.

The first implemented whole-corpus scan on 2026-08-02 found 403 warnings in
109 files: 355 outer bold spans, 36 outer inline literals, and 12 outer
emphasis spans.  The growth from the historical 175/49 is real corpus growth,
not a changed denominator hidden in the prose.  A naive "anything other than
one Text node" interpretation produced 482 candidates in 135 files and mixed
valid nested constructs with implicit links and incomplete delimiters; the
shipped rule keeps the grammar-backed signal without those two known false
positive classes.

Auto-fix is NOT free, though raised as an idea
worth reconsidering: RST cannot express both stylings in one span at
all (no nesting support exists to fall back to), so any fix must
drop ONE of the two — which one is a real style decision, not a
discovered fact, the same reasoning that keeps ``--fix`` out of
content-adjacent territory elsewhere.  A fixed project-wide
convention (e.g. "code wins over bold") could still be adopted
deliberately, the same way the hierarchy remap commits to one
canonical character ordering among other valid ones — but that is a
policy choice to make explicitly, not something to default into silently.
Detection is implemented; auto-fix remains deliberately unimplemented.

====================================================
A CLI option for snippet/preview truncation length
====================================================

*Current status: logged; not implemented or queued.*

(Max, 2026-07-22) — every block-preview kind (code-block, blockquote, table,
admonition, comment) shares one hardcoded constant,
``_OUTLINE_PREVIEW_LEN=74``, with no way to widen or narrow it per run.
Logged, not yet implemented — the natural shape, once picked up, is the same
precedent ``--word-samples`` already set for top/rare prose words: a flag with
a sensible default, never a silent behavior change.

=====================================================================
A ``ListEntry`` outline kind for bullet/enumerated/definition lists
=====================================================================

*Current status: shipped 2026-07-26.*

Found by the AI's own friction, 2026-07-22: hunting for a specific item inside
what were then this page's numbered "Agreed direction" and bulleted "Accepted,
deferred" lists, ``--outline-only`` answered nothing, so the fallback was a raw
``grep`` against the file's own markup — exactly the fragile pattern
``--outline-only`` exists to replace.  Those roadmap entries have since been
promoted to sections.  See "Finding one item among many: the two-level list
contract" in :doc:`rules` for the shipped design (a container entry
plus one entry per item for bullet/enumerated, standalone per-item entries for
definition lists) and the real nesting-depth bug it caught before shipping.

=============================================
Structure-aware list-to-section refactoring
=============================================

*Current status: accepted 2026-07-29; deferred.*

The real conversion of this roadmap exposed the reusable operation: five list
containers yielded 40 disposition entries and five nested list items, plus two
adjacent prose blocks whose correct section ownership still required judgment.
A future refactoring command should select exactly one outline container by the
same stable selector accepted by ``context`` and perform a deterministic
transformation rather than infer titles.  For example, with ``N=8``, copy the
first eight plain-text words of each item's first direct paragraph into a
provisional heading while retaining the *complete* original item as the new
section body.  The deliberate duplication loses no prose and leaves the next
AI edit a simple, visible job: improve each heading and reconcile the repeated
beginning in the ordinary Git diff.  Append an item ordinal only when generated
headings collide, and use a neutral ``Item N`` heading when an item has no
direct prose.

Preserve list nesting as section depth, retain tables/literals and body text
under their mechanical owner, and emit the standard placeholder adornments for
``--fix`` to normalize.  A dry-run mapping remains useful but is a convenience,
not a substitute for semantic inference inside the transformation.  Ownership
questions such as the two adjacent prose blocks found in this conversion stay
visible for the following edit instead of making the mechanical operation
guess.

The applied report should verify that the selected container disappeared and
that the expected sections replaced it.  It should also identify candidate
stale prose references such as "item 9", "the numbered list", or "the bullet
below", including candidates in incoming documents, but never rewrite those
semantic references automatically.  These postconditions cover the immediate
structural-assertion need; a general ``--assert-*`` CLI remains unjustified
until another independent use case appears.

=======================================
``--sections-only`` for ``--outline``
=======================================

*Current status: shipped 2026-07-26.*

(Max, 2026-07-22) — filters by KIND, not depth: every leaf entry (code-block,
blockquote, table, admonition, comment, list) is suppressed regardless of how
shallow it sits, unlike ``--outline-depth`` which bounds by depth regardless of
kind — the two compose rather than overlap.  A display filter, same contract as
structure-only ``outline``: the ``levels:``/``blocks:`` legend and every heading's own
bracketed subtree counts still reflect the whole document, computed against the
full entry list, never the filtered one — a leaf kind disappears from the tree,
never from the statistics.  The hidden-entries note names every reason at once
(``--outline-depth N, --sections-only``) rather than picking one.

=========================================
Markdown analysis via the pandoc bridge
=========================================

*Current status: documented bridge shipped; native Markdown parsing remains
deferred and may be unnecessary.*

(Max, 2026-07-18; verified by probe the same day) — instead of a native ``.md``
frontend, convert and analyze::

    pandoc --from gfm-gfm_auto_identifiers --to rst input.md --output converted.rst
    check_rst check --skip-fixable converted.rst

``--skip-fixable`` suppresses the adornment noise from pandoc's own
heading style, leaving exactly the semantic findings: the probe
caught a bold paragraph opener from Markdown source while correctly
exempting a ``>`` quotation (pandoc preserves it as a blockquote).
This delivers the Markdown bold-as-heading lint — the pattern
``CLAUDE.md`` itself carried — with zero new code.  Known limits:
findings point at converted-rst lines, not source lines (fine for
review, weak for precise fixes), and round-trip editing is lossy —
an analysis bridge, not an edit path — with one exception that makes
it a *pipeline*: an externally-maintained ``.md`` adopted into a
project (Max's downstream adoption workflow: a product-specific Yocto document, provenance
header with the upstream commit) is re-converted and re-checked on
every upstream update, so modifications stay visible and diffs
comparable; Phase 0 automatically cleans what such documents drag
along (form feeds — previously suppressed by hand).  The native
frontend stays deferred; the bridge may make it unnecessary.

==========================================
Trailing whitespace on every source line
==========================================

*Current status: shipped 2026-08-02.*

(Max, 2026-08-02) — Phase 0 now reports and fixes trailing spaces and tabs on
every source line, not only adornment-shaped lines.  This is a parser-equivalent
normalization rather than an editorial rewrite: docutils'
``statemachine.string2lines()`` expands tabs and then calls ``rstrip()`` on
every line before title, paragraph, literal, parsed-literal, line-block, or raw
states see it.  Direct before/after doctree tests cover all of those contexts,
including trailing whitespace in section-title and ordinary paragraph text.
The fixer preserves line count and whether the source has a final newline;
adornment lines retain their more specific diagnostic because hidden title
geometry can otherwise cause a misleading structural diagnosis.

The tracked corpus contained 801 affected lines across 263 files when the
feature was evaluated.  ``fix --fast`` reports the bounded mutation as
``trailing whitespace lines N``.  Internal whitespace is deliberately outside
this guarantee: docutils preserves it in text nodes, and blank-line runs can be
content inside whitespace-preserving constructs, so either change needs a
separate context-aware policy rather than extending this hygiene pass.

========================================
Opt-in redundant blank-line normalizer
========================================

*Current status: shipped 2026-08-02.*

(Max, 2026-08-02) — repeated blank separators are now available through
``--normalize-blank-lines``, a modifier accepted only by ordinary ``--fix`` and
``--diff``.  A global empty-line collapse is unsafe: direct probes produced the
same doctree for repeated separators between paragraphs, sections, lists, and
tables, but a different literal-block tree when the same source shape occurred
inside preserved content.  Internal doubled spaces likewise changed title and
paragraph text nodes and remain outside this feature.  The tracked corpus held
391 repeated-blank runs (457 removable-looking lines) across 283 files, enough
to justify automation but also enough to make a context-blind rewrite risky.
A dedicated EOF scan then found 515 tracked RST files with 698 empty terminal
lines beyond the single Unix final newline.  The symmetrical leading-edge scan
found zero tracked RST files, so that case completes the contract rather than
cleaning current corpus debt.

The implementation therefore makes parser equivalence the acceptance
predicate.  It first normalizes every leading, interior, and EOF candidate run
and compares the complete before/after docutils trees.  When that batch differs,
it retries runs independently, allowing safe separators and protected
literal/raw-style content to coexist in one document.  An interior run retains
one separator; an EOF run retains one final newline.  Leading runs and
all-blank files need different predicates: a leading run is removed completely
when a first document element follows, while an all-blank source is retained
because it has no first element.  The operation is whole-document and
explicitly opt-in; default ``--fix`` remains byte hygiene plus adornment and
hierarchy correction.  Parser-free ``fix --fast`` and ``diff --fast`` reject
the option rather than weakening their established performance contract.

TDD covers ordinary block separators, section adjacency, lists, grid tables,
mixed literal/parsed-literal/raw content, zero/one/multiple leading lines,
missing/single/duplicated final newlines, leading section and raw-directive
content, all-blank input, default-fix non-participation, diff preview without
writes, and the three rejected parser-free/no-mutation invocations.  The
implementation comments state the source-geometry candidate, semantic
predicate, granular fallback, and fixed-point decisions rather than leaving
safety to inference.

=======================================
Opt-in title and prose space policies
=======================================

*Current status: shipped 2026-08-02.*

Evaluation rejected one undifferentiated internal-whitespace cleanup.  The
tracked corpus contained 13,227 internal ASCII-space runs across 6,826 lines in
455 files: 7,598 appeared in table-shaped lines, 4,050 on indented lines, 523
at likely sentence boundaries, and only 22 in section titles.  The
``check_rst`` documentation alone contained 466 two-space sentence separators,
evidence of an established style rather than accidental universal debt.
Docutils probes also showed that title, paragraph, emphasis, inline-literal,
and link-label spacing survives in Text nodes and rendered output.  The
operation is therefore two named opt-in policies, never a default fix:
``--collapse-title-spaces`` and ``--single-space-prose``.

Both modifiers accept only internal runs of ASCII U+0020 spaces and require
ordinary parser-capable ``--fix`` or ``--diff``.  Titles and paragraphs are
separate scopes.  Literal, raw, code, math, substitution, indentation, tab,
Unicode-space, and newline content is protected.  Source-looking candidates
inside list-marker syntax or aligned-table padding are rejected because they
do not correspond to an eligible visible Text-node delta.  Title normalization
precedes structural correction so an accepted title edit and its resized
adornment converge in one plan.

The safety model intentionally differs from the blank-line normalizer's exact
tree identity.  It builds a canonical before/after doctree whose eligible Text
values are single-spaced for comparison, requires all node structure,
attributes, targets, and ids to remain identical, and separately requires the
eligible run-count reduction to equal every proposed source edit.  A batch is
tested first for the common fast path; a failed mixed batch is bisected from
higher to lower offsets, accepting independent safe edits without invalidating
untried ranges.  The resulting counts remain separated as title and prose
runs, making the granted editorial scope visible in ``--fix`` output.

TDD covers title text around protected inline literals, generated-id stability,
adornment resizing, ordinary prose, emphasis, link labels, list-item text,
timestamp-like prose, list syntax, literal and raw blocks, simple-table
alignment, tabs and non-breaking spaces, option composition, fixed points,
diff non-mutation, default-fix non-participation, and all parser-free or
non-mutating rejection paths.  The permitted-delta proof can establish exact
scope, not intent: a timestamp's doubled separator and an author's deliberate
sentence-spacing convention remain reasons to preview and select the policy
explicitly.

===================
Footer statistics
===================

*Current status: shipped 2026-07-18; statistics extended 2026-07-19.*

(Max): the summary line reports totals from Phase 0's own read — lines with the
empty-line count and ratio (empty lines are RST's block delimiter, so the ratio
is a structure signal), characters as code points with bytes alongside when the
two differ (``(= bytes)`` note when they coincide).  Reworked same evening into
a two-line footer (Max: "too long, and a mixture") — run facts and character
totals on line 1, everything about lines on line 2, with the length min/avg/max
spread in chars and bytes under the same collapse rule.  Extended 2026-07-19
(Max): spaces with their share of chars; a ``words:`` line (raw-text tokens —
markup included, deliberately not a prose count) with total, distinct and
once-only counts and the length spread; chars gained distinct and once-only
counts, and ``check --format=json`` lists the once-only characters as ``U+XXXX`` — for
characters the once-set is tiny and is an oddity scan (the June corpus: 11 of
190, including a stray variation selector and a lone Vietnamese letter).
Evaluating this also found by probe that a non-UTF-8 file crashed Phase 0 with
a raw UnicodeDecodeError traceback — now a clean per-file ERROR naming the byte
offset, same fix class as the not-a-git-repo diagnostic.

=================
Top prose words
=================

*Current status: shipped 2026-07-19; next-free-character guidance added
2026-08-13.*

(Max) — the meaningful frequency statistic the raw layer couldn't provide, from
existing dependencies only, after a four-domain scan: the Python stdlib has no
NLP; docutils' language modules are UI labels only; **sphinx.search** carries
curated stopword lists for 17 languages (en 174, ru 159, fr 164 — package
import, no Sphinx build or conf.py involved, so the statistic is unconditional
and works in heuristic mode); and **snowballstemmer**, Sphinx's own hard
dependency, provides stemming. Prose comes from the bare-docutils doctree (Text
nodes, skipping literal blocks, comments, raw, and generated topics —
``contents`` was rank 2 before that filter).  Stemming is used for *grouping*
only; the displayed word is always the group's most frequent real surface form,
never a stem; Cyrillic routes to the Russian stemmer, Latin to English (French
groups slightly imperfectly — a cosmetic approximation of grouping, never of
display).  Both imports are defensive: when unavailable the statistic is
omitted, never degraded to stopword noise.  Footer shows the top 13 with an
explicit "(yet N suppressed)" note and a first-match jump target per word
(``@line`` for a single file, ``@docname:line`` across a corpus — the corpus
form is knowingly heavy; bounding it is an open display question) — bounded
output, never silent truncation; ``check --format=json`` carries the top 10 with the
suppressed count.  June 2026 live: ``product (111), source (56), frame (46),
name (41), rst (41) (yet 3196 suppressed)`` — a thematic fingerprint of the
month.

==================
Rare prose words
==================

*Current status: shipped 2026-07-19.*

(Max) — the other extreme of the frequency distribution, in its honest form
after two probe-driven corrections.  A corpus-scale "least frequent word" is
degenerate (55% of prose groups occur once even after filtering, and the
alphabetical bottom is git hashes and timestamps), but Max's use-case is
per-page: on one document the once-set is an eyeball spell-scan.  The tool
states deterministic facts — once-only words, each annotated with its closest
frequent sibling where one is exactly ONE EDIT away (substitution,
insertion/deletion, adjacent transposition: the classical typo shape) — and the
typo-vs-morphology judgment stays human.  Precision guards, each
probe-motivated: identifier debris (digit-containing tokens) excluded from all
word statistics; a sibling pair unified by ANY stemmer is an inflection,
suppressed; and the Latin stemmer is chosen PER DOCUMENT by counting en-vs-fr
stopword hits — the stopword lists doubling as a language detector — after the
always-English routing mis-based French documents (Max: "wrong language taken
as a base for another language"; vérifier/vérifiée now group).  The one-edit
criterion replaced a 0.87 similarity cutoff after the cutoff missed a real,
confessed, journal-attested mistake by 0.013: померял (1 occurrence) vs померил
(146) — found and flagged by the feature it motivated. Footer top-13 with the
suppression note and first-match jump targets; ``check --format=json`` carries
``rare_words`` with the same contract.

=========================
Ranges, not start lines
=========================

*Current status: shipped 2026-07-19.*

(Max): outline entries — sections, code-blocks, blockquotes — carry their full
extent (``508-613:``), computed from the outline sequence and indentation.
Evidence: reading two foreign documents from a downstream project via
structure-only ``outline`` + ``sed``
needed exactly these ranges, and the end lines had to be re-derived by hand
from the *next* entry — deterministic arithmetic that is the tool's half of the
contract. Chosen over the ``context ENTRY FILE`` alternative as the cheap
first step (stage 3 remains on the roadmap); generalized as a principle: where
check_rst informs about a line number, it informs about the range instead,
where applicable.  Findings deliberately keep single-line anchors.

====================
Outline enrichment
====================

*Current status: shipped 2026-07-19.*

(Max, by analogy with the summary line): every heading shows its
direct-subsection count when non-zero (``[3 subsections]``), making each
outline line self-contained data — an AI consuming lines individually doesn't
reconstruct the tree; and ``--outline-depth N`` trims deep structure with an
explicit hidden-count note — bounded output, never silent truncation.  The two
compose for humans too (Max's point): under a depth limit the count on the
deepest shown level says exactly what the trimmed tree hides below each entry.
Reworked the same evening (Max: "too many Level N"): per-entry level/char info
folded into a single ``levels:`` legend carrying the depth→char mapping and
per-level section counts — the mapping is constant within a document (docutils
fixes a char's level at first appearance), so repeating it per entry was noise;
depth stays recoverable from a lone grepped line via its 4-spaces-per-level
indentation.  The legend now also reports the first free character, chosen in
check_rst's canonical order, after the section total, or explicitly reports
that none is free.  This turns the formerly manual set subtraction needed for a
new outer level into deterministic output.

==============================
Summary line and ``--quiet``
==============================

*Current status: shipped 2026-07-18.*

From session-transcript evidence (2026-07-18): mining all seven Claude session
logs of this project found 93 real ``check_rst`` executions, of which ~20 piped
the output through ``grep '^⚠'``/``grep -c``/ exit-code probes — five sessions
independently reinventing the same filters to recover findings and counts from
around the per-file OK lines and phase banners.  By the feedback loop's own
rule, a workaround hand-rolled five times is a feature request.  Every run now
ends with one machine-parseable summary line (``check_rst: N file(s) checked, E
error(s), W warning(s)``, plus fixed/would-change counts in
``--fix``/``--diff`` modes), and ``--quiet`` suppresses banners and OK lines
while keeping findings, requested reports, and the summary — a month audit
becomes findings plus one line.

===================================
A whole-report output line budget
===================================

*Current status: shipped 2026-07-31.*

Repeated ``check_rst ... | head`` use exposed a gap between the existing
semantic display controls and a caller that simply has a hard context budget.
``--max-output-lines N`` is the honest, whole-report alternative: it limits
what is emitted, never what is checked, and preserves the run's real exit
status.  The limit is applied after ``--quiet``, structure-only ``outline``,
``--sections-only``, ``--outline-depth``, and other semantic filters, so those
remain the first choice when the caller knows what information it needs.

``N`` counts every emitted program line and has a minimum of two.  Those two
lines are permanently reserved, in this order, for an explanatory output-limit
statistics line and the authoritative final status line.  The first ``N - 2``
lines come from the ordinary selected output.  The statistics line is present
even when nothing was skipped; when truncation occurs it reports how many of
the current run's detail lines were shown and skipped, classifies skipped
information where possible (at least ERROR/WARNING diagnostics and outline
entries), and states the limit needed to see the complete current report.  A
two-line run is therefore still honest::

    check_rst: output limited — 0 of 154 detail lines shown, 154 skipped; full output requires 156 lines
    check_rst: 12 file(s) checked, 1 error(s), 4 warning(s), ...

The final status is mandatory and always last.  This tightens an existing
inconsistency: the current summary precedes verbose line/word statistics and
explicit word samples, despite being described as the run's ending summary.
Early input, configuration, and preflight failures follow the same bounded
shape once command-line parsing has accepted the option: their category and a
useful rerun hint belong in the explanatory statistics line, while the final
line remains the authoritative failed status.  Only parser failures that
prevent the option itself from being recognized fall outside this contract.

The current scope is ``check``, ``fix``, and ``outline`` text reports, including
``fix --fast``.  Structured or copyable outputs are rejected: truncated
``check --format=json`` must never become invalid or masquerade as a complete
model, and truncated ``diff``/``diff --fast`` output must never resemble an
applicable patch.  ``diff-json``, ``refs``, and ``context`` likewise need
complete semantic/reference reports and therefore reject the generic limit.

Implementation uses a report/output sink, not a parser over the tool's own
rendered text after the fact: the checker continues to completion while the
sink retains the permitted prefix and counts discarded records by semantic
kind.  Explicit final-status routing also moves verbose statistics before the
footer whenever the budget is active.  TDD pins the two-line minimum, exact
``N``-line overflow shape, zero-suppression
shape, final-status position, preserved non-zero exit status when its detailed
diagnostic was skipped, diagnostic classification, filter composition, early
failure behavior, and explicit rejection of incompatible modes.  Terminal
wrapping is irrelevant; the budget counts newline-delimited program output.

====================================
Fast mechanical fix and diff modes
====================================

*Current status: shipped as* ``--fix-only``/``--diff-only`` *on 2026-07-30;
current interface* ``fix --fast``/``diff --fast`` *since 2026-08-07.*

Ordinary ``fix`` correctly favors safety: it applies the two deterministic
mutators, then continues through the remaining Python rules, the Sphinx-aware
phase, and the real Sphinx build.  None of those later phases computes an edit,
however.  Phase 0 byte normalization and Phase 1's raw-line adornment/hierarchy
logic are the complete mutation boundary; they need docutils' display-width and
valid-adornment definitions, but no docutils parse, Sphinx environment,
extension, reference graph, HTML build, stopword table, or stemmer.

``fix --fast`` is the write-side counterpart of ``diff --fast``.  Ordinary
``fix`` keeps its full post-fix validation contract; no dynamic or
implicit phase skipping.  The fast three-step workflow becomes a full human
review, one mechanical mutation pass, then one full confirmation::

    check_rst check --skip-fixable
    check_rst fix --fast
    check_rst check

It uses exactly the same file selection, Git allowlist/diff scoping, whole-file
hygiene and hierarchy exceptions, path validation, and unresolved-merge
preflight as ordinary ``fix``.  Before any write it reads, UTF-8-decodes, and computes
the fix plan for every selected file; one invalid input aborts without partially
mutating valid siblings.  It then applies hygiene followed by structure and
recomputes the plan as a local convergence postcondition.  Other Phase 1
warnings, statistics, Phase 2, and Phase 3 do not run.  A changed file is a
successful result; only input, write, or non-convergence failures make the mode
exit non-zero.

Configuration still supplies the project root and therefore Git selection, but
configured Sphinx source/build settings are inactive.  Explicit
``--sphinx-src``/``--build-dir`` are rejected as meaningless rather than
silently ignored.  ``--no-adornments`` remains useful and means hygiene-only
mutation; ``--skip-fixable`` is redundant and should be rejected.  Prefer this
goal-oriented mode over a generic ``--phases 0,1`` interface, which would expose
implementation structure and create a large compatibility matrix.

Fast fix output is mutation-oriented rather than a shortened normal check.
Before writing, state the effective scope (Git-selected/diff-scoped versus
explicit/whole-file, with the whole-file hygiene/hierarchy exceptions).  For
each changed file, report structured categories and counts — for example,
``BOM 1, CRLF line endings 42, structural lines 2`` — then print the mandatory
status footer.  Remaining diagnostics are additionally present under ordinary
``--fix``; generic phase banners, per-file OK lines, and unrelated statistics
belong under ``--verbose``.  The implementation adds a structured, converged
``FixPlan``/``FixResult`` path for the fast modes and preview paths while
retaining the older Boolean fixer entry points for direct callers.  The same
structured counts give the whole-report output limiter meaningful omitted-record
categories.

TDD pins selection/scope parity with ordinary ``fix``, plan-all-before-write
atomicity for invalid UTF-8 and other input failures, hygiene-before-structure
ordering, one-pass convergence, no docutils/Sphinx parse or build, inactive
configured Sphinx settings, rejected meaningless options, hygiene-only
``--no-adornments``, structured per-file results, and final-status/exit-code
semantics.

==================================
Single-colon directive typo lint
==================================

*Current status: shipped 2026-07-18.*

Proposed 2026-07-18 while evaluating an ideas note that contained one (``..
code: bash``), implemented within hours: a WARNING when a comment's first line
is a known directive name followed by a single colon.  Its first whole-corpus
run found exactly one finding — a true positive whose C++ listing had been
silently invisible in the rendered HTML for eight months — and zero false
positives.

================================================
Foreign-adornment exemption in per-repo config
================================================

*Current status: deferred; the motivating urgency is gone, but the request is
not retracted.*

(from heavy real usage in a downstream-project session, 2026-07-20 — dozens
of invocations across ~15 files): a plain ``check_rst check <file>`` on one of the
downstream project's four
pandoc-converted, deliberately underline-only adopted documents
(``product-yocto-*.rst``/``product-apps-claude.rst``) reports ~59 ``ERROR:
underline-only title`` — confirmed the true picture is ``--skip-fixable``'s (0
errors, 59 warnings), and every touch of one of those four files needed
remembering to add the flag. In the spirit of ``.check_rst.toml``'s existing
declaration-not-detection philosophy: a config key (working name
``foreign-adornment``) listing path globs whose plain-check severity for *all*
adornment/hierarchy ERRORs downgrades to WARNING permanently — an explicit,
versioned "this file's style is permanently accepted," never a guess.
Deliberately scoped to adornment/hierarchy only, not a blanket
``--skip-fixable``-forever: hygiene ERRORs (BOM, bad line endings, non-UTF-8)
on those same paths are unrelated to the intentional heading style and should
still surface normally. ``--fix``/``--diff`` on an explicit filename stay
untouched — normalizing one of these files on purpose remains possible.
Deferred pending a dedicated round (queued behind the verbosity-level work
landing the same day). **Update, 2026-07-21:** the motivating pain is resolved
a different way — an independent session normalized the downstream project's adopted documents
in full instead of waiting for a permanent exemption (see "Adopting a foreign
document" in :doc:`guide`).  The feature request itself is not retracted —
a genuinely permanent foreign-style exception may still be wanted here or in
another repo one day — but its urgency here is gone; noted so it does not sit
prioritized on a stale driver.

=================================================================
``diff --classify``: tag each hunk by what kind of change it is
=================================================================

*Current status: logged from one workaround; not accepted or queued.*

(an independent Claude Code session on a downstream project, 2026-07-21).
Before recommending a
real normalize of six adopted documents, that session hand-rolled a grep filter
over ``check_rst diff`` output to answer "did this touch only adornment
lines, never prose?" — hardcoding the adornment character set from outside the
tool rather than deriving it from check_rst's own model of what it just changed
(see "Why you can trust --fix" in :doc:`guide`, which states the underlying
guarantee directly and should already remove most of the need for this).  A
sturdier, tool-side answer: ``diff --classify`` would tag each hunk
``adornment``/``hygiene``/``content`` (the last should never appear, making its
presence itself the interesting signal) instead of a human re-deriving "is this
line only symbols" from the outside. First occurrence of this specific
workaround, not yet the "same auxiliary command twice" threshold this project
uses to prioritize — logged, not queued.

=========================================================================
A black-box subprocess test against a standing, combined Sphinx fixture
=========================================================================

*Current status: shipped 2026-08-09.*

(Max, 2026-07-26) — a real, confirmed gap, not a duplicate of existing
coverage: CLI tests call ``check_rst.main()`` in-process with monkeypatched
``sys.argv``, and every fixture is built fresh, inline, per test (the largest
is 4 files) — nothing runs ``check_rst`` as a genuine subprocess, and no
standing, checked-in, multi-construct project exists.  Motivated by concrete
evidence, not speculation: the ``ListEntry`` depth bug (a table nested inside a
bullet item printing at the wrong depth) slipped past the existing tests
specifically because none of them combine those two constructs in one document
— every existing test is deliberately minimal, one construct at a time, so a
cross-feature interaction bug is invisible to them *by construction*.  Real
subprocess execution (``subprocess.run([sys.executable, "-m", "check_rst",
...])``) additionally reaches things in-process calls structurally cannot: a
broken console installation, real ``argparse`` behavior against
genuine argv, real exit-code propagation through an actual process boundary
(``pytest.raises (SystemExit)`` inside the same interpreter is not the same
guarantee as a subprocess's own ``returncode``).

Weighed explicitly against the obvious risk (Max: "correct each time
the output, sync the implementation and the test") versus the profit
(Max: "examples are more evident to learn") — resolved as a hybrid,
not a pick-one: avoid a full raw-text snapshot/golden-file diff
entirely (the worst-case version of the risk — any cosmetic wording
change anywhere in the output breaks the test, whether or not
anything meaningful changed, and a Sphinx/docutils version bump could
break it for reasons unrelated to check_rst's own code).  Instead,
assert structural facts from ``check --format=json`` output (depth, kind, counts —
exactly the tripwire that would have caught the ``ListEntry`` bug,
and facts that rarely change on purpose, so they do not create sync
churn) plus a handful of targeted substring assertions against the
real console output for the illustrative constructs (a
mistyped-directive WARNING contains "looks like a mistyped
directive", a homoglyph WARNING contains the flagged word, …) —
substrings tolerate wording tweaks far better than a full match,
while still reading as real, concrete examples when the test file is
opened, delivering the pedagogical profit without the worst of the
maintenance cost.  A new, small, additional layer, not a replacement
for the existing precise unit-style tests, which catch different
things faster.

The implemented fixture under ``tests/fixtures/combined_sphinx`` combines
toctree traversal, nested list/admonition/table depths, bold openers, a
mistyped-directive comment, a homoglyph, a bare filename mention, live
incoming/outgoing references, fixable title geometry, and nested aligned
tables.  ``tests/test_cli_black_box.py`` copies and commits it for isolated
subprocess workflows.  Targeted predicates cover argparse and runtime argument
failures, all three CLI roles, Git diff selection, JSON structure, Sphinx
warning-versus-failure status, preview/write/idempotence, and ancestor-first
table conversion without pinning complete console transcripts.

=========================================================
Extend ``--outline`` across ``.. toctree::`` boundaries
=========================================================

*Current status: shipped 2026-07-26; nested-container provenance completed
2026-08-02.*

(Max, 2026-07-26) — the first entry kind whose items point at OTHER files, not
the one being outlined.  Grounded in a real 4-file, 2-level-deep nested-toctree
project built specifically to answer this, inspected at three layers: the raw
doctree (what Phase 2 already sees) shows a toctree as an inert placeholder
node — the included documents' own sections never appear in it at all; Sphinx's
own resolution API (``sphinx.environment.adapters.toctree.TocTree
.get_toctree_for``) is what actually builds a navigation LINK list from it,
nesting one extra level of an included document's own structure only as far as
that toctree's own ``:maxdepth:`` allows; and the real compiled HTML confirms
it — each included document renders as its own completely independent page, own
top-level ``<h1>``, never re-parented into the including document's own heading
depth.  So the correct design was never "flatten included content to the
current depth" (Sphinx itself never does that) — it is "show what Sphinx's own
resolver would show," recursively.

Universal formatting, no special-casing (Max: "we see that the new
file started, so line ranges are actual, and we know to which file
— no need to break the universal formatting for nodes"): a
cross-file entry uses the EXACT same ``{pos}:{char} {title}`` shape
every heading already uses, just prefixed with ``{docname}:`` when
the position lives in a different file — real line ranges from that
file's own ``--outline``, never a placeholder.  Verified output (full
recursion, no depth limit) against a real 4-file fixture: every cross-file
heading correctly carries its ``{docname}:`` prefix (``sub1:6-13:- Sub One
Child``, reached only through ``index.rst``'s own toctree), and the nested
toctree container one level deeper now follows the same universal format
(``sub1:11-13: toctree (...)``).  The root container remains unprefixed because
its position is local to the file being outlined.  See the resolved provenance
case under "Implementation" below::

    Outline: index.rst
      levels: 1 '=' (1), 2 '-' (2), 3 sections total; next free section char: '#'
      blocks: 2 toctrees
      1-20:= Index [2 subsections, 2 toctrees]
          6-15:- Section A [2 toctrees]
              11-15: toctree (2 entries, maxdepth=2)
                  sub1:1-13:= Sub One [1 subsection]
                      sub1:6-13:- Sub One Child
                          sub1:11-13: toctree (1 entry, maxdepth=unlimited)
                              subsub1:1-4:= Sub Sub One
                  sub2:1-4:= Sub Two
          17-20:- Section B

Each toctree's own configured ``maxdepth`` still DISPLAYS as
metadata (real information about what the author configured for
human browsing) but is deliberately not used as a traversal bound —
confirmed live that a naive port of Sphinx's own maxdepth-limited
resolver would have hidden ``subsub1`` (one hop beyond ``index``'s
own ``maxdepth: 2``) even though it is real, reachable content an AI
navigating the project graph would want to know about, unlike a
human clicking through an HTML sidebar one page at a time.  Max:
"we should not be afraid to output all, if the user wants —
``--outline-depth`` can always help, the limit is applied
universally to depth, including nested documents" — depth counting
continues seamlessly across the file boundary exactly like the
fixture's own numbers already show (``subsub1`` sits at depth 7
whether it got there by list nesting, section nesting, or a toctree
hop), so no new bounding flag is needed for the common case.

Two things full recursion by default does need, both agreed
explicitly, not assumed:

----------------------
Lazy cycle detection
----------------------

(Max: "inform the user when facing a cycle, warn that we don't go farther for
this branch because of the cycle, continue on the next item") — track the
current traversal PATH (the chain of docnames walked to reach this point), not
a precomputed whole-project graph; the moment a toctree would recurse into a
docname already on that path, stop only that branch, emit a visible note naming
the cycle, and continue with its siblings normally.  Silence here would be
exactly the kind of thing this project's own "never silent truncation" house
rule exists to prevent.

--------------------------------------------------------
An opt-out flag to suppress toctree traversal entirely
--------------------------------------------------------

Back to today's behavior (a toctree shown only as its own directive marker with
an entry count, no cross-file recursion at all) for when the recursive,
multi-file view is not wanted.

------------------------------------------------------
``--sections-only`` needs one deliberate distinction
------------------------------------------------------

Caught before implementation began (Max: "``--sections-only`` shouldn't stop
treating toctree elements"): the toctree CONTAINER marker itself (``11-15:
toctree (2 entries, maxdepth=2)``) is a leaf block, exactly like an admonition
or a table, correctly hidden by ``--sections-only`` — but the cross-file
headings it recurses into (``Sub One``, ``Sub One Child``, ``Sub Sub One``) are
sections in their own right, from another file, and must stay visible; a table
of contents is precisely what they are.  The implementation consequence: a
cross-file heading must actually BE an ``OutlineEntry`` (just carrying a
``docname`` field, empty for local headings), not a separate class
``--sections-only``'s ``isinstance(e, OutlineEntry)`` filter would exclude
alongside the toctree marker.  Same fixture, ``--sections-only`` applied — the
container disappears, the section chain does not, and depth stays each entry's
own fixed property regardless (the same "trims display, never information"
contract already established, not a special case for this feature)::

    Outline: index.rst
      levels: 1 '=' (1), 2 '-' (2), 3 sections total; next free section char: '#'
      1-20:= Index [2 subsections, 2 toctrees]
          6-15:- Section A [2 toctrees]
              sub1:1-13:= Sub One [1 subsection]
                  sub1:6-13:- Sub One Child
                      subsub1:1-4:= Sub Sub One
              sub2:1-4:= Sub Two
          17-20:- Section B
      (2 entries hidden — --sections-only)

----------------
Implementation
----------------

(2026-07-26): ``ToctreeEntry`` plus
``find_toctrees``/``_expand_toctrees``/``_expand_one_toctree``, now in
``src/check_rst/cli/_sphinx.py``, exactly matching this design — a plain
docname-path-tracked recursion (no dependency on ``TocTree.get_toctree_for``,
since a per-document ``env.get_doctree`` walk was simpler and already the
pattern every other ``find_*`` function in Phase 2 uses), one cluster per
root-level ``.. toctree::`` directive so cross-file entries splice into the
local outline at their container's own position without ever being re-sorted by
a foreign line number.  ``--no-toctree`` is the opt-out flag's name, following
the existing ``--no-adornments``/``--no-directives`` convention.  Verified
against this exact 4-file mockup, plus a real cyclic (``index -> a -> b ->
index``) and diamond (``index`` reaching ``b`` both directly and through ``a``)
fixture, before the test suite was written.  The original implementation
commit added nine dedicated tests for single- and multi-level recursion, cycle
detection, diamond de-duplication, ``--sections-only``, ``--outline-depth``
across the file boundary, ``--no-toctree``, ``--json`` shape, and
heuristic-mode invisibility; later changes added related toctree coverage.

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Resolved: nested toctree containers retain provenance
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

*Current status: shipped 2026-08-02.*

Found 2026-07-30 while regenerating this page's worked examples against real
output: existing coverage checked every cross-file HEADING's own
``{docname}:`` prefix but not a nested toctree CONTAINER line's — and the
container line was missing it.  Reproduced live on the same 4-file shape this
section documents: the top-level toctree in ``index.rst`` (local file,
correctly unprefixed) and the nested one inside ``sub1.rst`` (foreign file,
from ``index.rst``'s own vantage point) printed identically — ``11-13: toctree
(1 entry, maxdepth=unlimited)`` — with no way to tell from the line itself
which file it lived in, unlike every heading around it.  The same gap existed
in ``--json``: a ``toctrees`` entry carried no ``docname`` key at all, not even
``null``, while outline heading entries always did.

Resolved by giving ``ToctreeEntry.docname`` the same predicate as
``OutlineEntry.docname``: ``None`` means local to the file being outlined; a
non-empty value identifies an entry pulled from that foreign document.  Text
rendering now prefixes foreign nested containers and foreign cycle markers,
while the root container remains bare.  JSON exposes the same nullable field
instead of deleting it, so text, structured output, and ``context`` share one
provenance model.

The TDD red phase pinned all three boundaries independently: nested text
required ``sub1:``, the local root forbade ``index:``, and JSON required
``[null, "sub1"]`` for root and nested containers; the cycle fixture separately
required its foreign ``b:`` prefix.  The focused three tests, all 19
toctree-related tests, and the complete 1,247-test ``test_check_rst.py`` module
passed after the model-level fix.  The issue remains recorded here next to the
design and fixture that exposed it, per the report-friction contract in
:doc:`development`.

=======================================================
Subcommands: flag-soup incompatibilities become verbs
=======================================================

Current status: shipped 2026-08-07; global project-identity options and
``--no-config`` added 2026-08-08.

``_validate_cli_args`` used to be a hand-written incompatibility matrix over
roughly 30 flags: a mutually-exclusive mode group (``--fix``/``--fix-only``/
``--diff``/``--diff-only``), three flags that were each individually
self-contained and rejected nearly everything else (``--diff-json``, ``--refs``,
``--context``), and a scatter of narrower pairwise rules (``--normalize-blank-
lines`` required ``--fix``/``--diff``, ``--outline-depth`` required
``--outline``, ``--git-scope`` excluded ``--recursive``, and so on). None of
that was incidental complexity to trim — every one of those checks existed
because the underlying operations genuinely don't compose, the same way
``--fix-only``'s own docstring already said so explicitly ("a fast mutation-
only counterpart of ``--diff-only``"). The flags were never really peers on
one flat surface; the incompatibility matrix was a hand-maintained proxy for a
grouping ``argparse`` subparsers express directly, in the help text itself,
enforced structurally rather than by a runtime rejection message. Replaced by
``check``/``fix``/``diff``/``outline``/``context``/``refs``/``diff-json``
verbs (``_build_cli_parser()``); ``_validate_cli_args`` and the flat parser
are deleted.

Three "shapes" cover the mutating/reporting flag surface, each a parent
parser shared by the subcommands that need it. ``--config``/``--no-config``/
``--sphinx-src``/``--build-dir`` sit outside this table entirely: they are
global options on the main parser (extension below, 2026-08-08 — git-style,
before the verb: ``check_rst --sphinx-src docs check file.rst``, not
``check_rst check --sphinx-src docs file.rst``), not part of any one shape,
because every verb except ``diff-json`` can read them identically.

.. list-table::
   :header-rows: 1
   :widths: 14 56 30

   * - Shape
     - Flags it carries
     - Used by
   * - full
     - ``--recursive``/``--git-scope``/``--exclude``,
       ``--quiet``/``--verbose``/``--max-output-lines``/``--word-samples``,
       ``--no-warnings``/``--skip-fixable``/``--no-adornments``/
       ``--no-directives``
     - ``check``, ``fix``, ``diff``, ``outline``
   * - fast (``mutating`` parent)
     - ``--recursive``/``--git-scope``/``--exclude``, ``--quiet`` —
       deliberately no ``--sphinx-src``/``--build-dir`` at all: explicit
       use of either is rejected by ``_validate_fast_allowlist``, and a
       *configured* one is reported inactive rather than applied
     - ``fix --fast``, ``diff --fast``
   * - single-file
     - exactly one positional file, no shared parent left — see the
       2026-08-08 extension below
     - ``context``, ``refs``
   * - none
     - two positional JSON files, nothing else
     - ``diff-json``

------------------------------------------------------
Tier 1: the mode group became check/fix/diff/outline
------------------------------------------------------

``check_rst check``, ``check_rst fix``, ``check_rst diff``, ``check_rst fix
--fast``, ``check_rst diff --fast`` — the existing mutually-exclusive mode
group, renamed and restructured onto the *full* parent (plus *fast* for
fix/diff's own editorial flags), with ``--fast`` resolved as a flag scoped to
each verb's own parser rather than separate ``fix-only``/``diff-only`` verbs
(see "Naming," below). Making the old flagless default (``check``) an
explicit verb was itself a small win — a bare invocation now says what it
does. This tier deleted the mode-group mutex and both old
``--fix-only``/``--diff-only`` allow-lists (replaced by ``_FAST_ALLOWLIST``,
scoped per verb): an editorial flag like ``--single-space-prose`` simply
isn't *defined* on ``check``'s parser, so passing it there is an ordinary
"unrecognized argument," not a bespoke rejection message.

"A consolidated edit-validation cycle" above (working name ``--edit-cycle``)
still slots into this exact tier once built — one more *full*-parent verb
(``check_rst cycle``, or whatever name it keeps) alongside ``fix``/``diff``,
not a flag bolted onto one of them.

---------------------------------------------------------------
Tier 2: the three self-contained flags became their own verbs
---------------------------------------------------------------

``check_rst diff-json OLD.json NEW.json`` (*none* parent), ``check_rst refs
FILE``, ``check_rst context ENTRY FILE`` (each on its own dedicated parser).
These three were already, behaviorally, subcommands wearing a flag disguise
before this redesign — each used to hand-reject the rest of the flag surface
in its own ``_validate_cli_args`` block; now each simply never defines a
flag it doesn't need. ``diff-json`` additionally rejects the global project
flags explicitly (``_validate_diff_json_args``) rather than silently
ignoring them, since it reads no RST project at all — the same
fail-loudly precedent as every other verb-incompatible combination.

---------------------------------
Tier 3: the two forks, resolved
---------------------------------

``outline``: resolved as inverting the old default. "A structure-only view"
above already treated ``--outline-only`` as a named macro for a flag stack
("one flag instead of the ``--quiet --skip-fixable --no-warnings --outline``
stack"). The dedicated ``outline`` verb makes that macro the default
behavior — pure structure, no finding noise — with an opt-in
``--with-findings`` to layer the old plain ``--outline`` (structure *and*
findings together) on top. Stated plainly, as agreed: this is a real
behavior change, not just a rename.

``json``: resolved as ``check_rst check --format=json``, unifying it with
plain ``check`` rather than giving it its own verb, since underneath it is
the same run with a different writer. ``--no-toctree``'s old "requires one
of outline/outline-only/json/context" rule and ``--max-output-lines``'
json-incompatibility both became narrower, verb-scoped checks
(``_validate_check_args``) instead of surviving as the old five-way
incompatible-mode tuple.

-----------------------------------------------------
What still needs a runtime check regardless of tier
-----------------------------------------------------

Subcommands removed *mode* conflicts, not *value* validation:
``--max-output-lines >= 2``, ``--outline-depth >= 1``, ``context ENTRY``
non-empty, ``--word-samples >= 0`` stayed exactly as they were, now on
whichever parser owns each flag (``_validate_check_args``,
``_validate_outline_args``, ``_validate_context_args``).

-------------------------
Two decisions, resolved
-------------------------

^^^^^^^^
Naming
^^^^^^^^

Resolved: ``fix --fast``/``diff --fast`` — a flag scoped to each verb's own
parser, not separate ``fix-only``/``diff-only`` verbs. Both would have
deleted the identical validation code; the runtime status text was renamed
to match either way (``check_rst: N file(s)... fixed [fast]``, ``fast
scope — ...``, and the config-echo's ``inactive (--fast)`` marker).

^^^^^^^^^^^^^^^^^^^^^^^^
Backward compatibility
^^^^^^^^^^^^^^^^^^^^^^^^

Resolved: a clean break, recorded as the 0.2.0 version bump, no deprecation
shim. ``check_rst --fix file.rst`` (this project's own tooling, and at
least one downstream project's build wrapper) stopped working the moment
``d64ce2e`` landed; every known caller had to migrate to ``check_rst fix
file.rst`` in the same release.

------------------------------------------------------
Extended 2026-08-08: global project-identity options
------------------------------------------------------

``--config``/``--sphinx-src``/``--build-dir`` initially landed on each
verb's own parser (the *full* and *single-file* shapes above), matching
where they lived on the old flat CLI — each subparser called the same
``_add_project_flags`` helper. Reviewed the same day (Max, prompted by
noticing ``--sphinx-src`` "is rather global option," by analogy with
``git``'s own ``-C``/``--git-dir``): these three identify *which project* to
operate on, orthogonal to *which operation* (check/fix/diff/…) runs.
Moved to the main parser, once, before the verb — git-style, never
repeated per subcommand: ``check_rst --sphinx-src docs check file.rst``, not
``check_rst check --sphinx-src docs file.rst``. ``diff-json`` alone rejects
them (Tier 2, above); every other verb reads them identically.

A new ``--no-config`` joined them the same day. Previously there was no way
to skip ``.check_rst.toml``/``pyproject.toml`` auto-discovery at all — a
malformed or unknown-key committed config would fail loudly on discovery
alone, before any CLI flag got a say, even for a run that wanted to ignore
it entirely. ``--no-config`` opts out of discovery completely (as if the
working directory declared no project facts); ``_validate_config_flags``
rejects it alongside an explicit ``--config``, a direct contradiction
neither flag alone could satisfy.

Found live during the move, before either flag shipped: argparse's
``_SubParsersAction.__call__`` parses each subparser into a *fresh*
``Namespace``, then unconditionally copies every one of its keys back onto
the parent — no ``hasattr`` guard at that merge step, unlike the
single-parser default-fill loop every other name in ``_CLI_ATTR_DEFAULTS``
relies on. Confirmed by direct reproduction: ``check_rst --no-config check
file.rst`` measured ``args.no_config`` as ``False``, and a configured
``sphinx-src`` survived under a global ``--sphinx-src`` only by coincidence
(this repo's own test fixture happened to declare the same path in
``.check_rst.toml``). Fixed by removing ``build_dir``/``config``/
``no_config``/``sphinx_src`` from ``_CLI_ATTR_DEFAULTS`` entirely — every
subparser's own ``set_defaults()`` call had been silently resetting them to
``None``/``False`` after the merge, clobbering whatever the user passed
before the verb. Pinned by
``test_cli_attr_defaults_excludes_global_project_flags`` and a
six-verb-parametrized ``test_global_sphinx_src_survives_verb_dispatch``,
both in ``tests/test_cli_subcommands.py``.

A second, independent bug surfaced fixing the config-echo's "inactive"
label for the move: the branch marking a *configured* (not
explicitly-flagged) ``sphinx-src``/``build-dir`` inactive under ``--fast``
checked only ``args.fix_only``, never ``args.diff_only`` — so ``fix --fast``
correctly reported ``inactive (--fast)`` while ``diff --fast`` silently
applied the configured value instead, on the identical config (confirmed by
direct reproduction against the same ``.check_rst.toml`` before the fix).
Fixed (``args.fix_only or args.diff_only``, both branches); pinned by
``test_cli_diff_fast_ignores_configured_sphinx_and_never_parses``, the
``diff --fast`` sibling of the pre-existing ``fix --fast`` regression test.

=====================================================
Targeted aligned-table to list-table transformation
=====================================================

*Current status: accepted 2026-08-02; shipped 2026-08-08 as the*
``list-table`` *verb.*

The role/instance/context-state table distilled from the Claude feedback case
provided the motivating example: its prose-heavy cells are clearer and cheaper
to maintain in the ``.. list-table::`` form now present in
:doc:`rules`, while manually reconstructing the aligned source was
expensive enough that Claude Code declined the edit as disproportionate work.
The benefit is in source authoring and diff locality, not structural
retrieval: docutils already normalizes grid, simple, and directive tables to
the same two-dimensional ``table`` node, so ``outline``, ``context``, and the
planned column query see equivalent structures before and after conversion.

---------------------------------------
Settled shape, resolved from the fork
---------------------------------------

Two forks this entry originally left open were resolved during
implementation, both by explicit decision (Max) rather than by default:

* **A bulk-by-default verb, not a mandatory single-selector one.** The
  original sketch (``check_rst transform DOC:table@LINE --to list-table
  FILE``) required naming exactly one table per invocation. Reconsidered:
  every mechanically-eligible table in the selected file(s) converts by
  default — the same scope model ``fix``/``diff`` already use
  (``--recursive``/``--git-scope``/``--exclude``) — with ``--only``/``--skip``
  (both repeatable, ordinal-indexed in document order) as the opt-in
  narrowing mechanism instead of a mandatory selector. The combination rule:
  the eligible set starts as every table, narrows to ``--only``'s ordinals if
  any were given, then ``--skip`` removes ordinals from whatever that is.
* **A dedicated, self-explanatory verb name, not a flag.** ``--to
  list-table`` implied other destination formats were possible; there is
  only one. Renamed to the bare verb ``list-table`` (dropping ``--to``
  entirely) — the verb name states the destination on its own, the same
  way ``diff-json``/``refs``/``context`` already do, discoverable without
  reading a flag's own description.

Resulting contract::

    check_rst list-table FILE                       # dry-run diff, every eligible table
    check_rst list-table --apply FILE                # write
    check_rst list-table --only 2 FILE               # allowlist: only the 2nd table
    check_rst list-table --skip 2 --skip 5 FILE      # denylist: everything except #2 and #5

An ``--only``-named table that turns out refused (a span, an unsupported
option, an ineligible kind) is fatal for that file — the user asked for that
exact table. A refusal among the default, unnamed "every eligible table"
scope is reported but does not block converting the file's other eligible
tables — the same review-don't-block spirit as ``--skip-fixable``, not a
hard-error-either-way rule. ``--sphinx-src``/``--build-dir`` are rejected
(this verb is bare-docutils only, the same as ``find_tables`` itself);
``--config`` stays valid, since it still roots this verb's own
``--recursive``/``--git-scope`` discovery.

-------------------------------------------
Mechanical conversion, confirmed by probe
-------------------------------------------

The first version deliberately accepted only bare tables and
``.. table::``-wrapped tables with an optional caption.  The source-model
evaluation on 2026-08-09 proved and implemented the next increment:
``:name:``, ``:class:``, ``:align:``, ``:width:``, explicit numeric
``:widths:``, and ``:widths: grid`` all preserve the canonical tree when
carried to list-table syntax (``grid`` materializes the effective numeric
geometry).  A direct copy of ``:widths: auto`` does not: list-table manufactures
equal colspecs instead of retaining the aligned grid's parsed values.  The
2026-08-09 follow-up found the exact mapping rather than normalizing that
difference away: emit the parsed values as explicit widths and carry
Docutils' own ``colwidths-auto`` class.  HTML/LaTeX writers still select
automatic layout, while the canonical doctree retains the original colspecs.

Docutils' own ``GridTableParser``/``SimpleTableParser`` are used directly
rather than reimplementing the alignment grammar — confirmed by direct probe
that each cell arrives as ``(morerows, morecols, line_offset, StringList)``,
where the ``StringList`` is the cell's own **raw source text**, already
dedented, not a rendered tree. That makes verbatim preservation of inline
markup, references, and nested block content mostly copy-and-reindent rather
than re-serialization. A non-zero ``morerows``/``morecols`` on any real
(non-``None``) cell is list-table's hard, explanatory refusal — merged cells
are never flattened, duplicated, or guessed at.

--------------------------------------------
Semantic validation: simpler than expected
--------------------------------------------

The original entry expected the validation predicate to need a documented
exception for column-width representation. Confirmed by direct probe: it
does not. Emitting ``:widths:`` on the generated ``list-table``, derived
directly from the original table's own ``colspecs``, makes docutils compute
the *exact same* ``colwidth`` per column — not merely a proportional
equivalent. One genuine, one-directional delta is a ``'colwidths-given'``
class Docutils adds to any ``<table>`` node whose ``:widths:`` was given
explicitly on ``list-table`` syntax specifically — a grid/simple table never
carries it, having no "auto" alternative to distinguish itself from.  The
other normalized value is position bookkeeping: a ``system_message`` node's
physical ``line`` attribute shifts when identical ambiguous cell source moves
under list-table indentation.  With those two values excluded from the
comparison, canonical-tree equality (the same modeling technique as
``_text_space_evidence``'s permitted-delta model) is the complete predicate —
parse both whole-file variants and compare.  The extended implementation
applies that proof to each candidate first, so one unproven table does not
discard independent conversions in the same default-scope run, then repeats
the proof for the combined candidate before any write.

-----------------------------------------------------
A pre-existing bug, found building the real fixture
-----------------------------------------------------

Building the acceptance fixture from a real table (below) surfaced a defect
in ``find_tables`` itself, unrelated to ``list-table``'s own logic:
``_table_end`` extended a table's reported end only through a trailing
grid border/simple-table rule, assuming docutils' own ``.line`` tracking
already located the table's true last content line. For a table whose
*last row* spans multiple physical source lines, that assumption breaks —
docutils only reports the multi-line cell's first physical line, so the old
approach stopped there, one or more lines short of the real trailing border.
This silently truncated the reported range for **any** grid table with a
multi-line final row, in ``outline``/``context`` too, not only for this
feature's own use of it. Fixed by also extending through a grid table's own
bare ``|``-led continuation lines before looking for the border (no other
RST construct produces one immediately following confirmed table content).
The 2026-08-09 evaluation found the corresponding simple-table case: its
continuations have no marker, so the end is now recovered with Docutils'
matching-rule stopping predicate.  Independent regressions in
``tests/test_document_structure.py`` pin both syntaxes.

--------------------------------------------------
Acceptance evidence: a real table, not synthetic
--------------------------------------------------

The principal regression fixture is a real grid table — three formatting
styles (inline bold-in-literal, a real heading, a definition list) compared
by line cost, multi-line final cell included — matching this project's own
"real evidence over invented examples" convention rather than a hand-built
synthetic case.
``test_acceptance_real_world_table_converts_and_preserves_content``
(``tests/test_list_table.py``) converts it, asserts every inline-literal
span and the multi-line cell's logical structure survive reindentation,
confirms canonical-tree equivalence, and runs the converted result back
through ``check_rst check`` itself for a clean exit. Further focused coverage
(also in ``tests/test_list_table.py`` and the ``list-table``-specific tests in
``tests/test_cli_subcommands.py``/``tests/test_document_structure.py``): the
``--only``/``--skip`` ordinal resolver and their combination rule, continued
captions and directive-option preservation, span rejection for both row and
column merges, exact existing-list/CSV outcomes and ordinals, a direct
``:widths: auto`` canonical-model mapping, ancestor-first nested conversion,
per-table and combined semantic proof failures, partial safe writes, dry-run
non-mutation, and the CLI-level exit/``--quiet``/bare-Docutils behavior.

-------------------------------------------
Safety boundary after source-model review
-------------------------------------------

The 2026-08-09 review distinguished missing source capture from genuine
representation blockers.  Exact block capture now preserves CRLF/LF outside
the mutation, handles multiple blank lines before directive content, retains
enclosing-list indentation, and uses Docutils' own simple-table termination
predicate for multi-line final rows.  Directive options and rich cell content
were feasible; tests prove them rather than continuing to refuse them.

One representation blocker remains intentionally refused, with a stable
reason code, table context, impact, and next action in default CLI output:

* ``list-table.span``: list-table syntax cannot encode a merged row or column.

Two former boundaries are now proven transformations.  ``:widths: auto`` maps
to explicit parsed widths plus ``colwidths-auto`` and retains exact canonical
equality.  Default bulk conversion handles nested aligned tables in one run:
it converts ancestors in memory, rediscovers descendants at their exposed
source ranges, and proves every stage plus the final aggregate.  The
``list-table.nested-aligned-table`` code remains only for a descendant selected
without authorizing its still-aligned ancestor; ``--only`` never expands its
own scope implicitly.

Parser/range invariants and canonical-tree divergence are reported separately
as ``source-model`` and ``semantic-proof`` errors/refusals.  They never escape
as a traceback and never authorize a guessed rewrite.

***********************************************************
Declined decisions and reasons — counter-evidence welcome
***********************************************************

===========================
Grid table auto-alignment
===========================

*Current status: declined; counter-evidence welcome.*

This project's house style is ``list-table`` precisely because it needs no
character arithmetic; building an aligner for a syntax the workflow avoids is
effort against the current.  Revisit if foreign-project audits actually surface
grid tables needing fixes.

=========================================
Similarity-ranked hierarchy suggestions
=========================================

*Current status: declined as semantic judgment.*

("where should OAuth2 go") — semantic similarity is the AI's half of the
contract by the tool's founding principle; the parser's half is already
``--outline``.

================================
Cross-page content consistency
================================

*Current status: declined as semantic judgment.*

("PUT documented here, missing there") — reasoning about meaning, not
structure.

===================
Navigation/search
===================

*Current status: declined; existing search plus structural queries cover the
observed need.*

("where is MQTT discussed") — ``git grep`` across the journal's full history
plus ``--outline`` for context already covers it.

===============================
Min/max-frequent word display
===============================

*Current status: declined at the raw Phase 0 layer; the useful prose-level
alternative is shipped.*

(evaluated 2026-07-19, by probe): the min end is degenerate — 73% of the June
corpus vocabulary occurs exactly once, so "the least frequent word" is an
arbitrary pick among thousands of ties — and the max end at the raw-token layer
is markup and stopwords (``-``, ``de``, ``|``, ``в``); a meaningful version
needs linguistic filtering, which belongs to a doctree-level prose analysis,
not Phase 0.  The useful core shipped instead: distinct and once-only counts
for words and chars — and the same evening, the dependency scan found the
filtering already in-tree (sphinx.search stopwords + snowballstemmer), so the
meaningful version shipped as "top prose words" at the doctree layer; the
decline stands for the raw Phase 0 layer, where it belongs.

=======================================================
Splitting ``_helpers.py`` into smaller domain modules
=======================================================

*Current status: declined without a stronger cohesion or growth trigger.*

(evaluated 2026-08-10, from the 8-agent review of the interrupted-period
work, f0676f0..ba4813d, which called it a "dumping ground"): the historical
snapshot put it at 750 lines, below 6 of the other 11 ``cli/`` modules.  The
2026-08-12 refresh reaches the same conclusion: 905 lines, below 6 of the
other 12 modules (``_pipeline.py`` 937, ``_formatting.py`` 1012,
``_reports.py`` 1227, ``_document.py`` 1287, ``_sphinx.py`` 1313, and
``__init__.py`` 1411).  The real complaint is
cohesion, not size: it mixes six unrelated concerns (Git operations,
adornment/hierarchy policy constants, source hygiene/normalization,
title-block iteration, doctree-node helpers, enum-marker rendering)
that never call into each other, so a split along those lines would be
mechanically safe — but there is no single obviously-correct shape (two
files or six are both defensible), and it would touch the import lines
of every other ``cli/`` module.  Put to the project owner directly
rather than picked unilaterally; the decision was to leave it as-is,
consistent with AGENTS.md's caution against decomposing a module
outside a mechanical change or one already protected by characterization
tests.  Revisit if it actually grows past its current mid-pack size, or
if a 7th unrelated concern gets added to it.
