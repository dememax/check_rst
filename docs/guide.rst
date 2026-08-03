.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Detailed operational guide and CLI contract — check_rst project

###########
check_rst
###########

.. contents:: Contents
   :depth: 3
   :local:

``check_rst`` is a **deterministic front end** for reStructuredText and
Sphinx documentation.  It performs the symbolic processing that language
models are structurally weak at, and exposes verified document structure
for reading and editing.  Viewed as a CLI utility it is a linter — the
least interesting way to view it; for an AI assistant working in this
repository it is a **delegation contract**, and this page explains that
contract: what to delegate, how, and why.

Concretely, it is a four-phase checker and fixer: byte hygiene
(Phase 0), RST formatting rules (Phase 1), Sphinx-aware structure
resolution (Phase 2), and a real ``sphinx-build`` integrity check
(Phase 3).  It is project-agnostic — automatic configuration treats the
current working directory as the project root, while ``--config FILE``
selects a project explicitly from any directory.  Install the console entry
point once, then invoke ``check_rst`` from the documentation project being
checked.

The formatting rules themselves are documented in the tool
(``check_rst --help``) and are deliberately *not* duplicated in repository
instruction files: you do not need to know them, you need to invoke the tool
that enforces them.

.. important::

   If you read nothing else: writing, declare a new section with a
   9-character placeholder underline and no overline, then run
   ``check_rst --skip-fixable`` (review WARNINGs) → ``check_rst --fix``
   (bare form when the whole dirty RST set is yours) → ``check_rst``
   (confirm clean).  In a shared dirty worktree, add the same
   ``--git-scope path/to/owned.rst`` allowlist to all three commands.
   Reading, run ``check_rst --outline-only <file>`` before editing
   anything you have not already read this session.  Everything below
   is why those two habits are enough.

*******************
Documentation set
*******************

This page is the operational entry point.  Read the narrower companion
whose subject matches the task instead of loading implementation history
and the roadmap on every use:

* :doc:`example` — one complete check/fix/analyse demonstration;
* :doc:`rules` — why semantic WARNINGs remain human decisions;
* :doc:`development` — the feedback loop and evidence from real use;
* :doc:`roadmap` — open, completed, deferred, and declined ideas;
* :doc:`integration` — launcher, documentation layers, tests, and
  history.

***********************************************
The contract: delegate syntax, keep semantics
***********************************************

An LLM processes text as tokens, not characters.  Exact character
counting is therefore statistically plausible rather than reliable — and the
source Journal corpus contains many Cyrillic titles, where tokenization is even
less related to character count (``Конфигурация`` is a handful of tokens
whose boundaries say nothing about its 12 characters).  Display-width
rules (CJK counts 2 columns, combining accents 0) make hand-computation
worse still.  Asking an LLM to produce an adornment of exactly
``column_width(title) + 2`` is asking it to reconstruct information its
internal representation never held.

The task split follows directly:

.. list-table:: Who does what
   :header-rows: 1

   * - Task
     - Owner
   * - Choosing document structure, wording, section nesting
     - AI (semantic)
   * - Judging whether a bold line is really a heading
     - AI (semantic)
   * - Choosing which inline role survives when RST cannot nest two roles
     - AI (semantic)
   * - Synthesizing calendar notes into aggregation pages
     - AI (semantic)
   * - Computing adornment widths, characters, and required title separators
     - ``check_rst --fix`` (deterministic)
   * - Normalizing leading, repeated separator, and terminal blank lines
     - ``check_rst --fix --normalize-blank-lines`` (opt-in, parser-verified)
   * - Collapsing repeated spaces in visible section-title text
     - ``check_rst --fix --collapse-title-spaces`` (opt-in, permitted delta)
   * - Enforcing single-space style in eligible paragraph text
     - ``check_rst --fix --single-space-prose`` (opt-in, permitted delta)
   * - Tracking the 32-character adornment hierarchy
     - ``check_rst`` (deterministic)
   * - Line endings, BOM, byte hygiene
     - ``check_rst --fix`` (deterministic)
   * - Detecting inline markup silently trapped inside another inline role
     - ``check_rst`` (deterministic)
   * - Recovering a file's section tree and code-block inventory
     - ``check_rst --outline`` (deterministic)
   * - Verifying ``:doc:``/``:ref:`` cross-references actually resolve
     - ``check_rst`` Phase 3 (deterministic)

The pipeline is the one compilers have used for decades: the AI emits
*semantic intent*, the tool materializes *valid source*.  A probabilistic
stage followed by a deterministic stage is strictly more robust than two
probabilistic stages — the second stage no longer compounds uncertainty.

The principle behind the whole project, stated once in full: **the goal
is not to make the AI better at reStructuredText — it is to stop
requiring the AI to perform work that deterministic software can perform
perfectly.**  Both halves of the contract follow from it: the writing
workflow delegates syntax generation, the reading workflow delegates
structure recovery.  Nothing in the principle is specific to RST — it
extends to any format whose syntax is low-entropy but character-exact.

**********************************************************
Writing RST: declare intent, let the tool materialize it
**********************************************************

==========================
The placeholder workflow
==========================

Never write finished adornments.  Declare that a section exists and let
``--fix`` compute everything else::

    Sensors
    *********

That 9-character underline (no overline) is not syntax — it is metadata
meaning "a new section starts here".  ``check_rst --fix`` converts it
into a correct overline+underline pair, exactly two columns wider than
the title's display width.  Nine characters is the convention because
the tool needs at least 4 to recognize an underline attempt at all, and
9 is unambiguous for any real title.  (This is the actual placeholder
used by :doc:`example`, before ``--fix`` ever touched it.)

The split of responsibility is precise: the *length* is always the
tool's job, but the *character* is your declaration of which level the
section belongs to — pick the one your target level already uses in
this document (check ``--outline``), same as matching the surrounding
sections.  ``--fix`` remaps characters only when the document's
first-appearance order deviates from the project ranking; it cannot
read your mind about intended depth — that is the semantic half of the
contract, and it stays yours.

When creating a whole new multi-level file, write every title this way,
choosing underline characters in the order the levels first appear
(``#`` for the page title, then ``*``, ``=``, ``-``, ``^``, ``"``); the
lengths never matter.  This very page was written exactly so and fixed by
the tool.

==============================================
Source verbosity buys geometry and retrieval
==============================================

RST itself permits underline-only section titles.  This project deliberately
requires both an overline and an underline, exactly two display columns wider
than the title.  That convention is not source-compact: it consumes more
characters and lines than an ATX Markdown heading, and changing a title makes
the old adornment widths stale.  The placeholder workflow exists so the
creator declares semantic structure without manually paying that measurement
cost.

The extra geometry is intentional.  A cold human reader can find section
boundaries and hierarchy while scanning source before reading the prose.  A
fresh-context AI can ask the parsed model for a named section, its verified
range, and its surroundings.  Automation receives an actual section node
instead of typography whose structural meaning must be guessed.  The project
accepts a larger byte count where it buys those repeated human, AI, and
automation benefits.

.. list-table::
   :header-rows: 1
   :widths: 24 35 41

   * - Measure
     - Informal bold or compact markup
     - Real project-style RST section
   * - Source compactness
     - Fewer characters, separators, and blank lines
     - More physical markup; geometry delegated to ``--fix``
   * - Human scanning
     - Dense source with a weak inline cue
     - Strong, pre-attentive boundaries and visible hierarchy
   * - AI retrieval
     - Often requires a full read or lexical search
     - Named outline entry, selector, range, and targeted context
   * - Automation
     - Emphasis may have no structural meaning
     - Explicit doctree node and stable section identity

This is a lifecycle compactness trade: spend source lines once when doing so
prevents repeated full reads, fuzzy searches, and ambiguous edits later.  It
does not justify heading inflation.  Short co-equal legend, checklist,
classification, and chronological-register entries remain more honestly
represented as lists; decorative emphasis should become prose.  The
role/instance/context gate and the ``promote``/``retain``/``rewrite``
dispositions are specified in :doc:`rules`.

Markdown still wins the local syntax comparison: a real Markdown heading is
compact, visually recognizable, and easy to search.  When Markdown is the
primary source, promote an independently meaningful bold opener to a real
Markdown heading upstream; Pandoc is the bridge that lets ``check_rst``
audit that structure, not a reason to replace Markdown with RST.

Section titles also help orient ordinary patches because distinctive nearby
heading lines are recognizable context, while ``check_rst`` provides the
stronger guarantees: verified ranges and selectors, plus section-identity
matching in ``--diff-json``.  Do not claim that Git currently puts RST
titles into hunk headers automatically: this repository has no RST diff
driver configured in ``.gitattributes``.  A future driver could make titles
formal hunk anchors, but that would be a separate integration enhancement,
not a present ``check_rst`` feature.

==========================================================
The same principle applies to numbered lists: use ``#.``
==========================================================

The identical reasoning, a different construct: never hand-write
``10.``, ``11.`` on a growing enumerated list.  Use ``#.`` (RST's own
auto-numbering marker) for every item instead, and let docutils
compute the actual digits — the same "declare intent, the tool
materializes syntax" split as the placeholder workflow above, just
applied to sequence numbers instead of adornment lengths.

Found live in :doc:`roadmap` (2026-07-26): its "Agreed
direction" register had grown to an explicitly-numbered 11-item list — ``1.``
through ``11.``, each digit hand-typed — the exact failure mode the
placeholder workflow exists to prevent, just for counting instead of
measuring.  Adding a 12th item means correctly knowing 11 items
already exist; inserting one in the middle means correctly
renumbering every item after it by hand — precise sequential counting
is exactly the class of task an AI performs unreliably, whether the
thing being counted is characters in a title or items in a list.
``#.`` sidesteps both failure modes at once: the count is never
tracked by hand, and an insertion anywhere never requires touching
any other line.

To differentiate a nested list from its parent visually, use a
DIFFERENT numbering style per level, not per item: ``#.`` alone always
renders arabic (confirmed by direct probe — it carries no memory of a
different style, so a ``#.``-only list can never render as
``a.``/``b.``/``c.``), but writing one real, explicit marker on a
nested list's FIRST item establishes that level's own style, and every
item after it can go straight back to ``#.``, auto-continuing
correctly in that same style — confirmed by direct probe::

    #. first
    #. second

       a. explicit — establishes THIS list as loweralpha
       #. auto-continues as 'b.'
       #. auto-continues as 'c.'

    #. third

Exactly one hand-typed marker per nesting level (never one per item)
is the actual floor: the parent needs none at all (``#.`` alone
already defaults to arabic), and each deeper level needs only its own
first item to declare a style — ``a.`` for lowercase-alpha, ``A.`` for
uppercase, ``i.`` / ``I.`` for roman.  This is exactly how the roadmap's
"Reference intelligence" sub-list is written.

================================================
Titles should carry information, not structure
================================================

The tool cannot check this — it is entirely semantic, not a WARNING
candidate — but it belongs stated explicitly rather than assumed
obvious, the same way bold-as-heading is called out in
:doc:`rules` rather than left implicit (Max, 2026-07-24): a
section title should say what is
*in* the section, not merely that a section exists.  ``Rationale``
tells a reader nothing a bare heading marker didn't already say;
``Rationale about determinism in production`` does.  A child section
does not need to repeat context its parent already established — the
parent's own title already scopes it — so the added specificity is
about the child's *own* content, not a restatement of the whole path
to it.  This is the AI's half of the contract (deciding what a section
is about), not the tool's; there is no deterministic test for "is this
title specific enough."

=====================
The three-step loop
=====================

Within a configured Git project::

    check_rst --skip-fixable   # 1. review WARNINGs (exit 0)
    check_rst --fix-only       # 2. bare form only — mutate without validation phases
    check_rst                  # 3. confirm clean

When unrelated or user-owned RST changes share the worktree, preserve the
same Git-diff protection while selecting only your file::

    check_rst --skip-fixable --git-scope path/to/owned.rst
    check_rst --fix-only --git-scope path/to/owned.rst
    check_rst --git-scope path/to/owned.rst

No long options: ``.check_rst.toml`` at the repo root declares
``sphinx-src`` and ``build-dir``, so the bare commands already run
verified with Phase 3 — see "Per-repo configuration" below for the
full contract.

Step 1 shows only what needs *your* judgment (see "What the tool
deliberately leaves to you").  It reports how many auto-fixable findings
were suppressed per file and removes only their duplicate structural
messages from Sphinx; unrelated Sphinx warnings remain visible.  Step 2
plans the complete selected set, applies every deterministic fix, and stops
without parsing or building.  Step 3 is the single full validation run and
verifies convergence — a clean pass is a machine-checked guarantee, not an
impression.  The fixed ``--build-dir`` keeps repeat runs cheap: Sphinx
recompiles only changed pages.

=================================
What ``--fix`` computes for you
=================================

* Byte hygiene: BOM removal, CRLF/CR and exotic line separators to LF,
  trailing whitespace on every source line (Unix LF policy, whole-file).
* Adornment geometry: display-width+2 lengths on both sides, overline
  synthesis for placeholder underlines, and insertion of a missing blank
  separator around a title block.
* Hierarchy: remaps adornment characters so first-appearance order
  matches the project ranking — the check and the remap are the same
  computation, so a clean check guarantees ``--fix`` changes nothing.

Repeated blank separators are intentionally absent from that default list.
They need the separate, parser-verified operation below because an empty source
line can be literal content rather than disposable geometry.

=================================
Opt-in blank-line normalization
=================================

Use ``--normalize-blank-lines`` only with ordinary ``--fix`` or ``--diff``::

    check_rst --diff --normalize-blank-lines path/to/document.rst
    check_rst --fix --normalize-blank-lines path/to/document.rst

The operation considers leading empty lines before content and repeated
empty-line runs between content or at EOF, and changes a run only when the
complete docutils tree remains identical.  Interior runs retain one separator.
Terminal runs retain the single empty ``split`` element representing the
normal Unix final newline, so ``Text.\n\n\n`` becomes ``Text.\n`` rather than
losing termination.  It first
verifies the common all-runs candidate in one parse.  If a literal,
parsed-literal, raw, or other whitespace-preserving construct makes that
unsafe, each run is retried independently: safe block separators elsewhere in
the same document still collapse, while content-bearing runs remain byte for
byte.  A leading run is removed completely when a first non-empty document
line exists; an all-blank file remains unchanged because it has no first
element and therefore no useful leading-versus-trailing distinction.

This is an explicit whole-document source normalization for every selected
file, including files selected through ``--git-scope``.  Preview it when source
history matters.  The option is rejected with ``--fix-only`` and
``--diff-only``: their defining contract is that no RST parser runs, whereas
this operation's safety proof is the parse comparison itself.  Internal spaces
inside a title or paragraph remain editorial content and are never changed by
this option.

===============================
Opt-in editorial text spacing
===============================

Two separate modifiers expose two separate authoring decisions::

    check_rst --diff --collapse-title-spaces path/to/document.rst
    check_rst --fix --collapse-title-spaces path/to/document.rst
    check_rst --diff --single-space-prose path/to/document.rst
    check_rst --fix --single-space-prose path/to/document.rst

``--collapse-title-spaces`` changes visible text owned by section titles.
``--single-space-prose`` changes eligible visible text owned by paragraphs,
including ordinary emphasis, link labels, and list-item paragraphs.  The two
scopes are independent and may be requested together.  Title edits run before
the structural fixer so their adornment widths are recomputed in the same
plan.

These are editorial transformations, not parser-equivalent hygiene.  Only an
internal run of two or more ASCII U+0020 spaces between non-space characters
is replaced with one ASCII space.  Leading and trailing whitespace,
indentation, tabs, non-breaking or other Unicode spaces, and newlines are not
candidates.  Literal and inline-literal text, raw content, code, math, and
substitution payloads are protected.  RST syntax such as list-marker spacing
and aligned-table geometry is proposed by the source scanner only to be
rejected by the semantic gate because it is not eligible visible text.

The gate is a permitted-delta proof over complete before/after docutils trees.
It requires identical node shape, attributes, targets, and generated ids after
eligible title and paragraph Text values are canonicalized to one space, plus
an exact eligible Text-node run reduction for every accepted source edit.  The
common case is verified as one batch.  If syntax or protected content makes a
mixed batch unsafe, the candidates are bisected and retried from later source
offsets to earlier ones, so valid prose edits survive without shifting the
untried ranges.

The proof establishes *where* a change lands; it cannot establish the author's
stylistic intent.  For example, a paragraph timestamp such as ``Max  20 h 01``
is eligible prose and will become ``Max 20 h 01`` when the prose policy is
explicitly selected.  This Journal also contains an established two-space
sentence-separator style: evaluation found 466 such runs in the ``check_rst``
documentation alone.  Across the tracked corpus, 13,227 internal repeated-space
runs included 7,598 table-shaped and 4,050 indented occurrences, while only 22
runs were in section titles.  Those facts are why the options are named,
separate, whole-document, and never part of default ``--fix``.  Preview the
selected files and choose the style deliberately.

Like blank-line normalization, both modifiers require ordinary ``--fix`` or
``--diff`` and are rejected by parser-free ``--fix-only`` and ``--diff-only``.

=======================================================
History protection: bare mode and selective Git scope
=======================================================

Bare ``check_rst --fix`` uses ``git status`` to select the existing
changed/untracked ``.rst`` files, resolving porcelain paths against
Git's worktree root even when invoked from a subdirectory.  Adornment
geometry is scoped to hunks from ``git diff -U0 HEAD``.  Two
document-level policies are deliberately wider: Phase 0 byte hygiene
(BOM/line-ending/control/trailing-whitespace normalization) is whole-file, and
hierarchy character remapping is whole-document because a heading
character's rank has no per-hunk meaning.

Every explicitly selected blank-line or editorial-spacing modifier is also a
whole-document policy.  Git scope limits which files may change; it does not
turn a document-wide style request into a hunk-local one.

Passing a filename (or ``--recursive``) makes adornment geometry
whole-file too — including pre-existing, deliberately non-standard
adornments in historical ``calendar/`` entries that must not be
renormalized.  Fix a specific file in full only when the user explicitly
confirms that file should be normalized.

``--git-scope`` is the safe exception to that explicit-file rule.  Its
positional files are an allowlist intersected with Git's
changed/untracked ``.rst`` set: unchanged names are ignored, files outside
the selected worktree are rejected before any write, and selected tracked
files keep bare mode's ``git diff -U0 HEAD`` adornment scope.  The same two
document-level exceptions still apply: byte hygiene and hierarchy remap
operate on the whole selected document.  Use this mode when the worktree
contains other RST edits that do not belong to the current task.

Before any phase or fixer starts, one atomic preflight validates the
complete selected set: every explicit input is a regular file, an
existing ``--build-dir`` is a directory, files paired with
``--sphinx-src`` live under that source tree, and Git reports no
unresolved merge entries.  One invalid input aborts the whole operation;
valid siblings are not partially modified.  In particular, conflict
separators such as ``=======`` are also legal RST adornments and could
otherwise be promoted/remapped as headings, so an unmerged file fails
with ``unresolved Git merge conflict — resolve before checking or
fixing``.  If selection produces no existing RST files, no phase runs.

=======================================
Fast mechanical mutation and previews
=======================================

``--fix-only`` is the write-side counterpart of ``--diff-only``.  It plans
every selected file before writing, applies only Phase 0 byte hygiene and the
raw-line adornment/hierarchy fixer, verifies that the computed result is a
local fixed point, and stops.  It never runs the remaining Phase 1 rules,
docutils parsing, statistics, the Sphinx environment, or the Sphinx build.  A
changed file is success; input, write, and non-convergence failures are the
only non-zero outcomes.  Run an ordinary check afterwards for the semantic
and Sphinx validation::

    check_rst --fix-only --git-scope path/to/owned.rst
    check_rst --git-scope path/to/owned.rst

Before writing, the default output states whether adornment geometry is
Git-diff-scoped or whole-file.  Each changed file then receives a structured
count such as ``BOM 1, CRLF line endings 42, trailing whitespace lines 3,
structural lines 2``; the final status line is always last.  ``--verbose``
additionally names mechanically clean files, while ``--quiet`` reduces a
successful run to the status footer.  ``--no-adornments`` deliberately leaves
a hygiene-only mutation pass.

``--normalize-blank-lines``, ``--collapse-title-spaces``, and
``--single-space-prose`` are deliberately rejected here.  They are not raw
mechanical fast-path operations: their acceptance predicates require the
docutils comparisons described above.

Project configuration still roots Git discovery, but configured
``sphinx-src`` and ``build-dir`` values are reported inactive because this mode
does not use them.  Explicit ``--sphinx-src``/``--build-dir`` and
``--skip-fixable`` are rejected rather than silently ignored.  File selection,
``--git-scope``, ``--recursive``/``--exclude``, whole-file hygiene/hierarchy
exceptions, path preflight, and unresolved-merge rejection otherwise match
ordinary ``--fix``.

``--diff`` previews the composed result of both default fixers, plus any
requested editorial-spacing and blank-line stages, and then continues
through the normal findings, statistics, and Sphinx phases.  When the only
question is "what would the deterministic fix change?", ``--diff-only``
prints that same unified diff and stops before those phases.  It exits 1
when a change would be made (or an input error occurs) and 0 when the
selected files are already mechanically clean::

    check_rst --diff-only --git-scope path/to/owned.rst

The mode is intentionally self-contained: file/configuration selection,
``--git-scope``, ``--recursive``/``--exclude``, ``--no-adornments`` and
``--quiet`` may shape the preview; checking/reporting options do not mix
with it.  Use ordinary ``--diff`` when the same invocation must also run
the full validation pipeline.

===============================================================
Why you can trust --fix: adornments and hygiene, nothing else
===============================================================

An independent Claude Code session, before recommending a real project
normalize six real, externally-authored documents in full, needed to
answer one question first: does ``--fix`` touch only adornment
geometry, or can it also mutate prose content?  It hand-rolled a grep
filter over ``check_rst --diff`` output to check every changed line was
made of nothing but adornment characters — a workaround worth
retiring by stating the guarantee directly, since it is true and
provable, not just true by convention: default ``--fix`` has exactly two
fixers.  ``fix_hygiene`` (Phase 0: BOM removal, CRLF/CR/exotic line
separators to LF, control whitespace to space, and parser-ignored trailing
whitespace on every source line) and ``fix_structure`` (Phase 1: adornment
geometry and hierarchy remap).  Neither has a code path that reaches a prose
line's words or meaningful whitespace: the all-line right strip exactly
materializes what docutils' own ``string2lines()`` already does before parsing.
A dedicated test pins this as a general,
whole-document property — not scenario-by-scenario, one document
exercising every fixer path (underline-only synthesis, wrong-length
correction, hierarchy remap, BOM/CRLF/trailing-whitespace normalization) at
once, asserting every prose line's semantic content survives, in order.  If you want the
same confidence the hard way: ``check_rst --diff`` before trusting any
normalize, same as "Fixing foreign content needs one extra caution"
above already recommends — this section is why that recommendation is
safe to act on, not just cautious phrasing.

``--normalize-blank-lines`` is a deliberately visible exception, never an
implicit expansion of that promise.  It reaches meaningful source whitespace
only after the user opts in, and accepts a candidate only when docutils' full
before/after tree is identical.  It never changes words or internal prose
spacing; a content-bearing blank run simply fails the equivalence predicate and
is retained.

The two editorial-spacing modifiers are a different, equally visible
exception.  Their option names state the requested style, and their proof
allows only the exact eligible visible Text-node space reductions described
above while holding structure, attributes, targets, and ids constant.  This is
strictly narrower than arbitrary prose rewriting but deliberately broader than
tree identity.  Omitting the modifiers preserves the default guarantee.

******************************************************
Reading RST: verified structure instead of inference
******************************************************

RST structure is implicit — a ``***********`` line means "level 2" only
by first-appearance convention, and an LLM reading raw markup *infers*
the tree, imperfectly, burning context on parser work.  ``check_rst``
externalizes that parse: **it is the parser you consult instead of
reconstructing structure yourself.**

The acceptance reader here is deliberately cold: an unfamiliar human
reviewer, a fresh-context AI, or automation with no authoring-session memory.
A warm author or in-context AI may understand weakly encoded structure from
memory or a prior full read, but that compensation must not be used as the
document-quality gate.  Structure that serves the cold human through visible
geometry generally also serves the fresh AI through the parsed model; both
lose when a concept that should be independently retrievable exists only as
bold prose.

======================================
``--outline``: the structural oracle
======================================

::

    check_rst --sphinx-src . --build-dir /tmp/journal-sphinx-build --outline <file>

prints a ``levels:`` legend — each depth with its adornment character
and section count, plus the document's total section count, stated
once since the mapping is constant within a document — then a
``blocks:`` line totalling code-blocks, blockquotes, and tables
document-wide (omitted when the document has none of them) — then
every heading as a line **range** and title, indented 4 spaces per
level, with a bracketed count of its direct subsections *and* every
code-block/blockquote/table anywhere in that section's range (its whole
subtree, not just the section's own text) — plus every real code-block
with its language, unquoted (``code-block (python)``, not
``code-block ('python')``) and a preview of its content; every
blockquote with the same preview contract over its quoted text; and
every table with its syntax kind (``grid``/``simple``/``table``/
``list``/``csv``), its row-x-column dimensions, its caption when it has
one, and a preview chaining every row's cells in document order — each
entry with its own range.  Every preview — code-block, blockquote,
table alike — is whitespace-collapsed (no leading/trailing or doubled
internal spaces) and bounded at 74 characters, ``...``-truncated when
it doesn't fit: a quick identity for the entry, never its full content.
The range is the entry's full extent: feed it straight to a targeted
read (``sed -n 'START,ENDp'``) with no arithmetic — where check_rst
informs about a line number, it informs about the range instead,
wherever a range applies (findings keep single-line anchors: they
point *at* a defect, not over a span) — quote zones are exempt
from the heading-substitute warnings, so seeing them in the outline
explains absent findings and shows composition — in document order.
Read it **before editing any file you have not already read this
session, and again after any edit that could have moved things** —
having read a file once does not make a remembered line number trust-
worthy after your own inserts shift everything below them; a fresh
``--outline-only`` is authoritative regardless of how many times you
have already read the file this session, a stale mental line map never
is.  It answers "where does my new section attach, and at what level"
as data instead of interpretation, and it is a compressed
representation (a hundred headings instead of thousands of lines) when
the full text would not fit comfortably in context.  Consulting it
first — and again after editing — is cheaper on both budgets at once:
less context spent, fewer structural mistakes made.  For machine consumption use ``--json`` — the
same model as one JSON object (findings included, stable section ids,
every entry's own preview/kind/dims fields) — and for the
human-readable pure structure query use ``--outline-only``: one flag
implying ``--outline`` and ``--quiet`` and suppressing the finding
lines — a display filter, so the footer still counts findings and the
exit code stays honest.  ``--outline-depth N`` bounds the view under
one contract: **the depth limit trims entries, never information** —
the ``levels:``/``blocks:`` legend always describes the whole document,
a section's bracketed counts always reflect its full subtree regardless
of what the depth limit hides below it, and a hidden-entries note
counts what was trimmed.  ``--sections-only`` is the orthogonal filter
— by KIND instead of depth: every leaf entry (code-block, blockquote,
table, admonition, comment, list) disappears from the tree regardless
of how shallow it sits, for a pure table-of-contents view; the same
"trims display, never information" contract applies, and the two flags
compose.  With ``--sphinx-src`` the section/code-block
structure comes from a real Sphinx environment; without it, from a
clearly-labeled heuristic — trust the label.  Tables are the one entry
kind exempt from that split: a real Sphinx build adds no trace of which
RST syntax produced a table (confirmed directly — a grid table, a
simple table, and the table/list-table/csv-table directives all produce
the identical doctree shape), so ``kind`` always comes from the raw
source text, verified mode or not.

========================================================
Entry selectors: stable sections and universal aliases
========================================================

Every entry in the heterogeneous outline stream has a universal selector of
the form ``docname:kind@line``.  The kind label is lowercased and each run of
non-alphanumeric characters becomes one hyphen: for example, ``code block``
becomes ``code-block`` and ``toctree cycle`` becomes ``toctree-cycle``.
Current list kinds similarly produce selectors such as
``docname:enumerated-item@line``; the vocabulary is deliberately extensible,
not a closed list that must be updated whenever another entry class appears.

Sections additionally have a stable, title-based selector,
``docname:Title``.  That preferred form is also the section ``id`` stored by
``--json`` and matched by ``--diff-json``; repeated titles gain ``#2``, ``#3``,
and so on.  Universal ``kind@line`` aliases are accepted by ``--context`` for
sections too, but are not JSON ids.  When exact semantic text is ambiguous,
copy the generated selector from ``--context``'s candidate report — its spelling
and occurrence suffix are authoritative.

The superficially similar ``@line``/``@docname:line`` suffix printed beside a
top or rare prose word is only a source jump target.  It is not an entry
selector and cannot be passed to ``--context``.

===================================================
``--context``: one entry without the full outline
===================================================

``--sections-only`` is intentionally blind to list items and every other
leaf entry; the complete outline is intentionally exhaustive.  When one
view hides the target and the other is too large, do not return to raw
``grep`` (see "Piping anti-patterns" below).  Ask the document model
for the one entry directly::

    check_rst --context 'roadmap:Table queries' \
        docs/roadmap.rst

``--context ENTRY`` is a self-contained, read-only query requiring exactly
one positional ``.rst`` file.  It resolves the same heterogeneous entry
stream that ``--outline`` prints — sections, list containers and items,
code-blocks, blockquotes, tables, admonitions, comments, toctrees, and future
entry classes, using the selector scheme above or exact title, term, caption,
or preview text.  Resolution is exact, never fuzzy; even an anonymous list
container or empty block remains addressable through its generated selector.

A unique match reports its selector, kind, exact range and depth; the full
enclosing section/container path; its parent, previous and next sibling, and
direct children; findings whose anchors fall in the selected range; outgoing
references written inside that range; and document-level incoming
references.  References require verified Sphinx mode; heuristic mode says
explicitly that they are unavailable.  Child/reference lists are bounded
with a suppression count rather than silently truncated.

An exact semantic value may legitimately occur more than once.  In that
case the command exits 1 and prints compact candidates with selector, kind,
range, and parent path instead of guessing; at most 20 are printed, followed
by the suppressed count.  Repeat the command with the chosen selector.  No
match also exits 1.  A unique resolution exits 0 even when the briefing
contains an applicable ERROR: the exit status answers whether the query was
resolved, not whether the document validates.  ``--context`` prepares an
edit; the three-step validation loop still validates it.

=============================================================
Block previews: know what's inside without opening the file
=============================================================

Every code-block, blockquote, table, admonition, comment, and list
item in ``--outline`` carries a preview of its own content — not just
its location and kind.  This is the difference between a table of
contents and an index: a bare list of headings tells you a section
exists, a preview tells you *what is in it*, at a glance, at the exact
spot a full read would cost the most context.

Five previously separate facts unify into one (a sixth, lists, works
differently enough to earn its own section below): is this code-block
actually the code you think it is (``code-block (python):
READ_INTERVAL = 300 # seconds, not prose`` settles it without opening
the file); does this table have the columns and sample rows you
expect (``Table (list, 3x2), "Sensor readings": Time Temp 09:00 21.4
09:05 21.6``); does this blockquote say what the surrounding prose
claims it says; does a ``.. note::``/``.. important::`` carry the
weight its placement implies, or is it filler (``admonition
(important): If you read nothing else: ...`` — this page's own tl;dr,
found live to be completely invisible to ``--outline`` before this
entry kind existed, even though docutils parsed it fine all along);
and is this comment really just a comment, or a directive that lost
its second colon (``comment "code: bash" [suspicious — looks like a
mistyped directive]``).  All five kinds share one contract —
whitespace-collapsed, 74-character-bounded, ``...``-truncated — so
scanning an outline for "what's really here" never means learning a
second format per entry kind.  The generic ``.. admonition:: Title``
form carries an explicit title too, the same role as a table's
caption — the other nine named admonitions (``note``, ``warning``,
``important``, …) never have one.  Blockquotes are also the one place
quoted material is visible in the outline at all: they are exempt from
the bold/rubric heading-substitute warnings *because* they are
quotation, and the preview is what lets you confirm that exemption is
doing the right thing on a specific quote, not just trust it in the
abstract.

The practical payoff: a month-scale ``--recursive --outline`` audit
becomes skimmable.  Where a corpus-wide grep for a suspicious code
snippet or a mis-captioned table used to mean opening candidate files
one by one, the preview usually answers the question from the outline
line itself.

=======================================================
Verbosity levels: ``--quiet``, default, ``--verbose``
=======================================================

Three honest levels, not two flags bolted onto an undifferentiated
default.  The gap that motivated this: ``--quiet``'s own ``--help``
text promised "only the summary line still prints," but one whole
group — the footer's ``lines:``/``words:``/top-and-rare-prose-words —
ignored that promise and printed unconditionally, for every run,
whether requested or not.  Caught twice independently the same day
(2026-07-19→20): once by a first-principles inventory of every
``print()`` call site and its guard, once by a session doing heavy editing in
a downstream project and complaining that "``--quiet`` doesn't quiet the
prose-statistics tail" on a check-fix-recheck loop where those lines
were pure repeated noise after the first read.

.. list-table:: The ladder
   :header-rows: 1
   :widths: 15 40 45

   * - Level
     - Flag
     - Shows
   * - 0
     - ``--quiet``
     - Findings, each repeated finding kind's shared rationale, the one-line
       summary, and anything explicitly requested (``--outline``, ``--diff``,
       ``--json``)
   * - 1
     - *(default)*
     - Level 0, plus phase banners, per-file progress notices, the
       config echo, and — deliberately not demoted — the outline's
       ``levels:`` legend
   * - 2
     - ``--verbose``
     - Level 1, plus the outline's ``blocks:`` summary, the footer's
       ``lines:``/``words:`` counts, top/rare prose words, and the
       bold/rubric WARNING extra detail (the actual text, a preview of
       the following paragraph, the enclosing section title —
       everything needed to judge promote-vs-leave with no file read
       at all)

The ``levels:`` legend is the one deliberate exception folded *into*
the default rather than promoted out of it: section structure is core
information an AI orients by on every read, not verbose detail — it
was already unconditional whenever ``--outline`` ran, and stays that
way.  ``blocks:`` — one line, but strictly a summary the entries below
it already contain — is the one demoted alongside the genuinely
detailed lines.

``--word-samples N`` is the ladder's one deliberate escape hatch: it
promotes top/rare prose words at *any* level, ``--quiet`` included,
independent of ``--verbose`` — the single line-4 exception, because a
targeted typo-scan is sometimes exactly what a quiet run is for.
Omit it and the level decides (10 under ``--verbose``, hidden
otherwise); ``--word-samples 0`` disables the lines even under
``--verbose`` — an explicit request always wins, in either direction.
This also unifies what used to be two independent, silently
mismatched defaults: the footer's old hardcoded 13 and the ``--json``
model's old hardcoded 10 are now the one shared, flag-controlled value.

Real output, same file, three levels::

    $ check_rst --quiet station.rst
      (bold paragraph opener: AI documents often use this pattern as an
      informal heading; consider a proper section title)
    station.rst:11: WARNING: bold paragraph opener 'Note:'
    check_rst: 1 file(s) checked, 0 error(s), 1 warning(s), 719 char(s)
      (87 distinct, 31 once), 835 byte(s), 112 space(s) (16%)

    $ check_rst --quiet --word-samples 3 station.rst
      (bold paragraph opener: AI documents often use this pattern as an
      informal heading; consider a proper section title)
    station.rst:11: WARNING: bold paragraph opener 'Note:'
    check_rst: 1 file(s) checked, 0 error(s), 1 warning(s), 719 char(s)
      (87 distinct, 31 once), 835 byte(s), 112 space(s) (16%)
    top prose words: sensor (6 @11), датчик (4 @5), readings (3 @25) (yet 41 suppressed)
    rare prose words: batery @14 ↔ battery @11, sensro @13 (~sensor 6x), about @11 (yet 35 suppressed)

Level 0 stayed level 0 — the summary line is identical in both runs —
and one flag alone reached into it for exactly the one thing worth
seeing under a quiet loop.  The full ``--verbose`` picture (``blocks:``,
``lines:``, ``words:``, top/rare at their default of 10) is in the
worked demonstration in :doc:`example`.

Costs, not just display, respect the level: ``_top_prose_words``/
``_rare_prose_words`` — the stopword-filtering, stemmer-grouping
machinery — are never even *called* when nothing would show their
result, not merely printed and discarded.  A ``--recursive`` audit
across hundreds of files at the default level pays zero stemmer cost;
asking with ``--word-samples``/``--verbose`` is what turns the
machinery on, precisely when its answer is wanted.

=================================
A hard whole-report line budget
=================================

Semantic selectors remain the first choice, but sometimes the real constraint
is simply a caller's context window.  ``--max-output-lines N`` caps the emitted
text report without stopping the checker or replacing its exit status.  ``N``
has a minimum of two because the last two lines are permanently reserved for
an output-limit statistics line and the authoritative final status::

    check_rst --max-output-lines 40 --git-scope path/to/owned.rst

The first ``N - 2`` lines are the ordinary output after ``--quiet``,
``--outline-only``, ``--sections-only``, ``--outline-depth``, and other
semantic display controls have already acted.  The statistics line then says
how many detail lines were shown and skipped, classifies suppressed
ERROR/WARNING diagnostics and outline records, and gives the limit required
for the complete current report.  It is present even when zero lines were
suppressed, and short reports are never padded.  The status line is always
last, including after verbose line/word statistics::

    check_rst: output limited — 0 of 154 detail line(s) shown, 154 skipped (1 ERROR, 3 WARNING, 61 outline); full output requires 156 lines
    check_rst: 12 file(s) checked, 1 error(s), 4 warning(s), ...

The sink retains only the permitted prefix and counters; the validation itself
continues to completion.  A diagnostic hidden past the limit therefore still
changes the footer totals and exit status.  Input, configuration, and preflight
failures receive the same bounded shape, with a rerun hint in the statistics
line when no normal run summary was reached.  Counts refer to newline-delimited
program output, not terminal-wrapped display rows.

The initial compatibility boundary protects formats whose completeness is
part of their meaning.  Ordinary checks, ``--fix``, outline modes, and
``--fix-only`` accept the limit.  ``--json``, ``--diff-json``, ``--refs``,
``--context``, ``--diff``, and ``--diff-only`` reject it: truncated JSON must
not become invalid or look complete, and a truncated patch must not look
applicable.

======================
Piping anti-patterns
======================

Two shell reflexes reach for a generic text filter to solve a problem
``check_rst`` already has a dedicated, honest answer for.  Both share
the same failure shape: a filter bounds output by *position* (byte
count, line count, pattern match) with no idea which line carries the
information that matters.  Prefer the tool's explicit verbosity,
semantic-filter, and structured-report contracts, whose omissions are
defined rather than accidental.

``tail``/``head`` to limit how much scrolls by
  Guessing a line count and piping through it risks cutting the
  summary line (the actual finding/error counts and exit-code-
  relevant totals) or a real entry past the cut, silently — the
  truncation carries no signal that anything was lost.  The pipeline's
  apparent success can also be ``head``'s exit status rather than
  ``check_rst``'s unless the caller preserves the producer status.
  ``--quiet``, ``--outline-only``, and ``--sections-only`` already bound
  output through explicit display contracts, while ``--outline-depth``
  additionally reports exactly how many entries it hid.  Reach for one
  of these first; when only a hard line budget fits, use
  ``--max-output-lines`` above.  A piped line-count guess that happens not
  to lose anything today is luck, not a guarantee for the next file.

``--no-warnings`` is different
  This is a destructive finding-class filter, not a non-destructive
  verbosity control.  It removes WARNING diagnostics and currently makes
  the summary report zero warnings without a separate suppressed count.
  Use it only when an errors-only answer is explicitly wanted, never as a
  generic way to shorten an ordinary validation report.

``grep`` to recover one thing from a noisier whole
  Two different temptations, two different existing answers.  Findings
  buried in progress noise: ``--quiet`` already strips everything but
  findings, their once-per-kind shared rationale, the requested report,
  and the summary — see "De-facto compiler output" below, which is what made the old
  ``grep '^⚠'``/``grep 'WARNING:'`` habit largely moot.  One specific
  structural entry buried in a large ``--outline``: ``--context ENTRY``
  (see above) resolves it exactly, with its full sibling/parent/
  reference context attached — something no grep over raw markup can
  reconstruct.

Neither rule is absolute.  A deliberately targeted pipeline —
``grep`` for one known, stable substring, with the complete output
still redirected somewhere the full result and exit code remain
inspectable — is a reasonable *addition* to a check, never a
replacement for actually looking at what ``check_rst`` reported.  The
line to hold: never pipe *instead of* running the validation loop's
own steps, only ever *alongside* them, and only when the flags above
genuinely do not fit.

==========================
De-facto compiler output
==========================

Every finding is bare ``path:line: WARNING: message`` or
``path:line: ERROR: message`` — nothing before the path, nothing
decorating the severity word beyond the word itself.  This is the
shape generic tooling already knows how to consume: an IDE's
jump-to-error, a build-task problem matcher, anything that expects
gcc/clang/mypy-style diagnostics.  A leading glyph — even a single,
consistent one — breaks that: it puts a character before the path
that the tooling's pattern doesn't expect.

This *replaces* an earlier design, not merely a cosmetic tweak: every
``⚠``/``✗`` finding line used to open with that glyph, added
2026-07-18 from real evidence (five AI sessions independently piping
output through ``grep '^⚠'`` to recover findings from progress
noise).  Reversed 2026-07-20 (Max: "those prefixes are optional, we've
got the text warning or error... will it be better to delete them?"):
the same recovery is ``grep 'WARNING:'``/``grep 'ERROR:'`` now, barely
more typing, and ``--quiet`` — added the same day as the glyph, from
the same evidence — already gives a cleaner path to "findings only"
that makes the grep workaround largely moot on its own.  Documentation
follows reality here, not the other way around.  Historical examples in
the roadmap remain evidence of old friction, not recommended usage.

The one thing that is *not* a per-finding diagnostic — the shared
rationale a repeated finding kind prints once per run (see "Verbosity
levels" above and :doc:`example`) — stays
un-decorated too, but for the opposite reason: it was never meant to
look like a diagnostic line at all.  It carries no path, no line, no
severity word, the same shape as the outline's ``levels:``/``blocks:``
legend lines — metadata about the run, not a location a reader would
ever jump to.

===========================================
Phase 3: Sphinx integrity and diagnostics
===========================================

After adding ``:doc:``/``:ref:`` links (the daily business of
aggregation pages), the check with ``--sphinx-src`` runs a real
``sphinx-build`` and reports broken references in the checked files.
An LLM writes links confidently; this is the stage that catches the
wrong ones.  Malformed RST can visually resemble correct RST and fool
both humans and models — docutils is not fooled.  When the parser and
your impression disagree, the parser is right.

The subprocess always uses the same Python interpreter as ``check_rst``;
it never picks an unrelated ``sphinx-build`` from ``PATH``.  A non-zero
Sphinx exit is always an ERROR even when the captured output contains only
WARNINGs, so a failed build cannot look successful merely because it also
printed a selected-file warning.  The verified-mode preamble records the
Python, Sphinx, and docutils versions that produced the result.

Some useful Sphinx concerns are not reliable selected-file diagnostics.
In particular, a document can be included by multiple toctree entries —
twice in one parent or once from each of several parents — while Sphinx
anchors or phrases the concern somewhere other than the file being checked.
Phase 2 therefore derives that anomaly from Sphinx's resolved
``env.toctree_includes`` graph and reports it against every selected parent
or child implicated in it.  The graph check survives incremental-cache
reuse; retaining the configured build directory remains the normal,
fast path.

A broken reference's own WARNING now names its likely fix: ``unknown
document: 'calendar/2026/07/2026-07-1/Notes' [ref.doc] — did you mean:
'calendar/2026/07/2026-07-17/Notes'?``.  The suggestion comes from the
SAME live Sphinx environment Phase 2 already built for this run —
``env.found_docs`` for a broken ``:doc:``, ``env.domaindata['std']
['anonlabels']`` for a broken ``:ref:`` — matched with
``difflib.get_close_matches`` (cutoff 0.6); never ``objects.inv``,
which needs a completed HTML build and holds less than the env
already in hand.  No candidate close enough means no suggestion is
appended — the WARNING is unchanged, not padded with a guess nobody
asked for.  This closes the "guess and wait" loop that broken
references used to leave entirely to you: previously, fixing a typo'd
target meant re-running the whole check to find out if your guess was
right; now the first run already names it.

===================================================
--refs: who this file points at, who points at it
===================================================

``check_rst --refs FILE`` (with project configuration, or explicit
``--sphinx-src``) prints two lists: every
``:doc:``/``:ref:``/``:term:`` target and resolved toctree child *FILE*
itself writes (``outgoing:``), and every OTHER file whose role or
toctree edge resolves to *FILE* (``incoming:``).  Toctree globs are
shown as the actual child documents Sphinx expanded them into.  For this
Journal, the incoming half answers the question aggregation-page
maintenance keeps asking: "which aggregation pages already point at
this calendar note" — before, that meant a corpus-wide grep and manual
cross-checking; now it is one command.  A self-contained mode, same
family as ``--diff-json``: incompatible flags or extra file arguments
are rejected, never silently ignored.

Both lists come from the SAME live Sphinx environment Phase 2 already
builds — never ``objects.inv``.  Outgoing reads *FILE*'s own doctree
for ``sphinx.addnodes.pending_xref`` nodes: the raw, still-unresolved
target text an author wrote, present because resolution happens later,
during a builder's write phase, and is never written back to the
pickled doctree (confirmed by direct probe, 2026-07-22).  Toctree edges
come from each node's Sphinx-resolved ``includefiles`` list — explicit
entries and glob expansions, but not external URLs.  Incoming is that
combined scan run once per document across the whole project, kept to
whatever resolves to *FILE*'s own docname — measured at ~2.6 seconds
across this Journal's full 1444 documents, fine for an on-demand
command, not something to pay on every default run.  A role target that
doesn't resolve prints ``BROKEN`` in the outgoing list — Phase 3 already
reports why (and, since the previous section, suggests the fix); this
list exists to show what's THERE, not to duplicate that diagnosis.

============================================
Semantic diffs: comparing two --json dumps
============================================

After a large edit — your own, or a subagent's — "did I break anything,
or just add what I meant to add?" is usually answered by eyeballing a
diff of the *file*, not of what changed *structurally*.
``--diff-json OLD.json NEW.json`` answers the structural question
directly, from two ``--json`` dumps taken before and after::

    $ check_rst --json guide.rst > before.json
    ... edit guide.rst: add a "Rollback" section with a bold opener ...
    $ check_rst --json guide.rst > after.json
    $ check_rst --diff-json before.json after.json
    Summary:
      files_checked: 1 -> 1 (0)
      errors: 0 -> 0 (0)
      warnings: 0 -> 1 (+1)

    guide.rst: changed
      outline: +1 section(s), hierarchy unchanged
        + guide:Rollback
      findings: +1 added, -0 resolved
        + WARNING: bold paragraph opener 'Emergency stop:'

One line answers "did the edit do what I think it did": one new
section, the rest of the hierarchy untouched, one new WARNING to
review — not "same warning count, same categories as before" verified
by eye across two large blobs.  Matching is deliberately not by line
number: files are matched by path, outline entries by their stable
``docname:title`` id (the section identity defined under "Entry selectors"
above), findings by ``(severity, text)``.
A finding that only *shifted* lines because of an unrelated earlier
edit must never appear as both resolved and added — matching on content
instead of position is what makes that true.  Sphinx findings are compared
the same way, separately from per-file findings, so one warning replacing
another cannot disappear behind an unchanged warning count.  The comparison
also warns when schema, heuristic/verified mode, or runtime provenance
differs; a Sphinx-version change is evidence about the comparison, not a
structural document change.  Self-contained: no RST
is read or checked, and no other flag applies alongside it — the two
arguments are always JSON files, never the documents themselves.
Malformed JSON, a non-object top level, or data missing the required
``files``/``summary`` report shape fails with a clean diagnostic rather
than a traceback or an invented empty comparison.

**************************************************************
Per-repo configuration: ``.check_rst.toml`` and ``--config``
**************************************************************

A repository declares its own facts in ``.check_rst.toml`` at its root
(the whole file is the table; ``pyproject.toml [tool.check_rst]`` is
the alternative — the dedicated file wins when both exist).  This
repository's own file, complete::

    sphinx-src = "docs"
    build-dir = "/tmp/check-rst-sphinx-build"

Those two keys are the entire vocabulary.  With them committed, the
bare commands run in verified mode with Phase 3 — the three-step loop
needs no long options, and every repo can carry different facts (a
repo whose ``conf.py`` sits at its root instead uses ``sphinx-src = "."``).

This is **declaration, not auto-detection** — nothing is guessed,
someone committed these values.  Automatic discovery and explicit
selection have separate, deterministic contracts.

====================================================
Automatic discovery stays at the working directory
====================================================

Without ``--config`` there is no parent-directory walking: run
``check_rst`` from the repo root to apply its declaration.  Bare Git
selection resolves porcelain paths against
``git rev-parse --show-toplevel`` when invoked from a repository
subdirectory, but it does not implicitly inherit a parent directory's
check-rst configuration.

=============================================
Explicit selection works from any directory
=============================================

Pass either supported file explicitly to select its project from an
unrelated working directory::

    check_rst --config /repo/.check_rst.toml /repo/docs/page.rst
    check_rst --config /repo/pyproject.toml /repo/docs/page.rst

The dedicated file's whole document remains the table; an explicitly
selected ``pyproject.toml`` uses ``[tool.check_rst]``.  ``--config``
suppresses automatic discovery in the invocation directory.  A relative
config filename is itself resolved from that invocation directory.

Relative ``sphinx-src`` and ``build-dir`` values resolve from the
selected config's directory.  With no positional files, bare Git
selection and diff scoping also run from that directory::

    check_rst --config /repo/.check_rst.toml

Positional files and ``--recursive`` directories retain normal CLI
semantics: their relative paths resolve from the invocation directory,
not the config directory.

===========================
Applied values are echoed
===========================

Every non-quiet run starts with ``config: .check_rst.toml —
sphinx-src=., build-dir=…`` for automatic discovery, or the selected
config's absolute path for ``--config``.  The ``--json`` model carries
the same ``config`` object saying which file supplied which values.
You always know why a run is in verified mode.  It also carries a schema
version and structured runtime metadata; normal verified output prints the
corresponding concise ``runtime: check_rst …, Python …, Sphinx …, docutils …``
line.
When prose-word sampling is requested, snowballstemmer's version joins the
runtime record because it affects grouping and typo candidates.

===========================
CLI flags always override
===========================

The config's TOML and schema are always validated.  An overridden path
value is not applied or checked for ``conf.py``/directory existence.  A
config-supplied ``build-dir`` without ``sphinx-src`` is reported as inactive
and never created; it may be a valid partial declaration overridden by a
later CLI invocation.  In contrast, an explicit ``--build-dir`` without a
resolved Sphinx source is almost certainly a command mistake and fails with
both remedies: ``--sphinx-src DIR`` or ``--config FILE``.

================================================
Unknown keys and non-string values fail loudly
================================================

A typo'd ``sphix-src`` silently ignored would be worse than no config
at all (the same fail-loudly precedent as ``--sphinx-src`` without a
``conf.py``).  An explicitly requested config that is missing, not a
regular file, malformed TOML, or empty also fails before Git discovery,
any checking phase, or ``--fix``.  ``--refs`` accepts ``--config`` because
it needs project settings; ``--diff-json`` rejects it because that mode is
self-contained and reads no RST project.

The same actionable verified-mode error applies to every option whose
meaning depends on Phase 3 data: ``--refs``, explicit ``--build-dir``, and
``--no-toctree``.  The last also requires an actual outline consumer
(``--outline``, ``--outline-only``, or ``--json``); otherwise it would do
nothing.

For a foreign repository: run heuristic (no flags) until its
``conf.py`` location is confirmed, then propose committing a
``.check_rst.toml`` there — after which that repo's bare commands are
verified too, and its facts travel with its history.

******************
Auditing a scope
******************

For a calendar month, a project's docs tree, or an external repository::

    check_rst --recursive <dir> --skip-fixable            # WARNINGs needing judgment
    check_rst --recursive <dir> --diff-only               # fast mechanical preview
    check_rst --recursive <dir> --diff                    # preview plus complete validation
    check_rst --recursive <dir> --exclude <name> ...      # skip specific files

Multi-document review has a correct order, not just a correct command
set: normalize each document before reasoning across all of them,
never the reverse — a hierarchy question asked against an unverified
file gets an unverified answer.  Concretely: (1) ``--skip-fixable``
surfaces this document's own latent structural candidates (bold
openers, rubrics); (2) the AI turns the ones that are genuine sections
into real placeholder headings; (3) ``--fix`` normalizes the result;
(4) a bare confirm run verifies convergence; only once every document
in scope has been through 1–4 does (5) cross-document reasoning
(``--refs``, ``--diff-json``, an aggregation-page pass) run against
verified structure instead of raw markup.  Skipping straight to step 5
on a scope that never passed 1–4 means every cross-document answer
inherits whatever the unverified documents got wrong.

``--recursive`` discovers ``*.rst`` natively (no shell, so spaced
filenames are safe) and always checks in full — which is exactly why an
audit never runs ``--fix`` automatically (see History protection).  The
``--exclude`` option is valid only with ``--recursive``; using it in any
other mode is an argument error rather than a silently ignored filter.
Likewise, ``--outline-depth`` must be at least 1 and must accompany an
outline mode.  Output modes reject combinations they cannot honestly apply:
``--outline-only`` is read-only and separate from ``--json``;
``--sections-only`` and ``--outline-depth`` do not pretend to filter the
JSON model; and ``--json`` cannot fix files.  ``--no-warnings``, when
explicitly chosen for a query, filters warnings consistently from per-file
findings, Sphinx findings, word-statistics diagnostics, and the summary.
The semantic-rules guide documents scope decisions, the dirty-file check that
must precede any fix outside the live-edit workflow, and the per-rule
rationale.

******************************************************************
Standalone documents and foreign projects: the two Phase 2 modes
******************************************************************

The tool is routinely pointed at unrelated repositories' documentation trees
and at standalone
documents — a single exported ``.rst``, a pasted cheatsheet, a file with
no Sphinx project around it at all.  ``check_rst`` has an explicit answer
for that situation, and knowing which mode you are in matters.

======================================
Verified mode: with ``--sphinx-src``
======================================

``--sphinx-src DIR`` builds a real, in-process Sphinx environment: the
structure behind ``--outline`` (headings *and* code-blocks) is resolved
exactly as a real build would resolve it, and Phase 3 runs
``sphinx-build`` for cross-reference integrity.  ``DIR`` must contain
``conf.py`` or the tool errors immediately — a typo'd path is a mistake
worth failing loudly on, not silently degrading.  Every selected file
must belong to that Sphinx source environment: a file from an unrelated
directory is rejected before Phase 1 (and therefore before ``--fix``);
a path Sphinx itself excludes is rejected after environment
construction.  Verified mode never builds one project while claiming
another project's file was clean.

The location is **never auto-detected**, even when a ``conf.py`` is
sitting right there in the working directory.  This is deliberate: a
tool that sometimes guesses your Sphinx configuration and sometimes
doesn't, with no way to suppress the guess, is worse than one that is
always explicit.  For this Journal the location is a stated project
fact (the repo root); for any other repository it must be *confirmed* —
ask the user when genuinely unknown — and each repo should get its own
``--build-dir`` (e.g. ``/tmp/<repo>-sphinx-build``).

==========================================
Heuristic mode: without ``--sphinx-src``
==========================================

Omit ``--sphinx-src`` and nothing is guessed: Phase 3 is skipped
entirely, and Phase 2's code-block detection switches to a pure
text-search fallback, **clearly labeled as heuristic in the output**.
Everything else keeps full strength — Phase 0 hygiene, all Phase 1
rules, the placeholder workflow and ``--fix``, heading outlines — none
of that ever needed Sphinx.

Why the heuristic exists at all: bare docutils cannot parse Sphinx-only
directive options (``:caption:``, ``:linenos:``, …) — the directive
fails and the code-block *silently vanishes* from the parse tree rather
than being detected.  An AST-based detector therefore loses recall
invisibly, the worst way to lose it.  The text search restores full
recall at the cost of two known, accepted limitations, both found by
real corpus differential tests and documented in the tool:

* a ``.. code-block::`` merely *quoted as example text* inside another
  real code-block is double-counted — without an AST there is nothing
  to guard against it (a cheatsheet documenting RST syntax itself hits
  this repeatedly);
* the ``code``, ``code-block``, and ``sourcecode`` aliases are treated
  as equivalent even though docutils' ``code`` accepts fewer options —
  per-alias validation would mean hardcoding a slice of Sphinx's own
  directive registry.

============================
How to treat the two modes
============================

-----------------
Trust the label
-----------------

Heuristic output says it is heuristic; treat its code-block inventory
as best-effort, never as verified fact.  When a task depends on exact
structure, obtain the ``conf.py`` location and re-run in verified mode.

-----------------------------------------------
Sphinx membership is not toctree reachability
-----------------------------------------------

A source file under ``DIR`` can be absent from every toctree and still
be a real Sphinx document: Sphinx discovers and parses such orphans into
``env.found_docs``.  It remains valid verified input.  "Not part of the
``--sphinx-src`` environment" instead means Sphinx did not discover the
file at all (outside ``DIR``, excluded by configuration, or not a source
type); that is a hard error, never a heuristic fallback.

------------------------------------------------
Fixing foreign content needs one extra caution
------------------------------------------------

``--fix`` remaps adornment characters to *this* project's preferred
ranking — a document written entirely with ``~`` headings gets
rewritten to ``#``.  On content from another project, always run
``--diff`` first and confirm the rewrite is wanted; and check the
target repo for uncommitted changes before writing (the semantic-rules
guide's audit workflow).

--------------------------------------------
Adopting a foreign document: a worked case
--------------------------------------------

An independent Claude Code session normalized six externally generated
documents in a downstream project this way (2026-07-21), and it is a materially
different claim than "it fixes my adornments" — the tool managing a
whole external-content lifecycle: pandoc converts Markdown to RST,
``check_rst --fix`` normalizes every adornment, and a human/AI judges
which bold-as-heading WARNINGs represent a real structural intent
(step 1 of the loop, same as always) — but the promoted bold-to-real-
heading decisions are *semantic*, and the pipeline reproduces
adornments, not semantic structure, on the next re-sync from the
upstream Markdown.  The session's own new practice: log each hand-
judged promotion in the normalized file's own header — "the pipeline
reproduces adornments but not semantic structure; here are the
bold→heading promotions to re-apply by hand next time" — so the
judgment survives the next pandoc pass instead of being silently
redone from scratch or silently lost.  This is not yet a check_rst
feature; it is a *project convention*, discovered by using the tool
for real, that deserves to travel with the contract: whenever adopting
and periodically re-syncing foreign generated content, record the
semantic decisions the tool cannot infer, in the file the decisions
apply to.
